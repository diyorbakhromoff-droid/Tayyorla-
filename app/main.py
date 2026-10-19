"""Bot va veb-serverni birga ishga tushiradi: python -m app.main"""

import asyncio
import logging

import uvicorn
from aiogram import Bot, Dispatcher
from aiogram.client.default import DefaultBotProperties
from aiogram.enums import ParseMode
from aiogram.types import BotCommand

from . import web
from .bot.handlers import router
from .config import settings
from .db import init_db


async def main() -> None:
    logging.basicConfig(level=logging.INFO)
    await init_db()

    bot = Bot(settings.bot_token, default=DefaultBotProperties(parse_mode=ParseMode.HTML))
    dp = Dispatcher()
    dp.include_router(router)

    async def notify(chat_id: int, text: str) -> None:
        try:
            await bot.send_message(chat_id, text)
        except Exception:
            logging.exception("Xabar yuborib bo'lmadi")

    web.notify = notify
    await bot.set_my_commands([
        BotCommand(command="start", description="Bosh menyu"),
        BotCommand(command="mysites", description="Mening saytlarim"),
        BotCommand(command="help", description="Yordam"),
    ])

    server = uvicorn.Server(uvicorn.Config(web.app, host=settings.host, port=settings.port, log_level="info"))
    await asyncio.gather(server.serve(), dp.start_polling(bot))


if __name__ == "__main__":
    asyncio.run(main())
