#!/usr/bin/env bash
set -euo pipefail

PACKAGING_DIR="$(cd "$(dirname "$0")" && pwd)"
REPO_ROOT="$(cd "$PACKAGING_DIR/../../.." && pwd)"
PYTHON_BIN="${PYTHON_BIN:-python3}"
VENV_DIR="${PI_WALLET_BUILD_VENV:-${TMPDIR:-/tmp}/pi-wallet-packaging-venv-py312}"
DIST_DIR="${PI_WALLET_DIST_DIR:-$REPO_ROOT/dist}"
WORK_DIR="${PI_WALLET_WORK_DIR:-${TMPDIR:-/tmp}/pi-wallet-pyinstaller-work}"
PID_BIN="$REPO_ROOT/src/pid"
TOR_BUNDLE_VERSION="15.0.24"
TOR_VERSION="0.4.9.13"
TOR_ARCHIVE_NAME="tor-expert-bundle-macos-x86_64-$TOR_BUNDLE_VERSION.tar.gz"
TOR_ARCHIVE_SHA256="8acb0b590f6be34084dcb6d84009ac0c61cc7c5261b7a19d2ab94845aa9bd5b6"
TOR_ARCHIVE_URL="https://dist.torproject.org/torbrowser/$TOR_BUNDLE_VERSION/$TOR_ARCHIVE_NAME"
TOR_CACHE_DIR="${PI_WALLET_TOR_CACHE_DIR:-${TMPDIR:-/tmp}/pi-wallet-tor-cache}"
TOR_ARCHIVE="${PI_WALLET_TOR_ARCHIVE:-$TOR_CACHE_DIR/$TOR_ARCHIVE_NAME}"
BOOTSTRAP_CONFIG="${PI_WALLET_BOOTSTRAP_CONFIG:-}"

if [[ "$(uname -s)" != "Darwin" ]]; then
    echo "error: Pi Wallet macOS packaging must run on macOS" >&2
    exit 1
fi

if [[ ! -x "$PID_BIN" ]]; then
    echo "error: build the Pi daemon first; expected executable: $PID_BIN" >&2
    exit 1
fi

if ! file "$PID_BIN" | grep -q "x86_64"; then
    echo "error: Patch P1 produces an Intel app, but src/pid is not x86_64" >&2
    exit 1
fi

for tool in curl file otool shasum tar; do
    if ! command -v "$tool" >/dev/null 2>&1; then
        echo "error: required packaging tool is unavailable: $tool" >&2
        exit 1
    fi
done

mkdir -p "$TOR_CACHE_DIR"
if [[ ! -f "$TOR_ARCHIVE" ]]; then
    TOR_DOWNLOAD="$TOR_ARCHIVE.download"
    curl --fail --location --silent --show-error \
        --output "$TOR_DOWNLOAD" \
        "$TOR_ARCHIVE_URL"
    mv "$TOR_DOWNLOAD" "$TOR_ARCHIVE"
fi

TOR_ARCHIVE_ACTUAL_SHA256="$(shasum -a 256 "$TOR_ARCHIVE" | awk '{print $1}')"
if [[ "$TOR_ARCHIVE_ACTUAL_SHA256" != "$TOR_ARCHIVE_SHA256" ]]; then
    echo "error: Tor Expert Bundle checksum mismatch" >&2
    echo "expected: $TOR_ARCHIVE_SHA256" >&2
    echo "actual:   $TOR_ARCHIVE_ACTUAL_SHA256" >&2
    exit 1
fi

TOR_WORK="$(mktemp -d "${TMPDIR:-/tmp}/pi-wallet-tor.XXXXXX")"
tar -xzf "$TOR_ARCHIVE" -C "$TOR_WORK"
TOR_BINARY="$TOR_WORK/tor/tor"
TOR_LIBEVENT="$TOR_WORK/tor/libevent-2.1.7.dylib"
TOR_LICENSE_DIR="$TOR_WORK/docs"

for required_file in \
    "$TOR_BINARY" \
    "$TOR_LIBEVENT" \
    "$TOR_LICENSE_DIR/tor.txt" \
    "$TOR_LICENSE_DIR/libevent.txt" \
    "$TOR_LICENSE_DIR/openssl.txt"; do
    if [[ ! -f "$required_file" ]]; then
        echo "error: Tor Expert Bundle is missing: $required_file" >&2
        exit 1
    fi
done
if [[ ! -x "$TOR_BINARY" ]]; then
    echo "error: bundled Tor is not executable" >&2
    exit 1
fi
for runtime_file in "$TOR_BINARY" "$TOR_LIBEVENT"; do
    if ! file "$runtime_file" | grep -q "x86_64"; then
        echo "error: Tor Expert Bundle contains a non-x86_64 runtime: $runtime_file" >&2
        exit 1
    fi
done
if ! "$TOR_BINARY" --version | grep -Fq "Tor version $TOR_VERSION "; then
    echo "error: unexpected Tor version in the verified Expert Bundle" >&2
    exit 1
fi
if ! otool -L "$TOR_BINARY" | grep -Fq "@executable_path/libevent-2.1.7.dylib"; then
    echo "error: bundled Tor does not load its adjacent libevent runtime" >&2
    exit 1
fi

CONFIG_WORK="$(mktemp -d "${TMPDIR:-/tmp}/pi-wallet-config.XXXXXX")"
PACKAGED_BOOTSTRAP_CONFIG=""
if [[ -n "$BOOTSTRAP_CONFIG" ]]; then
    if [[ ! -f "$BOOTSTRAP_CONFIG" ]]; then
        echo "error: release bootstrap configuration was not found: $BOOTSTRAP_CONFIG" >&2
        exit 1
    fi
    "$PYTHON_BIN" - "$REPO_ROOT/src/pi_wallet.py" "$BOOTSTRAP_CONFIG" <<'PY'
import importlib.util
from pathlib import Path
import sys

source = Path(sys.argv[1]).resolve()
config = Path(sys.argv[2]).resolve()
spec = importlib.util.spec_from_file_location("pi_wallet_config_validator", source)
module = importlib.util.module_from_spec(spec)
spec.loader.exec_module(module)
module.validate_tor_only_config(config, minimum_bootstraps=3)
PY
    PACKAGED_BOOTSTRAP_CONFIG="$CONFIG_WORK/pi.conf.release"
    cp "$BOOTSTRAP_CONFIG" "$PACKAGED_BOOTSTRAP_CONFIG"
    chmod 600 "$PACKAGED_BOOTSTRAP_CONFIG"
fi

read_define() {
    local name="$1"
    sed -n "s/^define(_CLIENT_VERSION_${name},[[:space:]]*\([0-9][0-9]*\)).*/\1/p" "$REPO_ROOT/configure.ac" | head -n 1
}

VERSION_MAJOR="$(read_define MAJOR)"
VERSION_MINOR="$(read_define MINOR)"
VERSION_BUILD="$(read_define BUILD)"
if [[ -z "$VERSION_MAJOR" || -z "$VERSION_MINOR" || -z "$VERSION_BUILD" ]]; then
    echo "error: could not derive the Pi version from configure.ac" >&2
    exit 1
fi
PI_WALLET_VERSION="$VERSION_MAJOR.$VERSION_MINOR.$VERSION_BUILD"

if [[ ! -x "$VENV_DIR/bin/python" ]]; then
    "$PYTHON_BIN" -m venv "$VENV_DIR"
fi
"$VENV_DIR/bin/python" -m pip install \
    --disable-pip-version-check \
    --require-hashes \
    --requirement "$PACKAGING_DIR/requirements.txt"

ICON_WORK="$(mktemp -d "${TMPDIR:-/tmp}/pi-wallet-icon.XXXXXX")"
trap 'rm -rf -- "$ICON_WORK" "$TOR_WORK" "$CONFIG_WORK"' EXIT
ICONSET="$ICON_WORK/PiWallet.iconset"
mkdir -p "$ICONSET"

qlmanage -t -s 1024 -o "$ICON_WORK" "$PACKAGING_DIR/pi-wallet.svg" >/dev/null 2>&1
ICON_SOURCE="$ICON_WORK/pi-wallet.svg.png"
if [[ ! -f "$ICON_SOURCE" ]]; then
    echo "error: macOS Quick Look could not render the Pi Wallet icon" >&2
    exit 1
fi

make_icon() {
    local pixels="$1"
    local output="$2"
    sips -z "$pixels" "$pixels" "$ICON_SOURCE" --out "$ICONSET/$output" >/dev/null
}

make_icon 16 icon_16x16.png
make_icon 32 icon_16x16@2x.png
make_icon 32 icon_32x32.png
make_icon 64 icon_32x32@2x.png
make_icon 128 icon_128x128.png
make_icon 256 icon_128x128@2x.png
make_icon 256 icon_256x256.png
make_icon 512 icon_256x256@2x.png
make_icon 512 icon_512x512.png
make_icon 1024 icon_512x512@2x.png
iconutil -c icns "$ICONSET" -o "$ICON_WORK/PiWallet.icns"

export PI_WALLET_ICON="$ICON_WORK/PiWallet.icns"
export PI_WALLET_VERSION
export PI_WALLET_TOR_BINARY="$TOR_BINARY"
export PI_WALLET_TOR_LIBEVENT="$TOR_LIBEVENT"
export PI_WALLET_TOR_LICENSE_DIR="$TOR_LICENSE_DIR"
if [[ -n "$PACKAGED_BOOTSTRAP_CONFIG" ]]; then
    export PI_WALLET_PACKAGED_BOOTSTRAP_CONFIG="$PACKAGED_BOOTSTRAP_CONFIG"
else
    unset PI_WALLET_PACKAGED_BOOTSTRAP_CONFIG || true
fi

"$VENV_DIR/bin/pyinstaller" \
    --clean \
    --noconfirm \
    --distpath "$DIST_DIR" \
    --workpath "$WORK_DIR" \
    "$PACKAGING_DIR/pi_wallet.spec"

APP_PATH="$DIST_DIR/Pi Wallet.app"
APP_TOR="$APP_PATH/Contents/Frameworks/tor"
APP_TOR_LIBEVENT="$APP_PATH/Contents/Frameworks/libevent-2.1.7.dylib"
plutil -lint "$APP_PATH/Contents/Info.plist"
codesign --verify --deep --strict --verbose=2 "$APP_PATH"

if [[ ! -x "$APP_TOR" || ! -f "$APP_TOR_LIBEVENT" ]]; then
    echo "error: Pi Wallet.app is missing its bundled Tor runtime" >&2
    exit 1
fi
if ! "$APP_TOR" --version | grep -Fq "Tor version $TOR_VERSION "; then
    echo "error: packaged Tor failed its version check" >&2
    exit 1
fi
if otool -L "$APP_TOR" | grep -E '/usr/local/|/opt/homebrew/|/private/tmp/|/var/folders/' >/dev/null; then
    echo "error: packaged Tor contains a build-machine runtime dependency" >&2
    exit 1
fi
for license_name in tor.txt libevent.txt openssl.txt; do
    if ! find "$APP_PATH/Contents" -path "*/licenses/tor/$license_name" -type f -print -quit | grep -q .; then
        echo "error: Pi Wallet.app is missing Tor license notice: $license_name" >&2
        exit 1
    fi
done
if [[ -n "$PACKAGED_BOOTSTRAP_CONFIG" ]]; then
    if ! find "$APP_PATH/Contents" -name pi.conf.release -type f -print -quit | grep -q .; then
        echo "error: Pi Wallet.app is missing its approved bootstrap configuration" >&2
        exit 1
    fi
fi

echo "Built: $APP_PATH"
echo "Architecture: x86_64"
echo "Version: $PI_WALLET_VERSION"
echo "Tor: $TOR_VERSION (Tor Expert Bundle $TOR_BUNDLE_VERSION)"
if [[ -n "${PI_WALLET_CODESIGN_IDENTITY:-}" ]]; then
    echo "Signature: $PI_WALLET_CODESIGN_IDENTITY (not notarized)"
else
    echo "Signature: ad hoc (not notarized)"
fi
