"""Video navbati ishchisi (alohida servis): python -m app.renderer

render_jobs jadvalidan navbatdagi ishni oladi, MP4 yasaydi va botga yuboradi.
Mehmonlar uchun shaxsiy videolarda faqat 1-sahna (konvertdagi ism) har kim uchun alohida,
qolgan 15 soniya bir marta yasalib, keyingi mehmonlarda qayta ishlatiladi.
"""

import asyncio
import io
import logging
import time
from pathlib import Path

from aiogram import Bot
from aiogram.client.default import DefaultBotProperties
from aiogram.enums import ParseMode
from PIL import Image
from sqlalchemy import func, select, update

from . import video, videobot
from .billing import refund_job
from .config import VIDEO_DIR, settings
from .db import Guest, RenderJob, Session, init_db, utcnow
from .i18n import tr
from .render_core import Renderer, concat_with_audio, encode

log = logging.getLogger("renderer")

SCENE1_MS = 5000
BASE_DIR = VIDEO_DIR / "base"
BASE_DIR.mkdir(exist_ok=True)


async def claim() -> RenderJob | None:
    """Navbatdagi eng eski ish (oddiy videolar mehmon videolaridan oldin). Boshqa ishchi olsa — keyingisi."""
    async with Session() as s:
        for _ in range(5):
            job_id = await s.scalar(
                select(RenderJob.id).where(RenderJob.status == "queued")
                .order_by(RenderJob.guest_id.is_not(None), RenderJob.id).limit(1))
            if not job_id:
                return None
            res = await s.execute(
                update(RenderJob).where(RenderJob.id == job_id, RenderJob.status == "queued")
                .values(status="rendering", started_at=utcnow(), progress=0))
            await s.commit()
            if res.rowcount == 1:
                return await s.get(RenderJob, job_id)
    return None


async def set_progress(job_id: int, pct: int) -> None:
    async with Session() as s:
        await s.execute(update(RenderJob).where(RenderJob.id == job_id).values(progress=pct))
        await s.commit()


async def edit_status(bot: Bot, job: RenderJob, text: str) -> None:
    if not job.status_msg_id:
        return
    try:
        await bot.edit_message_text(text, chat_id=job.owner_id, message_id=job.status_msg_id)
    except Exception:
        pass


def music_spec(job: RenderJob) -> dict | None:
    m = job.payload.get("music") or {}
    path = m.get("file")
    if not path:
        return None
    from .config import MEDIA_DIR
    full = (MEDIA_DIR / path.removeprefix("/media/")).resolve()
    if MEDIA_DIR.resolve() not in full.parents or not full.is_file():
        return None
    return {"path": str(full), "start": m.get("start") or 0}


def base_key(job: RenderJob) -> str:
    """Mehmonga bog'liq bo'lmagan qism (5-20 s) kaliti: konvertdagi ism olib tashlangan payload."""
    page = dict(job.payload["page"])
    page["t"] = {**page["t"], "dear": "", "guest": ""}
    page["f"] = {**page["f"], "guest": False}
    return video.render_hash(page, None)


async def make_cover(r: Renderer, html: str, out: Path) -> None:
    """Muqova (Kartochka sahnasi) va Telegram uchun kichik rasm (320 px gacha)."""
    data = await r.still(html, 7500, scale=2, quality=88)
    out.with_suffix(".cover.jpg").write_bytes(data)
    im = Image.open(io.BytesIO(data)).convert("RGB")
    im.thumbnail((180, 320))
    im.save(out.with_suffix(".thumb.jpg"), "JPEG", quality=85)


async def render_job(r: Renderer, bot: Bot, job: RenderJob) -> Path:
    page = job.payload["page"]
    html = video.page_html(job.design, page, mode="render")
    fps, scale, seconds = settings.video_fps, settings.video_scale, settings.video_seconds
    out = VIDEO_DIR / f"{job.id}-{job.hash[:8]}.mp4"
    music = music_spec(job)
    last = {"pct": -1, "edit": 0.0}

    async def progress(done: int, total: int, base_pct: int = 0, span: int = 100) -> None:
        pct = base_pct + int(span * done / total)
        if pct >= last["pct"] + 5:
            last["pct"] = pct
            await set_progress(job.id, pct)
            if not job.guest_id and time.time() - last["edit"] > 4:
                last["edit"] = time.time()
                lang = await videobot.user_lang(job.owner_id)
                await edit_status(bot, job, tr(lang, "bot.v_progress", pct=pct))

    if job.guest_id:
        base = BASE_DIR / f"{base_key(job)}.mp4"
        seg = VIDEO_DIR / f"{job.id}-s1.mp4"
        if not base.exists():
            tmp = base.with_suffix(".part.mp4")

            async def base_frames(sink):
                await r.frames(html, SCENE1_MS, seconds * 1000, fps, scale, sink,
                               on_frame=lambda d, t: progress(d, t, 0, 70))
            await encode(base_frames, tmp, fps, seconds - SCENE1_MS / 1000, with_audio=False)
            tmp.rename(base)

        async def s1_frames(sink):
            await r.frames(html, 0, SCENE1_MS, fps, scale, sink, on_frame=lambda d, t: progress(d, t, 70, 30))
        await encode(s1_frames, seg, fps, SCENE1_MS / 1000, with_audio=False)
        await concat_with_audio([seg, base], out, seconds, music)
        seg.unlink(missing_ok=True)
    else:
        async def frames(sink):
            await r.frames(html, 0, seconds * 1000, fps, scale, sink, on_frame=progress)
        await encode(frames, out, fps, seconds, music)
    await make_cover(r, html, out)
    return out


async def guest_batch_status(bot: Bot, job: RenderJob) -> None:
    """Mehmon videolari to'plami uchun bitta holat xabari: «23/120 tayyor»."""
    async with Session() as s:
        total = await s.scalar(select(func.count()).select_from(RenderJob).where(
            RenderJob.site_id == job.site_id, RenderJob.status_msg_id == job.status_msg_id, RenderJob.guest_id.is_not(None)))
        done = await s.scalar(select(func.count()).select_from(RenderJob).where(
            RenderJob.site_id == job.site_id, RenderJob.status_msg_id == job.status_msg_id,
            RenderJob.guest_id.is_not(None), RenderJob.status.in_(("done", "failed"))))
    lang = await videobot.user_lang(job.owner_id)
    key = "bot.guests_done" if done >= total else "bot.guests_progress"
    await edit_status(bot, job, tr(lang, key, done=done, total=total))


async def refresh_queue_messages(bot: Bot) -> None:
    """Navbat siljiganda kutayotganlarning «N-o'rin» xabarini yangilaydi."""
    async with Session() as s:
        jobs = (await s.execute(select(RenderJob).where(RenderJob.status == "queued", RenderJob.guest_id.is_(None))
                                .order_by(RenderJob.id).limit(15))).scalars().all()
    for j in jobs:
        lang = await videobot.user_lang(j.owner_id)
        await edit_status(bot, j, await videobot.status_text(j, lang))


async def process(r: Renderer, bot: Bot, job: RenderJob) -> None:
    started = time.time()
    try:
        out = await render_job(r, bot, job)
    except Exception as e:
        log.exception("Render xatosi: job %s", job.id)
        async with Session() as s:
            db_job = await s.get(RenderJob, job.id)
            db_job.status = "failed"
            db_job.error = str(e)[:500]
            db_job.finished_at = utcnow()
            await refund_job(s, db_job)
            await s.commit()
        lang = await videobot.user_lang(job.owner_id)
        if not job.guest_id:
            await edit_status(bot, job, tr(lang, "bot.v_failed"))
        return
    async with Session() as s:
        db_job = await s.get(RenderJob, job.id)
        db_job.status = "done"
        db_job.progress = 100
        db_job.file_path = str(out)
        db_job.finished_at = utcnow()
        if db_job.guest_id:
            g = await s.get(Guest, db_job.guest_id)
            if g:
                g.job_id = db_job.id
        await s.commit()
        job = db_job
    log.info("Video tayyor: job %s, %.1f s", job.id, time.time() - started)
    await videobot.deliver(bot, job)
    if job.guest_id:
        await guest_batch_status(bot, job)


def cleanup() -> None:
    """Eski video fayllarni o'chiradi (Telegram file_id qoladi, qayta yuborish ishlayveradi)."""
    limit = time.time() - settings.video_keep_days * 86400
    for p in list(VIDEO_DIR.glob("*.mp4")) + list(VIDEO_DIR.glob("*.jpg")) + list(BASE_DIR.glob("*.mp4")):
        if p.stat().st_mtime < limit:
            p.unlink(missing_ok=True)


async def main() -> None:
    logging.basicConfig(level=logging.INFO)
    await init_db()
    async with Session() as s:  # to'xtab qolgan ishlar qayta navbatga
        await s.execute(update(RenderJob).where(RenderJob.status == "rendering").values(status="queued", progress=0))
        await s.commit()
    bot = Bot(settings.bot_token, default=DefaultBotProperties(parse_mode=ParseMode.HTML))
    videobot.BOT = bot
    r = Renderer()
    await r.start()
    log.info("Renderer ishga tushdi: %sx%s, %s fps", 360 * settings.video_scale, 640 * settings.video_scale, settings.video_fps)
    last_clean = 0.0
    try:
        while True:
            job = await claim()
            if not job:
                if time.time() - last_clean > 3600:
                    last_clean = time.time()
                    cleanup()
                await asyncio.sleep(1.5)
                continue
            await process(r, bot, job)
            if not job.guest_id:
                await refresh_queue_messages(bot)
    finally:
        await r.stop()
        await bot.session.close()


if __name__ == "__main__":
    asyncio.run(main())
