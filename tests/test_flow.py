"""Botni haqiqiy Telegram'siz sinash: soxta sessiya orqali butun ssenariy o'tkaziladi.

Ishga tushirish: python -m tests.test_flow
"""

import asyncio
import os
import tempfile
from datetime import datetime

os.environ["DATABASE_URL"] = f"sqlite+aiosqlite:///{tempfile.mkdtemp()}/test.db"
os.environ["BOT_TOKEN"] = "123456:TEST"
os.environ["ADMIN_IDS"] = "999"

from aiogram import Bot, Dispatcher  # noqa: E402
from aiogram.client.default import DefaultBotProperties  # noqa: E402
from aiogram.client.session.base import BaseSession  # noqa: E402
from aiogram.types import CallbackQuery, Chat, Message, PhotoSize, Update, User  # noqa: E402
from sqlalchemy import select  # noqa: E402

from app import ai, web  # noqa: E402
from app.bot import handlers  # noqa: E402
from app.db import Rsvp, Session, Site, init_db  # noqa: E402

USER = User(id=111, is_bot=False, first_name="Diyor")
ADMIN = User(id=999, is_bot=False, first_name="Admin")


class FakeSession(BaseSession):
    def __init__(self):
        super().__init__()
        self.sent: list[tuple[int, str, object]] = []

    async def make_request(self, bot, method, timeout=None):
        name = type(method).__name__
        text = getattr(method, "text", None) or getattr(method, "caption", None)
        chat = getattr(method, "chat_id", None)
        if text:
            self.sent.append((chat, text, getattr(method, "reply_markup", None)))
        if name in ("SendMessage", "EditMessageText", "CopyMessage"):
            if name == "CopyMessage":
                from aiogram.types import MessageId
                return MessageId(message_id=1)
            return Message(message_id=len(self.sent), date=datetime.now(), chat=Chat(id=chat or 111, type="private"), text=text or "").as_(bot)
        return True

    async def stream_content(self, *a, **k):
        yield b""

    async def close(self):
        pass


session = FakeSession()
bot = Bot("123456:TEST", session=session, default=DefaultBotProperties(parse_mode="HTML"))
dp = Dispatcher()
dp.include_router(handlers.router)
n = 0


async def save_media_stub(bot, file_id, ext):
    return f"/media/{file_id}.{ext}"


async def write_stub(category, answers, brief, previous=None):
    return "Aziz onajonim!\n\nSiz bizning quyoshimizsiz." if not previous else "Ikkinchi variant matni."


async def edit_stub(config, request):
    new = dict(config, colors=dict(config["colors"], bg="#eef6ff"), texts={"hero_eyebrow": "Eng aziz onajonim"})
    return new, "Fon havorangga o'zgartirildi."


handlers.save_media = save_media_stub
ai.write_message = write_stub
ai.apply_edit = edit_stub
notified = []


async def notify(chat_id, text):
    notified.append((chat_id, text))

web.notify = notify


def msg(user=USER, **kw) -> Message:
    return Message(message_id=1, date=datetime.now(), chat=Chat(id=user.id, type="private"), from_user=user, **kw)


async def send(text=None, user=USER, **kw):
    global n
    n += 1
    await dp.feed_update(bot, Update(update_id=n, message=msg(user, text=text, **kw)))


async def click(data, user=USER):
    global n
    n += 1
    cq = CallbackQuery(id=str(n), from_user=user, chat_instance="x", data=data, message=msg(user, text="..."))
    await dp.feed_update(bot, Update(update_id=n, callback_query=cq))


def last() -> str:
    return session.sent[-1][1]


async def main():
    await init_db()

    await send("/start")
    assert "Tayyorla" in last()

    # --- tug'ilgan kun ssenariysi
    await click("cat:birthday")
    await send("Onam")
    await send("abc")
    assert "raqam" in last()
    await send("55")
    await send("32.13.2026")
    assert "kun.oy.yil" in last()
    await send("24.10.2026")
    await send("Farzandlaring")
    await send("O'zim yozaman")  # tanlov qilinmagan
    assert "Avval tanlang" in last()
    await click("msg:ai")
    await send("Juda mehribon, samimiy uslubda")
    assert "Variant" in last()
    await click("ai:again")
    assert "Ikkinchi" in last()
    await click("ai:ok")
    photo = [PhotoSize(file_id="p1", file_unique_id="u1", width=10, height=10)]
    await send(photo=photo)
    await send(photo=[PhotoSize(file_id="p2", file_unique_id="u2", width=10, height=10)])
    assert "2 ta rasm" in last()
    await click("done")
    await click("skip")  # musiqa
    await click("pal:osmon")
    await click("feat:countdown")
    await click("feat:balloons")
    await click("done")
    assert "Saytingiz tayyor" in last(), last()

    async with Session() as s:
        site = (await s.execute(select(Site))).scalars().first()
    cfg = site.config
    assert cfg["fields"]["name"] == "Onam" and cfg["fields"]["age"] == "55"
    assert cfg["message"].startswith("Ikkinchi")
    assert cfg["photos"] == ["/media/p1.jpg", "/media/p2.jpg"]
    assert cfg["palette"] == "osmon"
    assert cfg["features"]["countdown"] is True and cfg["features"]["balloons"] is False
    assert site.status == "draft"

    # --- namuna sahifasi
    html = await web.show(site.slug, type("R", (), {"cookies": {}, "query_params": {}})())
    assert "NAMUNA" in html and "Onam" in html

    # --- tahrir
    await click(f"edit:{site.id}")
    await send("Fonni havorang qil")
    assert "havorang" in last()
    await click("edit_done")
    async with Session() as s:
        site = await s.get(Site, site.id)
    assert site.edits_used == 1 and site.config["colors"]["bg"] == "#eef6ff"

    # --- to'lov
    await click(f"buy:{site.id}")
    await click(f"paid:{site.id}")
    await send(photo=[PhotoSize(file_id="chek", file_unique_id="c", width=10, height=10)])
    assert any(chat == 999 and "Yangi to'lov" in text for chat, text, _ in session.sent)
    await click(f"approve:{site.id}", user=USER)  # oddiy foydalanuvchi tasdiqlay olmaydi
    async with Session() as s:
        assert (await s.get(Site, site.id)).status == "pending"
    await click(f"approve:{site.id}", user=ADMIN)
    async with Session() as s:
        site = await s.get(Site, site.id)
    assert site.status == "paid"
    assert any(chat == 111 and "tasdiqlandi" in text for chat, text, _ in session.sent)

    html = await web.show(site.slug, type("R", (), {"cookies": {}, "query_params": {}})())
    assert "NAMUNA" not in html and "Eng aziz onajonim" in html
    assert notified and "birinchi marta" in notified[-1][1]

    # --- to'y: joylashuv va RSVP
    await click("cat:wedding")
    for a in ["Jasur", "Nilufar", "12.06.2027", "18.00"]:
        await send(a)
    await send("Oqsaroy")
    from aiogram.types import Location
    await send(location=Location(latitude=41.3, longitude=69.28))
    await send("Yunusobod, Amir Temur 108")
    await click("skip")  # taklif qiluvchilar
    await click("msg:own")
    await send("Sizni to'yimizga taklif qilamiz")
    await click("done")
    await click("skip")
    await click("pal:oltin")
    await click("done")
    async with Session() as s:
        wsite = (await s.execute(select(Site).where(Site.category == "wedding"))).scalars().first()
        wsite.status = "paid"
        await s.commit()
    assert wsite.config["fields"]["lat"] == "41.3" and wsite.config["fields"]["time"] == "18:00"
    await web.rsvp(wsite.slug, web.RsvpIn(name="Aziz aka", attending="yes", guests=3))
    async with Session() as s:
        assert len((await s.execute(select(Rsvp))).scalars().all()) == 1
    await click(f"guests:{wsite.id}")
    assert "jami 3 kishi" in last()

    # --- farzand: tugma orqali tanlash
    await click("cat:baby")
    await send("O'zim yozaman")  # tugma kutilmoqda
    assert "tugmalardan" in last()
    await click("choice:girl")
    await click("skip")  # ism
    for a in ["Jasur va Nilufar", "19.10.2026"]:
        await send(a)
    await send("3.2 kg, 50 sm")
    await send("Buvisi")
    await click("msg:own")
    await send("Farzand muborak!")
    await click("done")
    await click("skip")
    await click("pal:atirgul")
    await click("done")
    async with Session() as s:
        bsite = (await s.execute(select(Site).where(Site.category == "baby"))).scalars().first()
    assert bsite.config["fields"]["gender"] == "girl" and bsite.config["fields"]["baby_name"] is None
    html = await web.show(bsite.slug, type("R", (), {"cookies": {}, "query_params": {}})())
    assert "Kichkina malika" in html and "Qiz farzand muborak" in html

    # --- uzrnoma: va'dalar ro'yxati
    await click("cat:apology")
    for a in ["Malika", "Sardor"]:
        await send(a)
    await click("msg:own")
    await send("Kechir meni")
    await send("Kech qolmayman\nJahl qilmayman")
    await click("done")
    await click("skip")
    await click("pal:lavanda")
    await click("done")
    async with Session() as s:
        asite = (await s.execute(select(Site).where(Site.category == "apology"))).scalars().first()
    html = await web.show(asite.slug, type("R", (), {"cookies": {}, "query_params": {}})())
    assert html.count("<li>") == 2 and "Meni kechirasanmi?" in html

    # --- katalog (VIP) sayti: narx tarifga qarab, anketa javobi egasiga keladi
    from app.catalog import clean_order
    cat_cfg = clean_order({"template": "toy-maktub", "tarif": "vip", "rang": 12, "data": {
        "kuyov": "Jasur", "kelin": "Malika", "sana": "2027-06-12", "vaqt": "18:00", "manzil_nomi": "Oqsaroy",
        "manzil": "Toshkent", "matn": "Taklif qilamiz"}}, strict=True)
    async with Session() as s:
        csite = Site(slug="vip-toy", owner_id=111, category=cat_cfg["category"], config=cat_cfg)
        s.add(csite)
        await s.commit()
    await click(f"site:{csite.id}")
    assert "«Muhrlangan maktub»" in last() and "VIP" in last()
    await click(f"buy:{csite.id}")
    assert "79 000" in last()
    await click(f"paid:{csite.id}")
    await send(photo=[PhotoSize(file_id="chek2", file_unique_id="c2", width=10, height=10)])
    await click(f"approve:{csite.id}", user=ADMIN)
    page = await web.show("vip-toy", type("R", (), {"cookies": {}, "query_params": {}})())
    assert "NAMUNA • TAYYORLA" not in page and '"rang": 12' in page

    class Req:
        def __init__(self, data): self.data = data
        async def json(self): return self.data
    await web.anketa("vip-toy", Req({"ism": "Aziz <b>aka</b>", "keladi": "ha", "Necha kishi bo'lasiz?": "3"}))
    assert "Aziz &lt;b&gt;aka&lt;/b&gt;" in notified[-1][1]
    async with Session() as s:
        r = (await s.execute(select(Rsvp).where(Rsvp.site_id == csite.id))).scalars().one()
    assert r.attending and r.guests == 3
    await click(f"guests:{csite.id}")
    assert "jami 3 kishi" in last()

    # rasm qo'shish katalog saytida ham ishlaydi
    await click(f"edit:{csite.id}")
    await send(photo=[PhotoSize(file_id="p9", file_unique_id="u9", width=10, height=10)])
    assert "Rasm qo'shildi" in last()

    print(f"✅ Barcha tekshiruvlar o'tdi ({len(session.sent)} ta xabar)")


asyncio.run(main())
