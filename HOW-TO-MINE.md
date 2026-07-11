Getting Started with Pi

Pi is a peer-to-peer electronic currency.

Requirements

- Tor running on 127.0.0.1:9050

macOS

1. Download Pi-macos-x86_64.zip
2. Unzip files
3. Copy config

cp pi.conf.example "$HOME/Library/Application Support/Pi/pi.conf"

4. Start node

./pid -conf="$HOME/Library/Application Support/Pi/pi.conf" -daemon

5. Create wallet

./pi-cli -conf="$HOME/Library/Application Support/Pi/pi.conf" createwallet "pi_wallet"

6. Get address

./pi-cli -conf="$HOME/Library/Application Support/Pi/pi.conf" -rpcwallet=pi_wallet getnewaddress

7. Connect to network

./pi-cli -conf="$HOME/Library/Application Support/Pi/pi.conf" addnode x5htnjlwj6ymj4cdj5satcbp77mgqged3dryfnm3npdvcl523thqy5yd.onion:31415 add

8. Start mining

./pi-cli -rpcclienttimeout=0 -conf="$HOME/Library/Application Support/Pi/pi.conf" -rpcwallet=pi_wallet generatetoaddress 1 <your_address>

Note

Mining rewards first appear as immature balance.
Rewards become spendable after coinbase maturity (100 blocks).
