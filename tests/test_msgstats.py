"""Progrev va chegirma xabarlari natijasi (statistika TZ, 5-band): o'tkazib yuborish sabablari, 3-xabar tuzatishi (bloklaganlar
navbatni egallamaydi), tugma bosilishi (imzolangan belgi), blok vaqti (my_chat_member va yuborishdagi «Forbidden»),
chegirma xabarlari jurnali, har bir xabar ko'rsatkichlari (tugma, ilovaga qaytdi 24 s, sotib oldi 48 s, blokladi 24 s), CSV.

Ishga tushirish: python -m tests.test_msgstats
"""

import asyncio
import os
import re
import tempfile
from datetime import datetime, timedelta, timezone
from types import SimpleNamespace

os.environ["DATABASE_URL"] = os.environ.get("TEST_DATABASE_URL") or f"sqlite+aiosqlite:///{tempfile.mkdtemp()}/msgstats.db"
os.environ["BOT_TOKEN"] = "123456:TEST"
os.environ["ADMIN_IDS"] = "999"
os.environ["BASE_URL"] = "https://example.uz"

from aiogram.exceptions import TelegramForbiddenError  # noqa: E402
from aiogram.methods import SendMessage  # noqa: E402
from sqlalchemy import select  # noqa: E402

from app import admin, msgstats, nudges, pricing, store, track, webapp  # noqa: E402
from app.db import BalanceTx, Event, NudgeLog, Payment, Session, Song, User, init_db  # noqa: E402

# 2026-10-10 12:00 Toshkent = 07:00 UTC (hammasi bugungi kundan oldin — «Butun davr» bugun bilan tugaydi)
NOON = datetime(2026, 10, 10, 7, 0)
H = timedelta(hours=1)


class Bot:
    def __init__(self):
        self.sent, self.blocked = [], set()

    async def send_message(self, chat_id, text, **kw):
        if chat_id in self.blocked:
            raise TelegramForbiddenError(method=SendMessage(chat_id=chat_id, text="x"), message="Forbidden: bot was blocked by the user")
        self.sent.append((chat_id, text, kw.get("reply_markup")))


async def rows(uid=None, seq=None):
    async with Session() as s:
        q = select(NudgeLog).order_by(NudgeLog.id)
        if uid:
            q = q.where(NudgeLog.user_id == uid)
        if seq:
            q = q.where(NudgeLog.seq == seq)
        return [(x.seq, x.step, x.status, x.reason) for x in (await s.execute(q)).scalars().all()]


async def events(uid, kind):
    async with Session() as s:
        return list((await s.execute(select(Event).where(Event.user_id == uid, Event.kind == kind).order_by(Event.id))).scalars().all())


def song(uid, at, **kw):
    return Song(owner_id=uid, status="preview_ready", title="Opajonim", recipient="Ozoda", lyrics="x", preview="/media/p.mp3",
                created_at=at, preview_at=at, **kw)


async def main() -> None:
    await init_db()
    await msgstats.start()
    cfg = await nudges.config()
    gap = timedelta(hours=cfg["gap_hours"])

    # ---------- 1) o'tkazib yuborish sababi: tanaffus, tungi vaqt, «kech»
    t = NOON
    assert nudges.late_reason([t - 5 * H], t, t + 36 * H, gap, cfg) == "late"            # kunduz bo'sh vaqt bor edi
    assert nudges.late_reason([t - 5 * H], t, t + 36 * H, gap, cfg, "gap") == "gap"      # oxirgi marta tanaffus sabab kutilgan
    assert nudges.late_reason([t - H, t + 18 * H], t, t + 36 * H, gap, cfg) == "gap"     # 36 soat davomida tanaffus tugamadi
    # tanaffus 21:00 da tugaydi (Toshkent), keyingi xabar 09:00 da: bo'sh qolgan payt faqat tunda
    evening = datetime(2026, 10, 10, 15, 50)  # 20:50 Toshkent
    assert nudges.late_reason([evening - 20 * H + timedelta(minutes=20)], evening, evening + 12 * H, gap, cfg) == "night"

    # ---------- 2) sozlama tashxisi: tanaffus 36 soatdan tashqari — 3-xabar hech qachon yuborilmaydi
    bad = {**cfg, "gap_hours": 90}
    diag = nudges.diagnose(bad)
    assert any(w["level"] == "bad" and w["seq"] == "song" and w["step"] == 2 for w in diag), diag
    assert not [w for w in nudges.diagnose(cfg) if w["level"] == "bad"]
    assert any(w["level"] == "info" and w["seq"] == "song" for w in nudges.diagnose(cfg)), "«new» va «song» bir-birini kutadi"

    # ---------- 3) 3-xabar tuzatishi: bloklaganlar 300 talik navbatni egallamaydi, eng eski qadam birinchi
    nudges.MAX_PER_PASS = 3
    t0 = NOON + timedelta(days=5)
    async with Session() as s:
        s.add(User(tg_id=100, first_name="Faol", created_at=t0 - timedelta(days=30)))
        s.add(song(100, t0 - 73 * H))  # 3-xabar vaqti (72 soat) keldi
        s.add(NudgeLog(user_id=100, seq="song", step=0, ref="", status="sent", created_at=t0 - 71 * H))  # boshqa obyekt, eski
        for i in range(6):  # 6 ta bloklagan odam, yangi qo'shiqlar (1-xabar vaqti keldi)
            s.add(User(tg_id=110 + i, first_name="Blok", blocked=True, created_at=t0 - timedelta(days=30)))
            s.add(song(110 + i, t0 - 3 * H))
        await s.commit()
    async with Session() as s:
        sid100 = (await s.execute(select(Song.id).where(Song.owner_id == 100))).scalar_one()
    bot = Bot()
    res = await nudges.run_once(bot, t0)
    assert res["sent"] == 1 and bot.sent[0][0] == 100, (res, bot.sent)  # avval bloklaganlar navbatni to'ldirib, bu odam qolib ketardi
    assert (await rows(100, "song"))[-3:] == [("song", 0, "skipped", "late"), ("song", 1, "skipped", "late"), ("song", 2, "sent", "")]
    url = bot.sent[0][2].inline_keyboard[0][0].web_app.url
    assert url.startswith(f"https://example.uz/app?song={sid100}&mt=song.2_100_"), url
    assert await rows(110) == [], "bloklagan odamning qadami muddat tugaguncha kutadi (blokdan chiqsa — boradi)"
    await nudges.run_once(bot, t0 + 46 * H)  # 1-xabar muddati (2 + 36 soat) tugadi; 10:00 Toshkent
    assert ("song", 0, "skipped", "blocked") in await rows(110), await rows(110)
    nudges.MAX_PER_PASS = 300

    # ---------- 4) sotib olgan: keyingi qadamlar «allaqachon sotib olgan» sababi bilan
    t1 = NOON + timedelta(days=12)
    async with Session() as s:
        s.add(User(tg_id=200, first_name="Xaridor", created_at=t1 - timedelta(days=30)))
        s.add(song(200, t1 - 3 * H, paid=True))
        await s.commit()
    await nudges.run_once(bot, t1)
    assert await rows(200) == [("song", 0, "skipped", "bought")], await rows(200)

    # ---------- 5) tugma bosildi: imzolangan belgi; noto'g'ri belgi yozilmaydi; sahifa o'zgarmaydi
    token = url.split("mt=")[1]
    assert track.parse_click(token) == ("song.2", 100)
    assert track.parse_click(token[:-1] + ("0" if token[-1] != "0" else "1")) is None
    assert track.parse_click("song.2_101_" + token.rsplit("_", 1)[1]) is None, "boshqa odam nomidan bo'lmaydi"
    page = await webapp.app_page(mt=token)
    plain = await webapp.app_page()
    assert page.body == plain.body
    await webapp.app_page(mt="junk")
    clicks = await events(100, track.CLICK)
    assert len(clicks) == 1 and clicks[0].ref == "n:song.2"

    # ---------- 6) blok vaqti: Telegram xabari (my_chat_member) va yuborishda «Forbidden»
    from app.bot import handlers

    def upd(uid, old, new):
        return SimpleNamespace(chat=SimpleNamespace(type="private"), from_user=SimpleNamespace(id=uid),
                               old_chat_member=SimpleNamespace(status=old), new_chat_member=SimpleNamespace(status=new))

    await handlers.bot_member(upd(100, "member", "kicked"))
    await handlers.bot_member(upd(100, "member", "kicked"))  # takror — bitta hodisa
    assert len(await events(100, track.BLOCK)) == 1
    async with Session() as s:
        assert (await s.get(User, 100)).blocked
    await handlers.bot_member(upd(100, "kicked", "member"))
    async with Session() as s:
        assert not (await s.get(User, 100)).blocked
    assert len(await events(100, track.UNBLOCK)) == 1
    async with Session() as s:  # blok hodisasini xabardan 2 soat keyinga suramiz (24 soat ichida blokladi)
        ev = (await s.execute(select(Event).where(Event.user_id == 100, Event.kind == track.BLOCK))).scalar_one()
        ev.created_at = t0 + 2 * H
        s.add(Event(user_id=100, kind="app", created_at=t0 + 3 * H))                 # 24 soat ichida ilovaga qaytdi
        s.add(Event(user_id=100, kind="pay_success", num=69000, created_at=t0 + 30 * H))  # 48 soat ichida to'ladi
        clk = (await s.execute(select(Event).where(Event.user_id == 100, Event.kind == track.CLICK))).scalar_one()
        clk.created_at = t0 + H
        await s.commit()

    # ---------- 7) chegirma xabarlari jurnalga: taklif, bloklagan odam (bir marta), eslatmalar
    t2 = NOON + timedelta(days=20)
    async with Session() as s:
        s.add(User(tg_id=300, first_name="Ali", created_at=t2 - timedelta(days=30)))
        s.add(song(300, t2 - 2 * H))
        s.add(User(tg_id=301, first_name="Blok", blocked=True, created_at=t2 - timedelta(days=30)))
        s.add(song(301, t2 - 2 * H))
        s.add(User(tg_id=302, first_name="Paket", song_credits=2, created_at=t2 - timedelta(days=30)))
        s.add(song(302, t2 - 2 * H))
        await s.commit()
    pbot = Bot()
    assert await pricing.offer_due(pbot, t2) == 1 and pbot.sent[0][0] == 300
    kb = pbot.sent[0][2].inline_keyboard
    assert "mt=offer.0_300_" in kb[0][0].web_app.url and "packs=1" in kb[1][0].web_app.url and "mt=offer.0_300_" in kb[1][0].web_app.url
    async with Session() as s:
        sid300 = (await s.execute(select(Song.id).where(Song.owner_id == 300))).scalar_one()
    assert re.sub(r"&mt=[^&]*$", "", kb[0][0].web_app.url) == f"https://example.uz/app?song={sid300}", "mijoz ochadigan sahifa o'sha"
    assert await rows(300, "offer") == [("offer", 0, "sent", "")]
    assert await rows(301, "offer") == [("offer", 0, "skipped", "blocked")] and await rows(302, "offer") == [("offer", 0, "skipped", "pack")]
    await pricing.offer_due(pbot, t2 + timedelta(minutes=5))
    assert len(await rows(301, "offer")) == 1, "o'tkazib yuborish bir marta yoziladi"
    async with Session() as s:
        promo_until = (await s.execute(select(Song.promo_until).where(Song.owner_id == 300))).scalar_one()
    # 6 soat qolganda — 1-eslatma o'tib ketgan holda 2-eslatma (2 soat qolganda) yuboriladi: 1-si «o'tkazib yuborildi»
    loc = (promo_until - 2 * H + timedelta(minutes=1))
    assert await pricing.remind_due(pbot, loc) == 1
    assert await rows(300, "rem") == [("rem", 1, "skipped", "late"), ("rem", 2, "sent", "")], await rows(300, "rem")
    assert "mt=rem.2_300_" in pbot.sent[-1][2].inline_keyboard[0][0].web_app.url

    # ---------- 8) panel: har bir xabar ko'rsatkichlari (odamlar bo'yicha), sinov akkauntlari chiqariladi
    d = await admin.msgstats_get(frm=None, to=None, all_time=1, src="", uid=999)
    by = {x["key"]: x for x in d["rows"]}
    s3 = by["song.2"]
    assert (s3["sent"], s3["clicked"], s3["returned"], s3["bought"], s3["blocked"]) == (1, 1, 1, 1, 1), s3
    assert s3["pct"]["clicked"] == 100.0
    s1 = by["song.0"]
    assert {x["key"]: x["n"] for x in s1["skips"]} == {"late": 1, "blocked": 6, "bought": 1}, s1["skips"]
    assert by["offer.0"]["sent"] == 1 and {x["key"] for x in by["offer.0"]["skips"]} == {"blocked", "pack"}, by["offer.0"]
    assert by["rem.2"]["sent"] == 1 and by["rem.1"]["skips"][0]["key"] == "late"
    assert d["since"] and any(r["key"] == "gap" for r in d["skip_reasons"])
    # eski yozuv (sababsiz) — hozir bloklab turganlar alohida
    async with Session() as s:
        s.add(NudgeLog(user_id=110, seq="song", step=2, ref="song:1", status="skipped", reason="", created_at=t0))
        s.add(NudgeLog(user_id=200, seq="song", step=2, ref="song:2", status="skipped", reason="", created_at=t0))
        await s.commit()
    d = await admin.msgstats_get(frm=None, to=None, all_time=1, src="", uid=999)
    s3 = {x["key"]: x for x in d["rows"]}["song.2"]
    assert {x["key"]: x["n"] for x in s3["skips"]} == {"old_blocked": 1, "old": 1}, s3["skips"]
    # sinov akkaunti: 100 chiqarilsa — 3-xabar yuborilmagandek
    await track.set_test_ids([100])
    d = await admin.msgstats_get(frm=None, to=None, all_time=1, src="", uid=999)
    assert {x["key"]: x for x in d["rows"]}["song.2"]["sent"] == 0
    await track.set_test_ids([])
    # davr: 3-xabar yuborilgan kun
    day = (t0 + 5 * H).replace(tzinfo=timezone.utc).astimezone(nudges.TZ).date().isoformat()
    d = await admin.msgstats_get(frm=day, to=day, all_time=0, src="", uid=999)
    assert {x["key"]: x for x in d["rows"]}["song.2"]["sent"] == 1 and {x["key"]: x for x in d["rows"]}["offer.0"]["sent"] == 0
    # balansdan xarid ham «sotib oldi» (48 soat ichida)
    async with Session() as s:
        s.add(BalanceTx(user_id=300, amount=-39000, kind="song", ref="song:x", created_at=t2 + 3 * H))
        await s.commit()
    d = await admin.msgstats_get(frm=None, to=None, all_time=1, src="", uid=999)
    assert {x["key"]: x for x in d["rows"]}["offer.0"]["bought"] == 1

    # ---------- 9a) bloklar hisoboti: kunlar, manba, oxirgi xabar, Start → blok
    await track.mark_blocked([300], "promo")
    async with Session() as s:
        s.add(User(tg_id=400, first_name="Tez", ref="src_qoshiq_v1", created_at=t2))
        await s.commit()
    await track.mark_blocked(400, "update")
    async with Session() as s:
        for e in (await s.execute(select(Event).where(Event.kind == track.BLOCK, Event.user_id.in_([300, 400])))).scalars().all():
            e.created_at = t2 + (H if e.user_id == 300 else timedelta(minutes=30))
        await s.commit()
    bl = await admin.blocks_get(frm=None, to=None, all_time=1, src="", uid=999)
    assert bl["blocked_now"] == 9 and bl["unknown"] == 7, bl  # 110–115 va 301 — blok vaqti yozilmagan (eski)
    lm = {x["key"]: x["n"] for x in bl["last_msg"]}
    assert lm == {"": 8, "rem.2": 1}, lm  # butun davr: hozirgi bloklar, oxirgi yetgan xabar
    assert bl["last_scope"] == "now" and bl["start_to_block"]["h1"] == 1 and bl["start_to_block"]["later"] == 2  # 100 (keyin blokdan chiqdi), 300; 400 — 30 daqiqada
    assert any(x["key"] == "src_qoshiq_v1" and x["blocked"] == 1 and x["pct"] == 100.0 for x in bl["by_source"])
    day2 = t2.replace(tzinfo=timezone.utc).astimezone(nudges.TZ).date().isoformat()
    bl = await admin.blocks_get(frm=day2, to=day2, all_time=0, src="", uid=999)
    assert bl["by_day"] == [{"day": day2, "n": 2}] and bl["in_period"] == 2
    assert {x["key"]: x["n"] for x in bl["last_msg"]} == {"offer.0": 1, "": 1}, bl["last_msg"]  # blok paytigacha oxirgisi — taklif
    assert [x for x in bl["by_source"] if x["key"] == "src_qoshiq_v1"][0]["users"] == 1
    r = await admin.export("blocks", frm=day2, to=day2, all_time=0, uid=999)
    assert "Blokdan oldingi oxirgi xabar;Chegirma taklifi (namunadan keyin);1" in r.body.decode("utf-8-sig")

    # ---------- 9b) foydalanuvchilar: filtrlar va «Qo'shiq» ustuni; mijoz kartasida hodisalar tarixi
    async with Session() as s:
        s.add(Event(user_id=300, kind="sample_played", num=20, created_at=t2 + H))
        s.add(Event(user_id=400, kind="pay_open", num=69000, ref="pay:1", created_at=t2 + H))
        s.add(Event(user_id=100, kind="pay_open", num=69000, ref="pay:2", created_at=t0 + 29 * H))
        s.add(User(tg_id=401, first_name="Balans", balance=5000, created_at=t2))
        (await s.get(User, 300)).balance = 1000
        await s.commit()
    ids = lambda d: {u["id"] for u in d["users"]}  # noqa: E731
    assert ids(await admin.users_list(q="", sort="new", page=0, flt="played", uid=999)) == {300}
    assert ids(await admin.users_list(q="", sort="new", page=0, flt="payopen", uid=999)) == {400}, "100 to'lagan"
    assert ids(await admin.users_list(q="", sort="new", page=0, flt="idle", uid=999)) == {401}, "300 balansidan xarid qilgan"
    d = await admin.users_list(q="300", sort="new", page=0, flt="", uid=999)
    assert d["users"][0]["songs"] == 1 and d["users"][0]["songs_paid"] == 0 and len(d["filters"]) == 4
    r = await admin.export("users", frm=None, to=None, all_time=0, flt="idle", uid=999)
    lines = r.body.decode("utf-8-sig").strip().splitlines()
    assert len(lines) == 2 and lines[1].startswith("401;") and "qo'shiqlar" in lines[0]
    card = await admin.user_card(100, uid=999)
    hist = card["history"]
    assert hist == sorted(hist, key=lambda x: x["at"], reverse=True), "yangisi tepada"
    labels_ = [(h["label"], h["detail"]) for h in hist]
    assert ("Xabardagi tugmani bosdi", "Qo'shiq boshlab, sotib olmaganlar — 3-xabar") in labels_, labels_
    assert ("Botni blokladi", "Telegram xabar berdi") in labels_ and ("Pul tushdi", "69 000 so'm") in labels_
    assert any(lb.startswith("Progrev: Qo'shiq boshlab, sotib olmaganlar — 3-xabar — yetdi") for lb, _ in labels_)
    assert any(lb.endswith("1-xabar — o'tkazib yuborildi") and det.startswith("36 soatdan") for lb, det in labels_), labels_
    card = await admin.user_card(300, uid=999)
    assert any(h["label"].startswith("Chegirma: Chegirma taklifi") for h in card["history"])

    # ---------- 9) CSV
    r = await admin.export("msgstats", frm=None, to=None, all_time=1, uid=999)
    text = r.body.decode("utf-8-sig")
    assert "xabar;kalit;yuborildi (yetdi)" in text and "song.2" in text
    r = await admin.export("msgskips", frm=None, to=None, all_time=1, uid=999)
    text = r.body.decode("utf-8-sig")
    assert "Botni bloklagan" in text and "o'tkazib yuborildi" in text
    ng = await admin.nudges_get(uid=999)
    assert "diagnose" in ng

    # ---------- 10) nazorat guruhi: standart o'chiq; yoqilgach yangi odamlarning bir qismi progrev va chegirma olmaydi
    from app import control
    from app.db import utcnow
    c = await admin.control_get(uid=999)
    assert not c["on"] and c["groups"] == [] and control.member_sql(await control.config(), User.tg_id, User.created_at) is None
    assert all(control.bucket(u) == control.bucket(u) for u in (1, 2)) and 0 <= control.bucket(123456789) < 100
    split = [sum(control.bucket(u) < 10 for u in range(10**6, 10**6 + 5000)), sum(control.arm(u) == "b" for u in range(10**6, 10**6 + 5000))]
    assert 400 < split[0] < 600 and 2300 < split[1] < 2700, split  # ~10% va ~50%
    try:
        await admin.control_save(admin.ControlIn(on=True, pct=60), uid=999)
        raise AssertionError("60% qabul qilinmasligi kerak")
    except Exception as e:
        assert "50" in str(e) or getattr(e, "status_code", 0) in (400, 422)
    c = await admin.control_save(admin.ControlIn(on=True, pct=50), uid=999)
    assert c["on"] and c["since"] and c["pct"] == 50
    ccfg = await control.config()
    now = utcnow()
    ctl_uid = next(u for u in range(500, 900) if control.bucket(u) < 50)
    main_uid = next(u for u in range(500, 900) if control.bucket(u) >= 50)
    old_uid = next(u for u in range(900, 1300) if control.bucket(u) < 50)
    async with Session() as s:
        s.add(User(tg_id=ctl_uid, first_name="Nazorat", created_at=now + timedelta(seconds=1)))
        s.add(User(tg_id=main_uid, first_name="Asosiy", created_at=now + timedelta(seconds=1)))
        s.add(User(tg_id=old_uid, first_name="Eski", created_at=ccfg["since_dt"] - timedelta(days=1)))  # yoqilishidan oldin kelgan
        for u in (ctl_uid, main_uid, old_uid):
            s.add(song(u, now - 2 * H))
        await s.commit()
    assert control.is_member(ccfg, ctl_uid, now + timedelta(seconds=1)) and not control.is_member(ccfg, main_uid, now)
    assert not control.is_member(ccfg, old_uid, ccfg["since_dt"] - timedelta(days=1)), "eski foydalanuvchilarga ta'sir qilmaydi"
    nbot = Bot()
    await nudges.run_once(nbot, now + 2 * H, force=True)
    got = {u for u, *_ in nbot.sent}
    assert main_uid in got and old_uid in got and ctl_uid not in got, got
    assert await rows(ctl_uid) == [], "nazorat guruhi jurnalga ham yozilmaydi"
    await nudges.save({**(await nudges.config()), "from_hour": 0, "to_hour": 24})
    pbot = Bot()
    await pricing.offer_due(pbot, now + 2 * H)
    got = {u for u, *_ in pbot.sent}
    assert main_uid in got and ctl_uid not in got, got
    async with Session() as s:
        assert (await s.execute(select(Song.promo_until).where(Song.owner_id == ctl_uid))).scalar_one() is None, "chegirmaning o'zi ham yo'q"
        s.add(Payment(user_id=main_uid, amount=69000, status="approved", purpose="song"))
        await s.commit()
    await track.mark_blocked(ctl_uid, "update")
    c = await admin.control_get(uid=999)
    g = {x["key"]: x for x in c["groups"]}
    assert (g["main"]["users"], g["main"]["bought"], g["main"]["got"], g["main"]["revenue"]) == (1, 1, 1, 69000), g
    assert (g["control"]["users"], g["control"]["blocked"], g["control"]["blocked_pct"], g["control"]["got"]) == (1, 1, 100.0, 0), g
    r = await admin.export("control", frm=None, to=None, all_time=0, uid=999)
    assert "Nazorat guruhi (hech narsa olmaydi);1;0;0" in r.body.decode("utf-8-sig")
    c = await admin.control_save(admin.ControlIn(on=False), uid=999)
    assert not c["on"] and c["until"] and len(c["groups"]) == 2, "o'chirilgach taqqoslash o'sha oraliq bo'yicha qoladi"
    assert control.member_sql(await control.config(), User.tg_id, User.created_at) is None

    # ---------- 11) chegirma A/B: standart o'chiq; yoqilsa teng yarmi ikkinchi narxni oladi; voronka guruhlar bo'yicha
    pc = await pricing.config()
    assert pc["ab"] == {"on": False, "price": 0, "since": None} and pricing.offer_price(pc, 12345) == (39000, "")
    for bad, word in (({"on": True, "price": 0}, "kiriting"), ({"on": True, "price": 69000}, "kichik"), ({"on": True, "price": 39000}, "farq")):
        try:
            await admin.pricing_save({"packs": pc["packs"], "promo": pc["promo"], "ab": bad}, uid=999)
            raise AssertionError(bad)
        except Exception as e:
            assert getattr(e, "status_code", 0) == 400 and word in e.detail, (bad, e)
    out = await admin.pricing_save({"packs": pc["packs"], "promo": pc["promo"], "ab": {"on": True, "price": 29000}}, uid=999)
    assert out["ab"]["on"] and out["ab"]["price"] == 29000 and out["ab"]["since"]
    since_ab = out["ab"]["since"]
    out = await admin.pricing_save({"packs": pc["packs"], "promo": pc["promo"]}, uid=999)  # A/B yuborilmasa — o'zgarmaydi
    assert out["ab"] == {"on": True, "price": 29000, "since": since_ab}
    ua = next(u for u in range(2000, 2100) if control.arm(u) == "a" and control.bucket(u) >= 50)
    ub = next(u for u in range(2000, 2100) if control.arm(u) == "b" and control.bucket(u) >= 50)
    t3 = utcnow() - 3 * H
    async with Session() as s:
        for u in (ua, ub):
            s.add(User(tg_id=u, first_name="AB", created_at=t3 - timedelta(days=3)))
            s.add(song(u, t3 - 2 * H))
        await s.commit()
    abot = Bot()
    await pricing.offer_due(abot, t3)
    msg = {u: text for u, text, _ in abot.sent}
    assert "<b>39 000 so‘m</b>" in msg[ua] and "<b>29 000 so‘m</b>" in msg[ub], msg
    async with Session() as s:
        prices_ = dict((await s.execute(select(Song.owner_id, Song.promo_price).where(Song.owner_id.in_([ua, ub])))).all())
        arms_ = dict((await s.execute(select(NudgeLog.user_id, NudgeLog.arm).where(NudgeLog.seq == "offer", NudgeLog.user_id.in_([ua, ub])))).all())
    assert prices_ == {ua: 39000, ub: 29000} and arms_ == {ua: "a", ub: "b"}
    async with Session() as s:  # B guruhidagi odam: tugma → «sotib olish» → to'lov oynasi → pul tushdi
        for k, ref in ((track.CLICK, "n:offer.0"), ("buy_click", ""), ("pay_open", "pay:9"), ("pay_success", "pay:9")):
            s.add(Event(user_id=ub, kind=k, ref=ref, created_at=t3 + H))
        s.add(Event(user_id=ua, kind="app", created_at=t3 + 50 * H))  # 48 soatdan keyin — hisoblanmaydi
        await s.commit()
    fu = await admin.discount_get(frm=None, to=None, all_time=1, uid=999)
    arms = {x["arm"]: x for x in fu["arms"]}
    assert arms["b"]["price"] == 29000 and [x["n"] for x in arms["b"]["steps"]] == [1, 1, 1, 1, 1], arms["b"]
    assert arms["a"]["price"] == 39000 and [x["n"] for x in arms["a"]["steps"]] == [1, 0, 0, 0, 0], arms["a"]
    assert arms[""]["offered"] >= 1 and fu["ab"]["on"]
    r = await admin.export("discount", frm=None, to=None, all_time=1, uid=999)
    assert "B — ikkinchi narx;29000;To'ladi yoki sotib oldi;1" in r.body.decode("utf-8-sig")
    # eslatma ham shu guruh bilan yoziladi
    async with Session() as s:
        until_b = (await s.execute(select(Song.promo_until).where(Song.owner_id == ub))).scalar_one()
    await pricing.remind_due(abot, until_b - 6 * H + timedelta(minutes=1))
    async with Session() as s:
        assert (await s.execute(select(NudgeLog.arm).where(NudgeLog.seq == "rem", NudgeLog.user_id == ub))).scalars().all() == ["b"]
    await admin.pricing_save({"packs": pc["packs"], "promo": pc["promo"], "ab": {"on": False, "price": 29000}}, uid=999)
    assert pricing.offer_price(await pricing.config(), ub) == (39000, "")
    store.forget()
    print("test_msgstats: OK")


if __name__ == "__main__":
    asyncio.run(main())
