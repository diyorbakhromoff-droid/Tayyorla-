"""Eski namunalarga bir martalik chegirma tarqatmasi (admin paneldan yoqiladi)."""
import asyncio
import os
import tempfile
from datetime import datetime, timedelta

os.environ["DATABASE_URL"] = f"sqlite+aiosqlite:///{tempfile.mkdtemp()}/bf.db"
os.environ["BOT_TOKEN"] = "123456:TEST"
os.environ["ADMIN_IDS"] = "999"
os.environ["BASE_URL"] = "https://tayyorla.test"

from aiogram.exceptions import TelegramForbiddenError  # noqa: E402
from aiogram.methods import SendMessage  # noqa: E402

from app import admin, pricing  # noqa: E402
from app.db import Session, Song, User, init_db  # noqa: E402

NOW = datetime(2026, 11, 18, 7, 0)  # 12:00 Toshkent
OLD = NOW - timedelta(days=20)


class Bot:
    def __init__(self, deny=()):
        self.msgs, self.deny = [], set(deny)

    async def send_message(self, chat, text, **kw):
        if chat in self.deny:
            raise TelegramForbiddenError(method=SendMessage(chat_id=chat, text=""), message="blocked")
        self.msgs.append((chat, text, kw.get("reply_markup")))


async def main():
    await init_db()
    async with Session() as s:
        for uid in range(1, 8):
            s.add(User(tg_id=uid, first_name=f"U{uid}", blocked=uid == 6, song_credits=2 if uid == 7 else 0))
        # 1: ikkita eski namuna — faqat oxirgisi; 2: preview_at yo'q (eski yozuv); 3: allaqachon sotib olgan
        s.add_all([
            Song(id=10, owner_id=1, title="Birinchi", recipient="Onam", status="preview_ready", lyrics="x", preview_at=OLD),
            Song(id=11, owner_id=1, title="Ikkinchi", recipient="Dadam", status="preview_ready", lyrics="x", preview_at=OLD + timedelta(days=1)),
            Song(id=20, owner_id=2, title="Eski", status="preview_ready", lyrics="x"),
            Song(id=30, owner_id=3, title="Sotilgan", status="ready", paid=True, lyrics="x", preview_at=OLD),
            Song(id=40, owner_id=4, title="Yangi", status="preview_ready", lyrics="x", preview_at=NOW - timedelta(hours=3)),  # yangi — oddiy oqim
            Song(id=50, owner_id=5, title="Besh", status="preview_ready", lyrics="x", preview_at=OLD),
            Song(id=60, owner_id=6, title="Bloklagan", status="preview_ready", lyrics="x", preview_at=OLD),
            Song(id=70, owner_id=7, title="Paketli", status="preview_ready", lyrics="x", preview_at=OLD),
            Song(id=80, owner_id=8, title="Faqat she'r", status="lyrics", lyrics="x", preview_at=OLD),
        ])
        s.add(User(tg_id=8, first_name="U8"))
        await s.commit()

    assert await pricing.backfill_eligible(NOW) == 3  # 1, 2, 5
    br = await pricing.backfill_breakdown(NOW)
    assert (br["people_unpaid"], br["people_ready"], br["people_fresh"], br["people_lyrics"], br["people_blocked"], br["eligible"]) == (7, 6, 1, 1, 1, 3), br
    page = await admin.pricing_get(uid=999)
    assert page["backfill"]["on"] is False
    bot = Bot(deny={5})
    assert await pricing.backfill_due(bot, NOW) == 0, "yoqilmaguncha yuborilmaydi"

    st = await admin.pricing_backfill(admin.BackfillIn(on=True, batch=10), uid=999)
    assert st["on"] and st["batch"] == 10
    try:
        await admin.pricing_backfill(admin.BackfillIn(on=True, batch=5000), uid=999)
        raise AssertionError("juda katta partiya")
    except admin.HTTPException as e:
        assert e.status_code == 400
    assert await pricing.backfill_due(bot, NOW.replace(hour=19)) == 0, "kechasi yubormaydi"
    assert await pricing.backfill_due(bot, NOW) == 2   # 5 — botni bloklagan
    sent = {c: t for c, t, _ in bot.msgs}
    assert set(sent) == {1, 2} and "«Ikkinchi»" in sent[1] and "Dadam uchun" in sent[1] and "39 000" in sent[1]
    assert "song=11" in bot.msgs[0][2].inline_keyboard[0][0].web_app.url or "song=11" in bot.msgs[1][2].inline_keyboard[0][0].web_app.url
    async with Session() as s:
        assert (await s.get(Song, 11)).promo_price == 39000 and (await s.get(Song, 10)).promo_until is None
        assert (await s.get(User, 5)).blocked, "bloklagan deb belgilanadi"
        assert (await s.get(Song, 40)).promo_until is None, "yangi namuna bu yerda emas"
    assert await pricing.backfill_eligible(NOW) == 0
    # takror: hech kimga ikkinchi marta bormaydi, hammasi tugagach o'zi to'xtaydi
    assert await pricing.backfill_due(bot, NOW + timedelta(minutes=3)) == 0
    st = await pricing.backfill_state()
    assert st["on"] is False and st["finished"] and st["sent"] == 2
    # eslatmalar ham ishlaydi (oddiy chegirma kabi)
    async with Session() as s:
        until = (await s.get(Song, 11)).promo_until
    assert await pricing.remind_due(bot, until - timedelta(minutes=359)) >= 1
    print("✅ Eski namunalarga chegirma tarqatmasi tekshiruvi o'tdi")


asyncio.run(main())
