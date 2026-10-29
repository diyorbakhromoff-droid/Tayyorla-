"""Video taklifnoma: obunadan keyin videoni olish va inline ulashish."""

import logging

from aiogram import F, Router
from aiogram.types import CallbackQuery, InlineQuery, InlineQueryResultCachedVideo
from sqlalchemy import select

from .. import video, videobot
from ..db import RenderJob, Session
from ..i18n import tr

log = logging.getLogger(__name__)
router = Router()


@router.callback_query(F.data.startswith("vsub:"))
async def subscribed(cb: CallbackQuery):
    job_id = int(cb.data.split(":")[1])
    lang = await videobot.user_lang(cb.from_user.id)
    async with Session() as s:
        job = await s.get(RenderJob, job_id)
    if not job or job.owner_id != cb.from_user.id:
        return await cb.answer()
    if job.status != "done":
        return await cb.answer(tr(lang, "bot.v_not_ready"), show_alert=True)
    if not await videobot.is_subscribed(cb.bot, cb.from_user.id):
        return await cb.answer(tr(lang, "bot.not_subscribed"), show_alert=True)
    await cb.answer("✅")
    try:
        await cb.message.delete()
    except Exception:
        pass
    await videobot.send_video(cb.bot, job)


@router.inline_query()
async def inline_share(q: InlineQuery):
    """«📤 Ulashish»: tanlangan chatga video va izoh yuboriladi. Bo'sh so'rovda — oxirgi videolar."""
    text = (q.query or "").strip()
    async with Session() as s:
        stmt = select(RenderJob).where(RenderJob.owner_id == q.from_user.id, RenderJob.tg_file_id != "")
        if text.startswith("v") and text[1:].isdigit():
            stmt = stmt.where(RenderJob.id == int(text[1:]))
        jobs = (await s.execute(stmt.order_by(RenderJob.id.desc()).limit(20))).scalars().all()
    results = []
    for j in jobs:
        page = j.payload.get("page") or {}
        t = page.get("t") or {}
        guest = j.payload.get("guest")
        results.append(InlineQueryResultCachedVideo(
            id=f"v{j.id}", video_file_id=j.tg_file_id, title=f"{t.get('event', '')} — {guest or t.get('names_line', '')}"[:60],
            description=t.get("date", ""), caption=video.caption(page, paid=not j.free, guest=guest), parse_mode="HTML"))
    await q.answer(results, cache_time=0, is_personal=True)
