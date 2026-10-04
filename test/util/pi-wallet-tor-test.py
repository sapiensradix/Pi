#!/usr/bin/env python3

import importlib.util
import os
from pathlib import Path
import subprocess
import tempfile
import unittest
from unittest.mock import patch


SOURCE = Path(__file__).resolve().parents[2] / "src" / "pi_wallet.py"
SPEC = importlib.util.spec_from_file_location("pi_wallet", SOURCE)
pi_wallet = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(pi_wallet)


class FakeProcess:
    def __init__(self, wait_results=None, returncode=None):
        self.returncode = returncode
        self.wait_results = list(wait_results or [0])
        self.terminate_called = False
        self.kill_called = False
        self.wait_calls = 0

    def poll(self):
        return self.returncode

    def wait(self, timeout=None):
        self.wait_calls += 1
        result = self.wait_results.pop(0)
        if isinstance(result, BaseException):
            raise result
        self.returncode = result
        return result

    def terminate(self):
        self.terminate_called = True

    def kill(self):
        self.kill_called = True


class TorControllerTest(unittest.TestCase):
    def setUp(self):
        self.tempdir = tempfile.TemporaryDirectory()
        self.datadir = Path(self.tempdir.name) / "Pi"
        self.tor_path = Path(self.tempdir.name) / "tor"
        self.tor_path.write_text("#!/bin/sh\n", encoding="utf-8")
        self.tor_path.chmod(0o700)

    def tearDown(self):
        self.tempdir.cleanup()

    def controller(self):
        return pi_wallet.TorController(
            tor_path=self.tor_path,
            datadir=self.datadir,
        )

    def test_attaches_to_external_tor_without_spawning(self):
        controller = self.controller()
        with patch.object(pi_wallet, "_tor_socks_ready", return_value=True), patch.object(
            pi_wallet.subprocess, "Popen"
        ) as popen:
            result = controller.attach_or_start()
        self.assertEqual(result, "external")
        self.assertEqual(controller.ownership, "external")
        self.assertIsNone(controller.process)
        popen.assert_not_called()

    def test_starts_managed_tor_once_and_uses_private_paths(self):
        controller = self.controller()
        process = FakeProcess()
        with patch.object(
            pi_wallet, "_tor_socks_ready", side_effect=[False, True]
        ), patch.object(
            pi_wallet, "_loopback_listener", return_value=False
        ), patch.object(
            pi_wallet.subprocess, "Popen", return_value=process
        ) as popen, patch.object(pi_wallet, "TOR_POLL_INTERVAL", 0):
            result = controller.attach_or_start()
        self.assertEqual(result, "managed")
        self.assertEqual(controller.ownership, "managed")
        self.assertIs(controller.process, process)
        popen.assert_called_once()
        command = popen.call_args.args[0]
        self.assertEqual(command[0], str(self.tor_path))
        self.assertIn("127.0.0.1:9050", command)
        self.assertIn(str(controller.tor_datadir), command)
        if os.name != "nt":
            self.assertEqual(controller.tor_datadir.stat().st_mode & 0o777, 0o700)
            self.assertEqual(controller.startup_log_path.stat().st_mode & 0o777, 0o600)
        self.assertTrue(popen.call_args.kwargs["stdout"].closed)

    def test_non_socks_listener_fails_closed_without_spawning(self):
        controller = self.controller()
        with patch.object(pi_wallet, "_tor_socks_ready", return_value=False), patch.object(
            pi_wallet, "_loopback_listener", return_value=True
        ), patch.object(pi_wallet.subprocess, "Popen") as popen:
            with self.assertRaisesRegex(pi_wallet.PiRPCError, "Port 9050 is in use"):
                controller.attach_or_start()
        self.assertEqual(controller.ownership, "none")
        popen.assert_not_called()

    def test_missing_bundled_tor_reports_clear_error(self):
        controller = pi_wallet.TorController(
            tor_path=Path(self.tempdir.name) / "missing-tor",
            datadir=self.datadir,
        )
        with patch.object(pi_wallet, "_tor_socks_ready", return_value=False), patch.object(
            pi_wallet, "_loopback_listener", return_value=False
        ):
            with self.assertRaisesRegex(pi_wallet.PiRPCError, "bundled Tor executable"):
                controller.attach_or_start()

    def test_cancelled_startup_terminates_exact_child(self):
        controller = self.controller()
        process = FakeProcess()

        def socks_ready():
            if controller.process is not None:
                controller.cancel()
            return False

        with patch.object(
            pi_wallet, "_tor_socks_ready", side_effect=socks_ready
        ), patch.object(
            pi_wallet, "_loopback_listener", return_value=False
        ), patch.object(
            pi_wallet.subprocess, "Popen", return_value=process
        ), patch.object(pi_wallet, "TOR_POLL_INTERVAL", 0):
            with self.assertRaisesRegex(pi_wallet.PiRPCError, "cancelled"):
                controller.attach_or_start()
        self.assertTrue(process.terminate_called)
        self.assertFalse(process.kill_called)
        self.assertEqual(controller.ownership, "none")
        self.assertIsNone(controller.process)

    def test_external_tor_survives_shutdown_request(self):
        controller = self.controller()
        controller.ownership = "external"
        controller.process = None
        self.assertEqual(controller.shutdown_managed(), "external")

    def test_managed_tor_stops_exact_child_gracefully(self):
        controller = self.controller()
        process = FakeProcess()
        controller.ownership = "managed"
        controller.process = process
        result = controller.shutdown_managed()
        self.assertEqual(result, "graceful")
        self.assertTrue(process.terminate_called)
        self.assertFalse(process.kill_called)
        self.assertEqual(controller.ownership, "none")
        self.assertIsNone(controller.process)

    def test_managed_tor_kills_exact_child_after_timeout(self):
        controller = self.controller()
        process = FakeProcess([subprocess.TimeoutExpired("tor", 15), 0])
        controller.ownership = "managed"
        controller.process = process
        result = controller.shutdown_managed()
        self.assertEqual(result, "killed")
        self.assertTrue(process.terminate_called)
        self.assertTrue(process.kill_called)
        self.assertEqual(process.wait_calls, 2)

    def test_second_controller_attaches_without_starting_second_tor(self):
        first = self.controller()
        first.process = FakeProcess()
        first.ownership = "managed"
        second = self.controller()
        with patch.object(pi_wallet, "_tor_socks_ready", return_value=True), patch.object(
            pi_wallet.subprocess, "Popen"
        ) as popen:
            result = second.attach_or_start()
        self.assertEqual(result, "external")
        self.assertEqual(first.ownership, "managed")
        self.assertEqual(second.ownership, "external")
        popen.assert_not_called()


if __name__ == "__main__":
    unittest.main()
