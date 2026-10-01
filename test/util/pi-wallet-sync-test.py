#!/usr/bin/env python3

import importlib.util
from pathlib import Path
import threading
import unittest
from unittest.mock import Mock, patch


SOURCE = Path(__file__).resolve().parents[2] / "src" / "pi_wallet.py"
SPEC = importlib.util.spec_from_file_location("pi_wallet", SOURCE)
pi_wallet = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(pi_wallet)


class MiningReadinessTest(unittest.TestCase):
    def wallet(self):
        wallet = pi_wallet.PiWallet.__new__(pi_wallet.PiWallet)
        wallet.closing = False
        wallet.mining = False
        wallet.mining_ready = False
        wallet.stop_event = threading.Event()
        wallet.mine_btn = Mock()
        wallet.status_var = Mock()
        wallet._queue_ui = lambda callback, *args: callback(*args)
        return wallet

    def check(self, peers, blocks, headers, progress=1, ibd=True):
        wallet = self.wallet()
        responses = [
            peers,
            {
                "blocks": blocks,
                "headers": headers,
                "verificationprogress": progress,
                "initialblockdownload": ibd,
            },
        ]
        with patch.object(pi_wallet, "_rpc_request", side_effect=responses):
            wallet._check_mining_readiness()
        return wallet

    def test_requires_at_least_one_peer(self):
        wallet = self.check(0, 17, 17)
        self.assertFalse(wallet.mining_ready)
        wallet.mine_btn.config.assert_called_with(state="disabled")

    def test_allows_synced_stale_chain_even_when_ibd_is_true(self):
        wallet = self.check(1, 17, 17, progress=1, ibd=True)
        self.assertTrue(wallet.mining_ready)
        wallet.mine_btn.config.assert_called_with(state="normal")

    def test_blocks_mining_while_headers_are_ahead(self):
        wallet = self.check(1, 16, 17)
        self.assertFalse(wallet.mining_ready)
        wallet.mine_btn.config.assert_called_with(state="disabled")

    def test_peer_loss_stops_future_mining_batches(self):
        wallet = self.wallet()
        wallet.mining = True
        wallet.mining_ready = True
        wallet._apply_mining_readiness(False, "Waiting for a Tor peer before mining...")
        self.assertFalse(wallet.mining)
        self.assertTrue(wallet.stop_event.is_set())
        wallet.mine_btn.config.assert_called_with(state="disabled")


if __name__ == "__main__":
    unittest.main()
