#!/usr/bin/env python3
"""Terminal de hotkeys para Lighter. Q compra, W vende, E cierra toda la posición.

Config en .env (ver .env.example). Sin claves y con DRY_RUN=1 solo simula.
"""
import asyncio
import os
import sys
import time
from pathlib import Path

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
MARGIN_PCT = float(os.environ.get("MARGIN_PCT", "10"))  # % del portfolio usado como margen
SLIPPAGE = float(os.environ.get("SLIPPAGE_PCT", "0.3")) / 100
STOP_PCT = float(os.environ.get("STOP_PCT", "0")) / 100  # stop-loss nativo opcional a esta distancia del entry; 0 = sin stop
ACCOUNT_INDEX = int(os.environ.get("ACCOUNT_INDEX", "0") or 0)
API_KEY_INDEX = int(os.environ.get("API_KEY_INDEX", "0") or 0)
API_PRIVATE_KEY = os.environ.get("API_PRIVATE_KEY", "")

COI = int(time.time() * 1000) % 2_000_000_000  # client_order_index único por sesión


def log(msg):
    print(f"\n[{time.strftime('%H:%M:%S')}] {msg}", flush=True)


class Terminal:
    def __init__(self):
        self.api = None
        self.signer = None
        self.market = None

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
            log(f"Apalancamiento {SYMBOL} fijado a {LEVERAGE}x (cross)")
        log(f"{'TESTNET' if TESTNET else 'MAINNET'} · {SYMBOL} market_id={self.market.id} · "
            f"{'DRY-RUN (simulado)' if DRY_RUN else f'{LEVERAGE}x · {MARGIN_PCT}% margen por entrada'}")
        log("Q compra · W vende · E cierra · Ctrl+C sale")

    async def price(self):
        book = await lighter.OrderApi(self.api).order_book_orders(market_id=self.market.id, limit=1)
        return float(book.bids[0].price), float(book.asks[0].price)

    async def account(self):
        if DRY_RUN:
            return 1000.0, []  # equity ficticia para simular
        data = await lighter.AccountApi(self.api).account(by="index", value=str(ACCOUNT_INDEX))
        acc = data.accounts[0]
        pos = [p for p in acc.positions if p.market_id == self.market.id and float(p.position) != 0]
        return float(acc.total_asset_value), pos

    async def status(self):
        bid, ask = await self.price()
        equity, pos = await self.account()
        p = pos[0] if pos else None
        size = float(p.position) * (1 if p.sign >= 0 else -1) if p else 0
        log(f"{SYMBOL} {bid:,.1f}/{ask:,.1f} · equity ${equity:,.2f} · "
            + (f"posición {'LONG' if size > 0 else 'SHORT'} {abs(size)} BTC · entry {p.avg_entry_price} · "
               f"PnL {p.unrealized_pnl} · liq {p.liquidation_price}" if p else "sin posición"))

    def size_int(self, btc):
        return int(round(btc * 10 ** self.market.size_decimals))

    def price_int(self, usd):
        return int(round(usd * 10 ** self.market.price_decimals))

    async def send(self, btc, is_ask, reduce_only):
        bid, ask = await self.price()
        worst = ask * (1 + SLIPPAGE) if not is_ask else bid * (1 - SLIPPAGE)
        base_amount, price = self.size_int(btc), self.price_int(worst)
        side = "SELL" if is_ask else "BUY"
        if base_amount <= 0:
            return log("Tamaño 0: nada que enviar")
        if not reduce_only and (btc < self.market.min_base or btc * ask < self.market.min_quote):
            return log(f"Bajo el mínimo del exchange ({self.market.min_base} BTC / {self.market.min_quote} USD)")
        if DRY_RUN:
            return log(f"[SIM] {side} {btc:.6f} {SYMBOL} · peor precio {worst:,.1f} · reduce_only={reduce_only}")
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
            return log(f"ERROR: {err}")
        log(f"{side} {btc:.6f} {SYMBOL} enviado · tx {tx_hash}")
        await asyncio.sleep(1.5)
        await self.status()
        if not reduce_only:
            await self.set_stop()

    async def set_stop(self):
        """Stop-loss nativo vinculado a la posición: el exchange lo cancela al cerrar o girar."""
        if not STOP_PCT:
            return
        _, pos = await self.account()
        if not pos:
            return log("Sin posición: no se pone stop")
        p = pos[0]
        entry = float(p.avg_entry_price)
        long = p.sign >= 0
        trigger = entry * (1 - STOP_PCT if long else 1 + STOP_PCT)
        worst = trigger * (1 - SLIPPAGE if long else 1 + SLIPPAGE)
        if DRY_RUN:
            return log(f"[SIM] stop {'LONG' if long else 'SHORT'} @ {trigger:,.1f} ({STOP_PCT * 100}% del entry)")
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
            return log(f"ERROR al poner el stop: {err}")
        log(f"Stop-loss puesto @ {trigger:,.1f} ({STOP_PCT * 100}% del entry {entry:,.1f})")

    async def open(self, is_ask):
        equity, _ = await self.account()
        _, ask = await self.price()
        btc = equity * MARGIN_PCT / 100 * LEVERAGE / ask
        btc = int(btc * 10 ** self.market.size_decimals) / 10 ** self.market.size_decimals
        log(f"Entrada {'SHORT' if is_ask else 'LONG'}: ${equity * MARGIN_PCT / 100:,.2f} margen "
            f"x{LEVERAGE} = {btc:.6f} {SYMBOL}")
        await self.send(btc, is_ask, reduce_only=False)

    async def close(self):
        _, pos = await self.account()
        if not pos:
            return log("No hay posición que cerrar")
        p = pos[0]
        size = float(p.position) * (1 if p.sign >= 0 else -1)
        await self.send(abs(size), is_ask=size > 0, reduce_only=True)

    async def on_key(self, key):
        try:
            if key == "q":
                await self.open(is_ask=False)
            elif key == "w":
                await self.open(is_ask=True)
            elif key == "e":
                await self.close()
        except Exception as e:
            log(f"ERROR: {e}")

    async def run(self):
        await self.start()
        await self.status()
        queue = asyncio.Queue()
        loop = asyncio.get_running_loop()

        if sys.stdin.isatty():
            import termios, tty, select
            fd = sys.stdin.fileno()
            old = termios.tcgetattr(fd)
            tty.setcbreak(fd)

            def read_keys():
                try:
                    while True:
                        select.select([sys.stdin], [], [])
                        for ch in sys.stdin.read(1).lower():
                            loop.call_soon_threadsafe(queue.put_nowait, ch)
                except Exception:
                    pass
            import threading
            threading.Thread(target=read_keys, daemon=True).start()
        else:
            async def read_lines():  # modo no interactivo: una letra por línea
                for line in sys.stdin:
                    for ch in line.strip().lower():
                        await queue.put(ch)
                await queue.put(None)  # EOF: salir limpio
            asyncio.create_task(read_lines())

        try:
            while True:
                ch = await queue.get()
                if ch is None:
                    break
                await self.on_key(ch)
        finally:
            if sys.stdin.isatty():
                termios.tcsetattr(fd, termios.TCSADRAIN, old)
            await self.api.close()
            if self.signer:
                await self.signer.close()


if __name__ == "__main__":
    try:
        asyncio.run(Terminal().run())
    except KeyboardInterrupt:
        print("\nSaliendo. Las posiciones quedan como estén.")
