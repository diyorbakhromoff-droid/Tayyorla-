"""Narxlar (admin), qo'shiq paketlari va namunadan keyingi 12 soatlik chegirma."""
import asyncio
import os
import tempfile
from datetime import datetime, timedelta

os.environ["DATABASE_URL"] = f"sqlite+aiosqlite:///{tempfile.mkdtemp()}/pricing.db"
os.environ["BOT_TOKEN"] = "123456:TEST"
os.environ["ADMIN_IDS"] = "999"
os.environ["BASE_URL"] = "https://tayyorla.test"

from fastapi import HTTPException  # noqa: E402

from app import admin, legal, pricing, songs, store  # noqa: E402
from app.billing import credit  # noqa: E402
from app.config import settings  # noqa: E402
from app.db import BalanceTx, Payment, Session, Song, User, init_db, utcnow  # noqa: E402

LYR = "[Naqorat]\nOnajonim, nurim\nSen borsan dunyom"


class Bot:
    def __init__(self):
        self.msgs = []

    async def send_message(self, chat, text, **kw):
        self.msgs.append((chat, text, kw.get("reply_markup")))


async def mk_song(uid, sid, preview_at):
    async with Session() as s:
        if not await s.get(User, uid):
            s.add(User(tg_id=uid, first_name="Ali"))
        s.add(Song(id=sid, owner_id=uid, title="Onajonim", recipient="Onam", status="preview_ready", lyrics=LYR, preview_at=preview_at))
        await s.commit()


async def main():
    await init_db()
    # --- narxlar: standart, saqlash, tekshiruv
    cfg = await pricing.config()
    assert cfg["prices"]["song"] == 69000 and [p["n"] for p in cfg["packs"]] == [2, 3, 5, 10]
    assert cfg["promo"] == {"on": True, "price": 39000, "hours": 12, "delay": 1, "reminders": [360, 120, 30]}
    out = await admin.pricing_save({"packs": cfg["packs"], "promo": {**cfg["promo"], "reminders": [30, 600, 30, 1000]}}, uid=999)
    assert out["promo"]["reminders"] == [600, 30], "takrorlar va muddatdan uzunlari olib tashlanadi"
    try:
        await admin.pricing_save({"promo": {"price": 70000}}, uid=999)
        raise AssertionError("chegirma oddiy narxdan qimmat bo'lmasligi kerak")
    except HTTPException as e:
        assert e.status_code == 400
    out = await admin.pricing_save({"prices": {"vip": 109000}, "packs": cfg["packs"], "promo": {**cfg["promo"], "hours": 6}}, uid=999)
    assert settings.price_vip == 109000 and out["promo"]["hours"] == 6
    assert "109 000 so‘m" in await legal.oferta(), "oferta yangi narxni ko'rsatadi"
    pub = pricing.packs_public(out)
    assert pub[1] == {"n": 3, "price": 129000, "label": "Ommabop", "on": True, "each": 43000, "off": 38}
    await admin.pricing_save({"packs": cfg["packs"], "promo": cfg["promo"]}, uid=999)  # 12 soatga qaytaramiz

    # --- paket: balansdan sotib olish va paketdan to'lash
    await mk_song(1, 10, datetime(2026, 11, 17, 4, 0))
    async with Session() as s:
        assert await pricing.buy_pack(s, 1, 3) is False, "balans yetmaydi"
        assert await pricing.buy_pack(s, 1, 4) is None, "bunday paket yo'q"
        await credit(s, 1, 150000, "topup", "t1")
        assert await pricing.buy_pack(s, 1, 3) is True
        await s.commit()
        u = await s.get(User, 1)
        await s.refresh(u)
        assert u.balance == 21000 and u.song_credits == 3
        song = await s.get(Song, 10)
        assert await songs.pay(s, song, 1) and song.paid and song.price == 0
        await s.commit()
        await s.refresh(u)
        assert u.balance == 21000 and u.song_credits == 2, "paketdan olindi — pul yechilmadi"
    st = await pricing.stats()
    assert st["packs_sold"] == {3: 1}

    # --- chegirma: namunadan 1 soat keyin, progrev soatlarida (12:00 Toshkent = 07:00 UTC)
    now = datetime(2026, 11, 17, 7, 0)
    await mk_song(2, 20, now - timedelta(hours=2))          # vaqti keldi
    await mk_song(3, 30, now - timedelta(minutes=20))       # hali erta
    await mk_song(4, 40, now - timedelta(hours=60))         # juda eski — taklif qilinmaydi
    await mk_song(1, 11, now - timedelta(hours=2))          # paketi bor — taklif kerak emas
    bot = Bot()
    assert await pricing.offer_due(bot, now) == 1
    assert [c for c, *_ in bot.msgs] == [2] and "39 000" in bot.msgs[0][1] and "69 000" in bot.msgs[0][1]
    kb = bot.msgs[0][2].inline_keyboard
    assert "song=20" in kb[0][0].web_app.url and "packs=1" in kb[1][0].web_app.url
    assert await pricing.offer_due(bot, now + timedelta(minutes=10)) == 0, "bir qo'shiqqa bir marta"
    night = datetime(2026, 11, 17, 19, 0)  # 00:00 Toshkent
    assert await pricing.offer_due(bot, night) == 0
    async with Session() as s:
        s2 = await s.get(Song, 20)
        # 12:00 + 12 soat = yarim tun: eslatmalar yetib borishi uchun ertasi kuni 9:00 + 6 soat = 15:00 (Toshkent) ga suriladi
        assert s2.promo_until == datetime(2026, 11, 18, 10, 0) and s2.promo_price == 39000
        assert pricing.promo_of(s2, now + timedelta(hours=1))["price"] == 39000
        assert pricing.promo_of(s2, now + timedelta(hours=28)) is None, "muddat tugagach narx qaytadi"
        assert (await s.get(Song, 40)).promo_until is None and (await s.get(Song, 11)).promo_until is None

    # --- tugashidan oldin 3 ta eslatma: 6 soat, 2 soat, 30 daqiqa qolganda (faqat progrev soatlarida)
    bot = Bot()
    d18 = datetime(2026, 11, 18)
    assert await pricing.remind_due(bot, d18.replace(hour=3)) == 0, "08:00 — hali erta"
    assert await pricing.remind_due(bot, d18.replace(hour=4)) == 1 and "6 soat qoldi" in bot.msgs[-1][1]
    assert await pricing.remind_due(bot, d18.replace(hour=4, minute=5)) == 0, "bir bosqich bir marta"
    assert await pricing.remind_due(bot, d18.replace(hour=8)) == 1 and "Atigi 2 soat" in bot.msgs[-1][1]
    assert await pricing.remind_due(bot, d18.replace(hour=9, minute=30)) == 1
    assert "oxirgi imkoniyat" in bot.msgs[-1][1] and "30 daqiqa" in bot.msgs[-1][1] and "39 000" in bot.msgs[-1][1]
    assert await pricing.remind_due(bot, d18.replace(hour=9, minute=40)) == 0
    assert [c for c, *_ in bot.msgs] == [2, 2, 2] and "song=20" in bot.msgs[-1][2].inline_keyboard[0][0].web_app.url
    # o'tib ketgan bosqichlar qayta yuborilmaydi: 25 daqiqa qolgan bo'lsa — faqat oxirgisi
    await mk_song(6, 60, now - timedelta(hours=2))
    async with Session() as s:
        s6 = await s.get(Song, 60)
        s6.promo_until, s6.promo_price = d18.replace(hour=9, minute=55), 39000
        await s.commit()
    bot = Bot()
    assert await pricing.remind_due(bot, d18.replace(hour=9, minute=30)) == 1 and "oxirgi" in bot.msgs[0][1]
    assert await pricing.remind_due(bot, d18.replace(hour=9, minute=35)) == 0

    # chegirma faol: haqiqiy vaqtga moslab, narx 39 000 va shu summa yechiladi
    async with Session() as s:
        s2 = await s.get(Song, 20)
        s2.promo_until = utcnow() + timedelta(hours=3)
        await credit(s, 2, 50000, "topup", "t2")
        await s.commit()
        assert await songs.price_for(s, 2, s2) == 39000 and await songs.price_for(s, 2) == 69000
        assert await songs.pay(s, s2, 2) and s2.price == 39000
        await s.commit()
        u2 = await s.get(User, 2)
        assert u2.balance == 11000
    st = await pricing.stats()
    assert st["offered"] == 2 and st["used"] == 1 and st["revenue"] == 39000

    # --- Click orqali paket: to'lov tushgach paket o'zi faollashadi va qo'shiq paketdan olinadi
    from app.bot.money import after_topup
    await mk_song(5, 50, now - timedelta(hours=2))
    async with Session() as s:
        p = Payment(user_id=5, amount=99000, status="approved", pack=2, song_id=50)
        s.add(p)
        await s.commit()
        await credit(s, 5, 99000, "topup", "pay:x")
        await s.commit()
        user = await s.get(User, 5)
    bot = Bot()
    await after_topup(bot, p, user)
    async with Session() as s:
        u5, s5 = await s.get(User, 5), await s.get(Song, 50)
        assert u5.balance == 0 and u5.song_credits == 1 and s5.paid and s5.price == 0
        kinds = (await s.execute(__import__("sqlalchemy").select(BalanceTx.kind).where(BalanceTx.user_id == 5))).scalars().all()
        assert "song_pack" in kinds and "song_credit" in kinds
    assert any("paketi faollashdi" in t for _, t, _ in bot.msgs)
    store.forget()
    print("✅ Narxlar, paketlar va chegirma tekshiruvi o'tdi")


asyncio.run(main())
