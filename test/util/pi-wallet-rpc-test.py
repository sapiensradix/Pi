#!/usr/bin/env python3

import base64
from contextlib import redirect_stderr, redirect_stdout
from decimal import Decimal
import importlib.util
import io
from pathlib import Path
import socket
import tempfile
import unittest
from unittest.mock import patch
import urllib.error


SOURCE = Path(__file__).resolve().parents[2] / "src" / "pi_wallet.py"
SPEC = importlib.util.spec_from_file_location("pi_wallet", SOURCE)
pi_wallet = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(pi_wallet)


class BundledExecutablePathTest(unittest.TestCase):
    def test_windows_runtime_uses_exe_suffix(self):
        directory = Path("C:/Pi Wallet")
        self.assertEqual(
            pi_wallet.bundled_executable_path("pid", "win32", directory),
            str(directory / "pid.exe"),
        )
        self.assertEqual(
            pi_wallet.bundled_executable_path("tor", "win32", directory),
            str(directory / "tor.exe"),
        )

    def test_unix_runtime_has_no_executable_suffix(self):
        directory = Path("/opt/pi-wallet")
        for platform in ("darwin", "linux"):
            self.assertEqual(
                pi_wallet.bundled_executable_path("pid", platform, directory),
                str(directory / "pid"),
            )
            self.assertEqual(
                pi_wallet.bundled_executable_path("tor", platform, directory),
                str(directory / "tor"),
            )


class Response:
    def __init__(self, body):
        self.body = body
        self.status = 200

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc_value, traceback):
        return False

    def read(self):
        return self.body


class PiWalletRPCTest(unittest.TestCase):
    def setUp(self):
        self.tempdir = tempfile.TemporaryDirectory()
        self.datadir = Path(self.tempdir.name)
        self.cookie = self.datadir / ".cookie"
        self.cookie.write_text("__cookie__:secret-one", encoding="utf-8")
        self.datadir_patch = patch.object(pi_wallet, "DATADIR", self.datadir)
        self.conf_patch = patch.object(
            pi_wallet, "CONF_PATH", self.datadir / "pi.conf"
        )
        self.datadir_patch.start()
        self.conf_patch.start()

    def tearDown(self):
        self.conf_patch.stop()
        self.datadir_patch.stop()
        self.tempdir.cleanup()

    def response(self, result=None, error=None):
        body = pi_wallet.json.dumps(
            {"result": result, "error": error, "id": "wallet"}
        ).encode("utf-8")
        return Response(body)

    def test_default_cookie_paths(self):
        home = Path("/home/pi-user")
        self.assertEqual(
            pi_wallet.default_pi_datadir("darwin", {}, home),
            home / "Library" / "Application Support" / "Pi",
        )
        self.assertEqual(
            pi_wallet.default_pi_datadir("linux", {}, home),
            home / ".pi",
        )
        self.assertEqual(
            pi_wallet.default_pi_datadir(
                "win32", {"APPDATA": "C:/Users/pi-user/AppData/Roaming"}, home
            ),
            Path("C:/Users/pi-user/AppData/Roaming") / "Pi",
        )

    def test_valid_cookie_authentication(self):
        def urlopen(request, timeout):
            expected = base64.b64encode(b"__cookie__:secret-one").decode("ascii")
            self.assertEqual(request.get_header("Authorization"), f"Basic {expected}")
            self.assertEqual(timeout, pi_wallet.RPC_TIMEOUT)
            return self.response(result=17)

        with patch.object(pi_wallet.urllib.request, "urlopen", side_effect=urlopen):
            success, result = pi_wallet.rpc_with_status("getblockcount")
        self.assertTrue(success)
        self.assertEqual(result, 17)

    def test_wallet_rpc_uses_encoded_wallet_endpoint(self):
        def urlopen(request, timeout):
            self.assertEqual(
                request.full_url,
                "http://127.0.0.1:8332/wallet/pi%20wallet",
            )
            return self.response(result={"walletname": "pi wallet"})

        with patch.object(pi_wallet.urllib.request, "urlopen", side_effect=urlopen):
            success, result = pi_wallet.rpc_with_status(
                "getwalletinfo", wallet="pi wallet"
            )
        self.assertTrue(success)
        self.assertEqual(result["walletname"], "pi wallet")

    def test_config_credentials_fallback_when_cookie_is_missing(self):
        self.cookie.unlink()
        pi_wallet.CONF_PATH.write_text(
            "rpcuser=config-user\nrpcpassword=config-secret\nrpcport=18443\n",
            encoding="utf-8",
        )

        def urlopen(request, timeout):
            expected = base64.b64encode(b"config-user:config-secret").decode("ascii")
            self.assertEqual(request.get_header("Authorization"), f"Basic {expected}")
            self.assertEqual(request.full_url, "http://127.0.0.1:18443")
            return self.response(result=18)

        with patch.object(pi_wallet.urllib.request, "urlopen", side_effect=urlopen):
            success, result = pi_wallet.rpc_with_status("getblockcount")
        self.assertTrue(success)
        self.assertEqual(result, 18)

    def test_cookie_takes_precedence_over_config_credentials(self):
        pi_wallet.CONF_PATH.write_text(
            "rpcuser=config-user\nrpcpassword=config-secret\n",
            encoding="utf-8",
        )

        def urlopen(request, timeout):
            expected = base64.b64encode(b"__cookie__:secret-one").decode("ascii")
            self.assertEqual(request.get_header("Authorization"), f"Basic {expected}")
            return self.response(result=True)

        with patch.object(pi_wallet.urllib.request, "urlopen", side_effect=urlopen):
            success, result = pi_wallet.rpc_with_status("getwalletinfo")
        self.assertTrue(success)
        self.assertTrue(result)

    def test_successful_null_result_is_not_an_rpc_failure(self):
        with patch.object(
            pi_wallet.urllib.request,
            "urlopen",
            return_value=self.response(result=None, error=None),
        ):
            success, result = pi_wallet.rpc_with_status("importprivkey")
        self.assertTrue(success)
        self.assertIsNone(result)
        self.assertEqual(getattr(pi_wallet._RPC_STATE, "error", None), "")

    def test_cookie_missing(self):
        self.cookie.unlink()
        with patch.object(pi_wallet.urllib.request, "urlopen") as urlopen:
            success, result = pi_wallet.rpc_with_status("getblockcount")
        self.assertFalse(success)
        self.assertIsNone(result)
        self.assertIn("credentials are unavailable", pi_wallet.rpc_error())
        urlopen.assert_not_called()

    def test_incomplete_config_credentials_are_rejected(self):
        self.cookie.unlink()
        pi_wallet.CONF_PATH.write_text("rpcuser=config-user\n", encoding="utf-8")
        with patch.object(pi_wallet.urllib.request, "urlopen") as urlopen:
            success, result = pi_wallet.rpc_with_status("getblockcount")
        self.assertFalse(success)
        self.assertIsNone(result)
        self.assertIn("configure both rpcuser and rpcpassword", pi_wallet.rpc_error())
        urlopen.assert_not_called()

    def test_stale_cookie_is_reloaded_after_auth_failure(self):
        calls = []

        def urlopen(request, timeout):
            calls.append(request.get_header("Authorization"))
            if len(calls) == 1:
                self.cookie.write_text("__cookie__:secret-two", encoding="utf-8")
                raise urllib.error.HTTPError(
                    request.full_url, 401, "Unauthorized", {}, io.BytesIO(b"")
                )
            return self.response(result=True)

        with patch.object(pi_wallet.urllib.request, "urlopen", side_effect=urlopen):
            success, result = pi_wallet.rpc_with_status("getwalletinfo")
        self.assertTrue(success)
        self.assertTrue(result)
        self.assertEqual(len(calls), 2)
        self.assertNotEqual(calls[0], calls[1])

    def test_wrong_cookie_is_reported_after_one_retry(self):
        error = urllib.error.HTTPError(
            "http://127.0.0.1:8332", 401, "Unauthorized", {}, io.BytesIO(b"")
        )
        with patch.object(
            pi_wallet.urllib.request, "urlopen", side_effect=[error, error]
        ) as urlopen:
            success, result = pi_wallet.rpc_with_status("getblockcount")
        self.assertFalse(success)
        self.assertIsNone(result)
        self.assertIn("rejected the RPC cookie", pi_wallet.rpc_error())
        self.assertEqual(urlopen.call_count, 2)

    def test_wrong_config_credentials_are_reported_after_one_retry(self):
        self.cookie.unlink()
        pi_wallet.CONF_PATH.write_text(
            "rpcuser=config-user\nrpcpassword=config-secret\n",
            encoding="utf-8",
        )
        error = urllib.error.HTTPError(
            "http://127.0.0.1:8332", 401, "Unauthorized", {}, io.BytesIO(b"")
        )
        with patch.object(
            pi_wallet.urllib.request, "urlopen", side_effect=[error, error]
        ) as urlopen:
            success, result = pi_wallet.rpc_with_status("getblockcount")
        self.assertFalse(success)
        self.assertIsNone(result)
        self.assertIn("credentials from pi.conf", pi_wallet.rpc_error())
        self.assertNotIn("config-secret", pi_wallet.rpc_error())
        self.assertEqual(urlopen.call_count, 2)

    def test_connection_refused(self):
        error = urllib.error.URLError(ConnectionRefusedError())
        with patch.object(pi_wallet.urllib.request, "urlopen", side_effect=error):
            success, _ = pi_wallet.rpc_with_status("getblockcount")
        self.assertFalse(success)
        self.assertIn("daemon may not be running", pi_wallet.rpc_error())

    def test_timeout(self):
        with patch.object(
            pi_wallet.urllib.request, "urlopen", side_effect=socket.timeout()
        ):
            success, _ = pi_wallet.rpc_with_status("getblockcount")
        self.assertFalse(success)
        self.assertIn("timed out", pi_wallet.rpc_error())

    def test_invalid_json(self):
        with patch.object(
            pi_wallet.urllib.request, "urlopen", return_value=Response(b"not-json")
        ):
            success, _ = pi_wallet.rpc_with_status("getblockcount")
        self.assertFalse(success)
        self.assertIn("invalid JSON", pi_wallet.rpc_error())

    def test_missing_result_or_error(self):
        with patch.object(
            pi_wallet.urllib.request,
            "urlopen",
            return_value=Response(b'{"id":"wallet"}'),
        ):
            success, _ = pi_wallet.rpc_with_status("getblockcount")
        self.assertFalse(success)
        self.assertIn("missing result or error", pi_wallet.rpc_error())

    def test_json_rpc_error_and_wallet_not_loaded(self):
        with patch.object(
            pi_wallet.urllib.request,
            "urlopen",
            return_value=self.response(
                error={"code": -18, "message": "Requested wallet does not exist"}
            ),
        ):
            success, _ = pi_wallet.rpc_with_status("getwalletinfo")
        self.assertFalse(success)
        self.assertEqual(pi_wallet.rpc_error(), "No Pi wallet is loaded.")

    def test_method_not_found_and_daemon_startup_errors(self):
        with patch.object(
            pi_wallet.urllib.request,
            "urlopen",
            return_value=self.response(
                error={"code": -32601, "message": "Method not found"}
            ),
        ):
            success, _ = pi_wallet.rpc_with_status("unknownmethod")
        self.assertFalse(success)
        self.assertEqual(
            pi_wallet.rpc_error(), "Pi Core RPC method not found: unknownmethod."
        )

        with patch.object(
            pi_wallet.urllib.request,
            "urlopen",
            return_value=self.response(
                error={"code": -28, "message": "Loading block index..."}
            ),
        ):
            success, _ = pi_wallet.rpc_with_status("getblockcount")
        self.assertFalse(success)
        self.assertIn("starting or shutting down", pi_wallet.rpc_error())

    def test_exact_decimal_amount_is_encoded_as_a_string(self):
        bodies = []

        def urlopen(request, timeout):
            bodies.append(pi_wallet.json.loads(request.data))
            return self.response(result="transaction-id")

        with patch.object(pi_wallet.urllib.request, "urlopen", side_effect=urlopen):
            success, result = pi_wallet.rpc_with_status(
                "sendtoaddress", ["pi-address", Decimal("0.10000000")]
            )
        self.assertTrue(success)
        self.assertEqual(result, "transaction-id")
        self.assertEqual(bodies[0]["params"][1], "0.10000000")

    def test_rpc_credentials_are_redacted_from_errors(self):
        exposed = "__cookie__:secret-one"
        stdout = io.StringIO()
        stderr = io.StringIO()
        with redirect_stdout(stdout), redirect_stderr(stderr):
            with patch.object(
                pi_wallet.urllib.request,
                "urlopen",
                return_value=self.response(
                    error={"code": -1, "message": f"authentication {exposed} failed"}
                ),
            ):
                success, _ = pi_wallet.rpc_with_status("getblockcount")
        self.assertFalse(success)
        self.assertNotIn("__cookie__", pi_wallet.rpc_error())
        self.assertNotIn("secret-one", pi_wallet.rpc_error())
        self.assertIn("[redacted]", pi_wallet.rpc_error())
        self.assertEqual(stdout.getvalue(), "")
        self.assertEqual(stderr.getvalue(), "")


if __name__ == "__main__":
    unittest.main()
