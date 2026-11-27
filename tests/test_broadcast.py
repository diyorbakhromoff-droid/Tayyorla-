"""Admin tarqatmasi: rasm/video yuklash (file_id), izoh chegarasi, rasm/video/matn bilan yuborish.

Ishga tushirish: python -m tests.test_broadcast
"""

import asyncio
import io
import os
import tempfile
from types import SimpleNamespace

os.environ["DATABASE_URL"] = f"sqlite+aiosqlite:///{tempfile.mkdtemp()}/bc.db"
os.environ["BOT_TOKEN"] = "123456:TEST"
os.environ["ADMIN_IDS"] = "1"

from fastapi import HTTPException, UploadFile  # noqa: E402
from starlette.datastructures import Headers  # noqa: E402

from app import admin, videobot  # noqa: E402
from app.db import Session, User, init_db  # noqa: E402


class Bot:
    def __init__(self):
        self.out = []

    async def send_photo(self, chat_id, photo, caption=None, **kw):
        self.out.append(("photo", chat_id, photo if isinstance(photo, str) else "upload", caption))
        return SimpleNamespace(photo=[SimpleNamespace(file_id="small"), SimpleNamespace(file_id="PHOTO_ID")])

    async def send_video(self, chat_id, video, caption=None, **kw):
        self.out.append(("video", chat_id, video if isinstance(video, str) else "upload", caption))
        return SimpleNamespace(video=SimpleNamespace(file_id="VIDEO_ID"), document=None, animation=None)

    async def send_message(self, chat_id, text, **kw):
        self.out.append(("text", chat_id, None, text))
        self.kb = kw.get("reply_markup")


def up(name, ct, size):
    return UploadFile(io.BytesIO(b"x" * size), filename=name, headers=Headers({"content-type": ct}))


async def main() -> None:
    await init_db()
    async with Session() as s:
        s.add_all([User(tg_id=1, first_name="Admin"), User(tg_id=20, first_name="A"), User(tg_id=21, first_name="B")])
        await s.commit()
    bot = Bot()
    videobot.BOT = bot

    r = await admin.broadcast_media(up("a.jpg", "image/jpeg", 1000), uid=1)
    assert r == {"media": "PHOTO_ID", "kind": "photo"} and bot.out[-1][:3] == ("photo", 1, "upload")
    r = await admin.broadcast_media(up("a.mp4", "video/mp4", 1000), uid=1)
    assert r == {"media": "VIDEO_ID", "kind": "video"}
    for f, code in [(up("a.pdf", "application/pdf", 10), 400), (up("b.jpg", "image/jpeg", 11 * 1024 * 1024), 413)]:
        try:
            await admin.broadcast_media(f, uid=1)
            raise AssertionError("qabul qilinmasligi kerak edi")
        except HTTPException as e:
            assert e.status_code == code

    # izoh 1024 belgidan oshsa — rad etiladi; rasmsiz va matnsiz — rad etiladi
    for body in [admin.BroadcastIn(segment="all", text="x" * 1100, media="PHOTO_ID", kind="photo"), admin.BroadcastIn(segment="all")]:
        try:
            await admin.broadcast_start(body, uid=1)
            raise AssertionError
        except HTTPException as e:
            assert e.status_code == 400

    bot.out.clear()
    admin.BROADCAST.update(sent=0, failed=0, blocked=0)
    await admin._run_broadcast([20, 21], "Salom", False, "PHOTO_ID", "photo")
    assert [o[0] for o in bot.out] == ["photo", "photo"] and bot.out[0][2:] == ("PHOTO_ID", "Salom")
    bot.out.clear()
    await admin._run_broadcast([20], "", False, "VIDEO_ID", "video")
    assert bot.out == [("video", 20, "VIDEO_ID", None)]
    bot.out.clear()
    await admin._run_broadcast([20], "Faqat matn", False)
    assert bot.out == [("text", 20, None, "Faqat matn")]
    assert admin.BROADCAST["sent"] == 4 and admin.BROADCAST["failed"] == 0

    # tugma: yo'q / «Ilovani ochish» / «Qo'shiq tayyorlash» (ilovada yangi qo'shiq oynasi), yozuvi o'zgartiriladi
    from app.config import settings
    assert admin.broadcast_markup("song") is None, "Telegram web_app faqat https bilan"
    old, settings.base_url = settings.base_url, "https://tayyorla.test"
    try:
        btn = lambda *a: admin.broadcast_markup(*a).inline_keyboard[0][0]  # noqa: E731
        assert (btn(True).text, btn(True).web_app.url) == ("✨ Ilovani ochish", "https://tayyorla.test/app")
        assert (btn("app").text, btn("app").web_app.url) == ("✨ Ilovani ochish", "https://tayyorla.test/app")
        assert (btn("song").text, btn("song").web_app.url) == ("🎵 Qo‘shiq tayyorlash", "https://tayyorla.test/app?song=new")
        assert btn("song", "  🎵 Qo‘shiq   yaratish ").text == "🎵 Qo‘shiq yaratish" and btn("song", "x" * 99).text == "x" * 64
        assert admin.broadcast_markup(False) is None and admin.broadcast_markup("none") is None and admin.broadcast_markup("") is None
        bot.out.clear()
        await admin._run_broadcast([20], "Aksiya!", "song", button_text="🎵 Qo‘shiq yaratish")
        assert bot.out == [("text", 20, None, "Aksiya!")]
        assert bot.kb.inline_keyboard[0][0].text == "🎵 Qo‘shiq yaratish" and bot.kb.inline_keyboard[0][0].web_app.url.endswith("/app?song=new")
        await admin._run_broadcast([20], "Tugmasiz", "none")
        assert bot.kb is None
        try:
            await admin.broadcast_start(admin.BroadcastIn(segment="me", text="x", button="sayt"), uid=1)
            raise AssertionError("noma'lum tugma qabul qilinmasligi kerak")
        except HTTPException as e:
            assert e.status_code == 400
        # JSON dan: eski so'rov (true/false) ham, yangi ("song") ham qabul qilinadi
        assert admin.BroadcastIn.model_validate({"segment": "all", "button": True}).button is True
        assert admin.BroadcastIn.model_validate({"segment": "all", "button": "song", "button_text": "🎵"}).button == "song"
    finally:
        settings.base_url = old
    print("test_broadcast: OK")


if __name__ == "__main__":
    asyncio.run(main())
