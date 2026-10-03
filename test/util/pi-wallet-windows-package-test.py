#!/usr/bin/env python3
import importlib.util
import io
from pathlib import Path
import struct
import tarfile
import tempfile
import unittest


REPO_ROOT = Path(__file__).resolve().parents[2]
BUILD_SCRIPT = REPO_ROOT / "contrib" / "windeploy" / "pi-wallet" / "build.py"
SPEC = REPO_ROOT / "contrib" / "windeploy" / "pi-wallet" / "pi_wallet.spec"

module_spec = importlib.util.spec_from_file_location(
    "pi_wallet_windows_build", BUILD_SCRIPT
)
build = importlib.util.module_from_spec(module_spec)
module_spec.loader.exec_module(build)


def write_test_pe(path, machine):
    data = bytearray(0x90)
    data[0:2] = b"MZ"
    struct.pack_into("<I", data, 0x3C, 0x80)
    data[0x80:0x84] = b"PE\x00\x00"
    struct.pack_into("<H", data, 0x84, machine)
    Path(path).write_bytes(data)


class WindowsPackagingTest(unittest.TestCase):
    def test_pe_machine_accepts_x86_64(self):
        with tempfile.TemporaryDirectory() as directory:
            executable = Path(directory) / "pid.exe"
            write_test_pe(executable, build.PE_MACHINE_AMD64)
            self.assertEqual(build.pe_machine(executable), build.PE_MACHINE_AMD64)
            build.require_x86_64_pe(executable)

    def test_pe_machine_rejects_non_pe(self):
        with tempfile.TemporaryDirectory() as directory:
            executable = Path(directory) / "pid.exe"
            executable.write_bytes(b"not an executable")
            with self.assertRaisesRegex(RuntimeError, "not a PE executable"):
                build.require_x86_64_pe(executable)

    def test_pe_machine_rejects_wrong_architecture(self):
        with tempfile.TemporaryDirectory() as directory:
            executable = Path(directory) / "pid.exe"
            write_test_pe(executable, 0x14C)
            with self.assertRaisesRegex(RuntimeError, "expected an x86_64"):
                build.require_x86_64_pe(executable)

    def test_safe_extract_rejects_parent_traversal(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            archive = root / "unsafe.tar.gz"
            with tarfile.open(archive, "w:gz") as bundle:
                member = tarfile.TarInfo("../outside")
                member.size = 1
                bundle.addfile(member, io.BytesIO(b"x"))
            with self.assertRaisesRegex(RuntimeError, "unsafe path"):
                build.safe_extract(archive, root / "output")

    def test_version_matches_configure_ac(self):
        self.assertEqual(build.pi_version(REPO_ROOT / "configure.ac"), "24.0.1")

    def test_release_spec_uses_supplied_binaries(self):
        text = SPEC.read_text(encoding="utf-8")
        self.assertIn('os.environ["PI_WALLET_DAEMON_BINARY"]', text)
        self.assertIn('os.environ["PI_WALLET_TOR_BINARY"]', text)
        self.assertNotIn("chainparams", text)
        self.assertNotIn("rpcpassword", text)

    def test_tor_archive_is_pinned(self):
        self.assertEqual(len(build.TOR_ARCHIVE_SHA256), 64)
        self.assertEqual(build.TOR_BUNDLE_VERSION, "15.0.24")
        self.assertEqual(build.TOR_VERSION, "0.4.9.13")


if __name__ == "__main__":
    unittest.main()
