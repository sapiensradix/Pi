# Pi Wallet macOS packaging

This directory builds the Python/Tk Pi Wallet and the Pi daemon into one Intel
macOS application bundle. It does not bundle Tor, bootstrap endpoints, a
configuration file, wallet data, credentials, or onion keys.

## Scope

- Application: `Pi Wallet.app`
- Bundle identifier: `org.sapiensradix.pi.wallet`
- Version source: `configure.ac`
- Architecture: `x86_64`
- Local-build signing: ad hoc
- Release signing: Developer ID Application with hardened runtime

Apple Silicon, Tor lifecycle management, and release configuration are
separate release tasks.

## Prerequisites

- macOS with Xcode Command Line Tools
- Python 3.12 with Tk 8.6
- An already-built x86_64 `src/pid`
- The build-time dynamic libraries required by `src/pid`
- Network access on the first run to install the pinned packaging tools

The packaging tools are installed into a temporary virtual environment. Set
`PI_WALLET_BUILD_VENV` to reuse a different isolated environment.

## Build

From the repository root:

```sh
contrib/macdeploy/pi-wallet/build.sh
```

The output is `dist/Pi Wallet.app`. Override the output directory with
`PI_WALLET_DIST_DIR`.

## Local verification

```sh
plutil -lint "dist/Pi Wallet.app/Contents/Info.plist"
codesign --verify --deep --strict --verbose=2 "dist/Pi Wallet.app"
file "dist/Pi Wallet.app/Contents/MacOS/Pi Wallet"
file "dist/Pi Wallet.app/Contents/Frameworks/pid"
otool -L "dist/Pi Wallet.app/Contents/Frameworks/pid"
```

An ad hoc signature proves bundle integrity on the build machine. It is not a
Developer ID signature and does not make the application ready for public macOS
distribution.

## Signed and notarized DMG

Public distribution requires an Apple Developer Program membership, a valid
`Developer ID Application` certificate installed in the login Keychain, and a
notarytool profile stored in the Keychain. Store notarization credentials
interactively; never put an Apple password, app-specific password, API key, or
private key in this repository or in a command-line argument:

```sh
xcrun notarytool store-credentials "pi-wallet-notary"
```

Then run the release pipeline with the exact certificate name shown by
`security find-identity -v -p codesigning`:

```sh
PI_WALLET_CODESIGN_IDENTITY="Developer ID Application: Example (TEAMID)" \
PI_WALLET_NOTARY_PROFILE="pi-wallet-notary" \
contrib/macdeploy/pi-wallet/release.sh
```

The release script fails closed when either credential is unavailable. On
success it:

1. builds the app with hardened-runtime Developer ID signing;
2. verifies the complete app signature;
3. creates and signs `Pi-Wallet-24.0.1-macos-x86_64.dmg`;
4. submits the DMG to Apple's notary service and waits for acceptance;
5. staples and validates the notarization ticket;
6. runs Gatekeeper assessment; and
7. writes `dist/release/SHA256SUMS`.

The DMG and checksums are release artifacts and must not be committed to Git.
