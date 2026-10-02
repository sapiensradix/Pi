# Pi Wallet macOS packaging

This directory builds the Python/Tk Pi Wallet, the Pi daemon, and the official
Tor Expert Bundle runtime into one Intel macOS application bundle. It never
bundles wallet data, credentials, or onion keys. A public release also embeds a
separately reviewed Tor-only bootstrap configuration supplied at build time.

## Scope

- Application: `Pi Wallet.app`
- Bundle identifier: `org.sapiensradix.pi.wallet`
- Version source: `configure.ac`
- Architecture: `x86_64`
- Tor: `0.4.9.13` from Tor Expert Bundle `15.0.24`
- Local-build signing: ad hoc
- Release signing: Developer ID Application with hardened runtime

Apple Silicon and release configuration are separate release tasks.

The local developer build may omit a bootstrap configuration. A public release
must provide a separately reviewed Tor-only configuration through
`PI_WALLET_BOOTSTRAP_CONFIG`. The release pipeline refuses to continue unless
that file contains at least three distinct, checksum-valid Tor v3 onion
bootstrap endpoints on port `31415` and all fail-closed network settings.

## Tor supply-chain verification

The build downloads the macOS x86_64 Tor Expert Bundle from the Tor Project and
accepts it only when its SHA-256 hash is:

```text
8acb0b590f6be34084dcb6d84009ac0c61cc7c5261b7a19d2ab94845aa9bd5b6
```

This hash was established from
`tor-expert-bundle-macos-x86_64-15.0.24.tar.gz` after its detached signature was
verified with the Tor Browser Developers signing-key fingerprint:

```text
EF6E286DDA85EA2A4BA7DE684E2C6E8793298290
```

Set `PI_WALLET_TOR_ARCHIVE` to use a previously downloaded copy. The same hash
check remains mandatory. The archive and extracted binaries are build inputs;
they must not be committed to Git.

## Prerequisites

- macOS with Xcode Command Line Tools
- Python 3.12 with Tk 8.6
- An already-built x86_64 `src/pid`
- The build-time dynamic libraries required by `src/pid`
- Network access on the first run to install the pinned packaging tools
  and download the checksum-pinned Tor Expert Bundle

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
"dist/Pi Wallet.app/Contents/Frameworks/tor" --version
otool -L "dist/Pi Wallet.app/Contents/Frameworks/tor"
find "dist/Pi Wallet.app/Contents" -path '*/licenses/tor/*' -type f -print
```

The packaged Tor executable must load its adjacent bundled libevent library and
must not reference `/usr/local`, `/opt/homebrew`, a temporary directory, or any
other build-machine package path.

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
PI_WALLET_BOOTSTRAP_CONFIG="/secure/release-input/pi.conf.release" \
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

On first launch, Pi Wallet installs the bundled configuration as `pi.conf` with
mode `0600` only when the user has no existing configuration. An existing
configuration is never overwritten and must independently pass the Tor-only
validation before Pi Core is started. The reviewed release input remains
outside Git so production endpoints are not committed before approval.

The DMG and checksums are release artifacts and must not be committed to Git.
