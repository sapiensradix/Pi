# Pi Wallet Windows x64 packaging

This directory builds Pi Wallet, the Pi daemon, and the official Tor Expert
Bundle into a self-contained Windows x64 application directory and ZIP archive.
Users do not need Python, a compiler, or a source checkout to run the result.

This is a packaging pipeline, not authorization to publish a release. A public
release must use a separately reviewed Tor-only bootstrap configuration and an
Authenticode code-signing certificate.

## Scope

- Supported release target: Windows 10 and Windows 11, x86_64
- Application: `Pi Wallet.exe`
- Version source: `configure.ac`
- Pi daemon: an x86_64 `pid.exe` built from this repository
- Tor: `0.4.9.13` from Tor Expert Bundle `15.0.24`
- Output: one-folder application plus `Pi-Wallet-<version>-windows-x86_64.zip`

The package never includes wallet data, RPC credentials, onion private keys,
or a maintainer's local configuration.

## Tor supply-chain check

The build downloads the official Windows x86_64 Tor Expert Bundle from the Tor
Project and accepts only this SHA-256 digest:

```text
e9dc6ccc93cd6afa507193f4de284d6424233ff5102155cd2c94b259e8a22b65
```

Set `--tor-archive` to use an existing archive. The hash check is mandatory.
The Tor runtime and its license notices are build inputs and must not be
committed to Git.

## Prerequisites

- Windows 10 or Windows 11 x64
- Python 3.12 x64
- An x86_64 Windows `src\pid.exe` built from the same reviewed commit
- A reviewed `pi.conf.release` for a release build

Pi Core's documented MinGW cross-build produces the required `pid.exe` without
renaming the daemon or changing its public command-line identity.

## Developer package

From PowerShell in the repository root:

```powershell
py -3.12 contrib\windeploy\pi-wallet\build.py
```

A developer package may omit the bootstrap configuration. It is not suitable
for publication and will fail closed on a clean computer until an independently
valid Tor-only configuration is present.

## Release-candidate package

```powershell
py -3.12 contrib\windeploy\pi-wallet\build.py `
  --release `
  --bootstrap-config C:\secure\release-input\pi.conf.release
```

`--release` refuses to continue unless the configuration contains all required
fail-closed settings and at least three distinct, checksum-valid Tor v3 onion
bootstrap endpoints on port `31415`. Existing user configuration is never
overwritten by the wallet.

## Required clean-machine verification

The ZIP is not releasable until a separate Windows 10 and Windows 11 x64 machine
has verified all of the following without Python or build tools installed:

1. extract the ZIP and start `Pi Wallet.exe`;
2. Windows shows a valid Authenticode publisher;
3. bundled Tor starts and no clearnet peer is used;
4. Pi Core starts or the wallet attaches to an existing valid Pi daemon;
5. a descriptor wallet is created or loaded locally;
6. the wallet connects to an approved onion bootstrap and synchronizes;
7. Start Mining, Stop Mining, restart, send, backup, and restore pass;
8. closing an attached wallet leaves the external daemon running;
9. closing a managed wallet stops only its exact child process; and
10. no credentials, wallet data, onion keys, or public IP information appear in
    the package or build log.

An unsigned local ZIP is only a developer artifact. Public Windows distribution
requires Authenticode signing, timestamping, signature verification, published
SHA-256 checksums, malware scanning, and maintainer approval.
