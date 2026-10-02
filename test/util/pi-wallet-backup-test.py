#!/usr/bin/env python3

import importlib.util
from pathlib import Path
import unittest
from unittest.mock import Mock, patch


SOURCE = Path(__file__).resolve().parents[2] / "src" / "pi_wallet.py"
SPEC = importlib.util.spec_from_file_location("pi_wallet", SOURCE)
pi_wallet = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(pi_wallet)


class WalletBackupTest(unittest.TestCase):
    def wallet(self):
        wallet = pi_wallet.PiWallet.__new__(pi_wallet.PiWallet)
        wallet.active_wallet = pi_wallet.DEFAULT_WALLET_NAME
        wallet.root = Mock()
        wallet.status_var = Mock()
        wallet._start_worker = Mock()
        wallet._queue_ui = Mock()
        wallet._wallet_rpc_with_status = Mock(return_value=(True, None))
        return wallet

    def test_backup_dialog_starts_wallet_backup_worker(self):
        wallet = self.wallet()
        destination = "/tmp/pi-wallet-backup.bak"
        with patch.object(
            pi_wallet.filedialog,
            "asksaveasfilename",
            return_value=destination,
        ) as dialog:
            wallet.backup_wallet()

        dialog.assert_called_once_with(
            title="Back Up Pi Wallet",
            defaultextension=".bak",
            filetypes=[("Pi Wallet Backup", "*.bak"), ("All Files", "*")],
            initialfile="pi_wallet_backup.bak",
            parent=wallet.root,
        )
        wallet.status_var.set.assert_called_once_with("Backing up Pi wallet...")
        wallet._start_worker.assert_called_once_with(
            wallet._backup_wallet,
            "wallet-backup",
            destination,
        )

    def test_cancelled_dialog_does_not_start_backup(self):
        wallet = self.wallet()
        with patch.object(
            pi_wallet.filedialog,
            "asksaveasfilename",
            return_value="",
        ):
            wallet.backup_wallet()

        wallet._start_worker.assert_not_called()
        wallet.status_var.set.assert_not_called()

    def test_no_loaded_wallet_does_not_open_dialog(self):
        wallet = self.wallet()
        wallet.active_wallet = None
        with patch.object(pi_wallet.filedialog, "asksaveasfilename") as dialog:
            with patch.object(pi_wallet.messagebox, "showwarning") as warning:
                wallet.backup_wallet()

        warning.assert_called_once_with("Backup Wallet", "No wallet is loaded yet.")
        dialog.assert_not_called()
        wallet._start_worker.assert_not_called()

    def test_backup_uses_wallet_scoped_rpc(self):
        wallet = self.wallet()
        destination = "/tmp/pi-wallet-backup.bak"

        wallet._backup_wallet(destination)

        wallet._wallet_rpc_with_status.assert_called_once_with(
            "backupwallet",
            [destination],
        )
        wallet._queue_ui.assert_any_call(
            wallet.status_var.set,
            "Wallet backup completed.",
        )
        wallet._queue_ui.assert_any_call(
            pi_wallet.messagebox.showinfo,
            "Backup Wallet",
            "The encrypted Pi wallet backup was saved successfully.\n\n"
            "Keep the backup file and wallet password in separate safe places.",
        )

    def test_backup_failure_reports_rpc_error(self):
        wallet = self.wallet()
        wallet._wallet_rpc_with_status.return_value = (False, None)
        with patch.object(pi_wallet, "rpc_error", return_value="backup error"):
            wallet._backup_wallet("/tmp/pi-wallet-backup.bak")

        wallet._queue_ui.assert_any_call(
            pi_wallet.messagebox.showerror,
            "Backup Wallet",
            "backup error",
        )
        wallet._queue_ui.assert_any_call(wallet.status_var.set, "backup error")


if __name__ == "__main__":
    unittest.main()
