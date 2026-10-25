"""Check offline startup, bundled cogs, storage and RPC without a Discord token.

Run from the repository root: python tools/smoke_python314.py
"""
import asyncio
import importlib.util
import tempfile
from contextlib import closing
from pathlib import Path

import aiohttp
import apsw

from redbot.core import _downloader, _drivers, data_manager
from redbot.core._cli import asyncio_run, parse_cli_flags
from redbot.core.bot import Red


async def main():
    with tempfile.TemporaryDirectory(prefix="red-py314-") as tmp:
        data_manager.basic_config = {
            **data_manager.basic_config_default,
            "DATA_PATH": tmp,
            "STORAGE_TYPE": "JSON",
            "STORAGE_DETAILS": {},
        }
        data_manager._instance_name = "py314-smoke"
        driver = _drivers.get_driver_class()
        await driver.initialize()
        bot = Red(
            cli_flags=parse_cli_flags(
                ["--no-prompt", "--owner", "123456789012345678", "--prefix", "!"]
            )
        )
        try:
            async with bot:
                await _downloader._init(bot)
                await bot._pre_login()
                await bot._pre_connect()
                for name in ("general", "mod", "permissions", "downloader"):
                    await bot.load_extension(importlib.util.find_spec("redbot.cogs." + name))
                    print("Loaded:", name)
                # Import audio to catch SQLite and Lavalink API incompatibilities,
                # without downloading or starting the Java audio server.
                import redbot.cogs.audio

                await bot.rpc.initialize(0)
                try:
                    port = bot.rpc._site._server.sockets[0].getsockname()[1]
                    async with aiohttp.ClientSession() as session:
                        async with session.ws_connect(f"http://127.0.0.1:{port}/") as ws:
                            await ws.send_json(
                                {"jsonrpc": "2.0", "method": "GET_METHODS", "id": 1}
                            )
                            payload = await ws.receive_json(timeout=5)
                            assert "result" in payload, payload
                finally:
                    await bot.rpc.close()
                await bot._config.description.set("Python 3.14 smoke check")
                assert await bot._config.description() == "Python 3.14 smoke check"
                with closing(apsw.Connection(str(Path(tmp) / "smoke.sqlite"))) as db:
                    assert db.execute("SELECT 1").fetchone() == (1,)
                print("Offline startup, cog loading, JSON/SQLite storage and WebSocket RPC: OK")
        finally:
            await driver.teardown()
            # Let cancelled background config writes finish before deleting the temp tree.
            tasks = [t for t in asyncio.all_tasks() if t is not asyncio.current_task()]
            for task in tasks:
                task.cancel()
            await asyncio.gather(*tasks, return_exceptions=True)
            await asyncio.get_running_loop().shutdown_default_executor()


if __name__ == "__main__":
    asyncio_run(main())
