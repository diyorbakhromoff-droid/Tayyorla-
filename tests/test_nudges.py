"""Progrev ketma-ketliklari, qo'shiq namunasining kunlik limiti va istalgan summaga to'ldirish.

Ishga tushirish: python -m tests.test_nudges
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

os.environ["DATABASE_URL"] = f"sqlite+aiosqlite:///{tempfile.mkdtemp()}/nudges.db"
os.environ["BOT_TOKEN"] = "123456:TEST"
os.environ["BASE_URL"] = "https://example.uz"

from aiogram.exceptions import TelegramForbiddenError  # noqa: E402
from aiogram.methods import SendMessage  # noqa: E402
from fastapi import HTTPException  # noqa: E402
from sqlalchemy import select  # noqa: E402

from app import nudges, songs, store, videoapi, videobot  # noqa: E402
from app.db import Event, NudgeLog, Payment, RenderJob, Session, Site, Song, User, init_db  # noqa: E402

# 2026-11-10 12:00 Toshkent = 07:00 UTC (bazadagi vaqt UTC, zonasiz)
NOON = datetime(2026, 11, 10, 7, 0)


def sign(user: dict, token="123456:TEST") -> str:
    data = {"user": json.dumps(user), "auth_date": str(int(time.time()))}
    check = "\n".join(f"{k}={v}" for k, v in sorted(data.items()))
    secret = hmac.new(b"WebAppData", token.encode(), hashlib.sha256).digest()
    data["hash"] = hmac.new(secret, check.encode(), hashlib.sha256).hexdigest()
    return urlencode(data)


class Bot:
    def __init__(self):
        self.sent, self.blocked = [], set()

    async def send_message(self, chat_id, text, **kw):
        if chat_id in self.blocked:
            raise TelegramForbiddenError(method=SendMessage(chat_id=chat_id, text="x"), message="Forbidden: bot was blocked by the user")
        self.sent.append((chat_id, text, kw.get("reply_markup")))


async def logs(uid=None):
    async with Session() as s:
        q = select(NudgeLog).order_by(NudgeLog.id)
        if uid:
            q = q.where(NudgeLog.user_id == uid)
        return [(x.user_id, x.seq, x.step, x.status) for x in (await s.execute(q)).scalars().all()]


async def main() -> None:
    await init_db()
    bot = Bot()

    # ---------- sozlama tekshiruvi
    cfg = nudges.clean(nudges.DEFAULTS)
    assert cfg == nudges.DEFAULTS and [len(cfg["seqs"][k]["steps"]) for k in nudges.SEQS] == [3, 3, 3]
    for bad in ({"from_hour": 22, "to_hour": 9}, {"gap_hours": 0},
                {"seqs": {"site": {"steps": [{"after": 5, "text": "a"}, {"after": 5, "text": "b"}]}}},
                {"seqs": {"song": {"steps": [{"after": 2, "text": ""}]}}},
                {"seqs": {"new": {"steps": [{"after": 9999, "text": "a"}]}}}):
        try:
            nudges.clean({**nudges.DEFAULTS, **bad})
            raise AssertionError(f"noto'g'ri sozlama qabul qilindi: {bad}")
        except nudges.ConfigError:
            pass
    assert nudges.fill("{name}, saytingiz tayyor. Narxi {price}", {"name": "", "price": "59 000 so‘m"}) == "Saytingiz tayyor. Narxi 59 000 so‘m"
    assert nudges.fill("{name}, salom", {"name": "Ali"}) == "Ali, salom"

    # ---------- 1) yangi foydalanuvchi: 1 soat -> video, 24 soat -> sayt, 72 soat -> qo'shiq
    async with Session() as s:
        s.add(User(tg_id=1, first_name="Aziz", created_at=NOON - timedelta(hours=2)))                 # yangi, hech narsa yasamagan
        s.add(User(tg_id=2, first_name="Eski", created_at=NOON - timedelta(days=30)))                 # eski — xabar ketmaydi
        s.add(User(tg_id=3, first_name="Vali", created_at=NOON - timedelta(hours=2)))                 # video yasagan
        s.add(RenderJob(owner_id=3, design="toy-1", payload={}, hash="h", status="done"))
        s.add(User(tg_id=4, first_name="Blok", created_at=NOON - timedelta(hours=2), blocked=True))   # botni bloklagan
        await s.commit()
    res = await nudges.run_once(bot, NOON)
    assert res["sent"] == 1 and bot.sent[0][0] == 1, (res, bot.sent)
    assert bot.sent[0][1].startswith("Aziz, Tayyorla’ga xush kelibsiz") and "2 ta video" in bot.sent[0][1]
    kb = bot.sent[0][2].inline_keyboard[0][0]
    assert kb.text == "Bepul video yasash" and kb.web_app.url == "https://example.uz/app?tab=videos"
    assert await logs(1) == [(1, "new", 0, "sent")]
    assert await logs(3) == [(3, "new", 0, "skipped")] and await logs(2) == [] and await logs(4) == []
    # takror: shu qadam ikkinchi marta ketmaydi
    assert (await nudges.run_once(bot, NOON + timedelta(minutes=10)))["sent"] == 0
    # 24 soatdan keyin: 1-odamga sayt; 3-odam (video yasagan) ham sayt taklifini oladi
    res = await nudges.run_once(bot, NOON + timedelta(hours=23))
    assert res["sent"] == 2 and {x[0] for x in bot.sent[1:]} == {1, 3}
    assert all("kichik sayt" in x[1] for x in bot.sent[1:])
    # 72 soat: qo'shiq (kuniga 2 ta bepul namuna)
    res = await nudges.run_once(bot, NOON + timedelta(hours=71))
    assert res["sent"] == 2 and all("2 ta 20 soniyalik namuna" in x[1] for x in bot.sent[3:])
    assert bot.sent[3][2].inline_keyboard[0][0].web_app.url == "https://example.uz/app?song=new"
    assert (await nudges.run_once(bot, NOON + timedelta(hours=100)))["sent"] == 0
    bot.sent.clear()

    # ---------- 2) tungi soat va o'chirilgan holat
    async with Session() as s:
        s.add(User(tg_id=10, first_name="Tun", created_at=NOON + timedelta(hours=100)))
        await s.commit()
    night = NOON + timedelta(hours=100) + timedelta(hours=10)  # 02:00 Toshkent
    assert night.replace(tzinfo=timezone.utc).astimezone(nudges.TZ).hour == 2
    assert (await nudges.run_once(bot, night))["sent"] == 0
    await nudges.save({**nudges.DEFAULTS, "on": False})
    assert (await nudges.run_once(bot, night + timedelta(hours=8)))["sent"] == 0
    await nudges.save(nudges.DEFAULTS)
    assert (await nudges.run_once(bot, night + timedelta(hours=8)))["sent"] == 1 and bot.sent[0][0] == 10
    bot.sent.clear()

    # ---------- 3) to'lanmagan sayt: 2 soat, 24 soat, 72 soat; to'lagach to'xtaydi; «new»dan ustun
    t0 = NOON + timedelta(days=10)
    site_cfg = {"engine": "catalog", "template": "tk8-shohizinda", "tarif": "vip", "data": {}}
    async with Session() as s:
        s.add(User(tg_id=20, first_name="Dilnoza", created_at=t0 - timedelta(hours=3)))
        s.add(Site(slug="draft20", owner_id=20, category="birthday", config=site_cfg, status="draft", created_at=t0 - timedelta(hours=3)))
        s.add(User(tg_id=21, first_name="Sotib", created_at=t0 - timedelta(days=40)))
        s.add(Site(slug="paid21", owner_id=21, category="birthday", config=site_cfg, status="paid", created_at=t0 - timedelta(hours=3)))
        s.add(User(tg_id=22, first_name="Qochgan", created_at=t0 - timedelta(days=40)))
        s.add(Site(slug="draft22", owner_id=22, category="birthday", config=site_cfg, status="draft", created_at=t0 - timedelta(hours=3)))
        await s.commit()
    bot.blocked.add(22)
    res = await nudges.run_once(bot, t0)
    assert res == {"sent": 1, "failed": 0, "blocked": 1}, res
    uid, text, markup = bot.sent[0]
    assert uid == 20 and "«Shohizinda»" in text and "99 000 so‘m" in text and text.startswith("Dilnoza, saytingiz tayyor")
    assert markup.inline_keyboard[0][0].web_app.url == "https://example.uz/app?tab=sites&mine=1"
    async with Session() as s:
        assert (await s.get(User, 22)).blocked
    # yangi foydalanuvchi xabari 20 soatlik tanaffus tufayli darhol ketmaydi
    assert (await nudges.run_once(bot, t0 + timedelta(minutes=30)))["sent"] == 0
    res = await nudges.run_once(bot, t0 + timedelta(hours=22))
    assert res["sent"] == 1 and bot.sent[1][0] == 20 and "hali sizni kutyapti" in bot.sent[1][1]
    async with Session() as s:  # to'ladi -> ketma-ketlik to'xtaydi
        x = (await s.execute(select(Site).where(Site.slug == "draft20"))).scalar_one()
        x.status = "paid"
        await s.commit()
    before = len(bot.sent)
    await nudges.run_once(bot, t0 + timedelta(hours=70))
    assert not [x for x in bot.sent[before:] if "yakunlamadingiz" in x[1]]
    bot.sent.clear()

    # ---------- 4) sotib olinmagan qo'shiq
    t1 = NOON + timedelta(days=30)
    async with Session() as s:
        s.add(User(tg_id=30, first_name="Madina", lang="cy", created_at=t1 - timedelta(days=60)))
        s.add(Song(owner_id=30, status="preview_ready", recipient="Ozoda", title="Opajonim", lyrics="x", preview="/media/p.mp3",
                   created_at=t1 - timedelta(hours=5), preview_at=t1 - timedelta(hours=3)))
        s.add(User(tg_id=31, first_name="Olgan", created_at=t1 - timedelta(days=60)))
        s.add(Song(owner_id=31, status="ready", recipient="A", title="B", lyrics="x", paid=True, created_at=t1 - timedelta(hours=5)))
        await s.commit()
    res = await nudges.run_once(bot, t1)
    assert res["sent"] == 1 and bot.sent[0][0] == 30
    assert "Опажоним" in bot.sent[0][1] and "69 000" in bot.sent[0][1], bot.sent[0][1]  # kirill foydalanuvchiga kirillcha
    song_id = (await logs(30))[0]
    async with Session() as s:
        sid = (await s.execute(select(Song.id).where(Song.owner_id == 30))).scalar_one()
    assert bot.sent[0][2].inline_keyboard[0][0].web_app.url == f"https://example.uz/app?song={sid}" and song_id[1:] == ("song", 0, "sent")

    st = await nudges.stats()
    assert st["reached"]["site"] == 1 and st["won"]["site"] == 1 and st["reached"]["song"] == 1 and st["won"]["song"] == 0
    assert st["steps"]["new"]["0"]["sent"] >= 2 and st["steps"]["new"]["0"]["skipped"] >= 1

    # ---------- 5) sinov xabari (admin o'ziga)
    bot.sent.clear()
    await nudges.send_test(bot, 20, "song", 0, {"text": "{name}, «{title}» — {price}", "button": "Ochish"})
    assert bot.sent[0][1] == "Dilnoza, «Opajonim» — 69 000 so‘m"

    # ---------- 6) qo'shiq namunasi: har kishiga kuniga 2 ta, admin paneldan o'zgaradi
    store.forget()
    assert await songs.limits() == (2, 30)
    async with Session() as s:
        song = Song(owner_id=40, status="lyrics", lyrics="x")
        s.add(song)
        await s.flush()
        assert await songs.free_previews_left(s, 40) == 2
        songs.count_preview(s, song)
        songs.count_preview(s, song)
        s.add(Event(user_id=40, kind=songs.PV_EVENT, src="9", created_at=datetime.now(timezone.utc).replace(tzinfo=None) - timedelta(days=1)))  # kechagi
        await s.flush()
        assert await songs.free_previews_left(s, 40) == 0 and await songs.free_previews_left(s, 41) == 2
        assert await songs.previews_today(s) == 2
        await songs.refund_preview(s, song)  # muvaffaqiyatsiz namuna qaytariladi
        await s.flush()
        assert await songs.free_previews_left(s, 40) == 1
        await s.commit()
    await store.put("song_limits", {"per_user": 5, "per_day": 0})
    assert await songs.limits() == (5, 0)
    async with Session() as s:
        assert await songs.free_previews_left(s, 40) == 4

    # ---------- 7) balansni istalgan summaga to'ldirish
    videobot.BOT = None
    init = sign({"id": 50, "first_name": "Sardor"})
    out = await videoapi.topup(videoapi.TopupIn(amount=15000), x_init_data=init)
    assert out["ok"]
    async with Session() as s:
        assert (await s.get(Payment, out["payment"])).amount == 15000
    out = await videoapi.topup(videoapi.TopupIn(amount=1000), x_init_data=init)
    assert out["ok"]
    try:
        videoapi.TopupIn(amount=999)
        raise AssertionError("eng kam summadan past qabul qilindi")
    except ValueError:
        pass
    videoapi.settings.topup_min = 5000
    try:
        await videoapi.topup(videoapi.TopupIn(amount=3000), x_init_data=init)
        raise AssertionError
    except HTTPException as e:
        assert e.status_code == 400 and "5 000" in e.detail

    # ---------- 8) admin paneli: sozlamalarni o'qish, saqlash, limitni o'zgartirish
    from app import admin
    d = await admin.nudges_get(uid=1)
    assert d["config"]["on"] and [x["key"] for x in d["seqs"]] == ["site", "song", "new"] and d["stats"]["reached"]["site"] == 1
    new_cfg = json.loads(json.dumps(d["config"]))
    new_cfg["seqs"]["new"]["steps"] = new_cfg["seqs"]["new"]["steps"][:1]
    new_cfg["seqs"]["site"]["on"] = False
    new_cfg["gap_hours"] = 12
    r = await admin.nudges_save(admin.NudgesIn(config=new_cfg), uid=1)
    assert r["config"]["gap_hours"] == 12 and not r["config"]["seqs"]["site"]["on"] and len(r["config"]["seqs"]["new"]["steps"]) == 1
    assert (await nudges.config())["gap_hours"] == 12
    new_cfg["seqs"]["song"]["steps"][0]["text"] = ""
    try:
        await admin.nudges_save(admin.NudgesIn(config=new_cfg), uid=1)
        raise AssertionError("bo'sh matn saqlandi")
    except HTTPException as e:
        assert e.status_code == 400 and "matni" in e.detail
    await admin.song_limits(admin.SongLimitsIn(per_user=2, per_day=30), uid=1)
    assert await songs.limits() == (2, 30)
    sysd = await admin.system(uid=1)
    assert sysd["songs"]["per_user"] == 2 and sysd["songs"]["daily_previews"] == 30 and sysd["songs"]["previews_today"] == 1
    print("✅ Progrev, namuna limiti va to'ldirish tekshiruvlari o'tdi")


asyncio.run(main())
