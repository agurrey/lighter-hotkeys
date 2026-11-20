#!/usr/bin/env python3
import argparse
import asyncio
import hmac
import json
import os
import secrets
import signal
import time
import webbrowser
from collections import deque
from pathlib import Path

from aiohttp import web
from aiohttp import WSMsgType

from trader import Terminal

BASE = Path(__file__).resolve().parent
URL_FILE = BASE / ".web.url"
PID_FILE = BASE / ".web.pid"


def write_private(path, content):
    fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
    with os.fdopen(fd, "w") as file:
        file.write(content)


class LocalPanel:
    def __init__(self, port):
        self.port = port
        self.origin = f"http://127.0.0.1:{port}"
        self.token = secrets.token_urlsafe(32)
        self.url = f"{self.origin}/#{self.token}"
        self.terminal = Terminal(logger=self.log)
        self.client = None
        self.logs = deque(maxlen=100)
        self.outbox = asyncio.Queue()
        self.command_lock = asyncio.Lock()
        self.results = {}
        self.result_ids = deque(maxlen=100)
        self.last_status_error = None

    def log(self, message):
        print(f"[{time.strftime('%H:%M:%S')}] {message}", flush=True)
        self.logs.append(message)
        self.outbox.put_nowait({"type": "log", "message": message})

    def emit(self, message):
        self.outbox.put_nowait(message)

    async def pump(self):
        while True:
            message = await self.outbox.get()
            client = self.client
            if client is None or client.closed:
                continue
            try:
                await client.send_json(message)
            except (ConnectionError, RuntimeError):
                pass

    async def index(self, request):
        headers = {
            "Cache-Control": "no-store",
            "Content-Security-Policy": "default-src 'self'; connect-src 'self' ws://127.0.0.1:*; script-src 'unsafe-inline'; style-src 'unsafe-inline'; base-uri 'none'; frame-ancestors 'none'",
            "X-Content-Type-Options": "nosniff",
        }
        return web.FileResponse(BASE / "panel.html", headers=headers)

    async def send_state(self, client=None):
        message = {"type": "state", "state": await self.terminal.snapshot()}
        if client is not None:
            await client.send_json(message)
        else:
            self.emit(message)

    def cached_result(self, command_id):
        return self.results.get(command_id)

    def cache_result(self, result):
        command_id = result["command_id"]
        if command_id in self.results:
            return
        if len(self.result_ids) == self.result_ids.maxlen:
            oldest = self.result_ids.popleft()
            self.results.pop(oldest, None)
        self.result_ids.append(command_id)
        self.results[command_id] = result

    async def command(self, data):
        command_id = data.get("command_id")
        action = data.get("action")
        if not isinstance(command_id, str) or not 1 <= len(command_id) <= 100:
            return {"type": "error", "message": "ID de comando inválido"}
        cached = self.cached_result(command_id)
        if cached:
            return cached
        if action not in {"long", "short", "close"}:
            return {"type": "error", "message": "Acción no permitida"}
        async with self.command_lock:
            cached = self.cached_result(command_id)
            if cached:
                return cached
            try:
                if action == "long":
                    outcome = await self.terminal.open(is_ask=False)
                elif action == "short":
                    outcome = await self.terminal.open(is_ask=True)
                else:
                    outcome = await self.terminal.close()
            except Exception as error:
                self.log(f"ERROR: {error}")
                outcome = {"ok": False, "message": str(error)}
            result = {"type": "result", "command_id": command_id, "action": action, **outcome}
            self.cache_result(result)
            self.emit(result)
            try:
                await self.send_state()
            except Exception as error:
                self.log(f"ERROR actualizando estado: {error}")
            return None

    async def websocket(self, request):
        if request.headers.get("Origin") != self.origin:
            return web.Response(status=403, text="Origen no permitido")
        client = web.WebSocketResponse(heartbeat=20)
        await client.prepare(request)
        try:
            try:
                data = await asyncio.wait_for(client.receive_json(), timeout=10)
            except (asyncio.TimeoutError, TypeError, ValueError):
                await client.close(code=4001, message=b"Autenticacion requerida")
                return client
            if not isinstance(data, dict) or data.get("type") != "auth" or not isinstance(data.get("token"), str) or not hmac.compare_digest(data["token"], self.token):
                await client.send_json({"type": "error", "message": "Sesión no autorizada"})
                await client.close(code=4001, message=b"Sesion no autorizada")
                return client
            if self.client is not None and not self.client.closed:
                await client.send_json({"type": "error", "message": "Ya hay otra pestaña controlando el panel"})
                await client.close(code=4003, message=b"Ya hay otra pestana activa")
                return client
            self.client = client
            await client.send_json({"type": "hello"})
            await client.send_json({"type": "logs", "messages": list(self.logs)[-8:]})
            await self.send_state(client)
            async for message in client:
                if message.type != WSMsgType.TEXT:
                    continue
                try:
                    data = json.loads(message.data)
                except json.JSONDecodeError:
                    await client.send_json({"type": "error", "message": "Mensaje inválido"})
                    continue
                if isinstance(data, dict) and data.get("type") == "command":
                    response = await self.command(data)
                    if response:
                        await client.send_json(response)
        finally:
            if self.client is client:
                self.client = None
        return client

    async def status_loop(self):
        while True:
            await asyncio.sleep(2)
            if self.client is None or self.client.closed:
                continue
            try:
                await self.send_state()
            except Exception as error:
                text = str(error)
                if text != self.last_status_error:
                    self.log(f"ERROR actualizando estado: {text}")
                    self.last_status_error = text
            else:
                self.last_status_error = None

    async def run(self, open_browser):
        runner = None
        tasks = []
        stop = asyncio.Event()
        loop = asyncio.get_running_loop()
        for sig in (signal.SIGINT, signal.SIGTERM):
            loop.add_signal_handler(sig, stop.set)
        try:
            await self.terminal.start()
            app = web.Application()
            app.router.add_get("/", self.index)
            app.router.add_get("/ws", self.websocket)
            runner = web.AppRunner(app, access_log=None)
            await runner.setup()
            site = web.TCPSite(runner, host="127.0.0.1", port=self.port, shutdown_timeout=2)
            await site.start()
            write_private(URL_FILE, self.url + "\n")
            write_private(PID_FILE, str(os.getpid()) + "\n")
            tasks = [asyncio.create_task(self.pump()), asyncio.create_task(self.status_loop())]
            print(f"Panel: {self.url}", flush=True)
            if open_browser:
                webbrowser.open(self.url, new=1)
            await stop.wait()
        finally:
            for task in tasks:
                task.cancel()
            if tasks:
                await asyncio.gather(*tasks, return_exceptions=True)
            if runner:
                await runner.cleanup()
            await self.terminal.shutdown()
            try:
                if URL_FILE.read_text().strip() == self.url:
                    URL_FILE.unlink(missing_ok=True)
                if PID_FILE.read_text().strip() == str(os.getpid()):
                    PID_FILE.unlink(missing_ok=True)
            except FileNotFoundError:
                pass


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Panel web local para Lighter Hotkeys")
    parser.add_argument("--port", type=int, default=int(os.environ.get("WEB_PORT", "8787")))
    parser.add_argument("--open", action="store_true", help="Abrir el panel en el navegador")
    args = parser.parse_args()
    panel = LocalPanel(args.port)
    try:
        asyncio.run(panel.run(args.open))
    except KeyboardInterrupt:
        pass
