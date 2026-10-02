#!/usr/bin/env bash
set -euo pipefail

PACKAGING_DIR="$(cd "$(dirname "$0")" && pwd)"
REPO_ROOT="$(cd "$PACKAGING_DIR/../../.." && pwd)"
PYTHON_BIN="${PYTHON_BIN:-python3}"
VENV_DIR="${PI_WALLET_BUILD_VENV:-${TMPDIR:-/tmp}/pi-wallet-packaging-venv-py312}"
DIST_DIR="${PI_WALLET_DIST_DIR:-$REPO_ROOT/dist}"
WORK_DIR="${PI_WALLET_WORK_DIR:-${TMPDIR:-/tmp}/pi-wallet-pyinstaller-work}"
PID_BIN="$REPO_ROOT/src/pid"

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
trap 'rm -rf -- "$ICON_WORK"' EXIT
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

"$VENV_DIR/bin/pyinstaller" \
    --clean \
    --noconfirm \
    --distpath "$DIST_DIR" \
    --workpath "$WORK_DIR" \
    "$PACKAGING_DIR/pi_wallet.spec"

APP_PATH="$DIST_DIR/Pi Wallet.app"
plutil -lint "$APP_PATH/Contents/Info.plist"
codesign --force --deep --sign - "$APP_PATH"
codesign --verify --deep --strict --verbose=2 "$APP_PATH"

echo "Built: $APP_PATH"
echo "Architecture: x86_64"
echo "Version: $PI_WALLET_VERSION"
echo "Signature: ad hoc (not notarized)"
