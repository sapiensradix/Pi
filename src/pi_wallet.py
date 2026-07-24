from pathlib import Path
import subprocess
#!/usr/bin/env python3
import tkinter as tk
from tkinter import messagebox, simpledialog, scrolledtext
import base64
from decimal import Decimal, InvalidOperation
import json
import os
import socket
import sys
import threading
import time
import urllib.error
import urllib.request

RPC_TIMEOUT = 10


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
DIR = os.path.dirname(os.path.abspath(__file__))
PI_BIN = os.path.join(DIR, "pi")
_RPC_STATE = threading.local()


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


def _rpc_request(method, params=None):
    try:
        conf = read_conf()
    except OSError as exc:
        raise PiRPCError("pi.conf cannot be read.", kind="config") from exc
    try:
        port = int(conf.get("rpcport", "8332"))
    except (TypeError, ValueError) as exc:
        raise PiRPCError("pi.conf contains an invalid rpcport.", kind="config") from exc
    if not 1 <= port <= 65535:
        raise PiRPCError("pi.conf contains an invalid rpcport.", kind="config")

    url = f"http://127.0.0.1:{port}"
    payload = json.dumps(
        {
            "jsonrpc": "1.0",
            "id": "wallet",
            "method": method,
            "params": _json_value(params if params is not None else []),
        },
        separators=(",", ":"),
    ).encode("utf-8")

    for attempt in range(2):
        username, password, auth_source = _read_auth(conf)
        credentials = f"{username}:{password}"
        auth = base64.b64encode(credentials.encode("utf-8")).decode("ascii")
        secrets = (username, password, credentials, auth)
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


def rpc_with_status(method, params=None):
    try:
        result = _rpc_request(method, params)
    except PiRPCError as exc:
        _RPC_STATE.error = str(exc)
        return False, None
    _RPC_STATE.error = ""
    return True, result


def rpc(method, params=None):
    success, result = rpc_with_status(method, params)
    return result if success else None


def rpc_error(default="Pi Core RPC request failed."):
    return getattr(_RPC_STATE, "error", "") or default

class PiWallet:
    def __init__(self, root):
        self.root = root
        self.root.title("Pi Wallet")
        self.root.geometry("520x760")
        self.root.configure(bg="white")
        self.root.resizable(False, False)
        self.mining = False
        self.blocks_mined = 0
        self.stop_event = threading.Event()
        self.root.protocol("WM_DELETE_WINDOW", self.on_close)
        self.build_ui()
        threading.Thread(target=self._init, daemon=True).start()

    def _init(self):
        self.status_var.set("Connecting...")
        addr = rpc("getnewaddress")
        if addr:
            self.address_var.set(addr)
            self.status_var.set("")
        else:
            self.status_var.set(rpc_error("Cannot connect to Pi Core."))
            return
        info = rpc("getwalletinfo")
        if info:
            mature = info.get("balance", Decimal("0"))
            immature = info.get("immature_balance", Decimal("0"))
            self.balance_var.set(f"Spendable: {mature:.8f} PI")
            self.blocks_var.set(f"Mining rewards: {immature:.8f} PI")
        else:
            self.status_var.set(rpc_error())
        self.root.after(10000, self._auto_refresh)

    def _auto_refresh(self):
        if not self.mining:
            threading.Thread(target=self._update_balance, daemon=True).start()
        self.root.after(10000, self._auto_refresh)

    def _update_balance(self):
        info = rpc("getwalletinfo")
        if info:
            mature = info.get("balance", Decimal("0"))
            immature = info.get("immature_balance", Decimal("0"))
            self.balance_var.set(f"Spendable: {mature:.8f} PI")
            self.blocks_var.set(f"Mining rewards: {immature:.8f} PI")
        else:
            self.status_var.set(rpc_error())

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
        tk.Button(bf2, text="Copy", command=self.copy_address, font=("Helvetica", 10, "bold"), fg="white", bg="#111111", relief="flat", cursor="hand2", padx=12, pady=5).pack(side="left")
        tk.Button(bf2, text="New Address", command=self.new_address, font=("Helvetica", 10, "bold"), fg="#111111", bg="white", relief="solid", bd=2, cursor="hand2", padx=12, pady=5).pack(side="left", padx=(8,0))
        tk.Button(bf2, text="History", command=self.show_history, font=("Helvetica", 10, "bold"), fg="#111111", bg="white", relief="solid", bd=2, cursor="hand2", padx=12, pady=5).pack(side="left", padx=(8,0))
        tk.Button(bf2, text="Backup Key", command=self.backup_key, font=("Helvetica", 10, "bold"), fg="#111111", bg="white", relief="solid", bd=2, cursor="hand2", padx=12, pady=5).pack(side="left", padx=(8,0))

        tk.Frame(self.root, height=1, bg="#cccccc").pack(fill="x", padx=30)

        imp_f = tk.Frame(self.root, bg="white", padx=30)
        imp_f.pack(fill="x", pady=8)
        tk.Label(imp_f, text="IMPORT WALLET", font=("Helvetica", 10, "bold"), fg="#555555", bg="white").pack(anchor="w")
        self.import_var = tk.StringVar()
        tk.Entry(imp_f, textvariable=self.import_var, font=("Courier", 9), fg="#111111", bg="#f0f0f0", relief="flat", bd=1).pack(fill="x", pady=4, ipady=6)
        tk.Button(imp_f, text="Import Private Key →", command=self.import_key, font=("Helvetica", 10, "bold"), fg="white", bg="#111111", relief="flat", cursor="hand2", padx=12, pady=5).pack(anchor="e", pady=2)

        tk.Frame(self.root, height=1, bg="#cccccc").pack(fill="x", padx=30)

        sf = tk.Frame(self.root, bg="white", padx=30)
        sf.pack(fill="x", pady=8)
        tk.Label(sf, text="SEND PI", font=("Helvetica", 10, "bold"), fg="#555555", bg="white").pack(anchor="w")
        self.send_addr_var = tk.StringVar()
        tk.Entry(sf, textvariable=self.send_addr_var, font=("Courier", 9), fg="#111111", bg="#f0f0f0", relief="flat", bd=1).pack(fill="x", pady=4, ipady=6)
        self.send_amt_var = tk.StringVar()
        tk.Entry(sf, textvariable=self.send_amt_var, font=("Helvetica", 10), fg="#111111", bg="#f0f0f0", relief="flat", bd=1).pack(fill="x", pady=4, ipady=6)
        tk.Button(sf, text="Send →", command=self.send_pi, font=("Helvetica", 11, "bold"), fg="white", bg="#111111", relief="flat", cursor="hand2", padx=20, pady=6).pack(anchor="e", pady=2)

        tk.Frame(self.root, height=1, bg="#cccccc").pack(fill="x", padx=30)

        mf = tk.Frame(self.root, bg="white", padx=30)
        mf.pack(fill="x", pady=10)
        self.mine_btn = tk.Button(mf, text="⛏  Start Mining", command=self.toggle_mine,
            font=("Helvetica", 13, "bold"), fg="white", bg="#111111",
            relief="flat", cursor="hand2", padx=20, pady=10)
        self.mine_btn.pack(fill="x")

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
            a = rpc("getnewaddress")
            if a:
                self.address_var.set(a)
                self.status_var.set("New address created!")
            else:
                self.status_var.set(rpc_error("Could not create a new address."))
        threading.Thread(target=_n, daemon=True).start()

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
            result = rpc("listreceivedbyaddress", [0, True])
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
            win.after(0, lambda: [txt.delete("1.0", "end"), txt.insert("end", text)])
        threading.Thread(target=_load, daemon=True).start()

    def backup_key(self):
        addr = self.address_var.get()
        if not addr or addr in ("Connecting...",):
            messagebox.showwarning("Backup", "No address loaded yet.")
            return
        def _dump():
            key = rpc("dumpprivkey", [addr])
            if key:
                win = tk.Toplevel(self.root)
                win.title("Private Key")
                win.geometry("480x180")
                win.configure(bg="white")
                tk.Label(win, text="KEEP SECRET! Anyone with this key owns your PI.", font=("Helvetica", 10, "bold"), fg="red", bg="white").pack(pady=8)
                entry = tk.Entry(win, font=("Courier", 9), bg="#f0f0f0", relief="flat")
                entry.pack(pady=4, padx=20, fill="x")
                entry.insert(0, key)
                entry.config(state="readonly")
                tk.Button(win, text="Copy Key", command=lambda: [win.clipboard_clear(), win.clipboard_append(key)],
                    font=("Helvetica", 10, "bold"), fg="white", bg="#111111", relief="flat", padx=12, pady=5).pack()
            else:
                messagebox.showerror("Backup", rpc_error("Could not export key."))
        threading.Thread(target=_dump, daemon=True).start()

    def import_key(self):
        key = self.import_var.get().strip()
        if not key:
            messagebox.showwarning("Import", "Enter a private key first.")
            return
        if not messagebox.askyesno("Import", "Import this private key?"):
            return
        def _imp():
            self.status_var.set("Importing...")
            success, _ = rpc_with_status("importprivkey", [key, "", True])
            if success:
                self.status_var.set("Import successful!")
                self.import_var.set("")
                threading.Thread(target=self._update_balance, daemon=True).start()
            else:
                self.status_var.set(rpc_error("Import failed."))
        threading.Thread(target=_imp, daemon=True).start()

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
        if messagebox.askyesno("Confirm", f"Send {amt} PI to\n{addr}?"):
            def _s():
                success, _ = rpc_with_status("sendtoaddress", [addr, amount])
                self.status_var.set("Sent!" if success else rpc_error("Send failed."))
                if success:
                    self.send_addr_var.set("")
                    self.send_amt_var.set("")
                    threading.Thread(target=self._update_balance, daemon=True).start()
            threading.Thread(target=_s, daemon=True).start()

    def toggle_mine(self):
        if not self.mining:
            self.mining = True
            self.stop_event.clear()
            self.mine_btn.config(text="⏹  Stop Mining", bg="#333333")
            self.status_var.set("Mining...")
            threading.Thread(target=self._mine_loop, daemon=True).start()
        else:
            self.mining = False
            self.stop_event.set()
            self.mine_btn.config(text="⛏  Start Mining", bg="#111111")
            self.status_var.set("Mining stopped.")
            threading.Thread(target=self._update_balance, daemon=True).start()

    def _mine_loop(self):
        while self.mining and not self.stop_event.is_set():
            addr = self.address_var.get()
            if addr and addr != "Connecting...":
                result = rpc("generatetoaddress", [1, addr])
                if self.stop_event.is_set():
                    break
                if result:
                    self.blocks_mined += 1
                    self.blocks_var.set(f"Blocks mined this session: {self.blocks_mined}")
                    info = rpc("getwalletinfo")
                    if info:
                        mature = float(info.get("balance", 0))
                        immature = float(info.get("immature_balance", 0))
                        self.balance_var.set(f"Spendable: {mature:.8f} PI")
                        self.blocks_var.set(f"Mining rewards: {immature:.8f} PI")
                    self.status_var.set(f"Block {self.blocks_mined} mined! +50 PI")
                time.sleep(1)


    def force_restart_node(self):
        """Stop stuck mining RPC by killing pid, then restart clean node."""
        try:
            subprocess.run(["pkill", "pid"], timeout=3)
        except Exception:
            pass

        time.sleep(2)

        try:
            subprocess.Popen([
                "./pid",
                f"-conf={str(Path.home() / 'Library/Application Support/Pi/pi.conf')}",
                "-daemon"
            ], cwd=str(Path.home() / "pi/src"))
        except Exception as e:
            print("restart node failed:", e)

    def on_close(self):
        if self.mining:
            if not messagebox.askokcancel("Quit", "Mining is running. Stop and close?"):
                return
        self.mining = False
        self.stop_event.set()
        self.root.destroy()

if __name__ == "__main__":
    root = tk.Tk()
    PiWallet(root)
    root.mainloop()
