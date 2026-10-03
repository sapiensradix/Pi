#!/usr/bin/env python3
"""Build the self-contained Windows x64 Pi Wallet application."""

from __future__ import annotations

import argparse
import hashlib
import importlib.util
import os
from pathlib import Path
import re
import shutil
import struct
import subprocess
import sys
import tarfile
import tempfile
import urllib.request


APP_NAME = "Pi Wallet"
TOR_BUNDLE_VERSION = "15.0.24"
TOR_VERSION = "0.4.9.13"
TOR_ARCHIVE_NAME = (
    f"tor-expert-bundle-windows-x86_64-{TOR_BUNDLE_VERSION}.tar.gz"
)
TOR_ARCHIVE_URL = (
    "https://dist.torproject.org/torbrowser/"
    f"{TOR_BUNDLE_VERSION}/{TOR_ARCHIVE_NAME}"
)
TOR_ARCHIVE_SHA256 = (
    "e9dc6ccc93cd6afa507193f4de284d6424233ff5102155cd2c94b259e8a22b65"
)
PE_MACHINE_AMD64 = 0x8664

PACKAGING_DIR = Path(__file__).resolve().parent
REPO_ROOT = PACKAGING_DIR.parents[2]


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as source:
        for block in iter(lambda: source.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def pe_machine(path: Path) -> int:
    """Return the COFF machine field from a PE executable."""
    with path.open("rb") as executable:
        if executable.read(2) != b"MZ":
            raise ValueError(f"not a PE executable: {path}")
        executable.seek(0x3C)
        offset_bytes = executable.read(4)
        if len(offset_bytes) != 4:
            raise ValueError(f"truncated PE executable: {path}")
        pe_offset = struct.unpack("<I", offset_bytes)[0]
        executable.seek(pe_offset)
        if executable.read(4) != b"PE\x00\x00":
            raise ValueError(f"invalid PE signature: {path}")
        machine_bytes = executable.read(2)
        if len(machine_bytes) != 2:
            raise ValueError(f"truncated PE header: {path}")
        return struct.unpack("<H", machine_bytes)[0]


def require_x86_64_pe(path: Path) -> None:
    if not path.is_file():
        raise RuntimeError(f"required executable was not found: {path}")
    try:
        machine = pe_machine(path)
    except (OSError, ValueError) as exc:
        raise RuntimeError(str(exc)) from exc
    if machine != PE_MACHINE_AMD64:
        raise RuntimeError(
            f"expected an x86_64 PE executable, got machine 0x{machine:04x}: {path}"
        )


def download_verified_tor(archive: Path) -> None:
    archive.parent.mkdir(parents=True, exist_ok=True)
    if not archive.exists():
        temporary = archive.with_suffix(archive.suffix + ".download")
        try:
            with urllib.request.urlopen(TOR_ARCHIVE_URL, timeout=60) as response:
                with temporary.open("wb") as output:
                    shutil.copyfileobj(response, output)
            os.replace(temporary, archive)
        finally:
            temporary.unlink(missing_ok=True)
    actual = sha256_file(archive)
    if actual != TOR_ARCHIVE_SHA256:
        raise RuntimeError(
            "Tor Expert Bundle checksum mismatch: "
            f"expected {TOR_ARCHIVE_SHA256}, got {actual}"
        )


def safe_extract(archive: Path, destination: Path) -> None:
    destination = destination.resolve()
    with tarfile.open(archive, "r:gz") as bundle:
        for member in bundle.getmembers():
            target = (destination / member.name).resolve()
            if destination not in target.parents and target != destination:
                raise RuntimeError(f"unsafe path in Tor archive: {member.name}")
            if member.issym() or member.islnk():
                raise RuntimeError(f"unexpected link in Tor archive: {member.name}")
        bundle.extractall(destination)


def pi_version(configure_ac: Path) -> str:
    text = configure_ac.read_text(encoding="utf-8")
    parts = []
    for name in ("MAJOR", "MINOR", "BUILD"):
        match = re.search(
            rf"^define\(_CLIENT_VERSION_{name},\s*([0-9]+)\)",
            text,
            flags=re.MULTILINE,
        )
        if match is None:
            raise RuntimeError(f"could not read Pi version component: {name}")
        parts.append(match.group(1))
    return ".".join(parts)


def validate_bootstrap_config(config: Path) -> None:
    wallet_source = REPO_ROOT / "src" / "pi_wallet.py"
    spec = importlib.util.spec_from_file_location(
        "pi_wallet_config_validator", wallet_source
    )
    if spec is None or spec.loader is None:
        raise RuntimeError("Pi Wallet configuration validator could not be loaded")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    module.validate_tor_only_config(config, minimum_bootstraps=3)


def write_version_file(path: Path, version: str) -> None:
    major, minor, build = (int(part) for part in version.split("."))
    path.write_text(
        f"""VSVersionInfo(
  ffi=FixedFileInfo(
    filevers=({major}, {minor}, {build}, 0),
    prodvers=({major}, {minor}, {build}, 0),
    mask=0x3f,
    flags=0x0,
    OS=0x40004,
    fileType=0x1,
    subtype=0x0,
    date=(0, 0),
  ),
  kids=[
    StringFileInfo([StringTable('040904B0', [
      StringStruct('CompanyName', 'Pi open-source contributors'),
      StringStruct('FileDescription', 'Pi Wallet'),
      StringStruct('FileVersion', '{version}'),
      StringStruct('InternalName', 'Pi Wallet'),
      StringStruct('LegalCopyright', 'Distributed under the MIT software license'),
      StringStruct('OriginalFilename', 'Pi Wallet.exe'),
      StringStruct('ProductName', 'Pi Wallet'),
      StringStruct('ProductVersion', '{version}'),
    ])]),
    VarFileInfo([VarStruct('Translation', [1033, 1200])]),
  ],
)
""",
        encoding="utf-8",
    )


def scripts_directory(venv: Path) -> Path:
    return venv / ("Scripts" if os.name == "nt" else "bin")


def run(command: list[str], **kwargs) -> None:
    printable = " ".join(command)
    print(f"+ {printable}", flush=True)
    subprocess.run(command, check=True, **kwargs)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--daemon",
        type=Path,
        default=REPO_ROOT / "src" / "pid.exe",
        help="path to the x86_64 Windows Pi daemon",
    )
    parser.add_argument(
        "--bootstrap-config",
        type=Path,
        help="reviewed Tor-only pi.conf.release (required with --release)",
    )
    parser.add_argument(
        "--release",
        action="store_true",
        help="require an approved production bootstrap configuration",
    )
    parser.add_argument(
        "--tor-archive",
        type=Path,
        default=Path(tempfile.gettempdir()) / "pi-wallet-tor-cache" / TOR_ARCHIVE_NAME,
    )
    parser.add_argument(
        "--venv",
        type=Path,
        default=Path(tempfile.gettempdir()) / "pi-wallet-packaging-venv-py312",
    )
    parser.add_argument("--dist-dir", type=Path, default=REPO_ROOT / "dist")
    parser.add_argument(
        "--work-dir",
        type=Path,
        default=Path(tempfile.gettempdir()) / "pi-wallet-pyinstaller-work-windows",
    )
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    if sys.platform != "win32":
        raise RuntimeError("Windows Pi Wallet packaging must run on Windows")
    if sys.version_info[:2] != (3, 12):
        raise RuntimeError("Windows Pi Wallet packaging requires Python 3.12")
    if args.release and args.bootstrap_config is None:
        raise RuntimeError("--release requires --bootstrap-config")

    daemon = args.daemon.resolve()
    require_x86_64_pe(daemon)
    download_verified_tor(args.tor_archive)
    version = pi_version(REPO_ROOT / "configure.ac")

    with tempfile.TemporaryDirectory(prefix="pi-wallet-windows-") as temp_name:
        temp = Path(temp_name)
        tor_root = temp / "tor-bundle"
        safe_extract(args.tor_archive, tor_root)
        tor_binary = tor_root / "tor" / "tor.exe"
        require_x86_64_pe(tor_binary)
        required_notices = [
            tor_root / "docs" / name
            for name in ("tor.txt", "libevent.txt", "openssl.txt", "zlib.txt")
        ]
        for notice in required_notices:
            if not notice.is_file():
                raise RuntimeError(f"Tor license notice is missing: {notice}")
        tor_version = subprocess.run(
            [str(tor_binary), "--version"],
            check=True,
            capture_output=True,
            text=True,
        ).stdout
        if f"Tor version {TOR_VERSION} " not in tor_version:
            raise RuntimeError("unexpected Tor version in the verified Expert Bundle")

        packaged_config = None
        if args.bootstrap_config is not None:
            config = args.bootstrap_config.resolve()
            if not config.is_file():
                raise RuntimeError(f"bootstrap configuration was not found: {config}")
            validate_bootstrap_config(config)
            packaged_config = temp / "pi.conf.release"
            shutil.copyfile(config, packaged_config)

        version_file = temp / "version_info.txt"
        write_version_file(version_file, version)

        if not (scripts_directory(args.venv) / "python.exe").exists():
            run([sys.executable, "-m", "venv", str(args.venv)])
        venv_python = scripts_directory(args.venv) / "python.exe"
        pyinstaller = scripts_directory(args.venv) / "pyinstaller.exe"
        run(
            [
                str(venv_python),
                "-m",
                "pip",
                "install",
                "--disable-pip-version-check",
                "--require-hashes",
                "--requirement",
                str(PACKAGING_DIR / "requirements.txt"),
            ]
        )

        environment = os.environ.copy()
        environment.update(
            {
                "PI_WALLET_DAEMON_BINARY": str(daemon),
                "PI_WALLET_TOR_BINARY": str(tor_binary),
                "PI_WALLET_TOR_LICENSE_DIR": str(tor_root / "docs"),
                "PI_WALLET_ICON": str(PACKAGING_DIR / "pi-wallet.ico"),
                "PI_WALLET_VERSION_FILE": str(version_file),
            }
        )
        if packaged_config is not None:
            environment["PI_WALLET_PACKAGED_BOOTSTRAP_CONFIG"] = str(packaged_config)
        else:
            environment.pop("PI_WALLET_PACKAGED_BOOTSTRAP_CONFIG", None)

        run(
            [
                str(pyinstaller),
                "--clean",
                "--noconfirm",
                "--distpath",
                str(args.dist_dir),
                "--workpath",
                str(args.work_dir),
                str(PACKAGING_DIR / "pi_wallet.spec"),
            ],
            env=environment,
        )

    app_directory = args.dist_dir / APP_NAME
    app_executable = app_directory / f"{APP_NAME}.exe"
    bundled_daemon = next(app_directory.rglob("pid.exe"), None)
    bundled_tor = next(app_directory.rglob("tor.exe"), None)
    for packaged_binary in (app_executable, bundled_daemon, bundled_tor):
        if packaged_binary is None:
            raise RuntimeError("packaged Windows application is missing a runtime")
        require_x86_64_pe(packaged_binary)
    for notice_name in ("tor.txt", "libevent.txt", "openssl.txt", "zlib.txt"):
        if not any(app_directory.rglob(notice_name)):
            raise RuntimeError(f"packaged Tor notice is missing: {notice_name}")
    if args.bootstrap_config is not None and not any(
        app_directory.rglob("pi.conf.release")
    ):
        raise RuntimeError("packaged release configuration is missing")

    archive_base = args.dist_dir / f"Pi-Wallet-{version}-windows-x86_64"
    archive_path = shutil.make_archive(
        str(archive_base), "zip", root_dir=args.dist_dir, base_dir=APP_NAME
    )
    print(f"Built: {app_directory}")
    print(f"Archive: {archive_path}")
    print("Architecture: x86_64")
    print(f"Version: {version}")
    print(f"Tor: {TOR_VERSION} (Tor Expert Bundle {TOR_BUNDLE_VERSION})")
    print("Signature: unsigned; public release requires Authenticode signing")
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except (OSError, RuntimeError, subprocess.CalledProcessError) as exc:
        print(f"error: {exc}", file=sys.stderr)
        raise SystemExit(1) from exc
