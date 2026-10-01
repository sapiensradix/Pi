#!/usr/bin/env python3

import importlib.util
import os
from pathlib import Path
import socket
import subprocess
import tempfile
import time
import unittest
from unittest.mock import Mock, call, patch


SOURCE = Path(__file__).resolve().parents[2] / "src" / "pi_wallet.py"
SPEC = importlib.util.spec_from_file_location("pi_wallet", SOURCE)
pi_wallet = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(pi_wallet)
PID = SOURCE.parent / "pid"


class FakeProcess:
    def __init__(self, wait_results=None):
        self.returncode = None
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


class DaemonControllerMockTest(unittest.TestCase):
    def setUp(self):
        self.tempdir = tempfile.TemporaryDirectory()
        self.datadir = Path(self.tempdir.name)
        self.conf_path = self.datadir / "pi.conf"
        self.daemon_path = self.datadir / "pid"
        self.daemon_path.write_text("#!/bin/sh\n", encoding="utf-8")
        self.daemon_path.chmod(0o700)

    def tearDown(self):
        self.tempdir.cleanup()

    def controller(self):
        return pi_wallet.DaemonController(
            daemon_path=self.daemon_path,
            datadir=self.datadir,
            conf_path=self.conf_path,
        )

    def test_attaches_to_existing_daemon(self):
        controller = self.controller()
        with patch.object(
            controller,
            "_validate_identity",
            return_value={"chain": "main"},
        ), patch.object(pi_wallet.subprocess, "Popen") as popen:
            result = controller.attach_or_start()
        self.assertEqual(result["chain"], "main")
        self.assertEqual(controller.ownership, "external")
        self.assertIsNone(controller.process)
        popen.assert_not_called()

    def test_starts_managed_daemon_without_listener(self):
        controller = self.controller()
        process = FakeProcess()
        errors_then_ready = [
            pi_wallet.PiRPCError("not running", kind="connection"),
            {"chain": "main"},
        ]
        with patch.object(
            controller,
            "_validate_identity",
            side_effect=errors_then_ready,
        ), patch.object(
            pi_wallet,
            "_loopback_rpc_listener",
            return_value=False,
        ), patch.object(
            pi_wallet.subprocess,
            "Popen",
            return_value=process,
        ) as popen, patch.object(
            pi_wallet,
            "DAEMON_POLL_INTERVAL",
            0,
        ):
            controller.attach_or_start()
        self.assertEqual(controller.ownership, "managed")
        self.assertIs(controller.process, process)
        popen.assert_called_once()
        command = popen.call_args.args[0]
        self.assertEqual(command[0], str(self.daemon_path))
        self.assertIn(f"-datadir={self.datadir}", command)
        self.assertIn("-daemon=0", command)
        self.assertEqual(popen.call_args.kwargs["stderr"], subprocess.STDOUT)
        startup_log = popen.call_args.kwargs["stdout"]
        self.assertEqual(Path(startup_log.name), controller.startup_log_path)
        self.assertTrue(startup_log.closed)

    def test_cancelled_startup_terminates_exact_started_child(self):
        controller = self.controller()
        process = FakeProcess()
        calls = 0

        def validate():
            nonlocal calls
            calls += 1
            if calls > 1:
                controller.cancel()
            raise pi_wallet.PiRPCError("not ready", kind="connection")

        with patch.object(
            controller,
            "_validate_identity",
            side_effect=validate,
        ), patch.object(
            pi_wallet,
            "_loopback_rpc_listener",
            return_value=False,
        ), patch.object(
            pi_wallet.subprocess,
            "Popen",
            return_value=process,
        ), patch.object(
            pi_wallet,
            "DAEMON_POLL_INTERVAL",
            0,
        ):
            with self.assertRaisesRegex(pi_wallet.PiRPCError, "cancelled"):
                controller.attach_or_start()
        self.assertTrue(process.terminate_called)
        self.assertFalse(process.kill_called)
        self.assertEqual(controller.ownership, "none")
        self.assertIsNone(controller.process)

    def test_auth_failure_does_not_spawn(self):
        controller = self.controller()
        self.conf_path.write_text(
            "rpcuser=wrong\nrpcpassword=wrong\n",
            encoding="utf-8",
        )
        with patch.object(
            controller,
            "_validate_identity",
            side_effect=pi_wallet.PiRPCError("unauthorized", kind="auth"),
        ), patch.object(
            pi_wallet,
            "_loopback_rpc_listener",
            return_value=True,
        ), patch.object(
            pi_wallet.subprocess,
            "Popen",
        ) as popen:
            with self.assertRaises(pi_wallet.PiRPCError):
                controller.attach_or_start()
        self.assertEqual(controller.ownership, "none")
        popen.assert_not_called()

    def test_wrong_chain_does_not_spawn(self):
        controller = self.controller()
        responses = [
            {"subversion": "/Pi:24.0.1/"},
            {"chain": "regtest"},
        ]
        with patch.object(
            pi_wallet,
            "_rpc_request",
            side_effect=responses,
        ), patch.object(pi_wallet.subprocess, "Popen") as popen:
            with self.assertRaisesRegex(pi_wallet.PiRPCError, "requires mainnet"):
                controller._validate_identity()
        popen.assert_not_called()

    def test_wrong_subversion_does_not_spawn(self):
        controller = self.controller()
        with patch.object(
            pi_wallet,
            "_rpc_request",
            return_value={"subversion": "/NotPi:24.0.1/"},
        ), patch.object(pi_wallet.subprocess, "Popen") as popen:
            with self.assertRaisesRegex(pi_wallet.PiRPCError, "not a recognized"):
                controller._validate_identity()
        popen.assert_not_called()

    def test_external_daemon_survives_shutdown_request(self):
        controller = self.controller()
        process = FakeProcess()
        controller.ownership = "external"
        controller.process = process
        with patch.object(pi_wallet, "_rpc_request") as rpc_request:
            result = controller.shutdown_managed()
        self.assertEqual(result, "external")
        self.assertIsNone(process.returncode)
        self.assertFalse(process.terminate_called)
        self.assertFalse(process.kill_called)
        rpc_request.assert_not_called()

    def test_managed_daemon_stops_gracefully(self):
        controller = self.controller()
        process = FakeProcess()
        controller.ownership = "managed"
        controller.process = process
        with patch.object(
            pi_wallet,
            "_rpc_request",
            return_value="Pi stopping",
        ) as rpc_request:
            result = controller.shutdown_managed()
        self.assertEqual(result, "graceful")
        self.assertEqual(process.returncode, 0)
        self.assertFalse(process.terminate_called)
        self.assertFalse(process.kill_called)
        rpc_request.assert_called_once_with("stop")

    def test_forced_shutdown_targets_exact_child(self):
        controller = self.controller()
        process = FakeProcess(
            [
                subprocess.TimeoutExpired("pid", 30),
                subprocess.TimeoutExpired("pid", 30),
                0,
            ]
        )
        controller.ownership = "managed"
        controller.process = process
        with patch.object(
            pi_wallet,
            "_rpc_request",
            side_effect=pi_wallet.PiRPCError("stop failed"),
        ), patch.object(pi_wallet.subprocess, "Popen") as popen:
            result = controller.shutdown_managed()
        self.assertEqual(result, "killed")
        self.assertTrue(process.terminate_called)
        self.assertTrue(process.kill_called)
        self.assertEqual(process.wait_calls, 3)
        popen.assert_not_called()

    def test_second_controller_attaches_without_starting_another_daemon(self):
        first = self.controller()
        first.process = FakeProcess()
        first.ownership = "managed"
        second = self.controller()
        with patch.object(
            second,
            "_validate_identity",
            return_value={"chain": "main"},
        ), patch.object(pi_wallet.subprocess, "Popen") as popen:
            second.attach_or_start()
        self.assertEqual(first.ownership, "managed")
        self.assertEqual(second.ownership, "external")
        popen.assert_not_called()


class FakeRoot:
    def __init__(self):
        self.destroyed = False

    def destroy(self):
        self.destroyed = True

    def after(self, _delay, _callback):
        return "after-id"


class PiWalletCloseMockTest(unittest.TestCase):
    def wallet_with_controller(self, controller):
        wallet = pi_wallet.PiWallet.__new__(pi_wallet.PiWallet)
        wallet.root = FakeRoot()
        wallet.daemon_controller = controller
        wallet.daemon_shutdown_started = False
        wallet.daemon_shutdown_thread = None
        wallet.close_after_id = None
        return wallet

    def test_closing_attached_gui_leaves_external_daemon_alive(self):
        controller = Mock()
        controller.ownership = "external"
        wallet = self.wallet_with_controller(controller)
        wallet._shutdown_daemon_then_destroy()
        self.assertTrue(wallet.root.destroyed)
        controller.shutdown_managed.assert_not_called()

    def test_closing_managed_gui_stops_only_managed_child(self):
        controller = Mock()
        controller.ownership = "managed"
        wallet = self.wallet_with_controller(controller)
        wallet._shutdown_daemon_then_destroy()
        wallet.daemon_shutdown_thread.join(timeout=5)
        wallet._wait_for_daemon_shutdown()
        self.assertFalse(wallet.daemon_shutdown_thread.is_alive())
        self.assertTrue(wallet.root.destroyed)
        controller.shutdown_managed.assert_called_once_with()


class PiWalletInitializationMockTest(unittest.TestCase):
    def test_daemon_ready_does_not_enable_controls_before_wallet_init(self):
        wallet = pi_wallet.PiWallet.__new__(pi_wallet.PiWallet)
        wallet.closing = False
        wallet._start_worker = Mock()
        wallet._set_daemon_controls_enabled = Mock()
        wallet._daemon_ready()
        wallet._set_daemon_controls_enabled.assert_not_called()
        wallet._start_worker.assert_called_once_with(wallet._init, "wallet-init")

    def test_wallet_init_enables_controls_after_address_and_info(self):
        wallet = pi_wallet.PiWallet.__new__(pi_wallet.PiWallet)
        wallet._queue_ui = Mock()
        wallet.status_var = Mock()
        with patch.object(
            wallet,
            "_ensure_wallet",
            return_value=pi_wallet.DEFAULT_WALLET_NAME,
        ), patch.object(
            pi_wallet,
            "rpc",
            side_effect=[
                "pi1address",
                {"balance": 1, "immature_balance": 2},
            ],
        ):
            wallet._init()
        self.assertIn(call(wallet._wallet_ready), wallet._queue_ui.call_args_list)

    def test_wallet_init_failure_keeps_controls_disabled(self):
        wallet = pi_wallet.PiWallet.__new__(pi_wallet.PiWallet)
        wallet._queue_ui = Mock()
        wallet.status_var = Mock()
        with patch.object(
            wallet,
            "_ensure_wallet",
            return_value=pi_wallet.DEFAULT_WALLET_NAME,
        ), patch.object(
            pi_wallet,
            "rpc",
            side_effect=["pi1address", None],
        ), patch.object(
            pi_wallet,
            "rpc_error",
            return_value="No Pi wallet is loaded.",
        ):
            wallet._init()
        self.assertNotIn(
            call(wallet._set_daemon_controls_enabled, True),
            wallet._queue_ui.call_args_list,
        )


def free_port():
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
        sock.bind(("127.0.0.1", 0))
        return sock.getsockname()[1]


@unittest.skipUnless(PID.is_file() and os.access(PID, os.X_OK), "pid binary is unavailable")
class DaemonControllerIntegrationTest(unittest.TestCase):
    def setUp(self):
        self.tempdir = tempfile.TemporaryDirectory()
        self.datadir = Path(self.tempdir.name)
        self.conf_path = self.datadir / "pi.conf"
        self.cookie_path = self.datadir / ".cookie"
        self.port = free_port()
        self.processes = []
        self.datadir_patch = patch.object(pi_wallet, "DATADIR", self.datadir)
        self.conf_patch = patch.object(pi_wallet, "CONF_PATH", self.conf_path)
        self.datadir_patch.start()
        self.conf_patch.start()
        self.write_conf()

    def tearDown(self):
        self.write_conf()
        for process in self.processes:
            if process.poll() is not None:
                continue
            try:
                pi_wallet._rpc_request("stop")
                process.wait(timeout=10)
            except Exception:
                process.terminate()
                try:
                    process.wait(timeout=10)
                except subprocess.TimeoutExpired:
                    process.kill()
                    process.wait(timeout=10)
        self.conf_patch.stop()
        self.datadir_patch.stop()
        self.tempdir.cleanup()

    def write_conf(self, extra=""):
        self.conf_path.write_text(
            "\n".join(
                [
                    "server=1",
                    "listen=0",
                    "discover=0",
                    "dnsseed=0",
                    "fixedseeds=0",
                    f"rpcport={self.port}",
                    "rpcbind=127.0.0.1",
                    "rpcallowip=127.0.0.1",
                    f"rpccookiefile={self.cookie_path}",
                    extra,
                    "",
                ]
            ),
            encoding="utf-8",
        )

    def write_regtest_conf(self):
        self.conf_path.write_text(
            "\n".join(
                [
                    "server=1",
                    "listen=0",
                    "discover=0",
                    "dnsseed=0",
                    "fixedseeds=0",
                    "regtest=1",
                    "[regtest]",
                    f"rpcport={self.port}",
                    "rpcbind=127.0.0.1",
                    "rpcallowip=127.0.0.1",
                    f"rpccookiefile={self.cookie_path}",
                    "",
                ]
            ),
            encoding="utf-8",
        )

    def command(self):
        return [
            str(PID),
            f"-datadir={self.datadir}",
            f"-conf={self.conf_path}",
            "-daemon=0",
        ]

    def start_external(self, extra_args=None):
        command = self.command()
        command.extend(extra_args or [])
        process = subprocess.Popen(
            command,
            stdin=subprocess.DEVNULL,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
        )
        self.processes.append(process)
        deadline = time.monotonic() + 30
        last_error = None
        while time.monotonic() < deadline:
            if process.poll() is not None:
                log_text = ""
                for log_path in (
                    self.datadir / "debug.log",
                    self.datadir / "regtest" / "debug.log",
                ):
                    if log_path.is_file():
                        log_text += log_path.read_text(
                            encoding="utf-8", errors="replace"
                        )[-2000:]
                self.fail(
                    f"external pid exited with status {process.returncode}: "
                    f"{log_text}"
                )
            try:
                pi_wallet._rpc_request("getnetworkinfo")
                return process
            except pi_wallet.PiRPCError as exc:
                last_error = exc
                time.sleep(0.1)
        self.fail(f"external pid did not become ready: {last_error}")

    def test_real_managed_daemon_starts_without_terminal_and_stops(self):
        controller = pi_wallet.DaemonController(
            daemon_path=PID,
            datadir=self.datadir,
            conf_path=self.conf_path,
        )
        controller.attach_or_start()
        process = controller.process
        self.assertEqual(controller.ownership, "managed")
        self.assertIsNotNone(process)
        self.processes.append(process)
        self.assertIsNone(process.poll())
        self.assertTrue(controller.startup_log_path.is_file())
        self.assertEqual(controller.shutdown_managed(), "graceful")
        self.assertIsNotNone(process.poll())

    def test_real_existing_daemon_is_external_and_survives(self):
        process = self.start_external()
        controller = pi_wallet.DaemonController(
            daemon_path=PID,
            datadir=self.datadir,
            conf_path=self.conf_path,
        )
        controller.attach_or_start()
        self.assertEqual(controller.ownership, "external")
        self.assertEqual(controller.shutdown_managed(), "external")
        self.assertIsNone(process.poll())

    def test_real_wrong_chain_fails_closed(self):
        self.write_regtest_conf()
        process = self.start_external()
        controller = pi_wallet.DaemonController(
            daemon_path=PID,
            datadir=self.datadir,
            conf_path=self.conf_path,
        )
        with patch.object(pi_wallet.subprocess, "Popen") as popen:
            with self.assertRaisesRegex(pi_wallet.PiRPCError, "requires mainnet"):
                controller.attach_or_start()
        popen.assert_not_called()
        self.assertIsNone(process.poll())

    def test_real_auth_failure_does_not_start_another_daemon(self):
        self.write_conf("rpcuser=correct\nrpcpassword=correct")
        process = self.start_external()
        if self.cookie_path.exists():
            self.cookie_path.unlink()
        self.write_conf("rpcuser=wrong\nrpcpassword=wrong")
        controller = pi_wallet.DaemonController(
            daemon_path=PID,
            datadir=self.datadir,
            conf_path=self.conf_path,
        )
        with patch.object(pi_wallet.subprocess, "Popen") as popen:
            with self.assertRaisesRegex(pi_wallet.PiRPCError, "rejected"):
                controller.attach_or_start()
        popen.assert_not_called()
        self.assertIsNone(process.poll())

    def test_real_second_controller_does_not_start_second_daemon(self):
        first = pi_wallet.DaemonController(
            daemon_path=PID,
            datadir=self.datadir,
            conf_path=self.conf_path,
        )
        first.attach_or_start()
        process = first.process
        self.processes.append(process)

        second = pi_wallet.DaemonController(
            daemon_path=PID,
            datadir=self.datadir,
            conf_path=self.conf_path,
        )
        with patch.object(pi_wallet.subprocess, "Popen") as popen:
            second.attach_or_start()
        self.assertEqual(first.ownership, "managed")
        self.assertEqual(second.ownership, "external")
        self.assertIsNone(process.poll())
        popen.assert_not_called()


if __name__ == "__main__":
    unittest.main()
