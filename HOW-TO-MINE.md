Getting Started with Pi

Pi is a peer-to-peer electronic currency. No accounts, no sign-ups. Just download, run, and mine.

macOS

Download Pi-macos.zip from the releases page and unzip it. You'll get these files:


pid — the node daemon
pi — the command-line tool
pi-wallet — wallet management
pi.conf.example — sample config


Copy the config:

cp pi.conf.example ~/Library/Application\ Support/Pi/pi.conf

Start the node:

./pid -conf="$HOME/Library/Application Support/Pi/pi.conf" -daemon

Connect to the network:

./pi -conf="$HOME/Library/Application Support/Pi/pi.conf" addnode 185.248.85.37:31415 add

Start mining:

./pi -conf="$HOME/Library/Application Support/Pi/pi.conf" generatetoaddress 1 $(./pi -conf="$HOME/Library/Application Support/Pi/pi.conf" getnewaddress)

Linux

Same steps, use Pi-linux.zip. Binaries are named pid-linux, pi-cli-linux, pi-tx-linux.

Windows

Build from source: https://github.com/sapiensradix/Pi

Network Nodes


IP: 185.248.85.37:31415
Tor: x5htnjlwj6ymj4cdj5satcbp77mgqged3dryfnm3npdvcl523thqy5yd.onion:31415
