#!/usr/bin/env python3
from pathlib import Path
import tkinter as tk
from tkinter import filedialog, messagebox, simpledialog, scrolledtext
import base64
from decimal import Decimal, InvalidOperation
import json
import os
import queue
import socket
import subprocess
import sys
import threading
import time
import urllib.error
import urllib.parse
import urllib.request

RPC_TIMEOUT = 10
DAEMON_START_TIMEOUT = 30
DAEMON_SHUTDOWN_TIMEOUT = 30
DAEMON_POLL_INTERVAL = 0.25
MINING_MAX_TRIES = 1_000_000
MINING_RETRY_DELAY = 0.05
WALLET_UNLOCK_SECONDS = 30
DEFAULT_WALLET_NAME = "pi_wallet"
RESTORED_WALLET_PREFIX = "pi_wallet_restored_"
SENSITIVE_WALLET_METHODS = {
    "createwallet",
    "encryptwallet",
    "walletpassphrase",
    "walletpassphrasechange",
}


def default_pi_datadir(platform=None, environ=None, home=None):
    platform = sys.platform if platform is None else platform
    environ = os.environ if environ is None else environ
    home = Path.home() if home is None else Path(home)
    if platform == "darwin":
        return home / "Library" / "Application Support" / "Pi"
    if platform == "win32":
        appdata = environ.get("APPDATA")
        if not appdata:
            raise RuntimeError("APPDATA is not set; the Pi data directory cannot be located.")
        return Path(appdata) / "Pi"
    return home / ".pi"


DATADIR = default_pi_datadir()
CONF_PATH = DATADIR / "pi.conf"
ACTIVE_WALLET_STATE_PATH = DATADIR / "wallet-gui-state.json"
DIR = os.path.dirname(os.path.abspath(__file__))
PID_BIN = os.path.join(DIR, "pid")
_RPC_STATE = threading.local()


def _is_gui_wallet_name(name):
    if name == DEFAULT_WALLET_NAME:
        return True
    if not isinstance(name, str) or not name.startswith(RESTORED_WALLET_PREFIX):
        return False
    return name[len(RESTORED_WALLET_PREFIX):].isdigit()


def read_active_wallet_name(path=None):
    path = ACTIVE_WALLET_STATE_PATH if path is None else Path(path)
    try:
        with path.open(encoding="utf-8") as state_file:
            state = json.load(state_file)
    except (FileNotFoundError, OSError, ValueError, TypeError):
        return DEFAULT_WALLET_NAME
    name = state.get("active_wallet") if isinstance(state, dict) else None
    return name if _is_gui_wallet_name(name) else DEFAULT_WALLET_NAME


def write_active_wallet_name(name, path=None):
    if not _is_gui_wallet_name(name):
        raise ValueError("Invalid Pi GUI wallet name.")
    path = ACTIVE_WALLET_STATE_PATH if path is None else Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(f".{path.name}.{os.getpid()}.tmp")
    try:
        with temporary.open("w", encoding="utf-8") as state_file:
            json.dump({"active_wallet": name}, state_file, separators=(",", ":"))
            state_file.write("\n")
        os.chmod(temporary, 0o600)
        os.replace(temporary, path)
    finally:
        try:
            temporary.unlink()
        except FileNotFoundError:
            pass


class PiRPCError(Exception):
    def __init__(self, message, kind="rpc", code=None):
        super().__init__(message)
        self.kind = kind
        self.code = code


def read_conf(path=None):
    conf = {"rpcport": "8332"}
    path = CONF_PATH if path is None else Path(path)
    try:
        with path.open(encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if "=" in line and not line.startswith("#"):
                    k, v = line.split("=", 1)
                    key = k.strip()
                    if key in ("rpcport", "rpccookiefile", "rpcuser", "rpcpassword"):
                        conf[key] = v.strip()
    except FileNotFoundError:
        pass
    return conf


def _rpc_port(conf):
    try:
        port = int(conf.get("rpcport", "8332"))
    except (TypeError, ValueError) as exc:
        raise PiRPCError("pi.conf contains an invalid rpcport.", kind="config") from exc
    if not 1 <= port <= 65535:
        raise PiRPCError("pi.conf contains an invalid rpcport.", kind="config")
    return port


def _loopback_rpc_listener(port):
    try:
        with socket.create_connection(("127.0.0.1", port), timeout=0.25):
            return True
    except OSError:
        return False


def _cookie_path(conf):
    configured = conf.get("rpccookiefile")
    if not configured:
        return DATADIR / ".cookie"
    path = Path(os.path.expanduser(configured))
    return path if path.is_absolute() else DATADIR / path


def _read_cookie(path):
    try:
        cookie = path.read_text(encoding="utf-8").strip()
    except FileNotFoundError as exc:
        raise PiRPCError(
            "Pi Core RPC cookie is missing.",
            kind="cookie_missing",
        ) from exc
    except OSError as exc:
        raise PiRPCError("Pi Core RPC cookie cannot be read.", kind="auth") from exc
    if ":" not in cookie:
        raise PiRPCError("Pi Core RPC cookie is invalid.", kind="auth")
    username, password = cookie.split(":", 1)
    if not username or not password:
        raise PiRPCError("Pi Core RPC cookie is invalid.", kind="auth")
    return username, password


def _read_auth(conf):
    try:
        username, password = _read_cookie(_cookie_path(conf))
        return username, password, "cookie"
    except PiRPCError as exc:
        if exc.kind != "cookie_missing":
            raise
    username = conf.get("rpcuser")
    password = conf.get("rpcpassword")
    if username and password:
        return username, password, "config"
    raise PiRPCError(
        "Pi Core RPC credentials are unavailable. Start the Pi daemon for cookie "
        "authentication or configure both rpcuser and rpcpassword in pi.conf.",
        kind="auth",
    )


def _json_value(value):
    if isinstance(value, Decimal):
        return format(value, "f")
    if isinstance(value, list):
        return [_json_value(item) for item in value]
    if isinstance(value, tuple):
        return [_json_value(item) for item in value]
    if isinstance(value, dict):
        return {key: _json_value(item) for key, item in value.items()}
    return value


def _sanitize(message, secrets):
    sanitized = str(message)
    for secret in secrets:
        if secret:
            sanitized = sanitized.replace(secret, "[redacted]")
    return sanitized


def _parse_rpc_response(raw, method, secrets):
    try:
        response = json.loads(raw.decode("utf-8"), parse_float=Decimal)
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise PiRPCError("Pi Core returned invalid JSON.", kind="response") from exc
    if not isinstance(response, dict):
        raise PiRPCError("Pi Core returned an invalid RPC response.", kind="response")
    if "result" not in response or "error" not in response:
        raise PiRPCError(
            "Pi Core RPC response is missing result or error.",
            kind="response",
        )
    error = response["error"]
    if error is not None:
        if not isinstance(error, dict):
            raise PiRPCError("Pi Core returned an invalid RPC error.", kind="response")
        code = error.get("code")
        message = _sanitize(error.get("message", "RPC request failed."), secrets)
        if code == -32601:
            message = f"Pi Core RPC method not found: {method}."
        elif code in (-18, -19):
            message = "No Pi wallet is loaded."
        elif code == -28:
            message = "Pi Core is starting or shutting down. Try again shortly."
        elif method in ("dumpprivkey", "importprivkey"):
            message = f"Pi Core rejected the wallet request (RPC error {code})."
        else:
            message = f"Pi Core RPC error {code}: {message}"
        raise PiRPCError(message, code=code)
    return response["result"]


def _rpc_request(method, params=None, wallet=None):
    try:
        conf = read_conf()
    except OSError as exc:
        raise PiRPCError("pi.conf cannot be read.", kind="config") from exc
    port = _rpc_port(conf)

    url = f"http://127.0.0.1:{port}"
    if wallet is not None:
        wallet_path = urllib.parse.quote(str(wallet), safe="")
        url = f"{url}/wallet/{wallet_path}"
    rpc_params = params if params is not None else []
    payload = json.dumps(
        {
            "jsonrpc": "1.0",
            "id": "wallet",
            "method": method,
            "params": _json_value(rpc_params),
        },
        separators=(",", ":"),
    ).encode("utf-8")

    for attempt in range(2):
        username, password, auth_source = _read_auth(conf)
        credentials = f"{username}:{password}"
        auth = base64.b64encode(credentials.encode("utf-8")).decode("ascii")
        sensitive_params = ()
        if method in SENSITIVE_WALLET_METHODS:
            sensitive_params = tuple(
                value for value in rpc_params if isinstance(value, str)
            )
        secrets = (username, password, credentials, auth, *sensitive_params)
        request = urllib.request.Request(
            url,
            data=payload,
            headers={
                "Authorization": f"Basic {auth}",
                "Content-Type": "application/json",
            },
        )
        try:
            with urllib.request.urlopen(request, timeout=RPC_TIMEOUT) as response:
                status = getattr(response, "status", 200)
                if status != 200:
                    raise PiRPCError(
                        f"Pi Core RPC returned HTTP status {status}.",
                        kind="transport",
                    )
                return _parse_rpc_response(response.read(), method, secrets)
        except urllib.error.HTTPError as exc:
            if exc.code == 401:
                if attempt == 0:
                    continue
                if auth_source == "config":
                    message = "Pi Core rejected the RPC credentials from pi.conf."
                else:
                    message = (
                        "Pi Core rejected the RPC cookie. Restart the daemon and "
                        "try again."
                    )
                raise PiRPCError(
                    message,
                    kind="auth",
                ) from exc
            body = exc.read()
            if body:
                try:
                    _parse_rpc_response(body, method, secrets)
                except PiRPCError as rpc_error:
                    if rpc_error.kind == "rpc":
                        raise
            raise PiRPCError(
                f"Pi Core RPC returned HTTP error {exc.code}.",
                kind="transport",
            ) from exc
        except (socket.timeout, TimeoutError) as exc:
            raise PiRPCError("Pi Core RPC request timed out.", kind="timeout") from exc
        except urllib.error.URLError as exc:
            if isinstance(exc.reason, (socket.timeout, TimeoutError)):
                raise PiRPCError("Pi Core RPC request timed out.", kind="timeout") from exc
            if isinstance(exc.reason, ConnectionRefusedError):
                raise PiRPCError(
                    "Cannot connect to Pi Core. The daemon may not be running.",
                    kind="connection",
                ) from exc
            raise PiRPCError("Cannot connect to Pi Core RPC.", kind="connection") from exc
        except ConnectionRefusedError as exc:
            raise PiRPCError(
                "Cannot connect to Pi Core. The daemon may not be running.",
                kind="connection",
            ) from exc
    raise PiRPCError("Pi Core RPC authentication failed.", kind="auth")


def rpc_with_status(method, params=None, wallet=None):
    try:
        result = _rpc_request(method, params, wallet=wallet)
    except PiRPCError as exc:
        _RPC_STATE.error = str(exc)
        return False, None
    _RPC_STATE.error = ""
    return True, result


def rpc(method, params=None, wallet=None):
    success, result = rpc_with_status(method, params, wallet=wallet)
    return result if success else None


def rpc_error(default="Pi Core RPC request failed."):
    return getattr(_RPC_STATE, "error", "") or default


class DaemonController:
    def __init__(self, daemon_path=None, datadir=None, conf_path=None):
        self.daemon_path = Path(PID_BIN if daemon_path is None else daemon_path)
        self.datadir = Path(DATADIR if datadir is None else datadir)
        self.conf_path = Path(CONF_PATH if conf_path is None else conf_path)
        self.startup_log_path = self.datadir / "pi-wallet-daemon.log"
        self.process = None
        self.ownership = "none"
        self.last_error = ""
        self.cancel_event = threading.Event()

    def _validate_identity(self):
        network_info = _rpc_request("getnetworkinfo")
        subversion = network_info.get("subversion") if isinstance(network_info, dict) else None
        if not isinstance(subversion, str) or not subversion.startswith("/Pi:"):
            raise PiRPCError(
                "The RPC service is not a recognized Pi Core daemon.",
                kind="identity",
            )

        chain_info = _rpc_request("getblockchaininfo")
        chain = chain_info.get("chain") if isinstance(chain_info, dict) else None
        if chain != "main":
            raise PiRPCError(
                f"Pi Wallet requires mainnet, but the daemon is using {chain or 'an unknown chain'}.",
                kind="identity",
            )
        return chain_info

    def _credentials_available(self):
        try:
            conf = read_conf(self.conf_path)
        except OSError:
            return False
        if _cookie_path(conf).is_file():
            return True
        return bool(conf.get("rpcuser") and conf.get("rpcpassword"))

    def _retryable_startup_error(self, error):
        if error.code == -28 or error.kind in ("connection", "timeout"):
            return True
        return error.kind == "auth" and not self._credentials_available()

    def _wait_for_rpc(self, deadline):
        last_error = None
        while time.monotonic() < deadline:
            if self.cancel_event.is_set():
                raise PiRPCError("Pi Core startup was cancelled.", kind="cancelled")

            try:
                chain_info = self._validate_identity()
                if self.process is not None and self.process.poll() is None:
                    self.ownership = "managed"
                else:
                    self.process = None
                    self.ownership = "external"
                self.last_error = ""
                return chain_info
            except PiRPCError as exc:
                last_error = exc
                if not self._retryable_startup_error(exc):
                    raise

            if self.process is not None and self.process.poll() is not None:
                self.process = None
                self.ownership = "none"
            time.sleep(DAEMON_POLL_INTERVAL)

        if last_error is not None:
            raise PiRPCError(
                f"Pi Core did not become ready before the startup deadline: {last_error}",
                kind="startup",
            ) from last_error
        raise PiRPCError(
            "Pi Core did not become ready before the startup deadline.",
            kind="startup",
        )

    def _start_managed(self):
        if self.process is not None:
            raise PiRPCError("Pi Core startup has already been attempted.", kind="startup")
        if not self.daemon_path.is_file() or not os.access(self.daemon_path, os.X_OK):
            raise PiRPCError(
                f"Pi Core daemon was not found at {self.daemon_path}.",
                kind="startup",
            )

        try:
            self.datadir.mkdir(parents=True, exist_ok=True)
        except OSError as exc:
            raise PiRPCError(
                "The Pi data directory could not be created.",
                kind="startup",
            ) from exc

        command = [
            str(self.daemon_path),
            f"-datadir={self.datadir}",
            "-daemon=0",
        ]
        if self.conf_path.is_file():
            command.append(f"-conf={self.conf_path}")

        try:
            startup_log = self.startup_log_path.open("ab")
        except OSError as exc:
            raise PiRPCError(
                f"Pi Core startup log could not be opened at {self.startup_log_path}.",
                kind="startup",
            ) from exc
        try:
            try:
                self.process = subprocess.Popen(
                    command,
                    stdin=subprocess.DEVNULL,
                    stdout=startup_log,
                    stderr=subprocess.STDOUT,
                )
            except OSError as exc:
                self.process = None
                raise PiRPCError(
                    "Pi Core daemon could not be started.",
                    kind="startup",
                ) from exc
        finally:
            startup_log.close()
        self.ownership = "managed"

    def _terminate_started_child(self):
        process = self.process
        if process is None:
            return
        if process.poll() is None:
            process.terminate()
            try:
                process.wait(timeout=DAEMON_SHUTDOWN_TIMEOUT)
            except subprocess.TimeoutExpired:
                process.kill()
                process.wait(timeout=DAEMON_SHUTDOWN_TIMEOUT)
        self.process = None
        self.ownership = "none"

    def attach_or_start(self):
        self.cancel_event.clear()
        try:
            chain_info = self._validate_identity()
        except PiRPCError as first_error:
            try:
                conf = read_conf(self.conf_path)
                port = _rpc_port(conf)
            except OSError as exc:
                raise PiRPCError("pi.conf cannot be read.", kind="config") from exc

            if _loopback_rpc_listener(port):
                if not self._retryable_startup_error(first_error):
                    self.last_error = str(first_error)
                    raise
                chain_info = self._wait_for_rpc(
                    time.monotonic() + DAEMON_START_TIMEOUT
                )
            else:
                self._start_managed()
                try:
                    chain_info = self._wait_for_rpc(
                        time.monotonic() + DAEMON_START_TIMEOUT
                    )
                except PiRPCError:
                    self._terminate_started_child()
                    raise
        else:
            self.process = None
            self.ownership = "external"
            self.last_error = ""
        return chain_info

    def cancel(self):
        self.cancel_event.set()

    def is_syncing(self):
        try:
            chain_info = _rpc_request("getblockchaininfo")
        except PiRPCError:
            return None
        return bool(chain_info.get("initialblockdownload", False))

    def shutdown_managed(self):
        process = self.process
        if self.ownership != "managed" or process is None:
            return "external"
        if process.poll() is not None:
            self.process = None
            self.ownership = "none"
            return "exited"

        try:
            _rpc_request("stop")
        except PiRPCError as exc:
            self.last_error = str(exc)

        result = "graceful"
        try:
            process.wait(timeout=DAEMON_SHUTDOWN_TIMEOUT)
        except subprocess.TimeoutExpired:
            result = "terminated"
            process.terminate()
            try:
                process.wait(timeout=DAEMON_SHUTDOWN_TIMEOUT)
            except subprocess.TimeoutExpired:
                result = "killed"
                process.kill()
                process.wait(timeout=DAEMON_SHUTDOWN_TIMEOUT)
        finally:
            self.process = None
            self.ownership = "none"
        return result


class PiWallet:
    def __init__(self, root):
        self.root = root
        self.root.title("Pi Wallet")
        self.root.geometry("520x760")
        self.root.configure(bg="white")
        self.root.resizable(False, False)
        self.mining = False
        self.blocks_mined = 0
        self.current_address = ""
        self.active_wallet = None
        self.wallet_encrypted = False
        self.wallet_transitioning = False
        self.stop_event = threading.Event()
        self.mining_thread = None
        self.balance_thread = None
        self.readiness_thread = None
        self.mining_ready = False
        self.closing = False
        self.workers = set()
        self.workers_lock = threading.Lock()
        self.ui_queue = queue.Queue()
        self.ui_after_id = None
        self.refresh_after_id = None
        self.close_after_id = None
        self.close_requested = False
        self.daemon_controller = DaemonController()
        self.daemon_dependent_widgets = []
        self.daemon_shutdown_started = False
        self.daemon_shutdown_thread = None
        self.root.protocol("WM_DELETE_WINDOW", self.on_close)
        self.build_ui()
        self._drain_ui_queue()
        self._start_worker(self._initialize_daemon, "daemon-init")

    def _start_worker(self, target, name, *args):
        if self.closing:
            return None

        def _run():
            try:
                target(*args)
            finally:
                with self.workers_lock:
                    self.workers.discard(threading.current_thread())

        worker = threading.Thread(target=_run, name=name)
        with self.workers_lock:
            self.workers.add(worker)
        worker.start()
        return worker

    def _queue_ui(self, callback, *args):
        if not self.closing:
            self.ui_queue.put((callback, args))

    def _drain_ui_queue(self):
        if self.closing:
            return
        while True:
            try:
                callback, args = self.ui_queue.get_nowait()
            except queue.Empty:
                break
            callback(*args)
        if not self.closing:
            self.ui_after_id = self.root.after(50, self._drain_ui_queue)

    def _set_balance(self, mature, immature):
        self.balance_var.set(f"Spendable: {mature:.8f} PI")
        self.blocks_var.set(f"Mining rewards: {immature:.8f} PI")

    def _set_address(self, address):
        self.current_address = address
        self.address_var.set(address)

    def _set_daemon_controls_enabled(self, enabled):
        state = "normal" if enabled else "disabled"
        for widget in self.daemon_dependent_widgets:
            widget.config(state=state)

    def _wallet_ready(self):
        self._set_daemon_controls_enabled(True)
        self.mining_ready = False
        self.mine_btn.config(state="disabled")
        self.status_var.set("Checking Pi network...")
        self._request_mining_readiness()
        self._schedule_auto_refresh()

    def _initialize_daemon(self):
        self._queue_ui(self.status_var.set, "Connecting to Pi Core...")
        try:
            self.daemon_controller.attach_or_start()
        except PiRPCError as exc:
            if not self.closing:
                self._queue_ui(self._daemon_failed, str(exc))
            return
        self._queue_ui(self._daemon_ready)

    def _daemon_ready(self):
        if self.closing:
            return
        self._start_worker(self._init, "wallet-init")

    def _daemon_failed(self, message):
        self._set_daemon_controls_enabled(False)
        self.status_var.set(message)

    def _schedule_auto_refresh(self):
        if not self.closing:
            self.refresh_after_id = self.root.after(10000, self._auto_refresh)

    def _request_balance_update(self):
        if self.closing:
            return
        if self.balance_thread is not None and self.balance_thread.is_alive():
            return
        self.balance_thread = self._start_worker(
            self._update_balance, "wallet-balance"
        )

    def _init(self):
        self._queue_ui(self.status_var.set, "Connecting...")
        try:
            self.active_wallet = self._ensure_wallet(
                require_encryption=True,
                preferred_wallet=read_active_wallet_name(),
            )
        except PiRPCError as exc:
            self._queue_ui(self.status_var.set, str(exc))
            return
        self._finish_wallet_init()

    def _ask_new_wallet_password(self, title, prompt):
        while not self.closing:
            passphrase = simpledialog.askstring(
                title,
                prompt,
                show="*",
                parent=self.root,
            )
            if passphrase is None:
                return None
            if not passphrase:
                messagebox.showerror(
                    title,
                    "The wallet password cannot be empty.",
                    parent=self.root,
                )
                continue
            confirmation = simpledialog.askstring(
                title,
                "Confirm the wallet password:",
                show="*",
                parent=self.root,
            )
            if confirmation is None:
                return None
            if passphrase != confirmation:
                messagebox.showerror(
                    title,
                    "The wallet passwords do not match.",
                    parent=self.root,
                )
                continue
            return passphrase
        return None

    def _request_new_wallet_password(self):
        result = queue.Queue(maxsize=1)
        completed = threading.Event()
        self._queue_ui(
            self._collect_new_wallet_password,
            result,
            completed,
        )
        while not completed.wait(0.1):
            if self.closing:
                return None
        return result.get()

    def _collect_new_wallet_password(self, result, completed):
        passphrase = self._ask_new_wallet_password(
            "Create Pi Wallet",
            "Create a password for your Pi wallet.\n\n"
            "This password is not stored and cannot be recovered.",
        )
        result.put(passphrase)
        completed.set()

    def _prompt_encrypt_existing_wallet(self):
        if self.closing:
            return
        passphrase = self._ask_new_wallet_password(
            "Protect Pi Wallet",
            "This Pi wallet is not encrypted. Create a password now.\n\n"
            "This password is not stored and cannot be recovered.",
        )
        if passphrase is None:
            self.status_var.set("Wallet encryption cancelled. Restart Pi Wallet to try again.")
            return
        self.status_var.set("Encrypting Pi wallet...")
        self._start_worker(
            self._encrypt_existing_wallet,
            "wallet-encrypt",
            passphrase,
        )

    def _encrypt_existing_wallet(self, passphrase):
        try:
            _rpc_request(
                "encryptwallet",
                [passphrase],
                wallet=self.active_wallet,
            )
        except PiRPCError as exc:
            self._queue_ui(self.status_var.set, str(exc))
            return
        self._finish_wallet_init()

    def _finish_wallet_init(self):
        addr = self._wallet_rpc("getnewaddress")
        if addr:
            self._queue_ui(self._set_address, addr)
        else:
            error = rpc_error("Cannot connect to Pi Core.")
            self._queue_ui(self.status_var.set, error)
            return False
        info = self._wallet_rpc("getwalletinfo")
        if not info:
            error = rpc_error()
            self._queue_ui(self.status_var.set, error)
            return False
        if hasattr(self, "wallet_encrypted"):
            if "unlocked_until" not in info:
                self._queue_ui(self._prompt_encrypt_existing_wallet)
                return True
            self.wallet_encrypted = True
        mature = info.get("balance", Decimal("0"))
        immature = info.get("immature_balance", Decimal("0"))
        self._queue_ui(self._set_balance, mature, immature)
        self._queue_ui(self._wallet_ready)
        return True

    def _ensure_wallet(
        self,
        passphrase=None,
        require_encryption=False,
        preferred_wallet=DEFAULT_WALLET_NAME,
    ):
        if not _is_gui_wallet_name(preferred_wallet):
            raise PiRPCError("Pi Wallet selected an invalid wallet name.")
        loaded = _rpc_request("listwallets")
        if not isinstance(loaded, list):
            raise PiRPCError("Pi Core returned an invalid wallet list.")
        if preferred_wallet in loaded:
            self._unload_other_gui_wallets(preferred_wallet, loaded)
            return preferred_wallet

        wallet_dir = _rpc_request("listwalletdir")
        entries = wallet_dir.get("wallets", []) if isinstance(wallet_dir, dict) else []
        wallet_names = {
            entry.get("name")
            for entry in entries
            if isinstance(entry, dict) and isinstance(entry.get("name"), str)
        }
        if preferred_wallet in wallet_names:
            load_params = [preferred_wallet]
            if preferred_wallet != DEFAULT_WALLET_NAME:
                load_params.append(True)
            _rpc_request("loadwallet", load_params)
        elif preferred_wallet != DEFAULT_WALLET_NAME:
            if DEFAULT_WALLET_NAME not in wallet_names:
                raise PiRPCError(
                    "The selected restored Pi wallet is missing. "
                    "The original wallet files were not changed."
                )
            preferred_wallet = DEFAULT_WALLET_NAME
            _rpc_request("loadwallet", [preferred_wallet])
            try:
                write_active_wallet_name(preferred_wallet)
            except OSError as exc:
                raise PiRPCError(
                    "Pi Wallet found the original wallet but could not update "
                    f"its local selection: {exc}"
                ) from exc
        else:
            if require_encryption and passphrase is None:
                passphrase = self._request_new_wallet_password()
                if passphrase is None:
                    raise PiRPCError(
                        "Wallet creation cancelled. Restart Pi Wallet to try again."
                    )
            create_params = [DEFAULT_WALLET_NAME]
            if passphrase is not None:
                create_params = [
                    DEFAULT_WALLET_NAME,
                    False,
                    False,
                    passphrase,
                    False,
                    True,
                    True,
                ]
            _rpc_request("createwallet", create_params)

        loaded = _rpc_request("listwallets")
        if preferred_wallet not in loaded:
            raise PiRPCError("Pi Core did not load the selected Pi wallet.")
        self._unload_other_gui_wallets(preferred_wallet, loaded)
        return preferred_wallet

    def _unload_other_gui_wallets(self, active_wallet, loaded_wallets):
        for wallet_name in loaded_wallets:
            if wallet_name != active_wallet and _is_gui_wallet_name(wallet_name):
                _rpc_request("unloadwallet", [wallet_name, False])

    def _wallet_rpc(self, method, params=None):
        return rpc(method, params, wallet=self.active_wallet)

    def _wallet_rpc_with_status(self, method, params=None):
        return rpc_with_status(method, params, wallet=self.active_wallet)

    def _auto_refresh(self):
        self.refresh_after_id = None
        if self.closing:
            return
        if not self.mining:
            self._request_balance_update()
        self._request_mining_readiness()
        self._schedule_auto_refresh()

    def _request_mining_readiness(self):
        if self.closing:
            return
        if self.readiness_thread is not None and self.readiness_thread.is_alive():
            return
        self.readiness_thread = self._start_worker(
            self._check_mining_readiness, "mining-readiness"
        )

    def _check_mining_readiness(self):
        try:
            peer_count = int(_rpc_request("getconnectioncount"))
            chain_info = _rpc_request("getblockchaininfo")
            blocks = int(chain_info.get("blocks", 0))
            headers = int(chain_info.get("headers", 0))
            progress = float(chain_info.get("verificationprogress", 0))
        except (PiRPCError, TypeError, ValueError):
            self._queue_ui(
                self._apply_mining_readiness,
                False,
                "Cannot verify Pi network readiness.",
            )
            return

        if peer_count < 1:
            ready = False
            message = "Waiting for a Tor peer before mining..."
        elif blocks < headers or progress < 0.999999:
            ready = False
            message = f"Synchronizing Pi blockchain: {blocks}/{headers} blocks"
        else:
            ready = True
            message = ""
        self._queue_ui(self._apply_mining_readiness, ready, message)

    def _apply_mining_readiness(self, ready, message):
        if self.closing:
            return
        self.mining_ready = ready
        if self.mining:
            if not ready:
                self.mining = False
                self.stop_event.set()
                self.mine_btn.config(state="disabled")
                self.status_var.set(message)
            return
        self.mine_btn.config(state="normal" if ready else "disabled")
        self.status_var.set(message)

    def _update_balance(self):
        info = self._wallet_rpc("getwalletinfo")
        if info:
            mature = info.get("balance", Decimal("0"))
            immature = info.get("immature_balance", Decimal("0"))
            self._queue_ui(self._set_balance, mature, immature)
        else:
            error = rpc_error()
            self._queue_ui(self.status_var.set, error)

    def build_ui(self):
        tk.Label(self.root, text="π", font=("Times New Roman", 80, "bold"), fg="black", bg="white").pack(pady=(20,0))
        tk.Label(self.root, text="Pi Wallet", font=("Helvetica", 14, "bold"), fg="#111111", bg="white").pack(pady=(0,10))
        tk.Frame(self.root, height=1, bg="#cccccc").pack(fill="x", padx=30)

        bf = tk.Frame(self.root, bg="white")
        bf.pack(pady=12)
        tk.Label(bf, text="BALANCE", font=("Helvetica", 10, "bold"), fg="#555555", bg="white").pack()
        self.balance_var = tk.StringVar(value="Loading...")
        tk.Label(bf, textvariable=self.balance_var, font=("Helvetica", 24, "bold"), fg="black", bg="white").pack()
        self.blocks_var = tk.StringVar(value="Blocks mined this session: 0")
        tk.Label(bf, textvariable=self.blocks_var, font=("Helvetica", 10), fg="#555555", bg="white").pack()

        tk.Frame(self.root, height=1, bg="#cccccc").pack(fill="x", padx=30)

        af = tk.Frame(self.root, bg="white", padx=30)
        af.pack(fill="x", pady=10)
        tk.Label(af, text="YOUR ADDRESS", font=("Helvetica", 10, "bold"), fg="#555555", bg="white").pack(anchor="w")
        self.address_var = tk.StringVar(value="Connecting...")
        tk.Entry(af, textvariable=self.address_var, font=("Courier", 9), fg="#111111", bg="#f0f0f0", relief="flat", bd=1, state="readonly").pack(fill="x", pady=4, ipady=6)
        bf2 = tk.Frame(af, bg="white")
        bf2.pack(fill="x")
        self.copy_btn = tk.Button(bf2, text="Copy", command=self.copy_address, font=("Helvetica", 10, "bold"), fg="white", bg="#111111", relief="flat", cursor="hand2", padx=12, pady=5, state="disabled")
        self.copy_btn.pack(side="left")
        self.new_address_btn = tk.Button(bf2, text="New Address", command=self.new_address, font=("Helvetica", 10, "bold"), fg="#111111", bg="white", relief="solid", bd=2, cursor="hand2", padx=12, pady=5, state="disabled")
        self.new_address_btn.pack(side="left", padx=(8,0))
        self.history_btn = tk.Button(bf2, text="History", command=self.show_history, font=("Helvetica", 10, "bold"), fg="#111111", bg="white", relief="solid", bd=2, cursor="hand2", padx=12, pady=5, state="disabled")
        self.history_btn.pack(side="left", padx=(8,0))
        self.backup_btn = tk.Button(bf2, text="Backup Wallet", command=self.backup_wallet, font=("Helvetica", 10, "bold"), fg="#111111", bg="white", relief="solid", bd=2, cursor="hand2", padx=12, pady=5, state="disabled")
        self.backup_btn.pack(side="left", padx=(8,0))

        tk.Frame(self.root, height=1, bg="#cccccc").pack(fill="x", padx=30)

        imp_f = tk.Frame(self.root, bg="white", padx=30)
        imp_f.pack(fill="x", pady=8)
        tk.Label(imp_f, text="RESTORE WALLET", font=("Helvetica", 10, "bold"), fg="#555555", bg="white").pack(anchor="w")
        self.restore_var = tk.StringVar(value="Choose an encrypted Pi wallet backup file.")
        self.restore_entry = tk.Entry(imp_f, textvariable=self.restore_var, font=("Courier", 9), fg="#111111", bg="#f0f0f0", relief="flat", bd=1, state="readonly")
        self.restore_entry.pack(fill="x", pady=4, ipady=6)
        self.restore_btn = tk.Button(imp_f, text="Restore Wallet →", command=self.restore_wallet, font=("Helvetica", 10, "bold"), fg="white", bg="#111111", relief="flat", cursor="hand2", padx=12, pady=5, state="disabled")
        self.restore_btn.pack(anchor="e", pady=2)

        tk.Frame(self.root, height=1, bg="#cccccc").pack(fill="x", padx=30)

        sf = tk.Frame(self.root, bg="white", padx=30)
        sf.pack(fill="x", pady=8)
        tk.Label(sf, text="SEND PI", font=("Helvetica", 10, "bold"), fg="#555555", bg="white").pack(anchor="w")
        self.send_addr_var = tk.StringVar()
        self.send_addr_entry = tk.Entry(sf, textvariable=self.send_addr_var, font=("Courier", 9), fg="#111111", bg="#f0f0f0", relief="flat", bd=1, state="disabled")
        self.send_addr_entry.pack(fill="x", pady=4, ipady=6)
        self.send_amt_var = tk.StringVar()
        self.send_amt_entry = tk.Entry(sf, textvariable=self.send_amt_var, font=("Helvetica", 10), fg="#111111", bg="#f0f0f0", relief="flat", bd=1, state="disabled")
        self.send_amt_entry.pack(fill="x", pady=4, ipady=6)
        self.send_btn = tk.Button(sf, text="Send →", command=self.send_pi, font=("Helvetica", 11, "bold"), fg="white", bg="#111111", relief="flat", cursor="hand2", padx=20, pady=6, state="disabled")
        self.send_btn.pack(anchor="e", pady=2)

        tk.Frame(self.root, height=1, bg="#cccccc").pack(fill="x", padx=30)

        mf = tk.Frame(self.root, bg="white", padx=30)
        mf.pack(fill="x", pady=10)
        self.mine_btn = tk.Button(mf, text="⛏  Start Mining", command=self.toggle_mine,
            font=("Helvetica", 13, "bold"), fg="white", bg="#111111",
            relief="flat", cursor="hand2", padx=20, pady=10, state="disabled")
        self.mine_btn.pack(fill="x")

        self.daemon_dependent_widgets.extend([
            self.copy_btn,
            self.new_address_btn,
            self.history_btn,
            self.backup_btn,
            self.restore_btn,
            self.send_addr_entry,
            self.send_amt_entry,
            self.send_btn,
            self.mine_btn,
        ])

        self.status_var = tk.StringVar(value="")
        tk.Label(self.root, textvariable=self.status_var, font=("Helvetica", 10), fg="#555555", bg="white").pack(pady=4)

    def copy_address(self):
        self.root.clipboard_clear()
        self.root.clipboard_append(self.address_var.get())
        self.status_var.set("Copied!")
        self.root.after(2000, lambda: self.status_var.set(""))

    def new_address(self):
        if not messagebox.askyesno("New Address", "Create a new address?\nYour old address still works."):
            return
        def _n():
            a = self._wallet_rpc("getnewaddress")
            if a:
                self._queue_ui(self._set_address, a)
                self._queue_ui(self.status_var.set, "New address created!")
            else:
                error = rpc_error("Could not create a new address.")
                self._queue_ui(self.status_var.set, error)
        self._start_worker(_n, "wallet-new-address")

    def show_history(self):
        win = tk.Toplevel(self.root)
        win.title("Wallet History")
        win.geometry("500x400")
        win.configure(bg="white")
        tk.Label(win, text="Addresses on this machine:", font=("Helvetica", 11, "bold"), bg="white").pack(pady=10)
        txt = scrolledtext.ScrolledText(win, font=("Courier", 9), bg="#f0f0f0", relief="flat")
        txt.pack(fill="both", expand=True, padx=20, pady=10)
        txt.insert("end", "Loading...\n")
        def _load():
            result = self._wallet_rpc("listreceivedbyaddress", [0, True])
            text = ""
            if isinstance(result, list):
                for item in result:
                    addr = item.get("address", "")
                    amount = item.get("amount", 0)
                    txids = item.get("txids", [])
                    text += f"Address: {addr}\n  Received: {amount:.8f} PI  |  Txs: {len(txids)}\n\n"
                if not result:
                    text = "No history found."
            else:
                text = rpc_error("Could not load wallet history.")
            self._queue_ui(self._replace_history, win, txt, text)
        self._start_worker(_load, "wallet-history")

    def _replace_history(self, win, txt, text):
        if win.winfo_exists():
            txt.delete("1.0", "end")
            txt.insert("end", text)

    def backup_wallet(self):
        if not self.active_wallet:
            messagebox.showwarning("Backup Wallet", "No wallet is loaded yet.")
            return
        destination = filedialog.asksaveasfilename(
            title="Back Up Pi Wallet",
            defaultextension=".bak",
            filetypes=[("Pi Wallet Backup", "*.bak"), ("All Files", "*")],
            initialfile="pi_wallet_backup.bak",
            parent=self.root,
        )
        if not destination:
            return
        self.status_var.set("Backing up Pi wallet...")
        self._start_worker(
            self._backup_wallet,
            "wallet-backup",
            destination,
        )

    def _backup_wallet(self, destination):
        success, _ = self._wallet_rpc_with_status("backupwallet", [destination])
        if success:
            self._queue_ui(self.status_var.set, "Wallet backup completed.")
            self._queue_ui(
                messagebox.showinfo,
                "Backup Wallet",
                "The encrypted Pi wallet backup was saved successfully.\n\n"
                "Keep the backup file and wallet password in separate safe places.",
            )
        else:
            self._queue_ui(
                messagebox.showerror,
                "Backup Wallet",
                rpc_error("Wallet backup failed."),
            )
            self._queue_ui(
                self.status_var.set,
                rpc_error("Wallet backup failed."),
            )

    def restore_wallet(self):
        if self.wallet_transitioning:
            return
        if self.mining:
            messagebox.showwarning(
                "Restore Wallet",
                "Stop mining before restoring a wallet.",
                parent=self.root,
            )
            return
        backup_file = filedialog.askopenfilename(
            title="Restore Pi Wallet",
            filetypes=[("Pi Wallet Backup", "*.bak"), ("All Files", "*")],
            parent=self.root,
        )
        if not backup_file:
            return
        if not messagebox.askyesno(
            "Restore Wallet",
            "Restore this backup and make it the active Pi wallet?\n\n"
            "The current wallet will be kept on disk and will not be deleted.",
            parent=self.root,
        ):
            return
        self.wallet_transitioning = True
        self.restore_var.set(Path(backup_file).name)
        self._set_daemon_controls_enabled(False)
        if self.refresh_after_id is not None:
            try:
                self.root.after_cancel(self.refresh_after_id)
            except tk.TclError:
                pass
            self.refresh_after_id = None
        self.status_var.set("Restoring Pi wallet...")
        self._start_worker(
            self._restore_wallet,
            "wallet-restore",
            backup_file,
        )

    def _restore_wallet(self, backup_file):
        old_wallet = self.active_wallet
        restored_wallet = f"{RESTORED_WALLET_PREFIX}{time.time_ns()}"
        old_wallet_unloaded = False
        try:
            _rpc_request(
                "restorewallet",
                [restored_wallet, backup_file, True],
            )
            info = _rpc_request("getwalletinfo", wallet=restored_wallet)
            if not isinstance(info, dict):
                raise PiRPCError("Pi Core could not verify the restored wallet.")
            if info.get("format") != "sqlite" or info.get("descriptors") is not True:
                raise PiRPCError(
                    "The selected backup is not a Pi descriptor wallet backup."
                )
            if info.get("private_keys_enabled") is not True:
                raise PiRPCError(
                    "The selected backup does not contain an enabled private-key wallet."
                )
            _rpc_request("unloadwallet", [old_wallet, False])
            old_wallet_unloaded = True
            write_active_wallet_name(restored_wallet)
        except (OSError, ValueError, PiRPCError) as exc:
            self._rollback_restored_wallet(
                restored_wallet,
                old_wallet,
                old_wallet_unloaded,
            )
            self._queue_ui(self._restore_wallet_failed, str(exc))
            return

        self.active_wallet = restored_wallet
        self.wallet_encrypted = False
        if not self._finish_wallet_init():
            self._queue_ui(self._restore_wallet_initialization_failed)
            return
        self._queue_ui(self._restore_wallet_completed)

    def _rollback_restored_wallet(
        self,
        restored_wallet,
        old_wallet,
        old_wallet_unloaded,
    ):
        try:
            loaded = _rpc_request("listwallets")
            if restored_wallet in loaded:
                _rpc_request("unloadwallet", [restored_wallet, False])
        except PiRPCError:
            pass
        if old_wallet_unloaded:
            try:
                _rpc_request("loadwallet", [old_wallet, True])
            except PiRPCError:
                pass

    def _restore_wallet_failed(self, message):
        self.wallet_transitioning = False
        self._set_daemon_controls_enabled(True)
        self.mine_btn.config(state="normal" if self.mining_ready else "disabled")
        self.status_var.set(message)
        if self.refresh_after_id is None:
            self._schedule_auto_refresh()

    def _restore_wallet_completed(self):
        self.wallet_transitioning = False
        messagebox.showinfo(
            "Restore Wallet",
            "The Pi wallet was restored successfully.\n\n"
            "Its existing password is still required to send PI.",
            parent=self.root,
        )

    def _restore_wallet_initialization_failed(self):
        self.wallet_transitioning = False
        self.status_var.set(
            "The wallet was restored, but Pi Wallet could not initialize it. "
            "Restart Pi Wallet to retry."
        )

    def send_pi(self):
        addr = self.send_addr_var.get().strip()
        amt = self.send_amt_var.get().strip()
        if not addr or not amt:
            messagebox.showwarning("Send", "Enter address and amount.")
            return
        try:
            amount = Decimal(amt)
            if not amount.is_finite():
                raise InvalidOperation
        except InvalidOperation:
            messagebox.showwarning("Send", "Enter a valid amount.")
            return
        if not messagebox.askyesno("Confirm", f"Send {amt} PI to\n{addr}?"):
            return
        passphrase = None
        if self.wallet_encrypted:
            passphrase = simpledialog.askstring(
                "Unlock Pi Wallet",
                "Enter your wallet password to send PI:",
                show="*",
                parent=self.root,
            )
            if passphrase is None:
                return
            if not passphrase:
                messagebox.showwarning(
                    "Send",
                    "Enter your wallet password.",
                    parent=self.root,
                )
                return
        self.status_var.set("Sending...")
        self._start_worker(
            self._send_pi_unlocked,
            "wallet-send",
            addr,
            amount,
            passphrase,
        )

    def _send_pi_unlocked(self, addr, amount, passphrase):
        unlocked = False
        try:
            if passphrase is not None:
                success, _ = self._wallet_rpc_with_status(
                    "walletpassphrase",
                    [passphrase, WALLET_UNLOCK_SECONDS],
                )
                if not success:
                    self._queue_ui(
                        self.status_var.set,
                        rpc_error("Wallet unlock failed."),
                    )
                    return
                unlocked = True

            success, _ = self._wallet_rpc_with_status(
                "sendtoaddress",
                [addr, amount],
            )
            if success:
                self._queue_ui(self.status_var.set, "Sent!")
                self._queue_ui(self.send_addr_var.set, "")
                self._queue_ui(self.send_amt_var.set, "")
                self._queue_ui(self._request_balance_update)
            else:
                self._queue_ui(
                    self.status_var.set,
                    rpc_error("Send failed."),
                )
        finally:
            if unlocked:
                success, _ = self._wallet_rpc_with_status("walletlock")
                if not success:
                    self._queue_ui(
                        self.status_var.set,
                        rpc_error("PI was sent, but the wallet could not be relocked."),
                    )

    def toggle_mine(self):
        if not self.mining:
            if not self.mining_ready:
                self.status_var.set("Pi must be connected and synchronized before mining.")
                return
            if self.mining_thread is not None and self.mining_thread.is_alive():
                return
            self.mining = True
            self.stop_event = threading.Event()
            self.mine_btn.config(text="⏹  Stop Mining", bg="#333333")
            self.status_var.set("Mining...")
            self.mining_thread = self._start_worker(
                self._mine_loop, "wallet-miner", self.stop_event
            )
        else:
            self.mining = False
            self.stop_event.set()
            self.mine_btn.config(
                text="Stopping mining...", bg="#333333", state="disabled"
            )
            self.status_var.set("Stopping mining...")

    def _mine_loop(self, stop_event):
        try:
            while not stop_event.is_set():
                addr = self.current_address
                if addr and addr != "Connecting...":
                    result = self._wallet_rpc(
                        "generatetoaddress",
                        [1, addr, MINING_MAX_TRIES],
                    )
                    if stop_event.is_set():
                        break
                    if result:
                        self.blocks_mined += 1
                        self._queue_ui(
                            self.blocks_var.set,
                            f"Blocks mined this session: {self.blocks_mined}",
                        )
                        info = self._wallet_rpc("getwalletinfo")
                        if info:
                            mature = float(info.get("balance", 0))
                            immature = float(info.get("immature_balance", 0))
                            self._queue_ui(self._set_balance, mature, immature)
                        self._queue_ui(
                            self.status_var.set,
                            f"Block {self.blocks_mined} mined! +50 PI",
                        )
                    if stop_event.wait(MINING_RETRY_DELAY):
                        break
        finally:
            self._queue_ui(self._mining_finished, stop_event)

    def _mining_finished(self, stop_event):
        if stop_event is not self.stop_event:
            return
        self.mining = False
        self.mining_thread = None
        self.mine_btn.config(
            text="⛏  Start Mining", bg="#111111", state="disabled"
        )
        self.status_var.set("Mining stopped.")
        self._request_balance_update()
        self._request_mining_readiness()

    def on_close(self):
        if self.closing or self.close_requested:
            return
        if self.mining:
            if not messagebox.askokcancel("Quit", "Mining is running. Stop and close?"):
                return
        self.close_requested = True
        self._set_daemon_controls_enabled(False)
        self.status_var.set("Checking Pi Core...")
        self._start_worker(self._check_sync_before_close, "daemon-sync-check")

    def _check_sync_before_close(self):
        syncing = False
        if self.daemon_controller.ownership == "managed":
            syncing = self.daemon_controller.is_syncing() is True
        self._queue_ui(self._confirm_syncing_close, syncing)

    def _confirm_syncing_close(self, syncing):
        if not self.close_requested or self.closing:
            return
        if syncing and not messagebox.askokcancel(
            "Quit",
            "Pi Core is still syncing. Stop Pi Core and close Pi Wallet?",
        ):
            self.close_requested = False
            self._set_daemon_controls_enabled(
                self.daemon_controller.ownership in ("external", "managed")
            )
            self.status_var.set("")
            return
        self._begin_close()

    def _begin_close(self):
        if self.closing:
            return
        self.closing = True
        self.daemon_controller.cancel()
        self.mining = False
        self.stop_event.set()
        self._set_daemon_controls_enabled(False)
        self.status_var.set("Closing...")
        for after_id in (self.ui_after_id, self.refresh_after_id):
            if after_id is not None:
                try:
                    self.root.after_cancel(after_id)
                except tk.TclError:
                    pass
        self._wait_for_workers()

    def _wait_for_workers(self):
        with self.workers_lock:
            active = any(worker.is_alive() for worker in self.workers)
        if active:
            self.close_after_id = self.root.after(50, self._wait_for_workers)
            return
        self._shutdown_daemon_then_destroy()

    def _shutdown_daemon_then_destroy(self):
        if self.daemon_controller.ownership != "managed":
            self.root.destroy()
            return
        if not self.daemon_shutdown_started:
            self.daemon_shutdown_started = True
            self.daemon_shutdown_thread = threading.Thread(
                target=self.daemon_controller.shutdown_managed,
                name="daemon-shutdown",
            )
            self.daemon_shutdown_thread.start()
        self._wait_for_daemon_shutdown()

    def _wait_for_daemon_shutdown(self):
        if (
            self.daemon_shutdown_thread is not None
            and self.daemon_shutdown_thread.is_alive()
        ):
            self.close_after_id = self.root.after(
                50, self._wait_for_daemon_shutdown
            )
            return
        self.root.destroy()

if __name__ == "__main__":
    root = tk.Tk()
    PiWallet(root)
    root.mainloop()
