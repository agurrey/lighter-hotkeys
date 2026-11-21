# lighter-hotkeys

A minimal, keyboard-only trading panel for [Lighter](https://lighter.xyz) perpetuals. A local Python process signs the orders; your positions show up in the normal Lighter web app. Use the lightweight localhost panel next to your charts, or the original terminal UI. No browser extension, frontend framework or build step.

The dropdown switches between BTC (50x, 0.3% stop) and LIT (5x, 1% stop). The selected market, leverage, size and stops are configurable. Each market keeps its own position tracking and session log.

## Keys

| Key | Action |
|---|---|
| `Q` | Market buy / long |
| `W` | Market sell / short |
| `E` | Close the whole position (reduce-only) |
| `Ctrl+C` | Quit the CLI (positions stay open on Lighter) |

The panel is intentionally minimal: selected side and size, PnL as a percentage of the position's initial margin (ROE), stop/leverage, connection and one short action confirmation. It shows **ACTIVO** in green when it has keyboard focus and **PAUSADO** in grey when it does not; the whole background also turns green or red. Paused only means that hotkeys cannot fire: position updates and the native stop remain active. Keep Lighter visible beside the panel and focus the panel once; there are no global hotkeys and no keylogging.

During a trade, **Queda** shows the actual remaining size as a percentage of the initial position and **Realizado** shows realized ROE on the original margin. The bottom log keeps the last 10 closed trades; **Sesión** is their realized return on the equity measured when the local server started. Closing or refreshing the browser preserves the session; restarting the server starts a new one. Partial closes use Lighter's `realized_pnl`. Since a flat market position disappears from the account response and the transaction-history endpoint is unavailable, the final tranche uses the last available position valuation, so the final logged result can differ slightly from the exact fill and fees.

By default, every BTC entry gets a **native hard stop-loss** 0.3% from your fill price; LIT uses 1%. It lives on the exchange, protects you even if you close the panel or lose internet, and is cancelled automatically when the position closes or flips. Set the market's stop to `0` to disable it or choose another distance. A stop triggers a market order with the configured slippage cap, so execution is not guaranteed during an extreme gap or crash.

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
- `SYMBOL=BTC`, `SYMBOLS=BTC,LIT`: initial market and dropdown markets.
- `LEVERAGE=50`, `LIT_LEVERAGE=5`: cross leverage set when each market is selected.
- `MARGIN_PCT=10`: each entry uses 10% of your portfolio as margin. At 50x that is a position of 5x your equity — know your risk.
- `SLIPPAGE_PCT=0.3`: worst acceptable price on market orders.
- `STOP_PCT=0.3`, `LIT_STOP_PCT=1.0`: native hard stops from entry. Set either to `0` to disable it.
- `WEB_PORT=8787`: loopback port for the panel.
- `ACCOUNT_INDEX`, `API_KEY_INDEX`, `API_PRIVATE_KEY`: only needed with `DRY_RUN=0`. Create a **dedicated API key index** at https://app.lighter.xyz/apikeys (not the one the web app uses). Never share the private key; it never leaves your machine except as local order signatures.

## Local web panel

```bash
./start-web.sh    # starts in the background and opens the panel
./stop-web.sh     # stops only the local server; positions/stops stay untouched
```

The page is served only on `127.0.0.1`, with a random session token in the URL fragment and strict WebSocket origin checks. The token never reaches Lighter. API keys, account indexes and order parameters stay in Python; the browser can only request `long`, `short` or `close`. Only one controlling tab is allowed. Commands are executed sequentially, key auto-repeat is ignored, cached command IDs prevent duplicate execution and reconnects never resend pending commands.

Optional aliases:

```bash
alias btc='cd ~/lighter-hotkeys && ./start-web.sh'
alias btc-web-stop='cd ~/lighter-hotkeys && ./stop-web.sh'
```

Runtime files (`.web.url`, `.web.pid`, `.web.log`) are local and gitignored. If the server restarts, open a fresh URL with `start-web.sh`; an old tab cannot trade with an expired session token.

## Terminal UI

```bash
.venv/bin/python hotkeys.py
```

Optional alias: `alias btc-cli='cd ~/lighter-hotkeys && .venv/bin/python hotkeys.py'`

## Safety notes

- Market orders are aggressive IOC limits with a worst-price cap (`SLIPPAGE_PCT`).
- Closes are always reduce-only, so a close can never open an opposite position.
- The web server must stay bound to `127.0.0.1`; do not expose it through a LAN address, reverse proxy or tunnel.
- An API key can trade and withdraw only to your own wallet, never to third parties. Still: dedicated key, small size first, test with `DRY_RUN=1`.
- This is a personal tool shared as-is, not financial advice. You are responsible for your orders.

MIT license. PRs welcome.
