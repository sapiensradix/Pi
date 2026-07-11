# Getting Started with Pi

Pi is a peer-to-peer electronic currency. No accounts, no sign-ups. Just download, run, and mine.

## Requirements

- Tor must be running on 127.0.0.1:9050
  - macOS: `brew install tor && brew services start tor`
  - Linux: `sudo apt install tor && sudo systemctl start tor`

## macOS

1. Download `Pi-macos-x86_64.zip` from the releases page and unzip

2. Copy config:
   ```
   cp pi.conf.example "$HOME/Library/Application Support/Pi/pi.conf"
   ```

3. Start node:
   ```
   ./pid -conf="$HOME/Library/Application Support/Pi/pi.conf" -daemon
   ```

4. Create wallet:
   ```
   ./pi-cli -conf="$HOME/Library/Application Support/Pi/pi.conf" createwallet "pi_wallet"
   ```

5. Get address:
   ```
   ./pi-cli -conf="$HOME/Library/Application Support/Pi/pi.conf" -rpcwallet=pi_wallet getnewaddress
   ```
   Returns: `pi1q...`

6. Start mining:
   ```
   ./pi-cli -rpcclienttimeout=0 \
     -conf="$HOME/Library/Application Support/Pi/pi.conf" \
     -rpcwallet=pi_wallet \
     generatetoaddress 1 "pi1q..."
   ```

## Linux

1. Download `Pi-linux-x86_64.zip` from the releases page and unzip

2. Make executable:
   ```
   chmod +x pid-linux pi-cli-linux pi-tx-linux
   ```

3. Copy config to `~/.pi/pi.conf` using `pi.conf.example`

4. Start node:
   ```
   ./pid-linux -conf="$HOME/.pi/pi.conf" -daemon
   ```

5. Create wallet:
   ```
   ./pi-cli-linux -conf="$HOME/.pi/pi.conf" createwallet "pi_wallet"
   ```

6. Get address:
   ```
   ./pi-cli-linux -conf="$HOME/.pi/pi.conf" -rpcwallet=pi_wallet getnewaddress
   ```

7. Start mining:
   ```
   ./pi-cli-linux -rpcclienttimeout=0 \
     -conf="$HOME/.pi/pi.conf" \
     -rpcwallet=pi_wallet \
     generatetoaddress 1 "pi1q..."
   ```

## Windows

Build from source: https://github.com/sapiensradix/Pi

## Check balance

```
./pi-cli -conf="..." getwalletinfo
```

- `balance` — spendable PI
- `immature_balance` — mining rewards waiting for coinbase maturity (100 blocks)

Mining rewards first appear as immature balance. Rewards become spendable after 100 blocks.

## Network

- Node (Tor): `x5htnjlwj6ymj4cdj5satcbp77mgqged3dryfnm3npdvcl523thqy5yd.onion:31415`
- Block reward: `50 PI`
- Halving: every `210,000` blocks
- Algorithm: SHA-256
- Address format: `pi1q...`

## Source

https://github.com/sapiensradix/Pi
