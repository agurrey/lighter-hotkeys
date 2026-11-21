import asyncio
import os
import time
from pathlib import Path
from types import SimpleNamespace

import lighter

from session import SessionTracker

BASE = Path(__file__).resolve().parent
ENV = BASE / ".env"
if ENV.exists():
    for line in ENV.read_text().splitlines():
        line = line.strip()
        if line and not line.startswith("#") and "=" in line:
            k, v = line.split("=", 1)
            os.environ.setdefault(k.strip(), v.split("#", 1)[0].strip())

DRY_RUN = os.environ.get("DRY_RUN", "1") == "1"
TESTNET = os.environ.get("TESTNET", "0") == "1"
URL = "https://testnet.zklighter.elliot.ai" if TESTNET else "https://mainnet.zklighter.elliot.ai"
DEFAULT_SYMBOL = os.environ.get("SYMBOL", "BTC").upper()
SYMBOLS = tuple(s.strip().upper() for s in os.environ.get("SYMBOLS", "BTC,LIT").split(",") if s.strip())
if DEFAULT_SYMBOL not in SYMBOLS:
    SYMBOLS = (DEFAULT_SYMBOL, *SYMBOLS)
MARGIN_PCT = float(os.environ.get("MARGIN_PCT", "10"))
SLIPPAGE = float(os.environ.get("SLIPPAGE_PCT", "0.3")) / 100
LEGACY_LEVERAGE = int(os.environ.get("LEVERAGE", "50"))
LEGACY_STOP = float(os.environ.get("STOP_PCT", "0.3"))
KNOWN_DEFAULTS = {"BTC": (50, 0.3), "LIT": (5, 1.0)}
MARKET_SETTINGS = {}
for symbol in SYMBOLS:
    known_leverage, known_stop = KNOWN_DEFAULTS.get(symbol, (LEGACY_LEVERAGE, LEGACY_STOP))
    leverage = int(os.environ.get(f"{symbol}_LEVERAGE", LEGACY_LEVERAGE if symbol == DEFAULT_SYMBOL else known_leverage))
    stop_pct = float(os.environ.get(f"{symbol}_STOP_PCT", LEGACY_STOP if symbol == DEFAULT_SYMBOL else known_stop)) / 100
    MARKET_SETTINGS[symbol] = {"leverage": leverage, "stop_pct": stop_pct}
ACCOUNT_INDEX = int(os.environ.get("ACCOUNT_INDEX", "0") or 0)
API_KEY_INDEX = int(os.environ.get("API_KEY_INDEX", "0") or 0)
API_PRIVATE_KEY = os.environ.get("API_PRIVATE_KEY", "")
COI = int(time.time() * 1000) % 2_000_000_000


def log(msg):
    print(f"\n[{time.strftime('%H:%M:%S')}] {msg}", flush=True)


class Terminal:
    def __init__(self, logger=None):
        self.api = None
        self.signer = None
        self.symbol = DEFAULT_SYMBOL
        self.markets = {}
        self.market = None
        self.log = logger or log
        self.paper = {}
        self.paper_stop = {}
        self.paper_realized = {}
        self.last_bid = None
        self.last_ask = None
        self.sessions = {symbol: SessionTracker(settings["leverage"]) for symbol, settings in MARKET_SETTINGS.items()}

    @property
    def leverage(self):
        return MARKET_SETTINGS[self.symbol]["leverage"]

    @property
    def stop_pct(self):
        return MARKET_SETTINGS[self.symbol]["stop_pct"]

    @property
    def session(self):
        return self.sessions[self.symbol]

    async def start(self):
        self.api = lighter.ApiClient(configuration=lighter.Configuration(host=URL))
        orders = lighter.OrderApi(self.api)
        books = await orders.order_books()
        by_symbol = {book.symbol: book for book in books.order_books}
        for symbol in SYMBOLS:
            book = by_symbol[symbol]
            details = await orders.order_book_details(market_id=book.market_id)
            d = details.order_book_details[0]
            self.markets[symbol] = type("M", (), {
                "id": book.market_id,
                "size_decimals": d.size_decimals,
                "price_decimals": d.price_decimals,
                "min_base": float(d.min_base_amount),
                "min_quote": float(d.min_quote_amount),
            })()
        self.market = self.markets[self.symbol]
        if not DRY_RUN:
            import sys
            if not (ACCOUNT_INDEX and API_PRIVATE_KEY):
                sys.exit("Faltan ACCOUNT_INDEX / API_PRIVATE_KEY en .env (o usa DRY_RUN=1)")
            self.signer = lighter.SignerClient(
                url=URL, account_index=ACCOUNT_INDEX,
                api_private_keys={API_KEY_INDEX: API_PRIVATE_KEY},
            )
            err = self.signer.check_client()
            if err:
                sys.exit(f"Clave rechazada por Lighter: {err}")
            await self.update_leverage()
        self.log(f"{'TESTNET' if TESTNET else 'MAINNET'} · {self.symbol} market_id={self.market.id} · "
                 f"{'DRY-RUN (simulado)' if DRY_RUN else f'{self.leverage}x · {MARGIN_PCT}% margen por entrada'}")
        markets = " · ".join(f"{s} {MARKET_SETTINGS[s]['leverage']}x SL {MARKET_SETTINGS[s]['stop_pct'] * 100:g}%"
                             for s in SYMBOLS)
        self.log(markets)
        self.log(f"Q compra · W vende · E cierra {self.symbol} · stop duro {self.stop_pct * 100:g}% · Ctrl+C sale")

    async def update_leverage(self):
        if DRY_RUN:
            return
        await self.signer.update_leverage(
            market_index=self.market.id,
            margin_mode=lighter.SignerClient.CROSS_MARGIN_MODE,
            leverage=self.leverage, api_key_index=API_KEY_INDEX,
        )
        self.log(f"Apalancamiento {self.symbol} fijado a {self.leverage}x (cross)")

    async def select(self, symbol):
        if symbol not in self.markets:
            return False
        if symbol == self.symbol:
            return True
        self.symbol = symbol
        self.market = self.markets[symbol]
        await self.update_leverage()
        self.log(f"Mercado seleccionado: {symbol} · {self.leverage}x · stop {self.stop_pct * 100:g}%")
        return True

    async def shutdown(self):
        if self.api:
            await self.api.close()
        if self.signer:
            await self.signer.close()

    async def price(self):
        book = await lighter.OrderApi(self.api).order_book_orders(market_id=self.market.id, limit=1)
        self.last_bid, self.last_ask = float(book.bids[0].price), float(book.asks[0].price)
        return self.last_bid, self.last_ask

    async def account(self):
        if not DRY_RUN:
            data = await lighter.AccountApi(self.api).account(by="index", value=str(ACCOUNT_INDEX))
            acc = data.accounts[0]
            pos = [p for p in acc.positions if p.market_id == self.market.id and float(p.position) != 0]
            return float(acc.total_asset_value), pos
        paper = self.paper.get(self.symbol)
        if not paper:
            return 1000.0, []
        size = paper["size"]
        mark = (self.last_bid + self.last_ask) / 2 if self.last_bid is not None else paper["entry"]
        pnl = (mark - paper["entry"]) * size
        pos = SimpleNamespace(
            market_id=self.market.id,
            position=str(abs(size)),
            sign=1 if size > 0 else -1,
            avg_entry_price=str(paper["entry"]),
            unrealized_pnl=str(pnl),
            realized_pnl=str(self.paper_realized.get(self.symbol, 0.0)),
            liquidation_price="0",
        )
        return 1000.0, [pos]

    async def snapshot(self):
        bid, ask = await self.price()
        equity, pos = await self.account()
        p = pos[0] if pos else None
        size = float(p.position) * (1 if p.sign >= 0 else -1) if p else 0
        position = None
        if p:
            entry = float(p.avg_entry_price)
            pnl = float(p.unrealized_pnl)
            margin = abs(size) * entry / self.leverage
            position = {
                "side": "LONG" if size > 0 else "SHORT",
                "size": abs(size),
                "entry": entry,
                "pnl": pnl,
                "pnl_pct": pnl / margin * 100 if margin else 0.0,
                "liquidation": float(p.liquidation_price),
            }
        realized_total = float(p.realized_pnl) if p else (self.paper_realized.get(self.symbol, 0.0) if DRY_RUN else None)
        session = self.session.update(equity, position, realized_total)
        return {
            "symbol": self.symbol,
            "markets": [{"symbol": s, "leverage": MARKET_SETTINGS[s]["leverage"],
                         "stop_pct": MARKET_SETTINGS[s]["stop_pct"] * 100} for s in SYMBOLS],
            "bid": bid,
            "ask": ask,
            "equity": equity,
            "position": position,
            "trade": session["trade"],
            "session": session["session"],
            "dry_run": DRY_RUN,
            "testnet": TESTNET,
            "leverage": self.leverage,
            "margin_pct": MARGIN_PCT,
            "stop_pct": self.stop_pct * 100,
            "paper_stop": self.paper_stop.get(self.symbol) if DRY_RUN else None,
        }

    async def status(self):
        state = await self.snapshot()
        p = state["position"]
        text = f"{self.symbol} {state['bid']:,.4f}/{state['ask']:,.4f} · equity ${state['equity']:,.2f} · "
        if p:
            text += (f"posición {p['side']} {p['size']} {self.symbol} · entry {p['entry']} · "
                     f"PnL {p['pnl']} · liq {p['liquidation']}")
        else:
            text += "sin posición"
        self.log(text)

    def size_int(self, amount):
        return int(round(amount * 10 ** self.market.size_decimals))

    def price_int(self, usd):
        return int(round(usd * 10 ** self.market.price_decimals))

    def update_paper(self, amount, is_ask, reduce_only, fill):
        signed = -amount if is_ask else amount
        paper = self.paper.get(self.symbol)
        old = paper["size"] if paper else 0.0
        old_entry = paper["entry"] if paper else 0.0
        if old and old * signed < 0:
            closed = min(abs(old), abs(signed))
            realized = (fill - old_entry) * closed * (1 if old > 0 else -1)
            self.paper_realized[self.symbol] = self.paper_realized.get(self.symbol, 0.0) + realized
        new = old + signed
        if reduce_only and old * new < 0:
            new = 0.0
        if abs(new) < 1 / 10 ** self.market.size_decimals / 2:
            self.paper.pop(self.symbol, None)
            self.paper_stop.pop(self.symbol, None)
            return
        if old == 0:
            entry = fill
        elif old * new < 0:
            entry = fill
        elif old * signed > 0:
            entry = (abs(old) * old_entry + abs(signed) * fill) / abs(new)
        else:
            entry = old_entry
        self.paper[self.symbol] = {"size": new, "entry": entry}

    async def send(self, amount, is_ask, reduce_only):
        bid, ask = await self.price()
        worst = ask * (1 + SLIPPAGE) if not is_ask else bid * (1 - SLIPPAGE)
        base_amount, price = self.size_int(amount), self.price_int(worst)
        side = "SELL" if is_ask else "BUY"
        if base_amount <= 0:
            message = "Tamaño 0: nada que enviar"
            self.log(message)
            return {"ok": False, "message": message}
        if not reduce_only and (amount < self.market.min_base or amount * ask < self.market.min_quote):
            message = f"Bajo el mínimo del exchange ({self.market.min_base} {self.symbol} / {self.market.min_quote} USD)"
            self.log(message)
            return {"ok": False, "message": message}
        if DRY_RUN:
            fill = bid if is_ask else ask
            actual_amount = base_amount / 10 ** self.market.size_decimals
            self.update_paper(actual_amount, is_ask, reduce_only, fill)
            message = f"[SIM] {side} {actual_amount:.6f} {self.symbol} · peor precio {worst:,.4f} · reduce_only={reduce_only}"
            self.log(message)
            result = {"ok": True, "message": message, "simulated": True, "tx_hash": None}
        else:
            global COI
            COI += 1
            api_key_index, nonce = self.signer.nonce_manager.next_nonce(API_KEY_INDEX)
            tx, tx_hash, err = await self.signer.create_order(
                market_index=self.market.id, client_order_index=COI, base_amount=base_amount,
                price=price, is_ask=is_ask,
                order_type=lighter.SignerClient.ORDER_TYPE_MARKET,
                time_in_force=lighter.SignerClient.ORDER_TIME_IN_FORCE_IMMEDIATE_OR_CANCEL,
                reduce_only=reduce_only, trigger_price=0, nonce=nonce, api_key_index=api_key_index,
                order_expiry=0,
            )
            if err:
                message = f"ERROR: {err}"
                self.log(message)
                return {"ok": False, "message": message}
            message = f"{side} {amount:.6f} {self.symbol} enviado"
            self.log(message)
            result = {"ok": True, "message": message, "simulated": False, "tx_hash": str(tx_hash)}
            await asyncio.sleep(1.5)
        await self.status()
        if not reduce_only:
            stop_ok = await self.set_stop()
            if stop_ok is False:
                result["warning"] = "La entrada se ejecutó, pero no se pudo colocar el stop-loss"
        return result

    async def set_stop(self):
        if not self.stop_pct:
            return None
        _, pos = await self.account()
        if not pos:
            self.log("Sin posición: no se pone stop")
            return False
        p = pos[0]
        entry = float(p.avg_entry_price)
        long = p.sign >= 0
        trigger = entry * (1 - self.stop_pct if long else 1 + self.stop_pct)
        worst = trigger * (1 - SLIPPAGE if long else 1 + SLIPPAGE)
        if DRY_RUN:
            self.paper_stop[self.symbol] = trigger
            self.log(f"[SIM] stop {self.symbol} {'LONG' if long else 'SHORT'} @ {trigger:,.4f} ({self.stop_pct * 100}% del entry)")
            return True
        global COI
        COI += 1
        api_key_index, nonce = self.signer.nonce_manager.next_nonce(API_KEY_INDEX)
        tx, tx_hash, err = await self.signer.create_order(
            market_index=self.market.id, client_order_index=COI, base_amount=0,
            price=self.price_int(worst), is_ask=long,
            order_type=lighter.SignerClient.ORDER_TYPE_STOP_LOSS,
            time_in_force=lighter.SignerClient.ORDER_TIME_IN_FORCE_IMMEDIATE_OR_CANCEL,
            reduce_only=True, trigger_price=self.price_int(trigger),
            nonce=nonce, api_key_index=api_key_index, order_expiry=-1,
        )
        if err:
            self.log(f"ERROR al poner el stop: {err}")
            return False
        self.log(f"Stop-loss {self.symbol} puesto @ {trigger:,.4f} ({self.stop_pct * 100}% del entry {entry:,.4f})")
        return True

    async def open(self, is_ask):
        equity, _ = await self.account()
        _, ask = await self.price()
        amount = equity * MARGIN_PCT / 100 * self.leverage / ask
        amount = int(amount * 10 ** self.market.size_decimals) / 10 ** self.market.size_decimals
        self.log(f"Entrada {self.symbol} {'SHORT' if is_ask else 'LONG'}: ${equity * MARGIN_PCT / 100:,.2f} margen "
                 f"x{self.leverage} = {amount:.6f} {self.symbol}")
        return await self.send(amount, is_ask, reduce_only=False)

    async def close(self):
        _, pos = await self.account()
        if not pos:
            message = f"No hay posición {self.symbol} que cerrar"
            self.log(message)
            return {"ok": True, "message": message, "unchanged": True}
        p = pos[0]
        size = float(p.position) * (1 if p.sign >= 0 else -1)
        return await self.send(abs(size), is_ask=size > 0, reduce_only=True)
