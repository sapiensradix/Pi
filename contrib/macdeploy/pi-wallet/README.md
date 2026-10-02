# Pi Wallet macOS packaging

This directory builds the Python/Tk Pi Wallet and the Pi daemon into one Intel
macOS application bundle. It does not bundle Tor, bootstrap endpoints, a
configuration file, wallet data, credentials, or onion keys.

## Scope

- Application: `Pi Wallet.app`
- Bundle identifier: `org.sapiensradix.pi.wallet`
- Version source: `configure.ac`
- Architecture: `x86_64`
- Signing: ad hoc for local validation only

Developer ID signing, Apple notarization, DMG production, Apple Silicon, Tor
lifecycle management, and release configuration are separate release tasks.

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
