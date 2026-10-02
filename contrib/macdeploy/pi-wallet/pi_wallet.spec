from pathlib import Path
import os


APP_NAME = "Pi Wallet"
BUNDLE_ID = "org.sapiensradix.pi.wallet"
PACKAGING_DIR = Path(SPECPATH).resolve()
REPO_ROOT = PACKAGING_DIR.parents[2]
WALLET_SCRIPT = REPO_ROOT / "src" / "pi_wallet.py"
DAEMON_BINARY = REPO_ROOT / "src" / "pid"
TOR_BINARY = Path(os.environ["PI_WALLET_TOR_BINARY"]).resolve()
TOR_LIBEVENT = Path(os.environ["PI_WALLET_TOR_LIBEVENT"]).resolve()
TOR_LICENSE_DIR = Path(os.environ["PI_WALLET_TOR_LICENSE_DIR"]).resolve()
BOOTSTRAP_CONFIG = os.environ.get("PI_WALLET_PACKAGED_BOOTSTRAP_CONFIG")
ICON_FILE = Path(os.environ["PI_WALLET_ICON"]).resolve()
VERSION = os.environ["PI_WALLET_VERSION"]
CODESIGN_IDENTITY = os.environ.get("PI_WALLET_CODESIGN_IDENTITY") or None

data_files = [
    (str(TOR_LICENSE_DIR / "tor.txt"), "licenses/tor"),
    (str(TOR_LICENSE_DIR / "libevent.txt"), "licenses/tor"),
    (str(TOR_LICENSE_DIR / "openssl.txt"), "licenses/tor"),
]
if BOOTSTRAP_CONFIG:
    data_files.append((str(Path(BOOTSTRAP_CONFIG).resolve()), "."))


analysis = Analysis(
    [str(WALLET_SCRIPT)],
    pathex=[str(REPO_ROOT / "src")],
    binaries=[
        (str(DAEMON_BINARY), "."),
        (str(TOR_BINARY), "."),
        (str(TOR_LIBEVENT), "."),
    ],
    datas=data_files,
    hiddenimports=[],
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=[],
    noarchive=False,
    optimize=0,
)

pyz = PYZ(analysis.pure)

executable = EXE(
    pyz,
    analysis.scripts,
    [],
    exclude_binaries=True,
    name=APP_NAME,
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=False,
    console=False,
    argv_emulation=False,
    target_arch="x86_64",
    codesign_identity=CODESIGN_IDENTITY,
    entitlements_file=None,
)

collection = COLLECT(
    executable,
    analysis.binaries,
    analysis.datas,
    strip=False,
    upx=False,
    upx_exclude=[],
    name=APP_NAME,
)

app = BUNDLE(
    collection,
    name=f"{APP_NAME}.app",
    icon=str(ICON_FILE),
    bundle_identifier=BUNDLE_ID,
    version=VERSION,
    info_plist={
        "CFBundleDisplayName": APP_NAME,
        "CFBundleName": APP_NAME,
        "CFBundleVersion": VERSION,
        "LSMinimumSystemVersion": "10.15",
        "NSHighResolutionCapable": True,
    },
)
