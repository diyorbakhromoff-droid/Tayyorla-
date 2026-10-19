"""Bot va veb-serverni birga ishga tushiradi: python -m app.main"""

import asyncio
import logging

import uvicorn
from aiogram import Bot, Dispatcher
from aiogram.client.default import DefaultBotProperties
from aiogram.enums import ParseMode
from aiogram.types import BotCommand, MenuButtonWebApp, WebAppInfo

from . import web, webapp
from .bot import keyboards as kb
from .bot.handlers import created_text, router
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

    async def on_created(site) -> None:
        try:
            await bot.send_message(site.owner_id, created_text(site), reply_markup=kb.site_actions(site))
        except Exception:
            logging.exception("Sayt haqida xabar yuborib bo'lmadi")

    web.notify = notify
    webapp.on_created = on_created
    if settings.base_url.startswith("https://"):
        # Mini App faqat HTTPS da ishlaydi
        await bot.set_chat_menu_button(menu_button=MenuButtonWebApp(text="✨ Yaratish", web_app=WebAppInfo(url=f"{settings.base_url}/app")))
    await bot.set_my_commands([
        BotCommand(command="start", description="Bosh menyu"),
        BotCommand(command="mysites", description="Mening saytlarim"),
        BotCommand(command="help", description="Yordam"),
    ])

    server = uvicorn.Server(uvicorn.Config(web.app, host=settings.host, port=settings.port, log_level="info"))
    await asyncio.gather(server.serve(), dp.start_polling(bot))


if __name__ == "__main__":
    asyncio.run(main())
