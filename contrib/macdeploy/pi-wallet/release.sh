#!/usr/bin/env bash
set -euo pipefail

PACKAGING_DIR="$(cd "$(dirname "$0")" && pwd)"
REPO_ROOT="$(cd "$PACKAGING_DIR/../../.." && pwd)"
DIST_DIR="${PI_WALLET_DIST_DIR:-$REPO_ROOT/dist}"
RELEASE_DIR="${PI_WALLET_RELEASE_DIR:-$DIST_DIR/release}"
IDENTITY="${PI_WALLET_CODESIGN_IDENTITY:-}"
NOTARY_PROFILE="${PI_WALLET_NOTARY_PROFILE:-}"
BOOTSTRAP_CONFIG="${PI_WALLET_BOOTSTRAP_CONFIG:-}"

if [[ "$(uname -s)" != "Darwin" ]]; then
    echo "error: Pi Wallet macOS release packaging must run on macOS" >&2
    exit 1
fi

if [[ -z "$IDENTITY" ]]; then
    echo "error: PI_WALLET_CODESIGN_IDENTITY must name a Developer ID Application certificate" >&2
    exit 1
fi

if [[ -z "$NOTARY_PROFILE" ]]; then
    echo "error: PI_WALLET_NOTARY_PROFILE must name a notarytool Keychain profile" >&2
    exit 1
fi

if [[ -z "$BOOTSTRAP_CONFIG" || ! -f "$BOOTSTRAP_CONFIG" ]]; then
    echo "error: PI_WALLET_BOOTSTRAP_CONFIG must name the reviewed Tor-only release configuration" >&2
    exit 1
fi

if ! security find-identity -v -p codesigning | grep -Fq "\"$IDENTITY\""; then
    echo "error: the requested Developer ID Application identity is not available in the Keychain" >&2
    exit 1
fi

case "$IDENTITY" in
    "Developer ID Application:"*) ;;
    *)
        echo "error: release signing requires a Developer ID Application identity" >&2
        exit 1
        ;;
esac

for tool in hdiutil codesign spctl shasum; do
    if ! command -v "$tool" >/dev/null 2>&1; then
        echo "error: required release tool is unavailable: $tool" >&2
        exit 1
    fi
done
xcrun --find notarytool >/dev/null
xcrun --find stapler >/dev/null

# Verify the Keychain profile before spending time building a release artifact.
xcrun notarytool history --keychain-profile "$NOTARY_PROFILE" >/dev/null

PI_WALLET_DIST_DIR="$DIST_DIR" \
PI_WALLET_CODESIGN_IDENTITY="$IDENTITY" \
    "$PACKAGING_DIR/build.sh"

APP_PATH="$DIST_DIR/Pi Wallet.app"
VERSION="$(/usr/libexec/PlistBuddy -c 'Print :CFBundleShortVersionString' "$APP_PATH/Contents/Info.plist")"
DMG_NAME="Pi-Wallet-$VERSION-macos-x86_64.dmg"
DMG_PATH="$RELEASE_DIR/$DMG_NAME"
CHECKSUM_PATH="$RELEASE_DIR/SHA256SUMS"

mkdir -p "$RELEASE_DIR"

codesign --verify --deep --strict --verbose=2 "$APP_PATH"
codesign -dv --verbose=4 "$APP_PATH" 2>&1 | grep -F "Authority=Developer ID Application:"

hdiutil create \
    -ov \
    -volname "Pi Wallet" \
    -srcfolder "$APP_PATH" \
    -format UDZO \
    -imagekey zlib-level=9 \
    "$DMG_PATH"

codesign \
    --force \
    --timestamp \
    --options runtime \
    --sign "$IDENTITY" \
    "$DMG_PATH"
codesign --verify --strict --verbose=2 "$DMG_PATH"

xcrun notarytool submit \
    "$DMG_PATH" \
    --keychain-profile "$NOTARY_PROFILE" \
    --wait \
    --timeout 30m

xcrun stapler staple "$DMG_PATH"
xcrun stapler validate "$DMG_PATH"
spctl --assess --type open --context context:primary-signature --verbose=4 "$DMG_PATH"

(
    cd "$RELEASE_DIR"
    shasum -a 256 "$DMG_NAME" > SHA256SUMS
)

echo "Release artifact: $DMG_PATH"
echo "Checksums: $CHECKSUM_PATH"
echo "Signing identity: $IDENTITY"
echo "Notarization: accepted and stapled"
