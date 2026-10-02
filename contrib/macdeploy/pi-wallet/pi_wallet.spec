from pathlib import Path
import os


APP_NAME = "Pi Wallet"
BUNDLE_ID = "org.sapiensradix.pi.wallet"
PACKAGING_DIR = Path(SPECPATH).resolve()
REPO_ROOT = PACKAGING_DIR.parents[2]
WALLET_SCRIPT = REPO_ROOT / "src" / "pi_wallet.py"
DAEMON_BINARY = REPO_ROOT / "src" / "pid"
ICON_FILE = Path(os.environ["PI_WALLET_ICON"]).resolve()
VERSION = os.environ["PI_WALLET_VERSION"]


analysis = Analysis(
    [str(WALLET_SCRIPT)],
    pathex=[str(REPO_ROOT / "src")],
    binaries=[(str(DAEMON_BINARY), ".")],
    datas=[],
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
    codesign_identity=None,
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
