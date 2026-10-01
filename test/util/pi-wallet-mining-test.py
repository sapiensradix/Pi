#!/usr/bin/env python3

import importlib.util
from pathlib import Path
import threading
import unittest
from unittest.mock import Mock, call, patch


SOURCE = Path(__file__).resolve().parents[2] / "src" / "pi_wallet.py"
SPEC = importlib.util.spec_from_file_location("pi_wallet", SOURCE)
pi_wallet = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(pi_wallet)


class MiningLoopTest(unittest.TestCase):
    def wallet(self):
        wallet = pi_wallet.PiWallet.__new__(pi_wallet.PiWallet)
        wallet.current_address = "pi1qtestaddress"
        wallet.active_wallet = pi_wallet.DEFAULT_WALLET_NAME
        wallet.blocks_mined = 0
        wallet.stop_event = threading.Event()
        wallet.mining = True
        wallet.mining_thread = object()
        wallet._queue_ui = lambda *_args, **_kwargs: None
        wallet._set_balance = lambda *_args, **_kwargs: None
        wallet.blocks_var = Mock()
        wallet.status_var = Mock()
        return wallet

    def test_mining_uses_finite_maxtries_and_stops_before_next_batch(self):
        wallet = self.wallet()

        def rpc_once(method, params=None, **kwargs):
            self.assertEqual(method, "generatetoaddress")
            self.assertEqual(
                kwargs.get("wallet"), pi_wallet.DEFAULT_WALLET_NAME
            )
            wallet.stop_event.set()
            return []

        with patch.object(pi_wallet, "rpc", side_effect=rpc_once) as rpc_mock:
            wallet._mine_loop(wallet.stop_event)

        rpc_mock.assert_called_once_with(
            "generatetoaddress",
            [1, wallet.current_address, pi_wallet.MINING_MAX_TRIES],
            wallet=pi_wallet.DEFAULT_WALLET_NAME,
        )
        self.assertGreater(pi_wallet.MINING_MAX_TRIES, 0)
        self.assertLess(pi_wallet.MINING_MAX_TRIES, 0xFFFFFFFFFFFFFFFF)

    def test_successful_block_updates_balance_then_stops_cleanly(self):
        wallet = self.wallet()

        def rpc_result(method, params=None, **kwargs):
            self.assertEqual(
                kwargs.get("wallet"), pi_wallet.DEFAULT_WALLET_NAME
            )
            if method == "generatetoaddress":
                if wallet.blocks_mined == 0:
                    return ["00" * 32]
                wallet.stop_event.set()
                return []
            if method == "getwalletinfo":
                return {"balance": 0, "immature_balance": 50}
            self.fail(f"unexpected RPC method: {method}")

        with patch.object(pi_wallet, "rpc", side_effect=rpc_result) as rpc_mock:
            wallet._mine_loop(wallet.stop_event)

        self.assertEqual(wallet.blocks_mined, 1)
        self.assertEqual(
            rpc_mock.call_args_list[:2],
            [
                call(
                    "generatetoaddress",
                    [1, wallet.current_address, pi_wallet.MINING_MAX_TRIES],
                    wallet=pi_wallet.DEFAULT_WALLET_NAME,
                ),
                call("getwalletinfo", None, wallet=pi_wallet.DEFAULT_WALLET_NAME),
            ],
        )


if __name__ == "__main__":
    unittest.main()
