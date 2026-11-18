# lighter-hotkeys

A minimal, keyboard-only trading terminal for [Lighter](https://lighter.xyz) perpetuals. One Python file, no UI framework, no browser extension. Press a key in your terminal, a signed market order goes to Lighter. Your positions show up in the normal Lighter web app, so you can watch charts there and trade from the terminal.

Defaults are meant for BTC perp, but the symbol, leverage, size and stop are configurable.

## Keys

| Key | Action |
|---|---|
| `Q` | Market buy / long |
| `W` | Market sell / short |
| `E` | Close the whole position (reduce-only) |
| `Ctrl+C` | Quit (positions stay open on Lighter) |

Optional: set `STOP_PCT` (e.g. `0.1`) to attach a **native stop-loss** to every entry, at that distance from your fill price. It lives on the exchange, protects you even if you close the terminal or lose internet, and is cancelled automatically when the position closes or flips. Disabled by default.

The terminal needs keyboard focus: Alt+Tab to it (or click it once), then trade. No global keylogging, no mouse.

## Install

```bash
git clone https://github.com/agurrey/lighter-hotkeys.git
cd lighter-hotkeys
python3 -m venv .venv
.venv/bin/pip install -r requirements.txt
cp .env.example .env   # then edit .env
chmod 600 .env
```

## Configure (`.env`)

- `DRY_RUN=1` simulates orders with live prices and no keys — try this first.
- `TESTNET=1` uses Lighter testnet (needs its own account and API key).
- `SYMBOL=BTC`, `LEVERAGE=50` (set on your account at startup, cross margin).
- `MARGIN_PCT=10`: each entry uses 10% of your portfolio as margin. At 50x that is a position of 5x your equity — know your risk.
- `SLIPPAGE_PCT=0.3`: worst acceptable price on market orders.
- `STOP_PCT=0`: no stop-loss by default. Set e.g. `0.1` to attach a native stop at 0.1% from entry.
- `ACCOUNT_INDEX`, `API_KEY_INDEX`, `API_PRIVATE_KEY`: only needed with `DRY_RUN=0`. Create a **dedicated API key index** at https://app.lighter.xyz/apikeys (not the one the web app uses). Never share the private key; it never leaves your machine except as local order signatures.

## Run

```bash
.venv/bin/python hotkeys.py
```

Optional alias in `~/.bashrc`: `alias btc='cd ~/lighter-hotkeys && .venv/bin/python hotkeys.py'`

## Safety notes

- Market orders are aggressive IOC limits with a worst-price cap (`SLIPPAGE_PCT`).
- Closes are always reduce-only, so a close can never open an opposite position.
- An API key can trade and withdraw only to your own wallet, never to third parties. Still: dedicated key, small size first, test with `DRY_RUN=1`.
- This is a personal tool shared as-is, not financial advice. You are responsible for your orders.

MIT license. PRs welcome.
