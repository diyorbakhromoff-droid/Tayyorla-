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
from types import SimpleNamespace
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
from datetime import timedelta  # noqa: E402

from sqlalchemy import select as sa_select  # noqa: E402

from app.db import CostLog, Payment, Session, Site, Song, User, init_db, utcnow  # noqa: E402

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


async def fake_compose(plan, store=False, info=None):
    calls["compose"] += 1
    calls["plans"].append(plan)
    if store and info is not None:
        info["song_id"] = f"el-{calls['compose']}"  # ElevenLabs saqlangan qo'shiq raqami (song-id sarlavhasi)
    return FAKE_MP3.read_bytes()


async def fake_write(song, instruction=""):
    calls["write"] += 1
    song._lyrics_usage = SimpleNamespace(input_tokens=3000, output_tokens=4000)  # Claude javobidagi kabi
    text = LYRICS if not instruction else LYRICS.replace("quyoshim", "osmonim")
    return "Onajonim", songs.render_lyrics(songs.parse_lyrics(text)), ["warm acoustic ballad", "dutor"]


songs.compose = fake_compose
songs.write_lyrics = fake_write
songapi.settings.song_lyrics_per_day = 100
songapi.settings.song_daily_previews = 20
songapi.settings.song_free_previews = 1  # kuniga bir kishiga (testlar shu qiymatga tayanadi)


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
        # namuna: saqlangan naqorat (ochiq /media da emas), to'liq qo'shiq hali yo'q
        demo = song.plan["_demo"]
        private = Path(demo["private"])
        assert private.exists() and MEDIA_DIR not in private.parents and demo["song_id"] == "el-1" and demo["ms"] > 5000
        assert not song.variants
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
    # namuna faqat naqorat edi (saqlangan); to'liq qo'shiq shu naqorat yozuvining o'zidan yasaladi, ikkinchi variant yo'q
    assert out["status"] == "ready" and len(out["variants"]) == 1 and out["chosen"] == 0 and out["file"] == out["variants"][0]
    assert (MEDIA_DIR / Path(out["file"]).name).exists()
    assert calls["compose"] == 2
    demo_plan, full_plan = calls["plans"][0]["chunks"], calls["plans"][1]["chunks"]
    assert len(demo_plan) == 1 and demo_plan[0]["text"].startswith("[Chorus]")
    refs = [c for c in full_plan if "song_id" in c]
    assert len(refs) == 2 and all(c["song_id"] == "el-1" and c["range"]["start_ms"] == 0 and c["range"]["end_ms"] > 5000 for c in refs)
    assert not any(c.get("text", "").startswith("[Chorus]") for c in full_plan), "naqorat qayta tayyorlanmasligi kerak"
    gen = [c for c in full_plan if "song_id" not in c]
    assert gen[0]["conditioning_ref"]["song_id"] == "el-1" and gen[0]["condition_strength"] == "high"
    assert [t for _, t in bot.audio[1:]] == ["Onajonim"]
    async with Session() as s:
        assert (await s.get(User, UID)).balance == 1000
        # xarajat jurnali: naqorat (namuna) + qolgan qismlar (to'liq), har she'r uchun Claude tokenlari
        logs = (await s.execute(sa_select(CostLog).order_by(CostLog.id))).scalars().all()
        music = [x for x in logs if x.kind == "music"]
        assert [x.purpose for x in music] == ["song_preview", "song_full"] and all(x.units_in > 5 and x.ref == f"song:{sid}" for x in music)
        assert any(x.purpose == "lyrics" and x.ref == f"song:{sid}" and x.units_in == 3000 and x.units_out == 4000 for x in logs)
        from app import costs
        sm = await costs.summary(s, utcnow() - timedelta(days=1), utcnow() + timedelta(days=1))
        assert sm["demo_n"] == 1 and sm["song"] > 0 and sm["total"] >= sm["song"] and "song_est" not in {i["purpose"] for i in sm["items"]}

    # 5) saytga qo'yish (bitta qo'shiq — mavjud bo'lmagan variantni tanlab bo'lmaydi)
    try:
        await songapi.song_choose(sid, songapi.ChooseIn(index=1), x_init_data=INIT)
        raise AssertionError("yo'q variant tanlandi")
    except HTTPException as e:
        assert e.status_code in (400, 404, 409)
    async with Session() as s:
        s.add(Site(slug="ona1", owner_id=UID, category="birthday", config={"engine": "catalog"}, status="paid", kind="site"))
        await s.commit()
    out = await songapi.song_attach(sid, songapi.AttachIn(site="ona1"), x_init_data=INIT)
    async with Session() as s:
        from sqlalchemy import select
        site = (await s.execute(select(Site).where(Site.slug == "ona1"))).scalar_one()
        assert site.config["music"] == out["file"] and out["site"] == "ona1"
    try:
        await songapi.song_lyrics(sid, songapi.LyricsIn(text=LYRICS), x_init_data=INIT)
        raise AssertionError("to'langan qo'shiq matni o'zgardi")
    except HTTPException as e:
        assert e.status_code == 409

    # 6) xato: mualliflik huquqi — namuna bepul hisobdan qaytariladi
    async def bad_compose(plan, store=False, info=None):
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
        return {"tier": "creator", "used": 99800, "limit": 100000, "remaining": 200, "reset": None, "songs_left": 0, "usage_based": False}
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

    # 10a) naqorat oxiridagi «yakun» jimligi qo'shiq ichiga tushmaydi (aks holda kupletlar orasida pauza qoladi)
    gap = TMP / "gap.mp3"
    subprocess.run(["ffmpeg", "-nostdin", "-y", "-loglevel", "error", "-f", "lavfi", "-i", "anullsrc=r=44100:cl=mono:d=1",
                    "-f", "lavfi", "-i", "sine=f=440:d=6", "-f", "lavfi", "-i", "anullsrc=r=44100:cl=mono:d=3.5",
                    "-filter_complex", "[0][1][2]concat=n=3:v=0:a=1", "-c:a", "libmp3lame", str(gap)], check=True)
    b, e = songs.audible_range(gap)
    assert 800 <= b <= 1100 and 6900 <= e <= 7300, (b, e)
    assert songs.audible_range(FAKE_MP3)[0] == 0

    # 10b) saqlangan naqorat rad etilsa (masalan, muddati o'tgan): to'lagan mijoz baribir oddiy to'liq qo'shiqni oladi
    songs.credits = no_credits  # yetarli kredit
    async def ref_rejected(plan, store=False, info=None):
        if any("song_id" in c for c in plan["chunks"]):
            raise songs.SongError("song not found")
        return await fake_compose(plan, store, info)
    songs.compose = ref_rejected
    u5 = sign({"id": 780, "first_name": "Vali"})
    async with Session() as s:
        s.add(User(tg_id=780, first_name="Vali", balance=100000))
        await s.commit()
    sid10 = (await songapi.song_create(body, x_init_data=u5))["id"]
    await songapi.song_preview(sid10, x_init_data=u5)
    await run_queue(bot)
    await songapi.song_pay(sid10, x_init_data=u5)
    await run_queue(bot)
    out = await songapi.song_get(sid10, x_init_data=u5)
    assert out["status"] == "ready" and len(out["variants"]) == 1, out
    assert len(calls["plans"][-1]["chunks"]) > 1 and not any("song_id" in c for c in calls["plans"][-1]["chunks"])
    songs.compose = fake_compose

    # 10c) Google Lyria: namuna — to'liq qo'shiqdan kesiladi, sotilganda aynan shu qo'shiq beriladi (qo'shimcha chaqiruv yo'q)
    from app import admin, lyria, store
    songs.compose = fake_compose
    sample = {"steps": [{"type": "model_output", "content": [
        {"type": "text", "text": "[Verse 1] 0:08\n[Chorus] 0:30"},
        {"type": "audio", "mime_type": "audio/mpeg", "data": __import__("base64").b64encode(FAKE_MP3.read_bytes()).decode()}]}]}
    raw, info = lyria.parse(sample)
    assert raw == FAKE_MP3.read_bytes() and lyria.chorus_seconds(info) == 30
    p_uz = lyria.prompt(songs.parse_lyrics(LYRICS), "Pop", ["modern pop"], "female", "Tug'ilgan kun", [], 95)
    assert "[Chorus]" in p_uz and "[Verse 1]" in p_uz and "O'zbek tilida" in p_uz and "quyoshim" in p_uz
    assert "Uzbek" in lyria.prompt(songs.parse_lyrics(LYRICS), "Pop", [], "male", "x", [], 95, "en")
    out = await admin.music_save(admin.MusicIn(provider="lyria", gemini_key="AIzaTESTkey_1234567890abcd", lang="uz"), uid=999)
    assert out["provider"] == "lyria" and out["lyria_key"] and "gemini_key" not in out and "AIza" not in str(out)
    try:
        await admin.music_save(admin.MusicIn(gemini_key="bad key with spaces!!"), uid=999)
        raise AssertionError("noto'g'ri kalit qabul qilindi")
    except HTTPException as e:
        assert e.status_code == 400
    lcalls = []
    async def fake_lyria(text):
        lcalls.append(text)
        return FAKE_MP3.read_bytes(), "[Chorus] 0:30"
    lyria.compose = fake_lyria
    songs.credits = empty_credits  # ElevenLabs krediti tugagan bo'lsa ham Lyria ishlayveradi
    u6 = sign({"id": 781, "first_name": "Laylo"})
    async with Session() as s:
        s.add(User(tg_id=781, first_name="Laylo", balance=100000))
        await s.commit()
    sid11 = (await songapi.song_create(body, x_init_data=u6))["id"]
    before = calls["compose"]
    out = await songapi.song_preview(sid11, x_init_data=u6)
    await run_queue(bot)
    out = await songapi.song_get(sid11, x_init_data=u6)
    assert out["status"] == "preview_ready" and len(lcalls) == 1 and calls["compose"] == before, out
    assert "O'zbek tilida" in lcalls[0] and "[Chorus]" in lcalls[0]
    assert 19 <= dur(MEDIA_DIR / Path(out["preview"]).name) <= 21
    async with Session() as s:
        song = await s.get(Song, sid11)
        assert song.plan["_provider"] == "lyria" and song.plan["_chorus_at"] == 30000 and len(song.variants) == 1
    await songapi.song_pay(sid11, x_init_data=u6)
    await run_queue(bot)
    out = await songapi.song_get(sid11, x_init_data=u6)
    assert out["status"] == "ready" and len(out["variants"]) == 1 and len(lcalls) == 1, "sotilganda Lyria qayta chaqirilmasligi kerak"
    async with Session() as s:
        rows = (await s.execute(sa_select(CostLog).where(CostLog.ref == f"song:{sid11}", CostLog.kind == "lyria"))).scalars().all()
        assert [r.purpose for r in rows] == ["song_preview"]
        from app import costs
        sm = await costs.summary(s, utcnow() - timedelta(days=1), utcnow() + timedelta(days=1))
        it = next(i for i in sm["items"] if i["purpose"] == "song_preview")
        assert it["som"] > 0
    # xizmatni qaytarish: ElevenLabs
    await admin.music_save(admin.MusicIn(provider="elevenlabs"), uid=999)
    assert await songs.provider() == "elevenlabs"
    songs.credits = no_credits

    # 11) she'r yozish kunlik limiti (Claude xarajati)
    songapi.settings.song_lyrics_per_day = 2
    u4 = sign({"id": 779, "first_name": "Ali"})
    await songapi.song_create(body, x_init_data=u4)
    await songapi.song_create(body, x_init_data=u4)
    try:
        await songapi.song_create(body, x_init_data=u4)
        raise AssertionError("kunlik she'r limiti ishlamadi")
    except HTTPException as e:
        assert e.status_code == 429

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
