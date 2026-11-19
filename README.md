# lighter-hotkeys

A minimal, keyboard-only trading panel for [Lighter](https://lighter.xyz) perpetuals. A local Python process signs the orders; your positions show up in the normal Lighter web app. Use the lightweight localhost panel next to your charts, or the original terminal UI. No browser extension, frontend framework or build step.

The panel includes a **BTC / LIT selector** with independent leverage and stop settings. Switching markets never closes positions or cancels orders. `Q/W/E` and the displayed position always refer only to the selected market.

## Keys

| Key | Action |
|---|---|
| `Q` | Market buy / long on the selected market |
| `W` | Market sell / short on the selected market |
| `E` | Close the selected market's whole position (reduce-only) |
| `Ctrl+C` | Quit the CLI (positions stay open on Lighter) |

The panel shows **ACTIVO** in green when it has keyboard focus and **PAUSADO** in grey when it does not. The whole background also turns green or red. Paused only means that hotkeys cannot fire: position updates and native stops remain active. Keep Lighter visible beside the panel and focus the panel once; there are no global hotkeys and no keylogging.

Default market settings:

| Market | Leverage | Native hard stop | Position at 10% margin |
|---|---:|---:|---:|
| BTC | 50x | 0.3% from fill | 5x equity |
| LIT | 5x | 1% from fill | 0.5x equity |

Stops live on the exchange, protect you even if you close the panel or lose internet, and are cancelled automatically when their position closes or flips. New stop settings apply to new entries; changing the panel does not modify an existing position's stop. A stop triggers a market order with the configured slippage cap, so execution is not guaranteed during an extreme gap or crash.

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

- `DRY_RUN=1` simulates positions, stops and closes with live prices and no keys — try this first.
- `TESTNET=1` uses Lighter testnet (needs its own account and API key).
- `SYMBOL=BTC`: initially selected market.
- `SYMBOLS=BTC,LIT`: markets available in the selector. The CLI uses the initial market.
- `BTC_LEVERAGE=50`, `BTC_STOP_PCT=0.3`, `LIT_LEVERAGE=5`, `LIT_STOP_PCT=1`: independent settings per market. Set a stop to `0` to disable it.
- `LEVERAGE` and `STOP_PCT`: legacy fallback for the initial market; per-market values take precedence.
- `MARGIN_PCT=10`: each entry uses 10% of your portfolio as margin, multiplied by the selected market's leverage.
- `SLIPPAGE_PCT=0.3`: worst acceptable price on market orders.
- `WEB_PORT=8787`: loopback port for the panel.
- `ACCOUNT_INDEX`, `API_KEY_INDEX`, `API_PRIVATE_KEY`: only needed with `DRY_RUN=0`. Create a **dedicated API key index** at https://app.lighter.xyz/apikeys (not the one the web app uses). Never share the private key; it never leaves your machine except as local order signatures.

## Local web panel

```bash
./start-web.sh    # starts in the background and opens the panel
./stop-web.sh     # stops only the local server; positions/stops stay untouched
```

The page is served only on `127.0.0.1`, with a random session token in the URL fragment and strict WebSocket origin checks. The token never reaches Lighter. API keys, account indexes and arbitrary order parameters stay in Python; the browser can only request `long`, `short`, `close` or an allowed market selection. Only one controlling tab is allowed. Commands and market switches are executed sequentially, stale-market orders are rejected, key auto-repeat is ignored, cached command IDs prevent duplicate execution and reconnects never resend pending commands.

Optional aliases:

```bash
alias btc-web='cd ~/lighter-hotkeys && ./start-web.sh'
alias btc-web-stop='cd ~/lighter-hotkeys && ./stop-web.sh'
```

Runtime files (`.web.url`, `.web.pid`, `.web.log`) are local and gitignored. If the server restarts, open a fresh URL with `start-web.sh`; an old tab cannot trade with an expired session token.

## Terminal UI

```bash
.venv/bin/python hotkeys.py
```

Optional alias: `alias btc='cd ~/lighter-hotkeys && .venv/bin/python hotkeys.py'`

## Safety notes

- Market orders are aggressive IOC limits with a worst-price cap (`SLIPPAGE_PCT`).
- Closes are always reduce-only, so a close can never open an opposite position.
- Switching markets is read-only except for applying that market's configured leverage; it never closes a position or changes an existing stop.
- The web server must stay bound to `127.0.0.1`; do not expose it through a LAN address, reverse proxy or tunnel.
- An API key can trade and withdraw only to your own wallet, never to third parties. Still: dedicated key, small size first, test with `DRY_RUN=1`.
- This is a personal tool shared as-is, not financial advice. You are responsible for your orders.

MIT license. PRs welcome.
