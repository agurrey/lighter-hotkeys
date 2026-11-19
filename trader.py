import asyncio
import os
import time
from pathlib import Path
from types import SimpleNamespace

import lighter

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
SYMBOL = os.environ.get("SYMBOL", "BTC")
LEVERAGE = int(os.environ.get("LEVERAGE", "50"))
MARGIN_PCT = float(os.environ.get("MARGIN_PCT", "10"))
SLIPPAGE = float(os.environ.get("SLIPPAGE_PCT", "0.3")) / 100
STOP_PCT = float(os.environ.get("STOP_PCT", "0.3")) / 100
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
        self.market = None
        self.log = logger or log
        self.paper = None
        self.paper_stop = None
        self.last_bid = None
        self.last_ask = None

    async def start(self):
        self.api = lighter.ApiClient(configuration=lighter.Configuration(host=URL))
        orders = lighter.OrderApi(self.api)
        books = await orders.order_books()
        book = next(b for b in books.order_books if b.symbol == SYMBOL)
        details = await orders.order_book_details(market_id=book.market_id)
        d = details.order_book_details[0]
        self.market = type("M", (), {
            "id": book.market_id,
            "size_decimals": d.size_decimals,
            "price_decimals": d.price_decimals,
            "min_base": float(d.min_base_amount),
            "min_quote": float(d.min_quote_amount),
        })()
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
            await self.signer.update_leverage(
                market_index=self.market.id,
                margin_mode=lighter.SignerClient.CROSS_MARGIN_MODE,
                leverage=LEVERAGE, api_key_index=API_KEY_INDEX,
            )
            self.log(f"Apalancamiento {SYMBOL} fijado a {LEVERAGE}x (cross)")
        self.log(f"{'TESTNET' if TESTNET else 'MAINNET'} · {SYMBOL} market_id={self.market.id} · "
                 f"{'DRY-RUN (simulado)' if DRY_RUN else f'{LEVERAGE}x · {MARGIN_PCT}% margen por entrada'}")
        stop = f"stop duro {STOP_PCT * 100:g}%" if STOP_PCT else "sin stop"
        self.log(f"Q compra · W vende · E cierra · {stop} · Ctrl+C sale")

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
        if not self.paper:
            return 1000.0, []
        size = self.paper["size"]
        mark = (self.last_bid + self.last_ask) / 2 if self.last_bid is not None else self.paper["entry"]
        pnl = (mark - self.paper["entry"]) * size
        pos = SimpleNamespace(
            market_id=self.market.id,
            position=str(abs(size)),
            sign=1 if size > 0 else -1,
            avg_entry_price=str(self.paper["entry"]),
            unrealized_pnl=str(pnl),
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
            position = {
                "side": "LONG" if size > 0 else "SHORT",
                "size": abs(size),
                "entry": float(p.avg_entry_price),
                "pnl": float(p.unrealized_pnl),
                "liquidation": float(p.liquidation_price),
            }
        return {
            "symbol": SYMBOL,
            "bid": bid,
            "ask": ask,
            "equity": equity,
            "position": position,
            "dry_run": DRY_RUN,
            "testnet": TESTNET,
            "leverage": LEVERAGE,
            "margin_pct": MARGIN_PCT,
            "stop_pct": STOP_PCT * 100,
            "paper_stop": self.paper_stop if DRY_RUN else None,
        }

    async def status(self):
        state = await self.snapshot()
        p = state["position"]
        text = f"{SYMBOL} {state['bid']:,.1f}/{state['ask']:,.1f} · equity ${state['equity']:,.2f} · "
        if p:
            text += (f"posición {p['side']} {p['size']} BTC · entry {p['entry']} · "
                     f"PnL {p['pnl']} · liq {p['liquidation']}")
        else:
            text += "sin posición"
        self.log(text)

    def size_int(self, btc):
        return int(round(btc * 10 ** self.market.size_decimals))

    def price_int(self, usd):
        return int(round(usd * 10 ** self.market.price_decimals))

    def update_paper(self, btc, is_ask, reduce_only, fill):
        signed = -btc if is_ask else btc
        old = self.paper["size"] if self.paper else 0.0
        old_entry = self.paper["entry"] if self.paper else 0.0
        new = old + signed
        if reduce_only and old * new < 0:
            new = 0.0
        if abs(new) < 1 / 10 ** self.market.size_decimals / 2:
            self.paper = None
            self.paper_stop = None
            return
        if old == 0:
            entry = fill
        elif old * new < 0:
            entry = fill
        elif old * signed > 0:
            entry = (abs(old) * old_entry + abs(signed) * fill) / abs(new)
        else:
            entry = old_entry
        self.paper = {"size": new, "entry": entry}

    async def send(self, btc, is_ask, reduce_only):
        bid, ask = await self.price()
        worst = ask * (1 + SLIPPAGE) if not is_ask else bid * (1 - SLIPPAGE)
        base_amount, price = self.size_int(btc), self.price_int(worst)
        side = "SELL" if is_ask else "BUY"
        if base_amount <= 0:
            message = "Tamaño 0: nada que enviar"
            self.log(message)
            return {"ok": False, "message": message}
        if not reduce_only and (btc < self.market.min_base or btc * ask < self.market.min_quote):
            message = f"Bajo el mínimo del exchange ({self.market.min_base} BTC / {self.market.min_quote} USD)"
            self.log(message)
            return {"ok": False, "message": message}
        if DRY_RUN:
            fill = bid if is_ask else ask
            actual_btc = base_amount / 10 ** self.market.size_decimals
            self.update_paper(actual_btc, is_ask, reduce_only, fill)
            message = f"[SIM] {side} {actual_btc:.6f} {SYMBOL} · peor precio {worst:,.1f} · reduce_only={reduce_only}"
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
            message = f"{side} {btc:.6f} {SYMBOL} enviado · tx {tx_hash}"
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
        if not STOP_PCT:
            return None
        _, pos = await self.account()
        if not pos:
            self.log("Sin posición: no se pone stop")
            return False
        p = pos[0]
        entry = float(p.avg_entry_price)
        long = p.sign >= 0
        trigger = entry * (1 - STOP_PCT if long else 1 + STOP_PCT)
        worst = trigger * (1 - SLIPPAGE if long else 1 + SLIPPAGE)
        if DRY_RUN:
            self.paper_stop = trigger
            self.log(f"[SIM] stop {'LONG' if long else 'SHORT'} @ {trigger:,.1f} ({STOP_PCT * 100}% del entry)")
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
        self.log(f"Stop-loss puesto @ {trigger:,.1f} ({STOP_PCT * 100}% del entry {entry:,.1f})")
        return True

    async def open(self, is_ask):
        equity, _ = await self.account()
        _, ask = await self.price()
        btc = equity * MARGIN_PCT / 100 * LEVERAGE / ask
        btc = int(btc * 10 ** self.market.size_decimals) / 10 ** self.market.size_decimals
        self.log(f"Entrada {'SHORT' if is_ask else 'LONG'}: ${equity * MARGIN_PCT / 100:,.2f} margen "
                 f"x{LEVERAGE} = {btc:.6f} {SYMBOL}")
        return await self.send(btc, is_ask, reduce_only=False)

    async def close(self):
        _, pos = await self.account()
        if not pos:
            message = "No hay posición que cerrar"
            self.log(message)
            return {"ok": True, "message": message, "unchanged": True}
        p = pos[0]
        size = float(p.position) * (1 if p.sign >= 0 else -1)
        return await self.send(abs(size), is_ask=size > 0, reduce_only=True)
