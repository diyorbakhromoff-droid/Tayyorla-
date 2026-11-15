"""Sinov: 20 soniyalik naqoratdan (namuna) o'sha kuy va ovozda to'liq qo'shiq yasash mumkinmi (ElevenLabs inpainting).

1) Faqat naqorat tayyorlanadi va ElevenLabs'da saqlanadi (store_for_inpainting).
2) To'liq qo'shiq: naqorat o'sha yozuvning o'zi (o'zgarmagan holda) qo'yiladi, qolgan qismlar shu naqoratga tayanib tayyorlanadi.
Ikkala fayl adminlarga botda yuboriladi, har bosqichda qancha kredit ketgani yoziladi.
Hisob inpaintingga ruxsat bermasa, xato matni yuboriladi. Hech bir so'rov qayta yuborilmaydi.

Ishga tushirish (serverda):  docker compose exec app python -m scripts.inpainttest
Muayyan qo'shiq bilan:       docker compose exec app python -m scripts.inpainttest 12
"""

import asyncio
import json
import subprocess
import sys
from pathlib import Path

import aiohttp
from aiogram import Bot
from aiogram.types import FSInputFile
from sqlalchemy import select

from app import songs
from app.config import MEDIA_DIR, settings
from app.db import Session, Song

API = "https://api.elevenlabs.io/v1/music"
OUT = MEDIA_DIR.parent / "inpainttest"

SAMPLE = """[1-kuplet]
Onajonim, quyoshim, mehribonim
Sen borsan-u yorug'dir har tongim
Qo'llaring iliq, so'zlaring shirin
Sen bilan to'kis bu hayotim

[Naqorat]
Onajon, onajon, jonim onajon
Sen menga eng aziz, eng mehribon
Duolaring bilan yashayman shodon
Onajon, onajon, jonim onajon

[2-kuplet]
Bolaligim o'tdi bag'ringda
Ertaklaring qoldi yodimda
Har bir yutug'imning ortida
Sening mehring bor, onajonim

[Naqorat]
Onajon, onajon, jonim onajon
Sen menga eng aziz, eng mehribon
Duolaring bilan yashayman shodon
Onajon, onajon, jonim onajon
"""


def say(msg: str) -> None:
    print(msg, flush=True)


async def used_credits() -> int | None:
    c = await songs.credits(force=True)
    return c["used"] if c else None


def seconds_of(path: Path) -> float:
    try:
        out = subprocess.run(["ffprobe", "-v", "error", "-show_entries", "format=duration", "-of", "csv=p=0", str(path)],
                             capture_output=True, text=True, timeout=30).stdout.strip()
        return float(out)
    except Exception:
        return 0.0


async def call(http: aiohttp.ClientSession, body: dict) -> tuple[int, bytes, dict]:
    async with http.post(API, params={"output_format": "mp3_48000_192"}, json=body,
                         headers={"xi-api-key": settings.elevenlabs_api_key, "accept": "audio/mpeg"}) as r:
        return r.status, await r.read(), dict(r.headers)


async def notify(bot: Bot | None, text: str, files: list[tuple[Path, str]] = ()) -> None:
    say(text)
    if not bot:
        return
    for admin in settings.admins:
        try:
            await bot.send_message(admin, text)
            for path, title in files:
                await bot.send_audio(admin, FSInputFile(path, filename=path.name), title=title, performer="Tayyorla sinov")
        except Exception as e:
            say(f"Adminga yuborib bo'lmadi ({admin}): {e}")


async def main() -> None:
    if not settings.elevenlabs_api_key:
        return say("ELEVENLABS kaliti sozlanmagan.")
    bot = Bot(settings.bot_token) if settings.bot_token else None
    try:
        await run(bot)
    finally:
        if bot:
            await bot.session.close()


async def run(bot: Bot | None) -> None:
    # she'r: berilgan raqamli qo'shiq, bo'lmasa oxirgi she'ri bor qo'shiq, bo'lmasa namuna matn
    song = None
    async with Session() as s:
        if len(sys.argv) > 1 and sys.argv[1].isdigit():
            song = await s.get(Song, int(sys.argv[1]))
        if not song:
            song = (await s.execute(select(Song).where(Song.lyrics != "").order_by(Song.id.desc()).limit(1))).scalar_one_or_none()
    lyrics, style, voice, tags = (song.lyrics, song.style, song.voice, song.tags or []) if song else (SAMPLE, "pop", "female", [])
    title = (song.title if song else "") or "Sinov"
    plan, chorus_at, chorus_len = songs.build_plan(songs.parse_lyrics(lyrics), style, voice, tags)
    chunks = plan["chunks"]
    starts, t = [], 0
    for c in chunks:
        starts.append(t)
        t += c["duration_ms"]
    chorus_idx = [i for i, c in enumerate(chunks) if c["text"] == chunks[starts.index(chorus_at)]["text"]] if chorus_at in starts else []
    if not chorus_idx:
        return await notify(bot, "Sinov: she'rda naqorat topilmadi, boshqa qo'shiq raqamini bering.")
    chorus = chunks[chorus_idx[0]]
    OUT.mkdir(parents=True, exist_ok=True)
    say(f"Qo'shiq: «{title}» ({'#' + str(song.id) if song else 'namuna matn'}), {len(chunks)} bo'lim, naqorat {chorus_len / 1000:.0f} s, "
        f"to'liq {t / 1000:.0f} s")

    timeout = aiohttp.ClientTimeout(total=900)
    async with aiohttp.ClientSession(timeout=timeout) as http:
        # 1) namuna: faqat naqorat, saqlab qo'yiladi
        before = await used_credits()
        status, data, headers = await call(http, {"composition_plan": {"chunks": [chorus]}, "model_id": settings.song_model,
                                                  "store_for_inpainting": True})
        after = await used_credits()
        cost1 = (after - before) if before is not None and after is not None else None
        if status != 200:
            return await notify(bot, f"❌ Sinov: naqoratni saqlab tayyorlab bo'lmadi (HTTP {status}).\n\n{data[:600].decode(errors='replace')}\n\n"
                                     "Agar xatoda ruxsat/enterprise haqida gap bo'lsa — hisobingizda inpainting yoqilmagan.")
        demo = OUT / f"{title[:30]}-1-namuna.mp3".replace("/", "-")
        demo.write_bytes(data)
        song_id = headers.get("song-id") or headers.get("Song-Id")
        if not song_id:
            return await notify(bot, "⚠️ Sinov: naqorat tayyorlandi, lekin ElevenLabs saqlangan qo'shiq raqamini (song-id) qaytarmadi — "
                                     f"hisobda inpainting yoqilmagan bo'lishi mumkin.\nKredit: {cost1}\nSarlavhalar: "
                                     + json.dumps({k: v for k, v in headers.items() if 'key' not in k.lower()})[:800],
                                [(demo, f"{title} — naqorat")])
        demo_ms = int(seconds_of(demo) * 1000) or chorus_len
        say(f"1) Naqorat tayyor: {demo_ms / 1000:.1f} s, song-id={song_id}, kredit={cost1}")

        # 2) to'liq qo'shiq: har bir naqorat — saqlangan yozuvning o'zi, qolganlari shunga tayanib
        ref = {"song_id": song_id, "range": {"start_ms": 0, "end_ms": demo_ms}}
        full_chunks, conditioned = [], False
        for i, c in enumerate(chunks):
            if i in chorus_idx:
                full_chunks.append(dict(ref))
                continue
            c = dict(c)
            if not conditioned:
                c["conditioning_ref"] = {"song_id": song_id, "range": {"start_ms": 0, "end_ms": min(demo_ms, 30000)}}
                c["condition_strength"] = "high"
                conditioned = True
            full_chunks.append(c)
        before = await used_credits()
        status, data, headers = await call(http, {"composition_plan": {"chunks": full_chunks}, "model_id": settings.song_model})
        after = await used_credits()
        cost2 = (after - before) if before is not None and after is not None else None
        if status != 200:
            return await notify(bot, f"❌ Sinov: to'liq qo'shiqni yasab bo'lmadi (HTTP {status}).\n\n{data[:600].decode(errors='replace')}\n\n"
                                     f"Naqorat krediti: {cost1}", [(demo, f"{title} — naqorat")])
        full = OUT / f"{title[:30]}-2-toliq.mp3".replace("/", "-")
        full.write_bytes(data)
        say(f"2) To'liq qo'shiq tayyor: {seconds_of(full):.1f} s, kredit={cost2}")

    total = (cost1 or 0) + (cost2 or 0) if cost1 is not None and cost2 is not None else None
    await notify(bot, (f"🎧 Inpainting sinovi: «{title}»\n\n"
                       f"1) Namuna (faqat naqorat, {demo_ms / 1000:.0f} s): {cost1 if cost1 is not None else '?'} kredit\n"
                       f"2) To'liq qo'shiq ({seconds_of(full):.0f} s): {cost2 if cost2 is not None else '?'} kredit\n"
                       f"Jami: {total if total is not None else '?'} kredit\n\n"
                       "Tinglang: to'liq qo'shiqdagi naqorat namunadagi bilan bir xil, kupletlardagi ovoz va kuy unga mos tushyaptimi?"),
                 [(demo, f"{title} — 1) namuna (naqorat)"), (full, f"{title} — 2) to'liq")])


if __name__ == "__main__":
    asyncio.run(main())
