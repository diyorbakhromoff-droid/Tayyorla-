"""Shaxsiy qo'shiq: she'r, namuna, bepul namuna chegarasi, to'lov, 2 ta variant, tanlash va saytga qo'yish.

ElevenLabs va Claude soxta (mock) javoblar bilan almashtiriladi. Ishga tushirish: python -m tests.test_songs
"""

import asyncio
import hashlib
import hmac
import json
import os
import subprocess
import tempfile
import time
from pathlib import Path
from urllib.parse import urlencode

TMP = Path(tempfile.mkdtemp())
os.environ["DATABASE_URL"] = f"sqlite+aiosqlite:///{TMP}/songs.db"
os.environ["BOT_TOKEN"] = "123456:TEST"
os.environ["ELEVENLABS_API_KEY"] = "test-key"
os.environ["SONG_PRICE"] = "69000"

from fastapi import HTTPException  # noqa: E402

from app import songapi, songs  # noqa: E402
from app.billing import credit  # noqa: E402
from app.config import MEDIA_DIR  # noqa: E402
from app.db import Payment, Session, Site, Song, User, init_db  # noqa: E402

UID = 501


def sign(user: dict, token="123456:TEST") -> str:
    pairs = {"auth_date": str(int(time.time())), "user": json.dumps(user)}
    check = "\n".join(f"{k}={v}" for k, v in sorted(pairs.items()))
    secret = hmac.new(b"WebAppData", token.encode(), hashlib.sha256).digest()
    pairs["hash"] = hmac.new(secret, check.encode(), hashlib.sha256).hexdigest()
    return urlencode(pairs)


INIT = sign({"id": UID, "first_name": "Dilnoza"})

LYRICS = """[1-kuplet]
Har tongda birinchi siz uyg'onasiz,
Choy damlab, duolar bilan kutasiz.
Charchasangiz ham sir boy bermaysiz,
Kulib «bolajonim» deb chaqirasiz.

[Naqorat]
Onajonim, onajonim,
Siz — mening quyoshim.
Onajonim, mehribonim,
Uzoq bo'lsin yoshingiz.

[2-kuplet]
Bolaligim — sizning issiq qo'lingiz,
Har yo'limni yoritgan duoingiz.
Bugun sizning tug'ilgan kuningiz,
Bu qo'shiq — qalbimdan, onajonim.

[Naqorat]
Onajonim, onajonim,
Siz — mening quyoshim.
Onajonim, mehribonim,
Uzoq bo'lsin yoshingiz.

[Yakun]
Rahmat sizga, onajonim..."""

# 90 soniyalik haqiqiy mp3 (ffmpeg bilan) — kesish va nusxalash haqiqatda tekshiriladi
FAKE_MP3 = TMP / "fake.mp3"
subprocess.run(["ffmpeg", "-nostdin", "-y", "-loglevel", "error", "-f", "lavfi", "-i", "sine=frequency=440:duration=90",
                "-c:a", "libmp3lame", "-b:a", "128k", str(FAKE_MP3)], check=True)
calls = {"compose": 0, "write": 0, "plans": []}


async def fake_compose(plan):
    calls["compose"] += 1
    calls["plans"].append(plan)
    return FAKE_MP3.read_bytes()


async def fake_write(song, instruction=""):
    calls["write"] += 1
    text = LYRICS if not instruction else LYRICS.replace("quyoshim", "osmonim")
    return "Onajonim", songs.render_lyrics(songs.parse_lyrics(text)), ["warm acoustic ballad", "dutor"]


songs.compose = fake_compose
songs.write_lyrics = fake_write


class FakeBot:
    def __init__(self):
        self.audio, self.msgs = [], []

    async def send_audio(self, chat_id, audio, **kw):
        self.audio.append((chat_id, kw.get("title")))

    async def send_message(self, chat_id, text, **kw):
        self.msgs.append(text)


def dur(path: Path) -> float:
    out = subprocess.run(["ffprobe", "-v", "error", "-show_entries", "format=duration", "-of", "csv=p=0", str(path)],
                         capture_output=True, text=True, check=True).stdout
    return float(out.strip())


async def run_queue(bot):
    """Navbatdagi qo'shiqlarni (worker kabi) qayta ishlaydi."""
    async with Session() as s:
        from sqlalchemy import select
        rows = (await s.execute(select(Song).where(Song.status.in_(("preview_queued", "paid_queued"))))).scalars().all()
        ids = []
        for x in rows:
            x.status = x.status.replace("_queued", "_gen")
            ids.append(x.id)
        await s.commit()
    for sid in ids:
        await songs.process(sid, bot)


async def main() -> None:
    await init_db()
    async with Session() as s:
        s.add(User(tg_id=UID, first_name="Dilnoza"))
        await s.commit()

    # matn <-> bo'limlar
    secs = songs.parse_lyrics(LYRICS)
    assert [x["kind"] for x in secs] == ["verse", "chorus", "verse", "chorus", "outro"], secs
    assert songs.render_lyrics(secs).startswith("[1-kuplet]\nHar tongda") and "[Naqorat]" in songs.render_lyrics(secs)
    assert songs.parse_lyrics("bir\nikki")[0]["kind"] == "verse"
    for bad in ("[Naqorat]\nbir", "[1-kuplet]\nbir\nikki\nuch\nto'rt"):
        try:
            songs.validate_lyrics(songs.parse_lyrics(bad))
            raise AssertionError("noto'g'ri matn qabul qilindi")
        except songs.SongError:
            pass
    plan, chorus_at, chorus_len = songs.build_plan(secs, "akustika", "female", ["dutor"])
    ch = plan["chunks"]
    assert ch[0]["text"] == "[Intro]" and "vocals" in ch[0]["negative_styles"] and ch[1]["text"].startswith("[Verse]\nHar tongda")
    assert chorus_at == ch[0]["duration_ms"] + ch[1]["duration_ms"] and chorus_len == ch[2]["duration_ms"]
    assert all(3000 <= c["duration_ms"] <= 120000 for c in ch) and "sung in Uzbek language" in ch[1]["positive_styles"]
    assert any("female" in t for t in ch[1]["positive_styles"]) and "dutor" in ch[1]["positive_styles"]

    meta = await songapi.songs_meta(x_init_data=INIT)
    assert meta["on"] and meta["price"] == 69000 and meta["free_previews"] == 1 and any(x["key"] == "milliy" for x in meta["styles"])

    # 1) buyurtma: she'r yoziladi
    body = songapi.SongIn(recipient="Onajonim", relation="onam", occasion="tugilgan_kun", style="akustika", voice="male",
                          answers={"xarakter": "mehribon", "erkalash": "onajonim", "begona": "x"})
    out = await songapi.song_create(body, x_init_data=INIT)
    sid = out["id"]
    assert out["status"] == "lyrics" and out["title"] == "Onajonim" and "[Naqorat]" in out["lyrics"]
    assert out["answers"] == {"xarakter": "mehribon", "erkalash": "onajonim"}
    try:
        await songapi.song_create(songapi.SongIn(recipient="X", relation="onam", occasion="x", style="pop"), x_init_data=INIT)
        raise AssertionError
    except HTTPException as e:
        assert e.status_code == 400

    # 2) tahrirlash: qo'lda va AI bilan
    out = await songapi.song_lyrics(sid, songapi.LyricsIn(text=LYRICS.replace("Rahmat sizga", "Ming rahmat")), x_init_data=INIT)
    assert "Ming rahmat" in out["lyrics"]
    try:
        await songapi.song_lyrics(sid, songapi.LyricsIn(text="faqat bir qator"), x_init_data=INIT)
        raise AssertionError
    except HTTPException as e:
        assert e.status_code == 400
    out = await songapi.song_lyrics(sid, songapi.LyricsIn(instruction="quyosh o'rniga osmon"), x_init_data=INIT)
    assert "osmonim" in out["lyrics"]

    # 3) namuna: 1-variant yashirin papkada, foydalanuvchiga faqat naqoratdan 20 s
    bot = FakeBot()
    out = await songapi.song_preview(sid, x_init_data=INIT)
    assert out["status"] == "preview_queued" and out["busy"]
    await run_queue(bot)
    out = await songapi.song_get(sid, x_init_data=INIT)
    assert out["status"] == "preview_ready" and out["preview"].startswith("/media/songp") and out["variants"] == []
    prev = MEDIA_DIR / Path(out["preview"]).name
    assert 19 <= dur(prev) <= 21, dur(prev)
    async with Session() as s:
        song = await s.get(Song, sid)
        private = Path(song.variants[0]["private"])
        assert private.exists() and MEDIA_DIR not in private.parents and song.variants[0]["file"] == ""
    assert calls["compose"] == 1 and bot.audio == [(UID, "Onajonim (namuna)")]

    # bepul namuna tugadi: ikkinchi qo'shiqqa namuna yo'q, to'g'ridan-to'g'ri sotib olish taklif qilinadi
    sid2 = (await songapi.song_create(body, x_init_data=INIT))["id"]
    try:
        await songapi.song_preview(sid2, x_init_data=INIT)
        raise AssertionError("ikkinchi bepul namuna berildi")
    except HTTPException as e:
        assert e.status_code == 402 and e.detail["code"] == "preview_limit"

    # 4) to'lov: balans yetmasa 402
    try:
        await songapi.song_pay(sid, x_init_data=INIT)
        raise AssertionError
    except HTTPException as e:
        assert e.status_code == 402 and e.detail["need"] == 69000
    async with Session() as s:
        await credit(s, UID, 70000, "topup", "t")
        await s.commit()
    out = await songapi.song_pay(sid, x_init_data=INIT)
    assert out["paid"] and out["status"] == "paid_queued" and out["price"] == 69000
    await run_queue(bot)
    out = await songapi.song_get(sid, x_init_data=INIT)
    assert out["status"] == "ready" and len(out["variants"]) == 2 and out["chosen"] == 0 and out["file"] == out["variants"][0]
    assert all((MEDIA_DIR / Path(f).name).exists() for f in out["variants"]) and len(set(out["variants"])) == 2
    assert calls["compose"] == 2, "namunadagi 1-variant qayta yaratilmasligi kerak"
    assert [t for _, t in bot.audio[1:]] == ["Onajonim (1-variant)", "Onajonim (2-variant)"]
    async with Session() as s:
        assert (await s.get(User, UID)).balance == 1000

    # 5) tanlash va saytga qo'yish
    out = await songapi.song_choose(sid, songapi.ChooseIn(index=1), x_init_data=INIT)
    assert out["chosen"] == 1 and out["file"] == out["variants"][1]
    async with Session() as s:
        s.add(Site(slug="ona1", owner_id=UID, category="birthday", config={"engine": "catalog"}, status="paid", kind="site"))
        await s.commit()
    out = await songapi.song_attach(sid, songapi.AttachIn(site="ona1"), x_init_data=INIT)
    async with Session() as s:
        from sqlalchemy import select
        site = (await s.execute(select(Site).where(Site.slug == "ona1"))).scalar_one()
        assert site.config["music"] == out["file"] and out["site"] == "ona1"
    await songapi.song_choose(sid, songapi.ChooseIn(index=0), x_init_data=INIT)
    async with Session() as s:
        site = (await s.execute(select(Site).where(Site.slug == "ona1"))).scalar_one()
        assert site.config["music"] == out["variants"][0], "tanlov almashganda saytdagi musiqa ham almashadi"
    try:
        await songapi.song_lyrics(sid, songapi.LyricsIn(text=LYRICS), x_init_data=INIT)
        raise AssertionError("to'langan qo'shiq matni o'zgardi")
    except HTTPException as e:
        assert e.status_code == 409

    # 6) xato: mualliflik huquqi — namuna bepul hisobdan qaytariladi
    async def bad_compose(plan):
        raise songs.SongError("Matnda mualliflik huquqi bilan himoyalangan so'z yoki nom bor.")
    songs.compose = bad_compose
    sid3 = (await songapi.song_create(body, x_init_data=INIT))["id"]
    async with Session() as s:  # bepul namuna limitini oshiramiz
        x = await s.get(Song, sid2)
        x.previews = 0
        await s.commit()
    songs.settings.song_free_previews = 2
    await songapi.song_preview(sid3, x_init_data=INIT)
    await run_queue(bot)
    out = await songapi.song_get(sid3, x_init_data=INIT)
    assert out["status"] == "lyrics" and "mualliflik" in out["error"] and bot.msgs
    async with Session() as s:
        assert (await s.get(Song, sid3)).previews == 0

    # 7) Click/chek orqali to'ldirilgan pul bilan qo'shiq o'zi to'lanadi
    songs.compose = fake_compose
    from app.bot.money import after_topup
    async with Session() as s:
        await credit(s, UID, 69000, "topup", "pay:x")
        p = Payment(user_id=UID, amount=69000, status="approved", song_id=sid2)
        s.add(p)
        await s.commit()
        user = await s.get(User, UID)
    await after_topup(None, p, user)
    async with Session() as s:
        assert (await s.get(Song, sid2)).status == "paid_queued"
    # 8) kunlik umumiy limit va kanalga obuna sharti (boshqa foydalanuvchilar)
    from app import videobot
    songs.settings.song_free_previews = 1
    songs.settings.song_daily_previews = 3  # bugun allaqachon 3 ta namuna so'ralgan (sid, sid3 va...)
    async with Session() as s:
        from sqlalchemy import func, select
        today_n = await songs.previews_today(s)
    assert today_n >= 1, today_n
    songs.settings.song_daily_previews = today_n  # limit to'ldi
    u2 = sign({"id": 777, "first_name": "Aziz"})
    sid7 = (await songapi.song_create(body, x_init_data=u2))["id"]
    try:
        await songapi.song_preview(sid7, x_init_data=u2)
        raise AssertionError("kunlik limitdan oshib ketdi")
    except HTTPException as e:
        assert e.status_code == 402 and e.detail["code"] == "preview_limit" and e.detail["reason"] == "daily"
    songs.settings.song_daily_previews = 0  # cheklovsiz

    class Member:
        status = "left"

    class SubBot:
        async def get_chat_member(self, chat, uid):
            return Member()
    songs.settings.channel_id = "@tayyorlaai"
    songs.settings.song_preview_sub = True
    videobot.BOT = SubBot()
    try:
        await songapi.song_preview(sid7, x_init_data=u2)
        raise AssertionError("obunasiz namuna berildi")
    except HTTPException as e:
        assert e.status_code == 403 and e.detail["code"] == "need_sub" and "t.me/tayyorlaai" in e.detail["channel"]
    Member.status = "member"
    videobot._SUBSCRIBED.clear()
    out = await songapi.song_preview(sid7, x_init_data=u2)
    assert out["status"] == "preview_queued"
    videobot.BOT = None
    meta = await songapi.songs_meta(x_init_data=u2)
    assert meta["preview_sub"] and meta["channel"].endswith("tayyorlaai") and "demos" in meta
    await run_queue(bot)

    # 9) kredit: kalit bor, lekin tarmoq yo'q — xato bermaydi, None qaytaradi
    async def no_credits(force=False):
        return {"tier": "creator", "used": 95000, "limit": 100000, "remaining": 5000, "reset": None, "songs_left": 3, "usage_based": False}
    songs.credits = no_credits

    class AdminBot:
        sent = []

        async def send_message(self, chat_id, text, **kw):
            self.sent.append((chat_id, text))
    songs.settings.admin_ids = "999"
    ab = AdminBot()
    await songs.check_credits(ab)
    await songs.check_credits(ab)  # 12 soat ichida qayta yuborilmaydi
    assert len(ab.sent) == 1 and ab.sent[0][0] == 999 and "5 000" in ab.sent[0][1]

    # 10) kredit yetmasa: namuna navbatga qo'yilmaydi, to'lovda pul yechilmaydi
    async def empty_credits(force=False):
        return {"tier": "creator", "used": 99009, "limit": 100000, "remaining": 991, "reset": None, "songs_left": 0, "usage_based": False}
    songs.credits = empty_credits
    u3 = sign({"id": 778, "first_name": "Bek"})
    sid9 = (await songapi.song_create(body, x_init_data=u3))["id"]
    try:
        await songapi.song_preview(sid9, x_init_data=u3)
        raise AssertionError("kreditsiz namuna navbatga qo'yildi")
    except HTTPException as e:
        assert e.status_code == 503
    async with Session() as s:
        s.add(User(tg_id=778, first_name="Bek", balance=100000))
        await s.commit()
    try:
        await songapi.song_pay(sid9, x_init_data=u3)
        raise AssertionError("kreditsiz to'lov qabul qilindi")
    except HTTPException as e:
        assert e.status_code == 503 and "pul yechilmadi" in e.detail
    async with Session() as s:
        assert (await s.get(User, 778)).balance == 100000 and not (await s.get(Song, sid9)).paid

    # test fayllarini tozalash
    async with Session() as s:
        from sqlalchemy import select
        for x in (await s.execute(select(Song))).scalars().all():
            for f in [x.preview, *[v.get("file", "") for v in x.variants or []]]:
                if f:
                    (MEDIA_DIR / Path(f).name).unlink(missing_ok=True)
            for v in x.variants or []:
                Path(v["private"]).unlink(missing_ok=True)
    print("✅ Qo'shiq tekshiruvlari o'tdi")


asyncio.run(main())
