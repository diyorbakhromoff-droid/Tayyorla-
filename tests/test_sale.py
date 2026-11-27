"""Aksiya («Barakali juma»): admin sozlamasi, bir kishiga bitta qo'shiq aksiya narxida, tugagach oddiy narx,
pul kechikib tushganda 2 soatlik imkoniyat, aksiya paytida chegirma xabarlari to'xtashi, ilova uchun meta va e'lon matni.

Ishga tushirish: python -m tests.test_sale
"""
import asyncio
import hashlib
import hmac
import json
import os
import tempfile
import time
from datetime import datetime, timedelta, timezone
from urllib.parse import urlencode

os.environ["DATABASE_URL"] = f"sqlite+aiosqlite:///{tempfile.mkdtemp()}/sale.db"
os.environ["BOT_TOKEN"] = "123456:TEST"
os.environ["ADMIN_IDS"] = "999"
os.environ["BASE_URL"] = "https://tayyorla.test"

from fastapi import HTTPException  # noqa: E402
from sqlalchemy import select  # noqa: E402

from app import admin, pricing, songapi, songflow, songs, store  # noqa: E402
from app.billing import credit  # noqa: E402
from app.db import Event, Payment, Session, Song, User, init_db, utcnow  # noqa: E402

LYR = "[Naqorat]\nOnajonim, nurim\nSen borsan dunyom\nOnajonim, quyoshim\nSen borsan bahorim"
TZ = timezone(timedelta(hours=5))


def sign(uid: int) -> str:
    pairs = {"auth_date": str(int(time.time())), "user": json.dumps({"id": uid, "first_name": "Ali"})}
    check = "\n".join(f"{k}={v}" for k, v in sorted(pairs.items()))
    secret = hmac.new(b"WebAppData", b"123456:TEST", hashlib.sha256).digest()
    pairs["hash"] = hmac.new(secret, check.encode(), hashlib.sha256).hexdigest()
    return urlencode(pairs)


def local(d: datetime) -> str:
    """Admin paneli yuboradigan ko'rinish: Toshkent vaqti, «+05:00» bilan."""
    return d.replace(tzinfo=timezone.utc).astimezone(TZ).isoformat(timespec="minutes")


class Bot:
    def __init__(self):
        self.msgs = []

    async def send_message(self, chat, text, **kw):
        self.msgs.append((chat, text, kw.get("reply_markup")))


async def mk_song(uid, sid, preview_at=None, balance=0, credits=0):
    async with Session() as s:
        if not await s.get(User, uid):
            s.add(User(tg_id=uid, first_name="Ali", song_credits=credits))
            await s.flush()
            if balance:
                await credit(s, uid, balance, "topup", f"t{uid}")
        s.add(Song(id=sid, owner_id=uid, title="Onajonim", recipient="Onam", status="preview_ready", lyrics=LYR,
                   preview_at=preview_at or utcnow() - timedelta(hours=3)))
        await s.commit()


async def pay(uid, sid) -> int | None:
    """Qo'shiqni balansdan to'laydi; yechilgan narx (yetmasa None)."""
    async with Session() as s:
        song = await s.get(Song, sid)
        ok = await songs.pay(s, song, uid)
        await s.commit()
        return song.price if ok else None


async def price(uid, sid=None) -> int:
    async with Session() as s:
        return await songs.price_for(s, uid, await s.get(Song, sid) if sid else None)


async def sale_events(uid=None):
    async with Session() as s:
        q = select(Event).where(Event.kind == pricing.EV_SALE)
        return (await s.execute(q.where(Event.user_id == uid) if uid else q)).scalars().all()


async def put_sale(**kw):
    """Aksiyani to'g'ridan-to'g'ri bazaga yozadi (vaqtni qo'lda boshqarish uchun)."""
    cfg = await pricing.config()
    cfg["sale"] = {**cfg["sale"], **{k: pricing._iso(v) if isinstance(v, datetime) else v for k, v in kw.items()}}
    await store.put(pricing.KEY, cfg)


async def main():
    await init_db()
    cfg = await pricing.config()
    assert cfg["sale"] == {"on": False, "id": "", "name": "Barakali juma", "price": 19000, "until": None, "since": None}
    assert pricing.default_until(datetime(2026, 11, 27, 6, 0)) == datetime(2026, 11, 27, 18, 59), "bugun 23:59 Toshkent"

    # --- aksiya yoqilmaguncha hech narsa o'zgarmaydi
    await mk_song(1, 10, balance=150000)
    await mk_song(1, 11)
    assert await price(1) == 69000 and await price(1, 10) == 69000
    meta = await songapi.songs_meta(x_init_data=sign(1))
    assert meta["price"] == 69000 and meta["sale"] is None

    # --- tekshiruv: narx oddiy narxdan kichik, tugash vaqti kelajakda
    soon = utcnow() + timedelta(hours=3)
    for bad in ({"price": 69000, "until": local(soon)}, {"price": 500, "until": local(soon)}, {"until": local(utcnow() - timedelta(minutes=5))},
                {"until": "ertaga"}):
        try:
            await admin.pricing_save({"sale": {"on": True, "name": "Barakali juma", "price": 19000, **bad}}, uid=999)
            raise AssertionError(f"qabul qilinmasligi kerak edi: {bad}")
        except HTTPException as e:
            assert e.status_code == 400, bad
    assert not (await pricing.config())["sale"]["on"]

    # --- yoqish: yangi id, Toshkent vaqti UTC ga o'giriladi; qayta saqlansa id o'zgarmaydi
    out = await admin.pricing_save({"sale": {"on": True, "name": "  Barakali   juma ", "price": 19000, "until": local(soon), "id": "hack"}}, uid=999)
    sale = out["sale"]
    sid1 = sale["id"]
    assert sale["on"] and sid1 and sid1 != "hack" and sale["name"] == "Barakali juma" and sale["price"] == 19000
    assert sale["until"] == soon.replace(second=0, microsecond=0).isoformat(timespec="seconds") and sale["since"]
    assert out["sale_active"] and out["sale_stats"] == {"buyers": 0, "revenue": 0}
    out = await admin.pricing_save({"prices": {"song": 69000}, "sale": {**sale, "price": 19000}}, uid=999)
    assert out["sale"]["id"] == sid1, "faol aksiyani tahrirlash — o'sha aksiya"
    out = await admin.pricing_save({"prices": {"song": 69000}}, uid=999)
    assert out["sale"]["id"] == sid1 and out["sale"]["on"], "aksiya yuborilmasa — o'zgarmaydi"
    try:
        await admin.pricing_save({"prices": {"song": 15000}, "promo": {"on": False, "price": 9000}}, uid=999)
        raise AssertionError("oddiy narx aksiya narxidan past bo'lib qolmasin")
    except HTTPException as e:
        assert e.status_code == 400

    # --- meta: aksiya narxi, nomi, oddiy narx va tugash vaqti
    meta = await songapi.songs_meta(x_init_data=sign(1))
    assert meta["price"] == 19000 and meta["sale"]["name"] == "Barakali juma" and meta["sale"]["price"] == 19000
    assert meta["sale"]["regular"] == 69000 and meta["sale"]["until"].startswith(sale["until"]) and meta["sale"]["until"].endswith("+00:00")

    # --- bir kishiga bitta: birinchi qo'shiq 19 000, ikkinchisi oddiy narxda
    assert await price(1, 10) == 19000
    assert await pay(1, 10) == 19000
    ev = await sale_events(1)
    assert len(ev) == 1 and ev[0].ref == f"sale:{sid1}" and ev[0].num == 19000 and ev[0].meta == {"song": 10}
    assert await price(1) == 69000 and await price(1, 11) == 69000
    assert await pay(1, 11) == 69000 and len(await sale_events(1)) == 1
    async with Session() as s:
        assert (await s.get(User, 1)).balance == 150000 - 19000 - 69000
    meta = await songapi.songs_meta(x_init_data=sign(1))
    assert meta["price"] == 69000 and meta["sale"] is None, "aksiyada olgan odamga banner ko'rsatilmaydi"

    # --- paket krediti avvalgidek ishlaydi (aksiya hodisasi yozilmaydi, aksiya keyingi qo'shiqqa qoladi)
    await mk_song(2, 20, balance=50000, credits=1)
    assert await pay(2, 20) == 0 and not await sale_events(2)
    assert await price(2) == 19000

    # --- qo'shiq chegirmasi aksiyadan arzon bo'lsa — chegirma, aksiya ishlatilmaydi
    await mk_song(3, 30, balance=50000)
    async with Session() as s:
        s3 = await s.get(Song, 30)
        s3.promo_until, s3.promo_price = utcnow() + timedelta(hours=2), 15000
        await s.commit()
    assert await price(3, 30) == 15000 and await pay(3, 30) == 15000
    assert not await sale_events(3) and await price(3) == 19000

    # --- balans yetmasa: 402 dagi summa aksiya narxi (ilova shu summaga to'ldirishni taklif qiladi)
    await mk_song(5, 50)
    try:
        await songapi.song_pay(50, x_init_data=sign(5))
        raise AssertionError
    except HTTPException as e:
        assert e.status_code == 402 and e.detail["need"] == 19000

    # --- ilova hodisasi: «Sotib olish» aksiya narxi ko'rsatilganda sale: true
    assert await songflow.client_event(5, "buy_click", "song:50", 19000, {"kind": "single", "disc": False, "sale": True, "at": "sample"})
    async with Session() as s:
        bc = (await s.execute(select(Event).where(Event.kind == "buy_click", Event.user_id == 5))).scalar_one()
    assert bc.meta == {"kind": "single", "disc": False, "sale": True, "at": "sample"}

    st = await pricing.sale_stats((await pricing.config())["sale"])
    assert st == {"buyers": 1, "revenue": 19000}

    # --- e'lon: faqat faol aksiya uchun; matn, tugma va segment tayyor
    ann = await admin.sale_announce(uid=999)
    assert ann["button"] == "song" and ann["button_text"] == "🎵 Qo‘shiq tayyorlash" and ann["segment"] == "all"
    assert "Barakali juma chegirmasi" in ann["text"] and "69 000 so‘m emas — atigi 19 000 so‘m" in ann["text"]
    fixed = {**await pricing.config(), "sale": {**sale, "until": "2026-11-27T18:59:00"}}
    text = pricing.sale_announcement(fixed, datetime(2026, 11, 27, 9, 0))
    print(text)
    assert "Faqat bugun 23:59 gacha" in text and text.startswith("🎉 Barakali juma chegirmasi!")
    assert all(sum(ch in "🎉⏳👇" for ch in line) <= 1 for line in text.splitlines()), "har qatorda ko'pi bilan bitta emoji"
    assert "30-noyabr 23:59" in pricing.sale_announcement({**fixed, "sale": {**sale, "until": "2026-11-30T18:59:00"}}, datetime(2026, 11, 27, 9, 0))

    # --- aksiya paytida avtomatik chegirma xabarlari to'xtaydi, tugagach davom etadi (12:00 va 14:00 Toshkent)
    during, after = datetime(2026, 11, 17, 7, 0), datetime(2026, 11, 17, 9, 0)
    await put_sale(on=True, id="fri1", until=datetime(2026, 11, 17, 8, 0), since=datetime(2026, 11, 17, 3, 0))
    await mk_song(6, 60, preview_at=datetime(2026, 11, 17, 6, 0))                     # yangi namuna — taklif vaqti keladi
    await mk_song(7, 70, preview_at=datetime(2026, 11, 16, 6, 0))                     # chegirmasi bor — eslatma
    await mk_song(8, 80, preview_at=datetime(2026, 11, 10, 6, 0))                     # eski namuna — tarqatma
    async with Session() as s:
        s7 = await s.get(Song, 70)
        s7.promo_until, s7.promo_price = after + timedelta(minutes=20), 39000
        await s.commit()
    await pricing.backfill_set(True, 50)
    bot = Bot()
    assert await pricing.offer_due(bot, during) == 0 and await pricing.remind_due(bot, during) == 0
    assert await pricing.backfill_due(bot, during) == 0 and not bot.msgs
    assert (await pricing.backfill_state())["on"], "tarqatma o'chmaydi — aksiyadan keyin davom etadi"
    async with Session() as s:
        assert (await s.get(Song, 60)).promo_until is None and (await s.get(Song, 70)).promo_sent == 0
    assert await pricing.offer_due(bot, after) == 1 and await pricing.remind_due(bot, after) == 1
    assert await pricing.backfill_due(bot, after) == 1
    assert sorted(c for c, *_ in bot.msgs) == [6, 7, 8]

    # --- aksiya tugadi: oddiy narx; aksiya davomida ochilgan to'lovning puli 2 soat ichida tushsa — aksiya narxi
    end = utcnow().replace(microsecond=0) - timedelta(minutes=30)
    await put_sale(on=True, id="fri2", until=end, since=end - timedelta(hours=8))
    await mk_song(9, 90)
    await mk_song(9, 91)
    async with Session() as s:
        p = Payment(user_id=9, amount=19000, status="approved", song_id=90, purpose="song", created_at=end - timedelta(minutes=10))
        s.add(p)
        s.add(Payment(user_id=9, amount=19000, song_id=91, purpose="song", created_at=end + timedelta(minutes=5)))  # tugagach ochilgan
        await s.commit()
        await credit(s, 9, 19000, "topup", "pay:x")
        await s.commit()
        user = await s.get(User, 9)
    assert await price(9) == 69000 and await price(9, 91) == 69000 and await price(9, 90) == 19000
    meta = await songapi.songs_meta(x_init_data=sign(9))
    assert meta["price"] == 69000 and meta["sale"] is None
    from app.bot.money import after_topup
    await after_topup(Bot(), p, user)
    async with Session() as s:
        s9, u9 = await s.get(Song, 90), await s.get(User, 9)
        assert s9.paid and s9.price == 19000 and u9.balance == 0
    assert [e.ref for e in await sale_events(9)] == ["sale:fri2"]
    # 2 soatdan keyin — aksiya davomida ochilgan to'lov ham oddiy narxda
    await put_sale(until=utcnow() - timedelta(hours=3), since=utcnow() - timedelta(hours=10))
    await mk_song(4, 40)
    async with Session() as s:
        s.add(Payment(user_id=4, amount=19000, song_id=40, purpose="song", created_at=utcnow() - timedelta(hours=4)))
        await s.commit()
    assert await price(4, 40) == 69000
    await put_sale(until=utcnow() - timedelta(hours=1))
    assert await price(4, 40) == 19000, "2 soat ichida — aksiya narxi"

    # --- tugagan aksiyani qayta yoqish — yangi aksiya (yangi id): har kim yana bitta qo'shiq oladi
    out = await admin.pricing_save({"sale": {"on": True, "name": "Barakali juma", "price": 19000, "until": local(utcnow() + timedelta(hours=2))}}, uid=999)
    assert out["sale"]["id"] not in (sid1, "fri2") and out["sale_active"]
    assert await price(1) == 19000 and await price(9, 91) == 19000
    out = await admin.pricing_save({"sale": {**out["sale"], "on": False}}, uid=999)
    assert not out["sale_active"] and await price(1) == 69000
    try:
        await admin.sale_announce(uid=999)
        raise AssertionError("o'chiq aksiyaga e'lon tayyorlanmaydi")
    except HTTPException as e:
        assert e.status_code == 400
    store.forget()
    print("✅ Aksiya tekshiruvi o'tdi")


asyncio.run(main())
