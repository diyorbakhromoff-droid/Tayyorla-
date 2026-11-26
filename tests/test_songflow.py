"""Qo'shiq voronkasi va namunasiz qolganlar (TZ 1 va 2-bandlar): eski ma'lumotdan tiklash, hodisalarni yozish
(server va ilova), voronka (odamlar bo'yicha, kogorta va davr), tushib qolganlar ro'yxati, manba filtri,
«Namunasiz qolganlar» sabablari, «Tizim» (namuna vaqti, xatolar, qayta urinishlar), adminlarga ogohlantirish, CSV.

Musiqa xizmati va she'r yozish soxta javoblar bilan almashtiriladi. Ishga tushirish: python -m tests.test_songflow
PostgreSQL da tekshirish (bo'sh baza kerak): TEST_DATABASE_URL=postgresql+asyncpg://… python -m tests.test_songflow
"""

import asyncio
import hashlib
import hmac
import json
import logging
import os
import subprocess
import tempfile
import time
from datetime import timedelta
from pathlib import Path
from types import SimpleNamespace
from urllib.parse import urlencode

TMP = Path(tempfile.mkdtemp())
os.environ["DATABASE_URL"] = os.environ.get("TEST_DATABASE_URL") or f"sqlite+aiosqlite:///{TMP}/songflow.db"
os.environ["BOT_TOKEN"] = "123456:TEST"
os.environ["ADMIN_IDS"] = "999"
os.environ["BASE_URL"] = "https://example.uz"
os.environ["ELEVENLABS_API_KEY"] = "test-key"
os.environ["SONG_PRICE"] = "69000"

from aiogram.exceptions import TelegramForbiddenError  # noqa: E402
from aiogram.methods import SendMessage  # noqa: E402
from fastapi import HTTPException  # noqa: E402
from sqlalchemy import insert, select, text  # noqa: E402

from app import admin, funnel, payflow, songapi, songflow, songs, store, track, videoapi, videobot  # noqa: E402
from app.billing import credit  # noqa: E402
from app.db import BalanceTx, CostLog, Event, Payment, Person, RenderJob, Session, Site, Song, User, engine, init_db, utcnow  # noqa: E402
from app.reminders import today  # noqa: E402

LYRICS = """[1-kuplet]
Har tongda birinchi siz uyg'onasiz,
Choy damlab, duolar bilan kutasiz.
Charchasangiz ham sir boy bermaysiz,
Kulib «bolajonim» deb chaqirasiz.

[Naqorat]
Onajonim, onajonim,
Siz — mening quyoshim.
Onajonim, mehribonim,
Uzoq bo'lsin yoshingiz."""

FAKE_MP3 = TMP / "fake.mp3"
subprocess.run(["ffmpeg", "-nostdin", "-y", "-loglevel", "error", "-f", "lavfi", "-i", "sine=frequency=440:duration=40",
                "-c:a", "libmp3lame", "-b:a", "128k", str(FAKE_MP3)], check=True)
FAIL: dict = {"compose": None, "write": False}


async def fake_compose(plan, store=False, info=None):
    if FAIL["compose"] is not None:
        raise FAIL["compose"]
    if store and info is not None:
        info["song_id"] = "stored-1"
    return FAKE_MP3.read_bytes()


async def fake_write(song, instruction=""):
    if FAIL["write"]:
        raise RuntimeError("AI xizmati javob bermadi")
    song._lyrics_usage = SimpleNamespace(input_tokens=3000, output_tokens=4000)
    return "Onajonim", songs.render_lyrics(songs.parse_lyrics(LYRICS)), ["warm acoustic ballad"]


async def subscribed(bot, uid):
    return uid != 32


async def no_credits_info(force=False):
    return None  # kredit qoldig'ini o'qib bo'lmadi — xizmat ruxsat beradi (tarmoqqa chiqilmaydi)


songs.compose = fake_compose
songs.write_lyrics = fake_write
songs.credits = no_credits_info
videobot.is_subscribed = subscribed
songapi.settings.song_lyrics_per_day = 100
songapi.settings.song_lyrics_total = 1000
songapi.settings.song_previews_total = 1000
songapi.settings.song_daily_previews = 50
songapi.settings.song_free_previews = 1  # bir kishiga kuniga bitta bepul namuna


def sign(user: dict, token="123456:TEST") -> str:
    data = {"user": json.dumps(user), "auth_date": str(int(time.time()))}
    check = "\n".join(f"{k}={v}" for k, v in sorted(data.items()))
    secret = hmac.new(b"WebAppData", token.encode(), hashlib.sha256).digest()
    data["hash"] = hmac.new(secret, check.encode(), hashlib.sha256).hexdigest()
    return urlencode(data)


INIT = {uid: sign({"id": uid, "first_name": f"U{uid}"}) for uid in (10, *range(20, 36), 50, 999)}
BODY = songapi.SongIn(recipient="Onajonim", relation="onam", occasion="tugilgan_kun", style="akustika", voice="male", answers={})


class Bot:
    def __init__(self):
        self.sent, self.audio, self.blocked = [], [], set()

    async def send_message(self, chat_id, text, **kw):
        if chat_id in self.blocked:
            raise TelegramForbiddenError(method=SendMessage(chat_id=chat_id, text="x"), message="Forbidden: bot was blocked by the user")
        self.sent.append((chat_id, text))

    async def send_audio(self, chat_id, audio, **kw):
        self.audio.append(chat_id)

    async def get_chat_member_count(self, chat_id):
        return 100

    def to(self, chat_id) -> list[str]:
        return [t for c, t in self.sent if c == chat_id]


async def events(kind=None, uid=None, ref=None):
    async with Session() as s:
        q = select(Event).order_by(Event.id)
        for col, v in ((Event.kind, kind), (Event.user_id, uid), (Event.ref, ref)):
            if v is not None:
                q = q.where(col == v)
        return (await s.execute(q)).scalars().all()


async def bump_ids(*tables) -> None:
    """PostgreSQL: qo'lda berilgan id lardan keyin ketma-ketlikni suradi (SQLite da kerak emas)."""
    if engine.dialect.name != "postgresql":
        return
    async with engine.begin() as c:
        for name in tables:
            await c.execute(text(f"SELECT setval(pg_get_serial_sequence('{name}', 'id'), (SELECT COALESCE(MAX(id), 1) FROM {name}))"))


async def tr(uid, kind, ref="", num=None, meta=None) -> bool:
    """Ilova yuborgan hodisa (POST /api/track)."""
    return (await videoapi.track_event(videoapi.TrackIn(kind=kind, ref=ref, num=num, meta=meta), x_init_data=INIT[uid]))["ok"]


async def run_queue(bot):
    """Navbatdagi qo'shiqlarni (worker kabi) qayta ishlaydi."""
    async with Session() as s:
        rows = (await s.execute(select(Song).where(Song.status.in_(("preview_queued", "paid_queued"))))).scalars().all()
        ids = []
        for x in rows:
            x.status = x.status.replace("_queued", "_gen")
            ids.append(x.id)
        await s.commit()
    for sid in ids:
        await songs.process(sid, bot)


async def new_song(uid) -> int:
    return (await songapi.song_create(BODY, x_init_data=INIT[uid]))["id"]


async def status_of(e) -> int:
    try:
        await e
    except HTTPException as err:
        return err.status_code
    return 200


def steps_of(rep) -> dict:
    return {x["key"]: x for x in rep["steps"]}


async def rewind_alerts(minutes=120):
    """Go'yo oxirgi ogohlantirishlar shuncha daqiqa oldin yuborilgan."""
    cfg = await store.get(songflow.KEY)
    cfg["alerted"] = {k: (utcnow() - timedelta(minutes=minutes)).isoformat(timespec="seconds") for k in cfg.get("alerted", {})}
    await store.put(songflow.KEY, cfg)


async def main() -> None:
    await init_db()
    await init_db()  # qayta ishga tushirish xavfsiz (bu qismda yangi ustun yo'q — mavjud events jadvali ishlatiladi)
    bot = Bot()
    videobot.BOT = bot
    T = (utcnow() - timedelta(days=40)).replace(hour=8, minute=0, second=0, microsecond=0)
    h, m = (lambda x: timedelta(hours=x)), (lambda x: timedelta(minutes=x))

    # ------------------------------------------------------------ 0) eski ma'lumot: hodisalar mavjud jadvallardan tiklanadi
    async with Session() as s:
        s.add_all([User(tg_id=u, first_name=f"U{u}", ref="src_insta1" if u == 10 else "", created_at=T - h(1)) for u in (10, 11, 12, 13, 14, 999)])
        s.add_all([
            Song(id=1, owner_id=10, status="preview_ready", preview="pv:1.mp3", preview_at=T + m(10), updated_at=T + m(11) + timedelta(seconds=30),
                 created_at=T, lyrics="x", previews=1),
            Song(id=2, owner_id=10, status="lyrics", created_at=T + h(1), updated_at=T + h(1), lyrics="x"),      # bir odam — ikki qo'shiq
            Song(id=3, owner_id=11, status="ready", paid=True, preview="pv:3.mp3", preview_at=T + h(2), created_at=T + m(110),
                 updated_at=T + h(3), lyrics="x"),                                                               # sotilgan
            Song(id=4, owner_id=12, status="lyrics", error="Navbat band, bir necha daqiqadan so'ng qayta urinib ko'ring.",
                 created_at=T + h(4), updated_at=T + h(4) + m(5), lyrics="x"),                                   # namuna xatosi saqlanib qolgan
            Song(id=5, owner_id=13, status="failed", paid=True, error="Qo'shiq tayyorlashda xato bo'ldi, qayta urinib ko'ring.",
                 created_at=T + h(5), updated_at=T + h(5) + m(10), lyrics="x"),                                  # to'liq qo'shiq xatosi
            Song(id=6, owner_id=14, status="lyrics", preview_at=T + h(6) + m(5), created_at=T + h(6), updated_at=T + h(6) + m(30), lyrics="x"),
            Song(id=7, owner_id=999, status="lyrics", created_at=T + h(7), updated_at=T + h(7), lyrics="x"),     # admin — sanalmaydi
        ])
        await s.execute(insert(Event), [
            {"user_id": 10, "kind": "start", "src": "src_insta1", "created_at": T - m(10)},
            {"user_id": 10, "kind": "app", "src": "", "created_at": T - m(9)},
            {"user_id": 10, "kind": songs.PV_EVENT, "src": "1", "created_at": T + m(10)},
            {"user_id": 11, "kind": songs.PV_EVENT, "src": "3", "created_at": T + h(2)},
            {"user_id": 14, "kind": songs.PV_EVENT, "src": "6", "created_at": T + h(6) + m(5)},  # she'r keyin tahrirlangan: namuna olib tashlangan
            {"user_id": 10, "kind": songs.PV_EVENT, "src": "9999", "created_at": T},              # yo'q qo'shiq — tashlab ketiladi
        ])
        s.add_all([CostLog(user_id=10, kind="ai", purpose="lyrics_edit", ref="song:2", created_at=T + h(1)) for _ in range(2)])
        await s.commit()
    await bump_ids("songs")

    assert await songflow.since() is None
    await songflow.start()
    since = await songflow.since()
    assert since and abs((utcnow() - since).total_seconds()) < 5
    bf = [e for e in await events() if (e.meta or {}).get("bf")]
    assert len(bf) == 16, len(bf)
    kinds = {}
    for e in bf:
        kinds.setdefault(e.kind, []).append(e)
    assert {k: len(v) for k, v in kinds.items()} == {"lyrics_ready": 7, "sample_requested": 3, "sample_ready": 3, "sample_failed": 1,
                                                    "song_failed": 1, "song_delivered": 1}
    ly = {e.ref: e for e in kinds["lyrics_ready"]}
    assert ly["song:2"].num == 2 and ly["song:1"].num == 0 and ly["song:1"].created_at == T and ly["song:1"].src == "src_insta1"
    ready = {e.ref: e for e in kinds["sample_ready"]}
    assert (ready["song:1"].num, ready["song:1"].created_at) == (90, T + m(11) + timedelta(seconds=30))  # kutish vaqti tiklandi
    assert ready["song:3"].num is None and ready["song:3"].created_at == T + h(2)                         # sotilgan: aniq vaqt saqlanmagan
    assert ready["song:6"].created_at == T + h(6) + m(5)
    assert kinds["sample_failed"][0].meta["r"] == "busy" and kinds["sample_failed"][0].ref == "song:4"
    assert kinds["song_failed"][0].meta["r"] == "unknown" and kinds["song_delivered"][0].created_at == T + h(3)
    await songflow.start()
    assert await songflow.backfill() == 0 and await songflow.since() == since  # takror yozilmaydi

    # eski davr voronkasi: odamlar bo'yicha (10-chi ikki qo'shiq bilan bitta), admin sanalmaydi
    old = await funnel.report("song", T - h(24), T + h(48), "period")
    st = steps_of(old)
    assert [x["n"] for x in old["steps"]] == [5, 5, 5, 5, 5, 3, 3, 1, 1, 1, 1, 1, 0], [x["n"] for x in old["steps"]]
    assert st["lyrics_ready"]["exact"] == 5 and st["start"]["exact"] == 1 and st["sample_played"]["exact"] == 0 and old["excluded"] == 1
    assert (st["sample_requested"]["lost"], st["sample_requested"]["lost_at"], st["sample_requested"]["pct"]) == (2, "lyrics_ready", 60.0)
    assert st["sample_ready"]["time"] == {"n": 3, "avg_s": 30, "median_s": 0}  # so'rovdan tayyor bo'lguncha: 90, 0, 0 soniya
    assert st["song_open"]["since"] == since.isoformat(timespec="seconds") and st["lyrics_ready"]["since"] is None
    assert {x["key"]: x["n"] for x in old["side"]} == {"lyrics_failed": 0, "sample_limit": 0, "sample_failed": 1}
    who = await funnel.people("song", T - h(24), T + h(48), "period", "", "lyrics_ready")
    assert who["total"] == 2 and {x["id"] for x in who["rows"]} == {12, 13} and who["label"] == "She'r tayyor bo'ldi"
    ns = await funnel.nosample(T - h(24), T + h(48), "period")
    g = {x["key"]: x for x in ns["groups"]}
    assert (ns["lyrics"], ns["with_sample"], ns["none"]) == (5, 3, 2) and g["error"]["n"] == 1 and g["old"]["n"] == 1 and g["nopress"]["n"] == 0
    assert g["error"]["sub"] == [{"key": "busy", "label": songflow.REASONS["busy"], "n": 1}]

    # ------------------------------------------------------------ 1) yangi odamlar: hodisalar haqiqiy oqimda yoziladi
    async with Session() as s:
        s.add_all([User(tg_id=u, first_name=f"U{u}", ref="src_insta1" if u == 20 else "", blocked=u == 22) for u in (*range(20, 36), 50)])
        s.add(Person(owner_id=20, name="onajonim", kind="birthday", day=8, month=3))
        await s.commit()
    await track.set_test_ids([50])

    # 20: to'liq yo'l — bo'limga kirdi, so'rovnoma, she'r (2 marta qayta yozildi), namuna, eshitdi, sotib oldi, yuklab oldi
    assert await tr(20, "song_open", meta={"from": "tab", "x": "y"})
    a20 = await new_song(20)
    fd = (await events("song_form_done", 20))[0]
    assert fd.ref == f"song:{a20}" and fd.meta == {"rel": "onam", "occ": "tugilgan_kun", "date": "03-08"} and fd.src == "src_insta1"
    assert [(e.num, e.meta["how"]) for e in await events("lyrics_ready", 20)] == [(0, "new")]
    assert fd.created_at <= (await events("lyrics_ready", 20))[0].created_at
    await songapi.song_lyrics(a20, songapi.LyricsIn(instruction="quvnoqroq"), x_init_data=INIT[20])
    await songapi.song_lyrics(a20, songapi.LyricsIn(text=LYRICS), x_init_data=INIT[20])
    assert [(e.num, e.meta["how"]) for e in await events("lyrics_ready", 20)] == [(0, "new"), (1, "ai"), (2, "manual")]

    assert (await songapi.song_preview(a20, x_init_data=INIT[20]))["status"] == "preview_queued"
    assert len(await events("sample_requested", 20)) == 1 and not await events("sample_ready", 20)
    async with Session() as s:  # go'yo 75 soniya oldin so'ralgan
        (await s.get(Song, a20)).preview_at = utcnow() - timedelta(seconds=75)
        await s.commit()
    await run_queue(bot)
    sr = (await events("sample_ready", 20))[0]
    assert 75 <= sr.num <= 95 and sr.meta == {"away": 1} and sr.ref == f"song:{a20}"       # kutish vaqti; odam ilovada emas edi
    assert [(e.num, e.ref) for e in await events("sample_away", 20)] == [(1, f"song:{a20}")]  # ...botdagi xabar yetdi
    assert len(bot.to(20)) == 1 and "namuna tayyor" in bot.to(20)[0]

    assert await tr(20, "sample_played", f"song:{a20}", 2, {"end": False, "of": 20})
    assert await tr(20, "sample_played", f"song:{a20}", 99999, {"end": True, "of": 20})
    assert [(e.num, e.meta) for e in await events("sample_played", 20)] == [(2, {"end": False, "of": 20}), (3600, {"end": True, "of": 20})]
    assert await tr(20, "buy_click", f"song:{a20}", 69000, {"kind": "single", "disc": False, "at": "sample", "hack": "x" * 99})
    bc = (await events("buy_click", 20))[0]
    assert (bc.num, bc.meta, bc.src) == (69000, {"kind": "single", "disc": False, "at": "sample"}, "src_insta1")
    # ilovadan kelgan hodisa tekshiriladi: begona qo'shiq, noto'g'ri qiymat, ruxsat etilmagan nom — yozilmaydi
    assert not await tr(21, "sample_played", f"song:{a20}", 5) and not await tr(21, "song_open", f"song:{a20}")
    assert not await tr(20, "sample_played", f"song:{a20}", 0) and not await tr(20, "sample_played", "song:abc", 5)
    assert not await tr(20, "buy_click", f"song:{a20}", 1, {"kind": "free"}) and not await tr(20, "buy_click", "", 1, {"kind": "single"})
    assert not await tr(20, "song_shared", f"song:{a20}", meta={"how": "download"})  # hali sotib olinmagan
    assert not await tr(20, "song_delivered", f"song:{a20}") and not await tr(20, "sample_ready", f"song:{a20}")
    assert len(await events("sample_played")) == 2 and len(await events("buy_click")) == 1

    async with Session() as s:
        p = Payment(user_id=20, amount=69000, song_id=a20, purpose="song")
        s.add(p)
        await s.commit()
    await payflow.opened(p)
    async with Session() as s:
        p = await s.get(Payment, p.id)
        p.status, p.provider, p.decided_at = "approved", "click", utcnow()
        await credit(s, 20, 69000, "topup", f"pay:{p.id}")
        await s.commit()
    await payflow.paid(p)
    assert (await songapi.song_pay(a20, x_init_data=INIT[20]))["status"] == "paid_queued"
    await run_queue(bot)
    dl = await events("song_delivered", 20)
    assert len(dl) == 1 and dl[0].ref == f"song:{a20}" and dl[0].num is not None and bot.audio == [20]
    assert await tr(20, "song_shared", f"song:{a20}", meta={"how": "download"})
    assert not await tr(20, "song_shared", f"song:{a20}", meta={"how": "email"})

    # 21: namuna tayyor bo'lganda ilovada kutib turgan (holatni so'rab turgan) — «chiqib ketgan» emas
    a21 = await new_song(21)
    await songapi.song_preview(a21, x_init_data=INIT[21])
    await songapi.song_get(a21, x_init_data=INIT[21])
    await run_queue(bot)
    assert (await events("sample_ready", 21))[0].meta is None and not await events("sample_away", 21) and len(bot.to(21)) == 1
    # 22: botni bloklagan — xabar yuborilmaydi; 23: yuborishda blok aniqlanadi; 29: xabar yetdi, lekin qaytib eshitmadi
    bot.blocked.add(23)
    for u in (22, 23, 29):
        await songapi.song_preview(await new_song(u), x_init_data=INIT[u])
    await run_queue(bot)
    assert not bot.to(22) and not bot.to(23) and len(bot.to(29)) == 1
    assert [(e.user_id, e.num) for e in await events("sample_away") if e.user_id in (22, 23, 29)] == [(22, 0), (23, 0), (29, 1)]
    async with Session() as s:
        assert (await s.get(User, 23)).blocked and not (await s.get(User, 29)).blocked

    # 24: birinchi namunani oldi, ikkinchi qo'shiqda kunlik limit — tugma bosilgani va limit yoziladi
    a24 = await new_song(24)
    await songapi.song_preview(a24, x_init_data=INIT[24])
    await songapi.song_get(a24, x_init_data=INIT[24])
    await run_queue(bot)
    b24 = await new_song(24)
    assert await status_of(songapi.song_preview(b24, x_init_data=INIT[24])) == 402
    assert len(await events("sample_requested", 24)) == 2
    assert [(e.ref, e.meta) for e in await events("sample_limit", 24)] == [(f"song:{b24}", {"l": "user_day"})]
    assert await tr(24, "sample_limit", f"song:{b24}")  # ilovada «bepul namuna tugadi» ko'rsatildi (tugma chiqmaydi)
    assert (await events("sample_limit", 24))[-1].meta == {"l": "user_day", "ui": 1}

    # 28: she'r yozildi, tugmani bosmadi; ikkinchi she'rda kunlik limit. Limiti bor odamdan «limit» hodisasi qabul qilinmaydi
    a28 = await new_song(28)
    assert not await tr(28, "sample_limit", f"song:{a28}")
    await store.put("song_limits", {"ly_day": 1})
    assert await status_of(songapi.song_create(BODY, x_init_data=INIT[28])) == 429
    lf = (await events("lyrics_failed", 28))[0]
    assert (lf.num, lf.meta, lf.ref) == (429, {"r": "limit_day"}, "") and len(await events("song_form_done", 28)) == 2
    await store.put("song_limits", {})
    # 26: so'rovnomani yubordi, she'r yozilmadi (AI xatosi)
    FAIL["write"] = True
    logging.disable(logging.CRITICAL)
    assert await status_of(songapi.song_create(BODY, x_init_data=INIT[26])) == 502
    logging.disable(logging.NOTSET)
    FAIL["write"] = False
    assert (await events("lyrics_failed", 26))[0].meta == {"r": "ai"} and (await events("song_form_done", 26))[0].ref == ""
    # 27 va eski foydalanuvchi 10: faqat bo'limga kirdi
    assert await tr(27, "song_open", meta={"from": "new"}) and await tr(10, "song_open", meta={"from": "tab"})

    # 30: hamma uchun kunlik chegara; 31: bir kishiga limit 0 (tugma chiqmaydi — ilova xabar beradi); 32: kanalga obuna sharti
    a30, a31, a32 = await new_song(30), await new_song(31), await new_song(32)
    async with Session() as s:
        used = await songs.previews_today(s)
    await store.put("song_limits", {"per_day": used})
    assert await status_of(songapi.song_preview(a30, x_init_data=INIT[30])) == 402
    await store.put("song_limits", {"per_user": 0})
    assert await tr(31, "sample_limit", f"song:{a31}") and not await events("sample_requested", 31)
    await store.put("song_limits", {})
    assert await status_of(songapi.song_preview(a32, x_init_data=INIT[32])) == 403
    assert [(e.user_id, e.meta["l"]) for e in await events("sample_limit") if e.user_id in (30, 31, 32)] == [(30, "all_day"), (31, "user_day"), (32, "sub")]

    # 34: namunasiz, balansidagi puldan sotib oldi
    a34 = await new_song(34)
    async with Session() as s:
        await credit(s, 34, 70000, "admin", "t")
        await s.commit()
    await songapi.song_pay(a34, x_init_data=INIT[34])
    await run_queue(bot)
    assert len(await events("song_delivered", 34)) == 1
    # 50: sinov akkaunt — hodisalari yoziladi, lekin statistikaga kirmaydi
    await songapi.song_preview(await new_song(50), x_init_data=INIT[50])
    await run_queue(bot)
    assert len(await events("sample_ready", 50)) == 1

    # ------------------------------------------------------------ 2) xatolar sababi bilan va adminlarga ogohlantirish
    assert not bot.to(999)
    a25 = await new_song(25)
    await songapi.song_preview(a25, x_init_data=INIT[25])
    FAIL["compose"] = songs.SongError("Matnda mualliflik huquqi bilan himoyalangan so'z yoki nom bor. Matnni o'zgartirib ko'ring.", "content")
    await run_queue(bot)
    sf = (await events("sample_failed", 25))[0]
    assert sf.meta["r"] == "content" and "mualliflik" in sf.meta["e"] and sf.ref == f"song:{a25}" and sf.num is not None
    async with Session() as s:
        song = await s.get(Song, a25)
        assert song.status == "lyrics" and song.error and song.previews == 0  # namuna hisobdan qaytarildi
    # xatolar ulushi 5% dan oshdi (10 ta urinishdan 1 tasi) — adminlarga bitta xabar; xizmat javob bergan, «javob bermayapti» emas
    assert len(bot.to(999)) == 1 and "xatolar ko'paydi" in bot.to(999)[0] and "Matn rad etildi" in bot.to(999)[0]
    # mijoz o'zi qayta so'radi — bu safar musiqa xizmati javob bermadi (vaqt tugadi)
    await songapi.song_preview(a25, x_init_data=INIT[25])
    FAIL["compose"] = asyncio.TimeoutError()
    logging.disable(logging.CRITICAL)
    await run_queue(bot)
    logging.disable(logging.NOTSET)
    assert [e.meta["r"] for e in await events("sample_failed", 25)] == ["content", "timeout"]
    assert len(bot.to(999)) == 2 and "javob bermayapti" in bot.to(999)[1]  # ikkinchi sabab — alohida xabar
    # to'liq qo'shiq xatosi: 20-chi ikkinchi qo'shiqni namunasiz sotib oldi, xizmat xato qaytardi; keyin qayta urindi
    c20 = await new_song(20)
    async with Session() as s:
        await credit(s, 20, 69000, "admin", "t")
        await s.commit()
    await songapi.song_pay(c20, x_init_data=INIT[20])
    FAIL["compose"] = songs.SongError("Qo'shiq tayyorlashda xato bo'ldi, qayta urinib ko'ring.")
    await run_queue(bot)
    ff = (await events("song_failed", 20))[0]
    assert ff.meta["r"] == "service" and ff.ref == f"song:{c20}"
    assert len(bot.to(999)) == 2  # bir sabab bo'yicha soatiga ko'pi bilan bitta xabar
    FAIL["compose"] = None
    assert (await songapi.song_retry(c20, x_init_data=INIT[20]))["status"] == "paid_queued"
    await run_queue(bot)
    assert (await events("song_retry", 20))[0].meta == {"by": "user"} and len(await events("song_delivered", 20)) == 2

    hour = await songflow.last_hour()
    assert (hour["attempts"], hour["errors"], hour["down"], hour["stuck"]) == (13, 3, 2, 0), hour  # 10 ta tayyor + 3 ta xato
    assert await songflow.alert_check(bot) == []
    await rewind_alerts()
    assert sorted(await songflow.alert_check(bot)) == ["down", "rate"] and len(bot.to(999)) == 4  # bir soatdan keyin yana
    await rewind_alerts()
    await admin.songflow_save(admin.SongAlertIn(alert_on=False), uid=999)
    assert await songflow.alert_check(bot) == [] and len(bot.to(999)) == 4                         # panelda o'chirilgan
    r = await admin.songflow_save(admin.SongAlertIn(alert_on=True, alert_pct=50, alert_min=3), uid=999)
    assert r["alert"] == {"on": True, "pct": 50, "min": 3}
    assert await songflow.alert_check(bot) == ["down"]                                             # 23% < 50% — faqat «javob bermayapti»
    # navbatda qotib qolgan qo'shiq ham «javob bermayapti» belgisi
    async with Session() as s:
        s.add(Song(owner_id=35, status="preview_gen", preview_at=utcnow() - m(45), lyrics="x"))
        await s.commit()
    hour = await songflow.last_hour()
    assert hour["stuck"] == 1
    assert f"1 ta qo'shiq {songflow.STUCK_MIN} daqiqadan beri" in songflow.alert_texts({**hour, "down": 0}, await songflow.config())["down"]
    async with Session() as s:
        await s.delete((await s.execute(select(Song).where(Song.owner_id == 35))).scalar_one())
        await s.commit()
    await admin.songflow_alert_test(uid=999)
    assert "Sinov" in bot.to(999)[-1]
    await songflow.requeued([(a21, 21, "preview_gen")])  # server qayta ishga tushganda yarim qolgan namuna
    assert (await events("sample_retry", 21))[0].meta == {"by": "restart"}

    # ------------------------------------------------------------ 3) voronka: bugungi harakatlar (davr) va bugun kelganlar (kogorta)
    d = today().isoformat()
    rep = await admin.funnel_report(product="song", mode="period", src="", frm=d, to=d, uid=999)
    st = steps_of(rep)
    assert [x["key"] for x in rep["steps"]] == ["start", "app", "song_open", "song_form_done", "lyrics_ready", "sample_requested", "sample_ready",
                                               "sample_played", "buy_click", "pay_open", "pay_success", "song_delivered", "song_shared"]
    assert [x["n"] for x in rep["steps"]] == [15, 15, 15, 13, 12, 10, 7, 2, 2, 2, 2, 2, 1], [x["n"] for x in rep["steps"]]
    assert [x["exact"] for x in rep["steps"]] == [0, 0, 3, 13, 12, 9, 6, 1, 1, 1, 1, 2, 1], [x["exact"] for x in rep["steps"]]
    assert {x["key"]: x["n"] for x in rep["side"]} == {"lyrics_failed": 2, "sample_limit": 4, "sample_failed": 1}
    assert (st["sample_ready"]["lost"], st["sample_ready"]["pct"], st["song_shared"]["of_first"]) == (3, 70.0, 6.7)
    assert st["sample_ready"]["time"]["n"] == 6 and st["sample_ready"]["time"]["avg_s"] is not None
    assert rep["excluded"] == 2 and rep["nosample"] and rep["sources"][0]["key"] == "" and rep["products"][0] == {"key": "song", "label": "Qo'shiq"}
    spans = {x["label"]: x for x in rep["spans"]}
    assert spans["Namuna tayyor bo'lgandan pul tushguncha"]["n"] == 1 and spans["Start bosgandan pul tushguncha"]["n"] == 0
    # tushib qolganlar: aynan shu qadamda to'xtagan odamlar (mijoz kartasiga havola uchun id bilan)
    lost = await admin.funnel_people(product="song", mode="period", src="", step="sample_requested", group="", frm=d, to=d, uid=999)
    assert lost["total"] == 3 and {x["id"] for x in lost["rows"]} == {25, 30, 32} and lost["rows"][0]["source"] and lost["rows"][0]["at"]
    lost = await admin.funnel_people(product="song", mode="period", src="", step="song_open", group="", frm=d, to=d, uid=999)
    assert {x["id"] for x in lost["rows"]} == {10, 27}
    # manba filtri: users.ref bo'yicha
    one = await admin.funnel_report(product="song", mode="period", src="src_insta1", frm=d, to=d, uid=999)
    assert [x["n"] for x in one["steps"]][:5] == [2, 2, 2, 1, 1] and steps_of(one)["song_shared"]["n"] == 1
    org = await admin.funnel_report(product="song", mode="period", src="organic", frm=d, to=d, uid=999)
    assert org["steps"][0]["n"] == 13 and (await admin.funnel_report(product="song", mode="period", src="src_yoq", frm=d, to=d, uid=999))["steps"][0]["n"] == 0
    # kogorta: bugun kelgan 16 kishi (33 va 35 hech narsa qilmagan), eski 10-chi kirmaydi; ular keyin nima qilgani
    coh = await admin.funnel_report(product="song", mode="cohort", src="", frm=d, to=d, uid=999)
    assert [x["n"] for x in coh["steps"]] == [16, 14, 14, 13, 12, 10, 7, 2, 2, 2, 2, 2, 1], [x["n"] for x in coh["steps"]]
    assert (coh["steps"][1]["lost"], coh["steps"][1]["lost_at"], coh["steps"][1]["pct"]) == (2, "start", 87.5)
    lost = await admin.funnel_people(product="song", mode="cohort", src="", step="start", group="", frm=d, to=d, uid=999)
    assert lost["total"] == 2 and {x["id"] for x in lost["rows"]} == {33, 35}
    yday = (today() - timedelta(days=1)).isoformat()
    assert (await admin.funnel_report(product="song", mode="cohort", src="", frm=yday, to=yday, uid=999))["steps"][0]["n"] == 0
    # butun davr: eski va yangi birga; bir odam ko'p qo'shiq bilan ham bitta
    full = await admin.funnel_report(product="song", mode="period", src="", frm=None, to=None, all_time=1, uid=999)
    assert steps_of(full)["lyrics_ready"]["exact"] == 17 and steps_of(full)["song_delivered"]["n"] == 3 and full["from"] is None
    try:
        await admin.funnel_report(product="xato", mode="period", src="", frm=d, to=d, uid=999)
        raise AssertionError("noma'lum mahsulot qabul qilindi")
    except HTTPException as e:
        assert e.status_code == 400

    # ------------------------------------------------------------ 4) namunasiz qolganlar: sabab bo'yicha
    ns = rep["nosample"]
    g = {x["key"]: x for x in ns["groups"]}
    assert (ns["lyrics"], ns["with_sample"], ns["bought"], ns["none"], ns["notified"]) == (12, 3, 1, 8, 1), ns
    assert {k: v["n"] for k, v in g.items()} == {"nopress": 1, "limit": 3, "error": 1, "left": 3, "pending": 0, "old": 0}
    assert g["limit"]["pct"] == 37.5 and {x["key"]: x["n"] for x in g["limit"]["sub"]} == {"all_day": 1, "user_day": 1, "sub": 1}
    assert g["error"]["sub"] == [{"key": "timeout", "label": songflow.REASONS["timeout"], "n": 1}]  # oxirgi to'siq sanaladi
    left = await admin.funnel_people(product="song", mode="period", src="", step="", group="left", frm=d, to=d, uid=999)
    assert left["total"] == 3 and {x["id"] for x in left["rows"]} == {22, 23, 29} and left["label"] == "Kutib o'tirmagan"
    assert {x["id"] for x in (await funnel.nosample_people(None, utcnow() + h(1), "period", "", "old"))["rows"]} == {13}

    # ------------------------------------------------------------ 5) «Umumiy» va «Tizim»: xatolar, namuna vaqti, qayta urinishlar
    ov = await admin.overview(frm=d, to=d, uid=999)
    sg = ov["cur"]["songs"]
    assert (sg["failed"], sg["failed_sample"], sg["failed_full"], sg["failed_people"]) == (3, 2, 1, 2), sg  # avval doim 0 edi
    sysd = (await admin.system(uid=999))["songflow"]
    day0 = sysd["by_day"][0]
    assert (day0["day"], day0["asked"], day0["ready"], day0["failed"], day0["fail_pct"]) == (d, 11, 6, 2, 25.0), day0
    assert day0["max_s"] >= 75 and day0["avg_s"] >= 12 and day0["timed"] == 6 and sysd["wait"]["max_s"] == day0["max_s"]
    assert sysd["retries"] == {"auto": 1, "manual": 1} and sysd["full"] == {"delivered": 3, "failed": 1, "retried": 1}
    assert {x["key"]: x["n"] for x in sysd["reasons"]} == {"content": 1, "timeout": 1, "service": 1}
    errs = sysd["errors"]
    assert [(e["kind"], e["reason"]) for e in errs[:4]] == [("song_failed", "service"), ("sample_failed", "timeout"),
                                                            ("sample_failed", "content"), ("lyrics_failed", "ai")]
    assert errs[0]["kind_label"] == "To'liq qo'shiq" and errs[0]["song_id"] == c20 and errs[0]["title"] == "Onajonim" and errs[0]["name"] == "U20"
    assert errs[1]["reason_label"] == songflow.REASONS["timeout"] and "TimeoutError" in errs[1]["error"] and not errs[1]["old"]
    assert [e["old"] for e in errs[-2:]] == [True, True] and sysd["alert"]["pct"] == 50 and sysd["hour"]["errors"] == 3

    # ------------------------------------------------------------ 6) sayt va video voronkasi: mavjud jadvallardan
    async with Session() as s:
        s.add_all([User(tg_id=u, first_name=f"U{u}") for u in (40, 41, 42, 43)])
        s.add_all([Site(slug="s40", owner_id=40, category="x", config={}, kind="site"), Site(slug="s41", owner_id=41, category="x", config={}, kind="site"),
                   Site(slug="e41", owner_id=41, category="x", config={}, kind="video"),
                   BalanceTx(user_id=41, amount=-59000, kind="site", ref="site:s41"),
                   RenderJob(owner_id=42, design="d", payload={}, hash="h1", charge="free", status="done"),
                   RenderJob(owner_id=43, design="d", payload={}, hash="h2", charge="paid", status="done"),
                   RenderJob(owner_id=43, design="d", payload={}, hash="h3", charge="package", status="done", guest_id=5),
                   BalanceTx(user_id=43, amount=-9900, kind="video", ref="job:2")])
        pay = Payment(user_id=41, amount=59000, purpose="site", status="approved", decided_at=utcnow())
        s.add(pay)
        await s.flush()
        await s.execute(insert(Event), [{"user_id": 40, "kind": "start", "src": ""}, {"user_id": 40, "kind": "app", "src": ""},
                                        {"user_id": 41, "kind": "pay_open", "src": "", "ref": f"pay:{pay.id}", "num": 59000},
                                        {"user_id": 41, "kind": "pay_success", "src": "", "ref": f"pay:{pay.id}", "num": 59000}])
        await s.commit()
    site = await admin.funnel_report(product="site", mode="period", src="", frm=d, to=d, uid=999)
    assert [(x["key"], x["exact"]) for x in site["steps"]] == [("start", 1), ("app", 1), ("site_made", 2), ("pay_open", 1), ("pay_success", 1), ("site_paid", 1)]
    assert [x["n"] for x in site["steps"]][2:] == [2, 1, 1, 1] and "nosample" not in site
    vid = await admin.funnel_report(product="video", mode="period", src="", frm=d, to=d, uid=999)
    assert {x["key"]: x["exact"] for x in vid["steps"]} == {"start": 1, "app": 1, "video_made": 2, "video_free": 1, "pay_open": 0, "pay_success": 0, "video_paid": 1}
    assert steps_of(vid)["video_paid"]["n"] == 1 and steps_of(vid)["video_free"]["n"] == 2
    # qo'shiq voronkasida boshqa mahsulot to'lovi sanalmaydi (sayt uchun ochilgan to'lov)
    assert steps_of(await admin.funnel_report(product="song", mode="period", src="", frm=d, to=d, uid=999))["pay_open"]["exact"] == 1

    # ------------------------------------------------------------ 7) CSV
    csv = (await admin.export("funnel", frm=d, to=d, product="song", mode="period", uid=999)).body.decode()
    assert csv.startswith("﻿#;qadam;hodisa;") and "5;She'r tayyor bo'ldi;lyrics_ready;12;" in csv and "↳ Limit sabab namuna berilmadi" in csv
    csv = (await admin.export("funnelpeople", frm=d, to=d, product="song", mode="period", step="sample_requested", uid=999)).body.decode()
    assert csv.count("\n") == 4 and "«Namunani tinglash»ni bosdi" in csv
    csv = (await admin.export("nosample", frm=d, to=d, product="song", mode="period", uid=999)).body.decode()
    assert "Kutib o'tirmagan;" in csv and "Namunasiz qolganlar;;8;" in csv and "↳ Kanalga obuna sharti bajarilmagan;;1" in csv
    csv = (await admin.export("sampletime", uid=999)).body.decode()
    assert f"{d};11;6;2;25,0;" in csv
    csv = (await admin.export("songerrors", frm=d, to=d, uid=999)).body.decode()
    assert csv.count("\n") == 4 and "Musiqa xizmati javob bermadi" in csv

    # ------------------------------------------------------------ 8) tezlik: ko'p odam va hodisa bilan ham sahifa tez ochiladi
    kinds = ["start", "app", "song_open", "song_form_done", "lyrics_ready", "sample_requested", "sample_ready", "sample_played", "buy_click"]
    rows = [{"user_id": 100000 + u, "kind": k, "src": "", "ref": f"song:{u}"} for u in range(8000) for k in kinds[:1 + u % len(kinds)]]
    async with Session() as s:
        for i in range(0, len(rows), 5000):
            await s.execute(insert(Event), rows[i:i + 5000])
        await s.commit()
    t0 = time.time()
    big = await admin.funnel_report(product="song", mode="period", src="", frm=d, to=d, uid=999)
    await admin.funnel_people(product="song", mode="period", src="", step="lyrics_ready", group="", frm=d, to=d, uid=999)
    took = time.time() - t0
    assert big["steps"][0]["n"] == 8000 + 15 + 1 and took < 3, took  # 40 mingdan ortiq hodisa; +1 — sayt voronkasidagi 40-chi (start)

    # ------------------------------------------------------------ 9) server qayta ishga tushdi: yarim qolgan namuna o'zi davom etadi
    async with Session() as s:
        half = Song(owner_id=35, status="preview_gen", preview_at=utcnow(), lyrics=songs.render_lyrics(songs.parse_lyrics(LYRICS)), title="Yarim")
        s.add(half)
        await s.commit()
    task = asyncio.create_task(songs.worker(bot))
    for _ in range(100):
        await asyncio.sleep(0.2)
        if await events("sample_ready", 35):
            break
    task.cancel()
    assert [(e.ref, e.meta) for e in await events("sample_retry", 35)] == [(f"song:{half.id}", {"by": "restart"})]
    assert len(await events("sample_ready", 35)) == 1 and (await songflow.system())["retries"]["auto"] == 2

    store.forget()
    print("test_songflow: OK")


if __name__ == "__main__":
    asyncio.run(main())
