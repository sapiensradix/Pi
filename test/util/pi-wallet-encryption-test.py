#!/usr/bin/env python3

from decimal import Decimal
import importlib.util
from pathlib import Path
import unittest
from unittest.mock import call, Mock, patch


SOURCE = Path(__file__).resolve().parents[2] / "src" / "pi_wallet.py"
SPEC = importlib.util.spec_from_file_location("pi_wallet", SOURCE)
pi_wallet = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(pi_wallet)


class WalletEncryptionTest(unittest.TestCase):
    def wallet(self):
        wallet = pi_wallet.PiWallet.__new__(pi_wallet.PiWallet)
        wallet.active_wallet = pi_wallet.DEFAULT_WALLET_NAME
        wallet.wallet_encrypted = True
        wallet.closing = False
        wallet.ui_queue = pi_wallet.queue.Queue()
        return wallet

    def test_creates_descriptor_wallet_with_passphrase(self):
        wallet = self.wallet()
        responses = [
            [],
            {"wallets": []},
            {"name": pi_wallet.DEFAULT_WALLET_NAME},
            [pi_wallet.DEFAULT_WALLET_NAME],
        ]
        with patch.object(
            pi_wallet, "_rpc_request", side_effect=responses
        ) as rpc_mock:
            name = wallet._ensure_wallet(passphrase="correct horse battery staple")

        self.assertEqual(name, pi_wallet.DEFAULT_WALLET_NAME)
        self.assertEqual(
            rpc_mock.call_args_list,
            [
                call("listwallets"),
                call("listwalletdir"),
                call(
                    "createwallet",
                    [
                        pi_wallet.DEFAULT_WALLET_NAME,
                        False,
                        False,
                        "correct horse battery staple",
                        False,
                        True,
                        True,
                    ],
                ),
                call("listwallets"),
            ],
        )

    def test_encrypts_existing_wallet_through_wallet_endpoint(self):
        wallet = self.wallet()
        with patch.object(wallet, "_finish_wallet_init") as finish_mock:
            with patch.object(pi_wallet, "_rpc_request") as rpc_mock:
                wallet._encrypt_existing_wallet("local secret")

        rpc_mock.assert_called_once_with(
            "encryptwallet",
            ["local secret"],
            wallet=pi_wallet.DEFAULT_WALLET_NAME,
        )
        finish_mock.assert_called_once_with()

    def test_encrypted_wallet_is_detected_from_wallet_info(self):
        wallet = self.wallet()
        responses = {
            "getnewaddress": "pi1qaddress",
            "getwalletinfo": {
                "unlocked_until": 0,
                "balance": Decimal("1.0"),
                "immature_balance": Decimal("2.0"),
            },
        }
        wallet._wallet_rpc = lambda method, params=None: responses[method]
        wallet._queue_ui = lambda callback, *args: None

        wallet._finish_wallet_init()

        self.assertTrue(wallet.wallet_encrypted)

    def test_unencrypted_wallet_requests_password_setup(self):
        wallet = self.wallet()
        wallet.wallet_encrypted = False
        queued = []
        wallet._queue_ui = lambda callback, *args: queued.append((callback, args))
        responses = {
            "getnewaddress": "pi1qaddress",
            "getwalletinfo": {
                "balance": Decimal("0"),
                "immature_balance": Decimal("0"),
            },
        }
        wallet._wallet_rpc = lambda method, params=None: responses[method]

        wallet._finish_wallet_init()

        self.assertFalse(wallet.wallet_encrypted)
        self.assertIn((wallet._prompt_encrypt_existing_wallet, ()), queued)

    def test_send_unlocks_then_relocks_encrypted_wallet(self):
        wallet = self.wallet()
        calls = []
        wallet.status_var = Mock()
        wallet.send_addr_var = Mock()
        wallet.send_amt_var = Mock()
        wallet._request_balance_update = lambda: None
        wallet._queue_ui = lambda callback, *args: None

        def rpc_call(method, params=None):
            calls.append((method, params))
            return True, None

        wallet._wallet_rpc_with_status = rpc_call
        wallet._send_pi_unlocked(
            "pi1qdestination",
            Decimal("0.10000000"),
            "wallet secret",
        )

        self.assertEqual(
            calls,
            [
                (
                    "walletpassphrase",
                    ["wallet secret", pi_wallet.WALLET_UNLOCK_SECONDS],
                ),
                ("sendtoaddress", ["pi1qdestination", Decimal("0.10000000")]),
                ("walletlock", None),
            ],
        )

    def test_wrong_password_does_not_send_or_lock(self):
        wallet = self.wallet()
        wallet.status_var = Mock()
        wallet._queue_ui = lambda callback, *args: None
        calls = []

        def rpc_call(method, params=None):
            calls.append((method, params))
            return False, None

        wallet._wallet_rpc_with_status = rpc_call
        with patch.object(pi_wallet, "rpc_error", return_value="Incorrect password"):
            wallet._send_pi_unlocked(
                "pi1qdestination",
                Decimal("0.10000000"),
                "wrong password",
            )

        self.assertEqual(
            calls,
            [
                (
                    "walletpassphrase",
                    ["wrong password", pi_wallet.WALLET_UNLOCK_SECONDS],
                )
            ],
        )

    def test_sensitive_wallet_error_redacts_passphrase(self):
        response = type(
            "Response",
            (),
            {
                "status": 200,
                "__enter__": lambda self: self,
                "__exit__": lambda self, *args: False,
                "read": lambda self: pi_wallet.json.dumps(
                    {
                        "result": None,
                        "error": {
                            "code": -14,
                            "message": "incorrect secret-passphrase",
                        },
                        "id": "wallet",
                    }
                ).encode("utf-8"),
            },
        )()
        with patch.object(pi_wallet, "_read_auth", return_value=("user", "rpc", "cookie")):
            with patch.object(pi_wallet.urllib.request, "urlopen", return_value=response):
                success, _ = pi_wallet.rpc_with_status(
                    "walletpassphrase",
                    ["secret-passphrase", pi_wallet.WALLET_UNLOCK_SECONDS],
                )

        self.assertFalse(success)
        self.assertNotIn("secret-passphrase", pi_wallet.rpc_error())
        self.assertIn("[redacted]", pi_wallet.rpc_error())


if __name__ == "__main__":
    unittest.main()
