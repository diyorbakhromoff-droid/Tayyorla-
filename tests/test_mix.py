"""Ovoz va musiqa balansi: namuna va to'liq qo'shiqqa ishlov, mavjud qo'shiqlarni qayta ishlash (bir marta, URL o'zgarmaydi)."""
import asyncio
import os
import subprocess
import tempfile
from pathlib import Path

os.environ["DATABASE_URL"] = f"sqlite+aiosqlite:///{tempfile.mkdtemp()}/mix.db"
os.environ["BOT_TOKEN"] = "123456:TEST"
os.environ["ADMIN_IDS"] = "999"

from app import admin, songs, store  # noqa: E402
from app.config import MEDIA_DIR  # noqa: E402
from app.db import Session, Song, User, init_db  # noqa: E402

TMP = Path(tempfile.mkdtemp())


def tone(path: Path, sec: int = 12) -> None:
    subprocess.run(["ffmpeg", "-nostdin", "-y", "-loglevel", "error", "-f", "lavfi", "-i", f"sine=f=440:d={sec}",
                    "-ac", "2", "-c:a", "libmp3lame", "-b:a", "128k", str(path)], check=True)


async def main():
    await init_db()
    songs.PRIVATE_DIR.mkdir(parents=True, exist_ok=True)
    MEDIA_DIR.mkdir(parents=True, exist_ok=True)
    demo, full, pv, pub = (songs.PRIVATE_DIR / "t-mix-clip.mp3", songs.PRIVATE_DIR / "t-mix-full.mp3",
                           songs.PRIVATE_DIR / "t-mix-pv.mp3", MEDIA_DIR / "songtmix.mp3")
    for p in (demo, full, pv, pub):
        tone(p)
    async with Session() as s:
        s.add(User(tg_id=1, first_name="A"))
        s.add(Song(id=1, owner_id=1, title="Bir", status="preview_ready", lyrics="x", preview="pv:t-mix-pv.mp3",
                   plan={"_demo": {"private": str(demo)}, "_chorus_at": 0}))
        s.add(Song(id=2, owner_id=1, title="Ikki", status="ready", paid=True, lyrics="x", preview="",
                   variants=[{"private": str(full), "file": "/media/songtmix.mp3"}], plan={}))
        await s.commit()

    # sozlama: standart «me'yorida», admin o'zgartira oladi
    assert await songs.mix_level() == "soft"
    info = await admin.music_save(admin.MusicIn(mix="strong"), uid=999)
    assert info["mix"] == "strong" and await songs.mix_level() == "strong"
    await admin.music_save(admin.MusicIn(mix="soft"), uid=999)

    before_pv, before_pub = pv.read_bytes(), pub.read_bytes()
    await songs.remix_all()
    st = await songs.remix_state()
    assert st["done"] == 2 and st["total"] == 2 and not st["running"] and st["failed"] == 0, st
    async with Session() as s:
        a, b = await s.get(Song, 1), await s.get(Song, 2)
        assert a.plan["_mix_pv"] == "soft" and b.plan["_mix_full"] == "soft"
        assert b.variants[0]["file"] == "/media/songtmix.mp3", "havola o'zgarmaydi"
    assert pv.read_bytes() != before_pv and pub.read_bytes() != before_pub
    # ikkinchi marta — o'sha darajada qayta ishlanmaydi (fayl o'zgarmaydi)
    after = pub.read_bytes()
    await songs.remix_all()
    assert pub.read_bytes() == after
    assert full.exists() and demo.exists(), "asl (ishlovsiz) manba saqlanadi"
    for p in (demo, full, pv, pub):
        p.unlink(missing_ok=True)
    store.forget()
    print("✅ Ovoz va musiqa balansi tekshiruvi o'tdi")


asyncio.run(main())
