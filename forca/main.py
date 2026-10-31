"""Um processo só: servidor web, bot do Telegram e avisos no mesmo loop."""

from __future__ import annotations

import asyncio
import logging
import os

import uvicorn

from . import bot, config, db, nudges
from .web import app

log = logging.getLogger("forca")


async def _main() -> None:
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")
    # httpx registra a URL completa, que contém o token do bot: não pode ir para o log.
    logging.getLogger("httpx").setLevel(logging.WARNING)
    db.init()

    server = uvicorn.Server(
        uvicorn.Config(
            app,
            host=os.environ.get("FORCA_HOST", "127.0.0.1"),
            port=int(os.environ.get("FORCA_PORT", "8000")),
            log_level="warning",
        )
    )
    tasks = [server.serve()]

    if config.TELEGRAM_TOKEN:
        telegram = bot.Telegram(config.TELEGRAM_TOKEN)
        try:
            me = await telegram.api("getMe")
            with db.tx() as c:
                db.set_setting(c, "bot_username", me["username"])
            log.info("Bot conectado: @%s", me["username"])
        except Exception:
            log.exception("Não consegui validar o token do Telegram; seguindo mesmo assim")
        the_bot = bot.Bot(telegram)

        async def send(chat: int, text: str, markup: dict | None) -> None:
            await telegram.send(chat, text, markup)

        tasks += [the_bot.run(), nudges.run(send, telegram.send_document)]
    else:
        log.warning("Sem TELEGRAM_BOT_TOKEN: bot e avisos desligados")

        async def no_send(chat: int, text: str, markup: dict | None) -> None:
            return None

        tasks.append(nudges.run(no_send))

    pending = {asyncio.ensure_future(t) for t in tasks}
    done, pending = await asyncio.wait(pending, return_when=asyncio.FIRST_COMPLETED)
    for task in pending:
        task.cancel()
    for task in done:
        task.result()


def main() -> None:
    asyncio.run(_main())


if __name__ == "__main__":
    main()
