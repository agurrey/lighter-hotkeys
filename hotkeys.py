#!/usr/bin/env python3
"""Terminal de hotkeys para Lighter. Q compra, W vende, E cierra toda la posición."""
import asyncio
import sys

from trader import Terminal


async def run():
    terminal = Terminal()
    try:
        await terminal.start()
        await terminal.status()
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
            async def read_lines():
                for line in sys.stdin:
                    for ch in line.strip().lower():
                        await queue.put(ch)
                await queue.put(None)
            asyncio.create_task(read_lines())

        try:
            while True:
                ch = await queue.get()
                if ch is None:
                    break
                try:
                    if ch == "q":
                        await terminal.open(is_ask=False)
                    elif ch == "w":
                        await terminal.open(is_ask=True)
                    elif ch == "e":
                        await terminal.close()
                except Exception as e:
                    terminal.log(f"ERROR: {e}")
        finally:
            if sys.stdin.isatty():
                termios.tcsetattr(fd, termios.TCSADRAIN, old)
    finally:
        await terminal.shutdown()


if __name__ == "__main__":
    try:
        asyncio.run(run())
    except KeyboardInterrupt:
        print("\nSaliendo. Las posiciones quedan como estén.")
