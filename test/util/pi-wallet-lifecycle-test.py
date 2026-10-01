#!/usr/bin/env python3

import importlib.util
from pathlib import Path
import unittest
from unittest.mock import call, patch


SOURCE = Path(__file__).resolve().parents[2] / "src" / "pi_wallet.py"
SPEC = importlib.util.spec_from_file_location("pi_wallet", SOURCE)
pi_wallet = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(pi_wallet)


class WalletLifecycleTest(unittest.TestCase):
    def wallet(self):
        wallet = pi_wallet.PiWallet.__new__(pi_wallet.PiWallet)
        wallet.active_wallet = None
        return wallet

    def test_reuses_loaded_default_wallet(self):
        with patch.object(
            pi_wallet,
            "_rpc_request",
            return_value=[pi_wallet.DEFAULT_WALLET_NAME],
        ) as rpc_mock:
            name = self.wallet()._ensure_wallet()

        self.assertEqual(name, pi_wallet.DEFAULT_WALLET_NAME)
        rpc_mock.assert_called_once_with("listwallets")

    def test_loads_default_wallet_from_wallet_directory(self):
        responses = [
            [],
            {"wallets": [{"name": pi_wallet.DEFAULT_WALLET_NAME}]},
            {"name": pi_wallet.DEFAULT_WALLET_NAME},
            [pi_wallet.DEFAULT_WALLET_NAME],
        ]
        with patch.object(
            pi_wallet, "_rpc_request", side_effect=responses
        ) as rpc_mock:
            name = self.wallet()._ensure_wallet()

        self.assertEqual(name, pi_wallet.DEFAULT_WALLET_NAME)
        self.assertEqual(
            rpc_mock.call_args_list,
            [
                call("listwallets"),
                call("listwalletdir"),
                call("loadwallet", [pi_wallet.DEFAULT_WALLET_NAME]),
                call("listwallets"),
            ],
        )

    def test_creates_default_wallet_when_missing(self):
        responses = [
            [],
            {"wallets": []},
            {"name": pi_wallet.DEFAULT_WALLET_NAME},
            [pi_wallet.DEFAULT_WALLET_NAME],
        ]
        with patch.object(
            pi_wallet, "_rpc_request", side_effect=responses
        ) as rpc_mock:
            name = self.wallet()._ensure_wallet()

        self.assertEqual(name, pi_wallet.DEFAULT_WALLET_NAME)
        self.assertEqual(
            rpc_mock.call_args_list,
            [
                call("listwallets"),
                call("listwalletdir"),
                call("createwallet", [pi_wallet.DEFAULT_WALLET_NAME]),
                call("listwallets"),
            ],
        )

    def test_wallet_rpc_is_scoped_to_active_wallet(self):
        wallet = self.wallet()
        wallet.active_wallet = pi_wallet.DEFAULT_WALLET_NAME
        with patch.object(pi_wallet, "rpc", return_value={}) as rpc_mock:
            wallet._wallet_rpc("getwalletinfo")
        rpc_mock.assert_called_once_with(
            "getwalletinfo", None, wallet=pi_wallet.DEFAULT_WALLET_NAME
        )


if __name__ == "__main__":
    unittest.main()
