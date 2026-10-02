#!/usr/bin/env python3

import importlib.util
from pathlib import Path
import tempfile
import unittest
from unittest.mock import call, Mock, patch


SOURCE = Path(__file__).resolve().parents[2] / "src" / "pi_wallet.py"
SPEC = importlib.util.spec_from_file_location("pi_wallet", SOURCE)
pi_wallet = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(pi_wallet)


class WalletRestoreTest(unittest.TestCase):
    def wallet(self):
        wallet = pi_wallet.PiWallet.__new__(pi_wallet.PiWallet)
        wallet.active_wallet = pi_wallet.DEFAULT_WALLET_NAME
        wallet.wallet_encrypted = True
        wallet.wallet_transitioning = False
        wallet.mining = False
        wallet.mining_ready = False
        wallet.refresh_after_id = None
        wallet.root = Mock()
        wallet.restore_var = Mock()
        wallet.status_var = Mock()
        wallet.mine_btn = Mock()
        wallet._set_daemon_controls_enabled = Mock()
        wallet._schedule_auto_refresh = Mock()
        wallet._start_worker = Mock()
        wallet._queue_ui = Mock()
        wallet._finish_wallet_init = Mock(return_value=True)
        return wallet

    def test_active_wallet_state_round_trip(self):
        with tempfile.TemporaryDirectory() as directory:
            state_path = Path(directory) / "wallet-state.json"
            name = f"{pi_wallet.RESTORED_WALLET_PREFIX}123"
            pi_wallet.write_active_wallet_name(name, state_path)

            self.assertEqual(pi_wallet.read_active_wallet_name(state_path), name)
            self.assertEqual(state_path.stat().st_mode & 0o777, 0o600)

    def test_invalid_active_wallet_state_falls_back_to_default(self):
        with tempfile.TemporaryDirectory() as directory:
            state_path = Path(directory) / "wallet-state.json"
            state_path.write_text('{"active_wallet":"../../other"}\n', encoding="utf-8")

            self.assertEqual(
                pi_wallet.read_active_wallet_name(state_path),
                pi_wallet.DEFAULT_WALLET_NAME,
            )

    def test_restore_dialog_starts_restore_worker(self):
        wallet = self.wallet()
        backup_file = "/tmp/pi-wallet-backup.bak"
        with patch.object(
            pi_wallet.filedialog,
            "askopenfilename",
            return_value=backup_file,
        ):
            with patch.object(pi_wallet.messagebox, "askyesno", return_value=True):
                wallet.restore_wallet()

        self.assertTrue(wallet.wallet_transitioning)
        wallet.restore_var.set.assert_called_once_with("pi-wallet-backup.bak")
        wallet._set_daemon_controls_enabled.assert_called_once_with(False)
        wallet._start_worker.assert_called_once_with(
            wallet._restore_wallet,
            "wallet-restore",
            backup_file,
        )

    def test_restore_is_blocked_while_mining(self):
        wallet = self.wallet()
        wallet.mining = True
        with patch.object(pi_wallet.messagebox, "showwarning") as warning:
            with patch.object(pi_wallet.filedialog, "askopenfilename") as dialog:
                wallet.restore_wallet()

        warning.assert_called_once()
        dialog.assert_not_called()
        wallet._start_worker.assert_not_called()

    def test_restore_switches_active_wallet_without_deleting_old_wallet(self):
        wallet = self.wallet()
        restored_name = f"{pi_wallet.RESTORED_WALLET_PREFIX}123"
        responses = [
            {"name": restored_name, "warning": ""},
            {
                "format": "sqlite",
                "descriptors": True,
                "private_keys_enabled": True,
            },
            {"warning": ""},
        ]
        with patch.object(pi_wallet.time, "time_ns", return_value=123):
            with patch.object(pi_wallet, "_rpc_request", side_effect=responses) as rpc:
                with patch.object(pi_wallet, "write_active_wallet_name") as write_state:
                    wallet._restore_wallet("/tmp/pi-wallet-backup.bak")

        self.assertEqual(
            rpc.call_args_list,
            [
                call(
                    "restorewallet",
                    [restored_name, "/tmp/pi-wallet-backup.bak", True],
                ),
                call("getwalletinfo", wallet=restored_name),
                call("unloadwallet", [pi_wallet.DEFAULT_WALLET_NAME, False]),
            ],
        )
        write_state.assert_called_once_with(restored_name)
        self.assertEqual(wallet.active_wallet, restored_name)
        self.assertFalse(wallet.wallet_encrypted)
        wallet._finish_wallet_init.assert_called_once_with()
        wallet._queue_ui.assert_called_once_with(wallet._restore_wallet_completed)

    def test_invalid_backup_rolls_back_without_switching_wallet(self):
        wallet = self.wallet()
        restored_name = f"{pi_wallet.RESTORED_WALLET_PREFIX}123"
        responses = [
            {"name": restored_name, "warning": ""},
            {
                "format": "bdb",
                "descriptors": False,
                "private_keys_enabled": True,
            },
            [pi_wallet.DEFAULT_WALLET_NAME, restored_name],
            {"warning": ""},
        ]
        with patch.object(pi_wallet.time, "time_ns", return_value=123):
            with patch.object(pi_wallet, "_rpc_request", side_effect=responses) as rpc:
                wallet._restore_wallet("/tmp/legacy-wallet.bak")

        self.assertEqual(wallet.active_wallet, pi_wallet.DEFAULT_WALLET_NAME)
        self.assertIn(
            call("unloadwallet", [restored_name, False]),
            rpc.call_args_list,
        )
        wallet._finish_wallet_init.assert_not_called()
        wallet._queue_ui.assert_called_once()
        self.assertEqual(
            wallet._queue_ui.call_args.args[0],
            wallet._restore_wallet_failed,
        )

    def test_state_write_failure_reloads_original_wallet(self):
        wallet = self.wallet()
        restored_name = f"{pi_wallet.RESTORED_WALLET_PREFIX}123"
        responses = [
            {"name": restored_name, "warning": ""},
            {
                "format": "sqlite",
                "descriptors": True,
                "private_keys_enabled": True,
            },
            {"warning": ""},
            [restored_name],
            {"warning": ""},
            {"name": pi_wallet.DEFAULT_WALLET_NAME, "warning": ""},
        ]
        with patch.object(pi_wallet.time, "time_ns", return_value=123):
            with patch.object(pi_wallet, "_rpc_request", side_effect=responses) as rpc:
                with patch.object(
                    pi_wallet,
                    "write_active_wallet_name",
                    side_effect=OSError("state write failed"),
                ):
                    wallet._restore_wallet("/tmp/pi-wallet-backup.bak")

        self.assertEqual(wallet.active_wallet, pi_wallet.DEFAULT_WALLET_NAME)
        self.assertIn(
            call("unloadwallet", [restored_name, False]),
            rpc.call_args_list,
        )
        self.assertIn(
            call("loadwallet", [pi_wallet.DEFAULT_WALLET_NAME, True]),
            rpc.call_args_list,
        )
        wallet._finish_wallet_init.assert_not_called()

    def test_restored_wallet_initialization_failure_is_not_reported_as_success(self):
        wallet = self.wallet()
        wallet._finish_wallet_init.return_value = False
        restored_name = f"{pi_wallet.RESTORED_WALLET_PREFIX}123"
        responses = [
            {"name": restored_name, "warning": ""},
            {
                "format": "sqlite",
                "descriptors": True,
                "private_keys_enabled": True,
            },
            {"warning": ""},
        ]
        with patch.object(pi_wallet.time, "time_ns", return_value=123):
            with patch.object(pi_wallet, "_rpc_request", side_effect=responses):
                with patch.object(pi_wallet, "write_active_wallet_name"):
                    wallet._restore_wallet("/tmp/pi-wallet-backup.bak")

        wallet._queue_ui.assert_called_once_with(
            wallet._restore_wallet_initialization_failed
        )

    def test_preferred_restored_wallet_is_loaded_on_restart(self):
        wallet = self.wallet()
        restored_name = f"{pi_wallet.RESTORED_WALLET_PREFIX}123"
        responses = [
            [],
            {
                "wallets": [
                    {"name": pi_wallet.DEFAULT_WALLET_NAME},
                    {"name": restored_name},
                ]
            },
            {"name": restored_name, "warning": ""},
            [restored_name],
        ]
        with patch.object(pi_wallet, "_rpc_request", side_effect=responses) as rpc:
            selected = wallet._ensure_wallet(preferred_wallet=restored_name)

        self.assertEqual(selected, restored_name)
        self.assertEqual(
            rpc.call_args_list,
            [
                call("listwallets"),
                call("listwalletdir"),
                call("loadwallet", [restored_name, True]),
                call("listwallets"),
            ],
        )

    def test_other_gui_wallet_is_unloaded_fail_closed(self):
        wallet = self.wallet()
        restored_name = f"{pi_wallet.RESTORED_WALLET_PREFIX}123"
        responses = [[pi_wallet.DEFAULT_WALLET_NAME, restored_name], {"warning": ""}]
        with patch.object(pi_wallet, "_rpc_request", side_effect=responses) as rpc:
            selected = wallet._ensure_wallet(
                preferred_wallet=pi_wallet.DEFAULT_WALLET_NAME
            )

        self.assertEqual(selected, pi_wallet.DEFAULT_WALLET_NAME)
        self.assertEqual(
            rpc.call_args_list,
            [
                call("listwallets"),
                call("unloadwallet", [restored_name, False]),
            ],
        )

    def test_missing_restored_wallet_falls_back_to_original_wallet(self):
        wallet = self.wallet()
        restored_name = f"{pi_wallet.RESTORED_WALLET_PREFIX}123"
        responses = [
            [],
            {"wallets": [{"name": pi_wallet.DEFAULT_WALLET_NAME}]},
            {"name": pi_wallet.DEFAULT_WALLET_NAME, "warning": ""},
            [pi_wallet.DEFAULT_WALLET_NAME],
        ]
        with patch.object(pi_wallet, "_rpc_request", side_effect=responses) as rpc:
            with patch.object(pi_wallet, "write_active_wallet_name") as write_state:
                selected = wallet._ensure_wallet(preferred_wallet=restored_name)

        self.assertEqual(selected, pi_wallet.DEFAULT_WALLET_NAME)
        write_state.assert_called_once_with(pi_wallet.DEFAULT_WALLET_NAME)
        self.assertEqual(
            rpc.call_args_list,
            [
                call("listwallets"),
                call("listwalletdir"),
                call("loadwallet", [pi_wallet.DEFAULT_WALLET_NAME]),
                call("listwallets"),
            ],
        )


if __name__ == "__main__":
    unittest.main()
