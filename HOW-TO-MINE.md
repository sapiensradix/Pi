# Building and Mining Pi from Source

Pi currently provides source code only. The `v1.0.0` release does not contain
verified binary assets. Do not download Pi binaries from third parties.

These instructions describe the current development main branch. They do not
declare a packaged production release.

## Requirements

- A 64-bit Linux or macOS computer
- Git, a C++ toolchain, Autotools, Boost, libevent, and SQLite
- Python 3 with Tk support for the Pi Wallet GUI
- Tor exposing a SOCKS5 proxy on `127.0.0.1:9050`

The complete inherited build documentation is available in:

- Linux: `doc/build-unix.md`
- macOS: `doc/build-osx.md`
- Windows: `doc/build-windows.md`

### Ubuntu or Debian dependencies

```bash
sudo apt-get update
sudo apt-get install build-essential libtool autotools-dev automake \
  pkg-config bsdmainutils python3 python3-tk libevent-dev libboost-dev \
  libsqlite3-dev tor
sudo systemctl enable --now tor
```

The default Pi wallet is a descriptor wallet backed by SQLite. The build below
disables legacy Berkeley DB wallet support and does not change the descriptor
wallet used by Pi Wallet.

## Build

```bash
git clone https://github.com/sapiensradix/Pi.git
cd Pi
./autogen.sh
./configure --without-gui --without-bdb --without-miniupnpc
make -j"$(nproc)"
```

On macOS, follow `doc/build-osx.md` for dependencies and replace `$(nproc)`
with `$(sysctl -n hw.ncpu)`.

Verify the executable names after the build:

```bash
./src/pid --version
./src/pi-cli --version
```

## Tor-only client configuration

Create the Pi data directory:

```bash
mkdir -p "$HOME/.pi"
chmod 700 "$HOME/.pi"
```

On Linux, save the following as `$HOME/.pi/pi.conf`. On macOS, save it as
`$HOME/Library/Application Support/Pi/pi.conf`.

```ini
server=1
listen=0
discover=0
dnsseed=0
fixedseeds=0
listenonion=0

onlynet=onion
proxy=127.0.0.1:9050
onion=127.0.0.1:9050

addnode=x5htnjlwj6ymj4cdj5satcbp77mgqged3dryfnm3npdvcl523thqy5yd.onion:31415

rpcbind=127.0.0.1
rpcallowip=127.0.0.1
```

Do not add a default `rpcuser` or `rpcpassword`. Pi Core creates an RPC cookie
inside the data directory and Pi Wallet uses that cookie automatically.

The published onion above is the currently available bootstrap endpoint. It is
not yet the intended three-node production bootstrap cluster.

## Start Pi Wallet

From the repository root:

```bash
python3 src/pi_wallet.py
```

Pi Wallet displays its window immediately. It starts `pid` when no Pi daemon is
running, creates or loads the descriptor wallet named `pi_wallet`, and enables
mining only after at least one Tor peer is connected and the local chain has
caught up with its headers.

Press **Start Mining** to mine. Press **Stop Mining** to prevent another finite
mining batch from starting. Closing a wallet that started its own daemon stops
that exact child process; closing a wallet attached to an external daemon leaves
the external daemon running.

## Command-line verification and mining

The GUI is the normal path. The following commands are useful for diagnosis.

Start Pi Core and wait for RPC readiness:

```bash
./src/pid -daemon
./src/pi-cli -rpcwait getblockchaininfo
./src/pi-cli getconnectioncount
```

Before mining, confirm that `getconnectioncount` is at least `1`, and that the
`blocks` and `headers` values reported by `getblockchaininfo` are equal.

For a new data directory, create a descriptor wallet and address:

```bash
./src/pi-cli createwallet "pi_wallet"
ADDRESS="$(./src/pi-cli -rpcwallet=pi_wallet getnewaddress)"
printf '%s\n' "$ADDRESS"
```

Run finite SHA-256d mining batches until stopped with `Ctrl-C`:

```bash
while true; do
  ./src/pi-cli -rpcwallet=pi_wallet \
    generatetoaddress 1 "$ADDRESS" 1000000
done
```

Each call tries at most 1,000,000 hashes. An empty result means that batch did
not find a block; it does not mean mining failed.

Check wallet balances:

```bash
./src/pi-cli -rpcwallet=pi_wallet getbalances
```

New block rewards first appear as immature balance. Coinbase rewards become
spendable after 100 blocks.

Stop an externally started daemon cleanly:

```bash
./src/pi-cli stop
```

## Current network identity

- P2P port: `31415`
- Tor transport: onion v3 only
- Address format: `pi1q...`
- Proof of work: SHA-256d
- Initial block subsidy: `50 PI`
- Halving interval: `210,000` blocks
