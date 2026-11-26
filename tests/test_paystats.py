"""To'lov bosqichi statistikasi (TZ 3-band): baza migratsiyasi, hodisalar, to'lov qadamlari, «qaysi qadamda to'xtadi»,
xulosa (odamlar bo'yicha), sinov akkauntlari, CSV va «Nega to'lamadingiz» so'rovi.

Ishga tushirish: python -m tests.test_paystats
"""

import asyncio
import hashlib
import hmac
import io
import json
import logging
import os
import sqlite3
import tempfile
import time
from datetime import datetime, timedelta, timezone
from types import SimpleNamespace
from urllib.parse import parse_qs, urlencode, urlparse

DB = f"{tempfile.mkdtemp()}/paystats.db"
os.environ["DATABASE_URL"] = f"sqlite+aiosqlite:///{DB}"
os.environ["BOT_TOKEN"] = "123456:TEST"
os.environ["ADMIN_IDS"] = "999"
os.environ["BASE_URL"] = "https://example.uz"
os.environ["CLICK_SERVICE_ID"] = "777"
os.environ["CLICK_MERCHANT_ID"] = "555"
os.environ["CLICK_MERCHANT_USER_ID"] = "1"
os.environ["CLICK_SECRET_KEY"] = "test-secret"

from aiogram.exceptions import TelegramForbiddenError  # noqa: E402
from aiogram.methods import SendMessage  # noqa: E402
from fastapi import HTTPException  # noqa: E402
from sqlalchemy import func, select  # noqa: E402

from app import admin, click, llm, payflow, paysurvey, store, track, videoapi, videobot  # noqa: E402
from app.billing import credit, spend  # noqa: E402
from app.bot import money  # noqa: E402
from app.db import Event, Payment, Session, Site, Song, User, init_db, utcnow  # noqa: E402

TZ = timezone(timedelta(hours=5))
AI = {}


def old_schema() -> None:
    """TZ dan oldingi baza: events.kind 12 belgi, ref/num/meta va payments.purpose yo'q."""
    con = sqlite3.connect(DB)
    con.executescript("""
        CREATE TABLE events (id INTEGER PRIMARY KEY, user_id BIGINT, kind VARCHAR(12) NOT NULL, src VARCHAR(32) NOT NULL DEFAULT '',
                             created_at DATETIME);
        CREATE INDEX ix_events_kind ON events (kind);
        CREATE TABLE payments (id INTEGER PRIMARY KEY, user_id BIGINT NOT NULL, amount INTEGER NOT NULL, status VARCHAR(12) NOT NULL,
            job_id INTEGER, admin_id BIGINT, receipt VARCHAR(255) DEFAULT '' NOT NULL, site_id INTEGER, song_id INTEGER,
            pack INTEGER DEFAULT 0 NOT NULL, provider VARCHAR(12) DEFAULT '' NOT NULL, ext_id VARCHAR(40) DEFAULT '' NOT NULL,
            receipt_hash VARCHAR(64) DEFAULT '' NOT NULL, created_at DATETIME, decided_at DATETIME);
        INSERT INTO events (user_id, kind, src, created_at) VALUES (10, 'start', 'src_insta1', '2026-09-01 10:00:00');
        INSERT INTO payments (id, user_id, amount, status, song_id, provider, created_at, decided_at)
            VALUES (1, 10, 69000, 'approved', 5, 'click', '2026-09-01 10:00:00', '2026-09-01 10:03:00');
        INSERT INTO payments (id, user_id, amount, status, pack, created_at) VALUES (2, 11, 149000, 'new', 3, '2026-09-01 11:00:00');
        INSERT INTO payments (id, user_id, amount, status, site_id, receipt, created_at) VALUES (3, 12, 59000, 'pending', 2, 'F', '2026-09-01 12:00:00');
        INSERT INTO payments (id, user_id, amount, status, job_id, admin_id, created_at, decided_at)
            VALUES (4, 13, 9900, 'rejected', 9, 999, '2026-09-01 13:00:00', '2026-09-01 13:30:00');
        INSERT INTO payments (id, user_id, amount, status, created_at) VALUES (5, 14, 29700, 'new', '2026-09-01 14:00:00');
        INSERT INTO payments (id, user_id, amount, status, provider, admin_id, created_at, decided_at)
            VALUES (6, 999, 9900, 'approved', 'card', 0, '2026-09-01 15:00:00', '2026-09-01 15:01:00');
    """)
    con.commit()
    con.close()


def sign(user: dict, token="123456:TEST") -> str:
    data = {"user": json.dumps(user), "auth_date": str(int(time.time()))}
    check = "\n".join(f"{k}={v}" for k, v in sorted(data.items()))
    secret = hmac.new(b"WebAppData", token.encode(), hashlib.sha256).digest()
    data["hash"] = hmac.new(secret, check.encode(), hashlib.sha256).hexdigest()
    return urlencode(data)


async def fake_generate(tier, system, prompt, max_tokens, effort="medium", schema=None, provider=None, model=None, image=None):
    return json.dumps(AI["r"]), SimpleNamespace(input_tokens=1500, output_tokens=80, model="test")


llm.generate = fake_generate


def ai(amount, is_receipt=True, tid="T1"):
    at = (utcnow().replace(tzinfo=timezone.utc) - timedelta(minutes=2)).astimezone(TZ)
    AI["r"] = {"is_receipt": is_receipt, "success": True, "amount": amount, "datetime": at.strftime("%Y-%m-%d %H:%M"),
               "recipient_last4": "4798", "recipient_name": "BAKHROMOV DIYORBEK", "transaction_id": tid, "app": "Click", "edited_signs": False}


class Bot:
    def __init__(self):
        self.sent, self.photos, self.blocked = [], [], set()

    async def send_message(self, chat_id, text, **kw):
        if chat_id in self.blocked:
            raise TelegramForbiddenError(method=SendMessage(chat_id=chat_id, text="x"), message="Forbidden: bot was blocked by the user")
        self.sent.append((chat_id, text, kw.get("reply_markup")))
        return Msg(self, chat_id, None)

    async def send_photo(self, chat_id, photo, caption="", **kw):
        self.photos.append((chat_id, caption))

    async def send_document(self, chat_id, doc, caption="", **kw):
        self.photos.append((chat_id, caption))

    async def get_file(self, file_id):
        return SimpleNamespace(file_path=f"photos/{file_id}.jpg")

    async def download_file(self, path):
        return io.BytesIO(("IMG:" + path).encode())


class Msg:
    def __init__(self, bot, uid, file_id):
        self.bot, self.from_user = bot, SimpleNamespace(id=uid)
        self.photo = [SimpleNamespace(file_id=file_id, file_size=1000)] if file_id else None
        self.document, self.text = None, None

    async def answer(self, text, **kw):
        return await self.bot.send_message(self.from_user.id, text, **kw)

    async def delete(self):
        pass


class Req:
    """Click so'rovi yoki brauzer so'rovi o'rnida."""
    def __init__(self, f=None, ua="Mozilla/5.0 (Linux; Android 14)"):
        self.f, self.headers = f or {}, {"user-agent": ua}

    async def form(self):
        return self.f


def click_form(pid, amount, trans, action=0, prepare_id=None, error=0):
    f = {"click_trans_id": trans, "service_id": "777", "click_paydoc_id": "1", "merchant_trans_id": str(pid),
         "amount": amount, "action": str(action), "error": str(error), "error_note": "x", "sign_time": "2026-11-11 10:00:00"}
    if prepare_id is not None:
        f["merchant_prepare_id"] = str(prepare_id)
    raw = f["click_trans_id"] + f["service_id"] + "test-secret" + f["merchant_trans_id"] + \
        (f["merchant_prepare_id"] if prepare_id is not None else "") + f["amount"] + f["action"] + f["sign_time"]
    f["sign_string"] = hashlib.md5(raw.encode()).hexdigest()
    return f


async def events(kind=None, uid=None, ref=None):
    async with Session() as s:
        q = select(Event).order_by(Event.id)
        if kind:
            q = q.where(Event.kind == kind)
        if uid:
            q = q.where(Event.user_id == uid)
        if ref:
            q = q.where(Event.ref == ref)
        return (await s.execute(q)).scalars().all()


async def row(pid: int) -> dict:
    """Admin jadvalidagi qator."""
    out = await admin.payments(status="all", limit=500, uid=999)
    return next(p for p in out["payments"] if p["id"] == pid)


async def pay(uid, amount, at=None, **kw) -> Payment:
    async with Session() as s:
        p = Payment(user_id=uid, amount=amount, **kw)
        if at:
            p.created_at = at
        s.add(p)
        await s.commit()
        return p


async def main() -> None:
    # ------------------------------------------------------------ 0) eski bazani yangilash (migratsiya) va tarixni tiklash
    old_schema()
    await init_db()
    await init_db()  # qayta ishga tushirish xavfsiz
    con = sqlite3.connect(DB)
    cols = {r[1] for r in con.execute("PRAGMA table_info(events)")}
    assert {"ref", "num", "meta"} <= cols, cols
    assert "purpose" in {r[1] for r in con.execute("PRAGMA table_info(payments)")}
    idx = {r[1] for r in con.execute("PRAGMA index_list(events)")}
    assert {"ix_events_ref", "ix_events_kind_created"} <= idx, idx
    assert dict(con.execute("SELECT id, purpose FROM payments")) == {1: "song", 2: "pack", 3: "site", 4: "video", 5: "balance", 6: "balance"}
    con.close()

    bot = Bot()
    videobot.BOT = bot
    async with Session() as s:
        s.add_all([User(tg_id=uid, first_name=f"U{uid}", ref="src_insta1" if uid in (10, 20) else "") for uid in
                   (10, 11, 12, 13, 14, 20, 21, 22, 23, 999)])
        s.add(Song(id=5, owner_id=20, title="Onam", status="preview_ready", lyrics="x"))
        await s.commit()

    assert await payflow.since() is None
    await payflow.start()
    since = await payflow.since()
    assert since and abs((utcnow() - since).total_seconds()) < 5
    opened = await events("pay_open")
    assert len(opened) == 6 and all(e.meta.get("bf") for e in opened)
    assert opened[0].created_at == datetime(2026, 9, 1, 10, 0) and opened[0].num == 69000 and opened[0].src == "src_insta1"
    assert opened[0].meta == {"p": "song", "bf": 1, "m": "click"} and opened[0].ref == "pay:1"
    ok = await events("pay_success")
    assert [(e.ref, e.created_at, e.meta["by"]) for e in ok] == [("pay:1", datetime(2026, 9, 1, 10, 3), "click"),
                                                                 ("pay:6", datetime(2026, 9, 1, 15, 1), "auto")]
    await payflow.start()
    assert await payflow.backfill() == 0 and len(await events("pay_open")) == 6  # takror yozilmaydi
    assert await payflow.since() == since

    # eski to'lovlarda usul va qadam mavjud ustunlardan tiklanadi
    hist = {p["id"]: (p["purpose"], p["method"], p["step"]) for p in (await admin.payments(status="all", limit=500, uid=999))["payments"]}
    assert hist == {1: ("song", "click", "paid"), 2: ("pack", "none", "open"), 3: ("site", "card", "receipt"),
                    4: ("video", "card", "reject"), 5: ("balance", "none", "open"), 6: ("balance", "card", "paid")}, hist
    r1 = await row(1)
    assert r1["purpose_label"] == "Qo'shiq" and r1["took_s"] == 180 and [x["k"] for x in r1["timeline"]] == ["pay_open", "pay_success"]
    assert (await row(6))["test"] and not r1["test"]  # admin akkaunti belgilanadi

    # ------------------------------------------------------------ 1) hodisa yozish: uzun nom, manba, xato chiqmaydi
    assert await track.event("sample_requested", 10, ref="song:5", num=3, meta={"x": 1})
    ev = (await events("sample_requested"))[0]
    assert (ev.user_id, ev.src, ev.ref, ev.num, ev.meta) == (10, "src_insta1", "song:5", 3, {"x": 1})
    assert await track.event("k" * 40, None) and (await events("k" * 24))[0].src == ""
    logging.disable(logging.CRITICAL)  # kutilgan xato jurnalga yozilmasin
    assert await track.event("bad", 10, meta={"x": object()}) is False  # yozib bo'lmadi — xato chaqiruvchiga chiqmaydi
    logging.disable(logging.NOTSET)
    assert not await events("bad")
    assert track.clean_meta({"p": "song", "n": 5, "big": "x" * 99, "obj": {}, "ok": True}) == {"p": "song", "n": 5, "big": "x" * 40, "ok": True}

    # ------------------------------------------------------------ 2) ilovadan to'lov: Click yo'li, qadamma-qadam
    init = sign({"id": 20, "first_name": "Zuhra"})
    assert (await videoapi.track_event(videoapi.TrackIn(kind="pay_sheet", num=69000, meta={"p": "song"}), x_init_data=init))["ok"]
    assert not (await videoapi.track_event(videoapi.TrackIn(kind="hack"), x_init_data=init))["ok"] and not await events("hack")
    assert (await events("pay_sheet"))[0].src == "src_insta1"

    r = await videoapi.topup(videoapi.TopupIn(amount=69000, song=5), x_init_data=init)
    pid = r["payment"]
    assert r["click_url"].startswith(f"https://example.uz/pay/c/{pid}/69000/") and r["card"]
    async with Session() as s:
        assert (await s.get(Payment, pid)).purpose == "song"
    e = (await events("pay_open", ref=f"pay:{pid}"))[0]
    assert (e.user_id, e.num, e.src, e.meta) == (20, 69000, "src_insta1", {"p": "song", "via": "app"})
    # botga ketgan to'lov ko'rsatmasidagi Click tugmasi ham kuzatuv havolasi orqali
    kb = json.dumps(bot.sent[-1][2].model_dump())
    assert r["click_url"] in kb and f"tcard:{pid}" in kb
    assert (await row(pid))["step"] == "open"

    key = r["click_url"].rsplit("/", 1)[1]
    resp = await click.to_click(pid, 69000, "0" * 12, Req())  # noto'g'ri imzo — botga, hodisa yo'q
    assert resp.headers["location"] == "https://t.me/tayyorla_aibot" and not await events("pay_click")
    await click.to_click(pid, 69000, key, Req(ua="TelegramBot (like TwitterBot)"))  # robot sanalmaydi
    assert not await events("pay_click")
    resp = await click.to_click(pid, 69000, key, Req())
    loc = urlparse(resp.headers["location"])
    q = parse_qs(loc.query)
    assert loc.netloc == "my.click.uz" and q["transaction_param"] == [str(pid)] and q["amount"] == ["69000.00"]
    assert q["return_url"] == [f"https://example.uz/pay/r/{pid}/69000/{key}"]
    assert len(await events("pay_click", ref=f"pay:{pid}")) == 1
    x = await row(pid)
    assert (x["method"], x["step"], x["step_label"]) == ("click", "click", "Click sahifasiga o'tdi, to'lamadi")

    resp = await click.from_click(pid, 69000, key, Req())
    assert resp.headers["location"] == "https://t.me/tayyorla_aibot" and (await row(pid))["step"] == "return"
    assert json.loads((await click.prepare(Req(click_form(pid, "69000.00", "9001")))).body)["error"] == 0
    assert (await row(pid))["step"] == "prepare" and len(await events("pay_prepare")) == 1
    assert json.loads((await click.complete(Req(click_form(pid, "69000.00", "9001", action=1, prepare_id=pid)))).body)["error"] == 0
    x = await row(pid)
    assert x["step"] == "paid" and x["took_s"] is not None
    assert [t["k"] for t in x["timeline"]] == ["pay_open", "pay_click", "pay_return", "pay_prepare", "pay_success"]
    e = (await events("pay_success", ref=f"pay:{pid}"))[0]
    assert e.meta == {"p": "song", "m": "click", "by": "click"} and e.num == 69000
    async with Session() as s:
        assert (await s.get(Song, 5)).paid  # to'lovdan keyingi ishlar buzilmagan

    # Click xato qaytarsa — «bekor qildi»
    p = await pay(23, 9900, purpose="balance")
    await payflow.opened(p)
    await click.prepare(Req(click_form(p.id, "9900.00", "9100")))
    await click.complete(Req(click_form(p.id, "9900.00", "9100", action=1, prepare_id=p.id, error=-5017)))
    assert (await row(p.id))["step"] == "cancel" and (await events("pay_cancel"))[0].meta == {"err": -5017}

    # kuzatuv o'chirilsa — to'g'ridan-to'g'ri Click havolasi
    await payflow.save({"click_track": False})
    assert (await click.link(1, 9900)).startswith("https://my.click.uz/services/pay?")
    await payflow.save({"click_track": True})
    assert (await click.link(1, 9900)).startswith("https://example.uz/pay/c/1/9900/")
    assert "https://x.uz/c" in json.dumps(videobot.pay_keyboard(5, 9900, "uz", card=True, click_url="https://x.uz/c").model_dump())

    # ------------------------------------------------------------ 3) karta yo'li: karta ko'rsatildi -> chek -> rad / tasdiq / bekor
    r = await videoapi.topup(videoapi.TopupIn(amount=29700, what="video"), x_init_data=sign({"id": 21, "first_name": "Vali"}))
    cid = r["payment"]
    assert (await row(cid))["purpose"] == "video"  # mahsulot yo'q, ilova maqsadni aytdi (mehmonlarga video paketi)
    p = await money.card_payment(cid, 21)
    assert (await row(cid))["step"] == "card" and len(await events("pay_card", ref=f"pay:{cid}")) == 1
    await money.card_payment(cid, 21)
    assert len(await events("pay_card", ref=f"pay:{cid}")) == 1  # qayta ko'rsatish qayta sanalmaydi
    ai(0, is_receipt=False)
    assert await money.process_receipt(Msg(bot, 21, "N1"), p) == "not_receipt"
    x = await row(cid)
    assert (x["step"], x["step_label"]) == ("badrcpt", "Chek yubordi, qabul qilinmadi")
    ai(1000, tid="R1")  # summa mos emas — qo'lda tekshiruvga
    assert await money.process_receipt(Msg(bot, 21, "N2"), p) == "review"
    assert (await row(cid))["step"] == "receipt" and (await events("pay_receipt"))[0].meta == {"auto": 0}
    assert await money.decide_payment(bot, cid, False, 999) == "ok"
    assert (await row(cid))["step"] == "reject" and len(await events("pay_reject")) == 1

    p = await pay(22, 9900, purpose="balance")
    await payflow.opened(p)
    p = await money.card_payment(p.id, 22)
    ai(9900, tid="A1")
    assert await money.process_receipt(Msg(bot, 22, "A1"), p) == "auto"
    e = (await events("pay_success", ref=f"pay:{p.id}"))[0]
    assert e.meta == {"p": "balance", "m": "card", "by": "auto"} and (await row(p.id))["step"] == "paid"
    assert await money.revert_payment(p.id, 999) == "ok"  # soxta chek: pul tushmagan — pay_success o'chadi
    assert not await events("pay_success", ref=f"pay:{p.id}") and (await row(p.id))["step"] == "reject"

    # botdagi «saytni Click orqali to'lash» tugmasi
    async with Session() as s:
        site = Site(slug="st1", owner_id=23, category="toy", config={"engine": "catalog", "template": "x", "tarif": "premium", "data": {}},
                    status="draft", kind="site")
        s.add(site)
        await s.commit()

    async def cb_answer(*a, **kw):
        pass
    await money.site_click(SimpleNamespace(data=f"sclick:{site.id}", from_user=SimpleNamespace(id=23), answer=cb_answer))
    e = (await events("pay_open", uid=23))[-1]
    assert e.meta["p"] == "site" and e.meta["via"] == "bot"

    # ------------------------------------------------------------ 4) xulosa: aniq sonlar (10-oktabr, Toshkent vaqti), odamlar bo'yicha
    day = "2026-10-10"
    T0 = datetime(2026, 10, 10, 7, 0)  # 12:00 Toshkent
    async with Session() as s:
        s.add_all([User(tg_id=uid, first_name=f"U{uid}") for uid in range(31, 38)])
        await s.commit()
    assert (await admin.paystats_save(admin.PayStatsIn(test_ids="37, 48"), uid=999))["settings"]["test_ids"] == [37, 48]
    assert await track.excluded_ids() == {999, 37, 48}
    try:
        await admin.paystats_save(admin.PayStatsIn(test_ids="37; drop"), uid=999)
        raise AssertionError("noto'g'ri ro'yxat qabul qilindi")
    except HTTPException as err:
        assert err.status_code == 400

    # 31: uch marta urindi, uchinchisida Click orqali to'ladi va qo'shiq oldi
    await pay(31, 69000, datetime(2026, 10, 9, 19, 30), purpose="song", song_id=7)  # 10-oktabr 00:30 Toshkent — shu kunga kiradi
    p = await pay(31, 69000, T0, purpose="song", song_id=7)
    await track.event("pay_click", 31, f"pay:{p.id}", at=T0 + timedelta(minutes=1))
    p = await pay(31, 69000, T0 + timedelta(hours=1), purpose="song", song_id=7, status="approved", provider="click",
                  decided_at=T0 + timedelta(hours=1, minutes=4))
    async with Session() as s:
        await credit(s, 31, 69000, "topup", f"pay:{p.id}")
        assert await spend(s, 31, 69000, "song", "song:7")
        for tx in s.new:
            tx.created_at = T0 + timedelta(hours=1, minutes=5)
        await s.commit()
    await pay(32, 29700, T0, purpose="balance", provider="card")                      # karta raqamini ko'rdi, chek yubormadi
    await pay(33, 29700, T0, purpose="balance", provider="card", status="pending", receipt="F")  # chek tekshiruvda
    await pay(34, 149000, T0, purpose="pack", pack=3, provider="click")              # Click'da boshladi, yakunlamadi
    await pay(34, 149000, T0 + timedelta(minutes=9), purpose="pack", pack=3, provider="click", status="cancelled")
    await pay(35, 9900, T0, purpose="video", job_id=4)                                # usul tanlamadi
    p = await pay(36, 49500, T0, purpose="balance", provider="card", status="approved", admin_id=0, decided_at=T0 + timedelta(minutes=30))
    async with Session() as s:
        await credit(s, 36, 49500, "topup", f"pay:{p.id}")  # balans to'ldirdi, hech narsa olmadi
        await s.commit()
    await pay(37, 69000, T0, purpose="song", status="approved", provider="click", decided_at=T0 + timedelta(minutes=1))  # sinov akkaunt
    await pay(999, 69000, T0, purpose="song")                                         # admin
    await pay(35, 9900, datetime(2026, 10, 10, 19, 30), purpose="video")              # 11-oktabr 00:30 Toshkent — kirmaydi
    for uid in (32, 33, 35, 37):
        await track.event("pay_ask", uid, "pay:1", 1, at=T0 + timedelta(minutes=20))
    await track.event("pay_why", 32, "pay:1", 2, {"a": "price"}, at=T0 + timedelta(minutes=21))
    await track.event("pay_why", 35, "pay:1", 5, {"a": "look"}, at=T0 + timedelta(minutes=22))
    await track.event("pay_why", 37, "pay:1", 1, {"a": "nocard"}, at=T0 + timedelta(minutes=22))
    for uid in (31, 35, 36, 37):
        await track.event("pay_sheet", uid, at=T0 - timedelta(minutes=1))
    await track.event("pay_sheet", 14, at=T0)  # oynani ko'rdi, summa tanlamadi

    d = await admin.paystats(frm=day, to=day, uid=999)
    assert d["total"] == {"people": 6, "paid": 2, "conv": 33.3, "attempts": 9, "paid_attempts": 2, "paid_sum": 118500}, d["total"]
    assert d["excluded"] == 3 and d["since"] and d["from"] == day
    cut = lambda rows: {x["key"]: (x["people"], x["paid"]) for x in rows}  # noqa: E731
    assert cut(d["by_product"]) == {"song": (1, 1), "pack": (1, 0), "video": (1, 0), "balance": (3, 1)}, d["by_product"]
    assert cut(d["by_method"]) == {"click": (2, 1), "card": (3, 1), "none": (2, 0)}, d["by_method"]
    assert cut(d["by_amount"]) == {"0": (1, 0), "1": (2, 0), "2": (1, 1), "3": (1, 1), "5": (1, 0)}, d["by_amount"]
    assert [(x["label"], x["people"], x["paid"], x["attempts"]) for x in d["by_day"]] == [(day, 6, 2, 9)]
    stop = lambda m: {x["key"]: x["n"] for x in d["stops"][m]["steps"] if x["n"]}  # noqa: E731
    assert d["stops"]["click"]["people"] == 2 and stop("click") == {"cancel": 1, "paid": 1}
    assert d["stops"]["card"]["people"] == 3 and stop("card") == {"card": 1, "receipt": 1, "paid": 1}
    assert d["stops"]["none"] == 1  # 35: hech bir usulni bosmadi (31 keyin Click'ni tanlagan)
    rp = d["repeat"]
    assert [x["n"] for x in rp["dist"]] == [4, 1, 1, 0] and (rp["avg"], rp["max"], rp["multi"], rp["multi_unpaid"]) == (1.5, 3, 2, 1)
    assert (rp["paid_first_try"], rp["paid_avg_try"]) == (1, 2.0)
    tm = d["time"]
    assert (tm["n"], tm["avg_s"], tm["median_s"]) == (2, 1020, 1020) and tm["click"]["median_s"] == 240 and tm["card"]["median_s"] == 1800
    idle = d["idle"]
    assert (idle["people"], idle["payers"], idle["balance"]) == (1, 2, 49500) and idle["rows"][0]["id"] == 36
    sv = d["survey"]
    assert (sv["sent"], sv["answered"], sv["answer_rate"]) == (3, 2, 66.7)
    assert {x["key"]: (x["n"], x["pct"]) for x in sv["answers"] if x["n"]} == {"price": (1, 50.0), "look": (1, 50.0)}
    assert d["sheet"] == {"people": 4, "chose": 3}  # 31, 35, 36 summani tanladi; 14 tanlamadi; 37 sinov akkaunt
    nxt = await admin.paystats(frm="2026-10-11", to="2026-10-11", uid=999)
    assert nxt["total"]["people"] == 1 and nxt["total"]["attempts"] == 1 and nxt["survey"]["sent"] == 0
    assert (await admin.paystats(all_time=1, uid=999))["total"]["people"] > 6

    # jadval: davr bo'yicha, yangi ustunlar; «Chekni tekshirish» davrga qaramaydi
    rows = (await admin.payments(status="new", limit=500, frm=day, to=day, uid=999))["payments"]
    assert {p["user_id"] for p in rows} == {31, 32, 34, 35, 999} and all(p["purpose_label"] and p["step_label"] for p in rows)
    assert next(p for p in rows if p["user_id"] == 999)["test"]
    pend = (await admin.payments(status="pending", limit=500, frm="2026-10-11", to="2026-10-11", uid=999))["payments"]
    assert {p["id"] for p in pend} >= {3} and any(p["user_id"] == 33 for p in pend)

    # CSV: yangi ustunlar va jadvallar
    body = (await admin.export("payments", frm=day, to=day, uid=999)).body.decode()
    assert "nima uchun;usul;qaysi qadamda to'xtadi" in body and "Qo'shiq paketi;Click;Click to'lovni bekor qildi" in body
    assert body.count("\n") == 12  # sarlavha + shu kundagi 11 ta urinish (sinov akkauntlari ham, «ha» belgisi bilan)
    assert "Click sahifasiga o'tdi 12:01" in body  # qadamlar Toshkent vaqtida
    full = (await admin.export("payments", uid=999)).body.decode()
    assert full.count("\n") > body.count("\n") and full.startswith("﻿id;foydalanuvchi;summa;holat")
    body = (await admin.export("paystats", frm=day, to=day, uid=999)).body.decode()
    assert "Jami;To'lov oynasini ochgan odamlar;6;2;33,3" in body and "Mahsulot;Balans;3;1;33,3" in body
    assert "To'xtagan qadam: Click;Click to'lovni bekor qildi;1;;50,0" in body and "so'rovi;Qimmat ekan;1;;50,0" in body
    body = (await admin.export("payidle", frm=day, to=day, uid=999)).body.decode()
    assert "36;U36;;49500;2026-10-10 12:30;49500" in body and body.count("\n") == 2
    body = (await admin.export("paywhy", frm=day, to=day, uid=999)).body.decode()
    assert "32;U32;;Qimmat ekan;1;2026-10-10 12:21" in body and "37;" not in body

    # ------------------------------------------------------------ 5) «Nega to'lamadingiz» so'rovi
    base = (utcnow() + timedelta(days=2)).replace(hour=7, minute=0, second=0, microsecond=0)  # 12:00 Toshkent, hisob boshlangandan keyin
    NOW = base
    m = lambda n: timedelta(minutes=n)  # noqa: E731
    async with Session() as s:
        s.add_all([User(tg_id=uid, first_name=f"S{uid}", blocked=uid == 45, lang="ru" if uid == 42 else "uz") for uid in range(41, 53)])
        await s.commit()
    night = NOW - timedelta(hours=13)  # 23:00 Toshkent
    await pay(50, 9900, night - m(30), purpose="balance")
    n0 = len(bot.sent)
    assert await paysurvey.run_once(bot, now=night) == {"sent": 0, "failed": 0, "blocked": 0}  # tunda yuborilmaydi
    res = await paysurvey.run_once(bot, now=NOW - timedelta(hours=3) + m(5))  # ertalab 09:05 — yuboriladi
    assert res["sent"] == 1 and bot.sent[-1][0] == 50
    kb = json.dumps(bot.sent[-1][2].model_dump(), ensure_ascii=False)
    assert "to‘lov yakunlanmadi" in bot.sent[-1][1] and kb.count("callback_data") == 5
    for word in ("Kartam yo‘q yoki Click ishlamadi", "Qimmat ekan", "Keyinroq olaman", "Qanday to‘lashni tushunmadim", "Shunchaki ko‘rayotgan edim"):
        assert word in kb, word

    p41 = await pay(41, 69000, NOW - m(20), purpose="song")                 # so'raladi
    await pay(42, 69000, NOW - m(10), purpose="song")                       # hali 15 daqiqa o'tmagan
    await pay(43, 69000, NOW - m(30), purpose="song")
    p43 = await pay(43, 69000, NOW - m(5), purpose="song")                  # yana urinayapti — kutamiz
    await pay(44, 69000, NOW - m(30), purpose="song")
    await pay(44, 69000, NOW - m(28), purpose="song", status="approved", decided_at=NOW - m(25))  # shu orada to'lagan
    await pay(45, 69000, NOW - m(30), purpose="song")                       # botni bloklagan
    await pay(46, 69000, NOW - m(30), purpose="song")
    await pay(46, 69000, NOW - m(29), purpose="song", status="pending", provider="card")          # cheki tekshiruvda
    await pay(47, 69000, NOW - m(30), purpose="song")                       # yuborishda blok chiqadi
    await pay(48, 69000, NOW - m(30), purpose="song")                       # sinov akkaunt
    await pay(999, 69000, NOW - m(30), purpose="song")                      # admin
    await pay(49, 69000, NOW - timedelta(hours=30), purpose="song")         # juda eski
    bot.blocked.add(47)
    n0 = len(bot.sent)
    assert await paysurvey.run_once(bot, now=NOW) == {"sent": 1, "failed": 0, "blocked": 1}
    assert [x[0] for x in bot.sent[n0:]] == [41] and f"pw:{p41.id}:1" in json.dumps(bot.sent[-1][2].model_dump())
    async with Session() as s:
        assert (await s.get(User, 47)).blocked
        asks = dict((await s.execute(select(Event.user_id, Event.num).where(Event.kind == "pay_ask", Event.user_id.in_((41, 47))))).all())
    assert asks == {41: 1, 47: 0}
    assert await paysurvey.run_once(bot, now=NOW + m(1)) == {"sent": 0, "failed": 0, "blocked": 0}  # ikkinchi marta ketmaydi
    assert (await paysurvey.run_once(bot, now=NOW + m(6)))["sent"] == 1 and bot.sent[-1][0] == 42
    assert "окно оплаты" in bot.sent[-1][1] and "Дорого" in json.dumps(bot.sent[-1][2].model_dump(), ensure_ascii=False)
    assert (await paysurvey.run_once(bot, now=NOW + m(11)))["sent"] == 1 and bot.sent[-1][0] == 43
    assert f"pw:{p43.id}:" in json.dumps(bot.sent[-1][2].model_dump())  # eng oxirgi urinishi haqida
    await pay(41, 69000, NOW + m(60), purpose="song")
    assert (await paysurvey.run_once(bot, now=NOW + m(120)))["sent"] == 0  # bir odamga umrida bir marta
    assert {x[0] for x in bot.sent[n0:]} == {41, 42, 43}

    # javob: bir bosishda, bir marta
    assert await paysurvey.answer(41, p41.id, 2) == "ok" and await paysurvey.answer(41, p41.id, 3) == "dup"
    assert await paysurvey.answer(42, 1, 9) == "bad" and await paysurvey.answer(999, 0, 1) == "test"
    edits = []

    async def edit_text(text, **kw):
        edits.append(text)
    await money.pay_why(SimpleNamespace(data=f"pw:{p43.id}:4", from_user=SimpleNamespace(id=43), answer=cb_answer,
                                        message=SimpleNamespace(edit_text=edit_text)))
    assert "Qanday to‘lashni tushunmadim" in edits[-1] and "Rahmat" in edits[-1]
    why = await events("pay_why", uid=43)
    assert len(why) == 1 and (why[0].num, why[0].meta, why[0].ref) == (4, {"a": "how"}, f"pay:{p43.id}")
    async with Session() as s:
        st = await paysurvey.stats(s, utcnow() - timedelta(days=1), NOW + timedelta(days=1), await track.excluded_ids())
    assert (st["sent"], st["failed"], st["answered"]) == (4, 1, 2), st  # 50, 41, 42, 43 ga yetdi; 47 ga yetmadi
    assert {x["key"]: x["pct"] for x in st["answers"] if x["n"]} == {"price": 50.0, "how": 50.0}

    # o'chirib-yoqish: o'chiq paytda ketmaydi; qayta yoqilganda o'sha paytdagi urinishlar haqida so'ralmaydi
    assert (await admin.paystats_save(admin.PayStatsIn(survey_on=False), uid=999))["settings"]["survey_on"] is False
    await pay(51, 69000, NOW + m(170), purpose="song")
    assert (await paysurvey.run_once(bot, now=NOW + m(200)))["sent"] == 0
    await admin.paystats_save(admin.PayStatsIn(survey_on=True), uid=999)
    cfg = await store.get(payflow.KEY)
    assert cfg["survey_from"] and cfg["since"] == since.isoformat(timespec="seconds")
    cfg["survey_from"] = (NOW + m(180)).isoformat()  # go'yo shu paytda qayta yoqilgan
    await store.put(payflow.KEY, cfg)
    await pay(52, 69000, NOW + m(185), purpose="song")
    res = await paysurvey.run_once(bot, now=NOW + m(205))
    assert res["sent"] == 1 and bot.sent[-1][0] == 52

    n0 = len(bot.sent)
    await admin.paystats_survey_test(uid=999)  # adminning o'ziga namuna
    assert bot.sent[-1][0] == 999 and "pw:0:1" in json.dumps(bot.sent[-1][2].model_dump()) and len(bot.sent) == n0 + 1
    async with Session() as s:
        assert not await s.scalar(select(func.count()).select_from(Event).where(Event.kind == "pay_ask", Event.user_id.in_((999, 48, 45, 44, 46, 49))))

    store.forget()
    print("test_paystats: OK")


if __name__ == "__main__":
    asyncio.run(main())
