"""Video bilan bog'liq bot amallari: obuna tekshiruvi, videoni yuborish, holat xabarlari.

Bu yordamchilarni bot (app.main), API va renderer servisi birga ishlatadi.
"""

import logging
import time
from pathlib import Path

from aiogram import Bot
from aiogram.types import CopyTextButton, FSInputFile, InlineKeyboardMarkup, WebAppInfo
from aiogram.utils.keyboard import InlineKeyboardBuilder
from sqlalchemy import func, select

from . import video
from .config import settings
from .db import RenderJob, Session, Site, User
from .i18n import tr

log = logging.getLogger(__name__)

BOT: Bot | None = None  # main.py yoki renderer o'rnatadi
_SUBSCRIBED: dict[int, float] = {}


def money(n: int) -> str:
    return f"{n:,}".replace(",", " ") + " so‘m"


async def user_lang(uid: int) -> str:
    async with Session() as s:
        u = await s.get(User, uid)
    return (u.lang or "uz") if u else "uz"


async def is_subscribed(bot: Bot, uid: int) -> bool:
    """Bepul videoni olish sharti: kanal a'zosi. Kanal sozlanmagan yoki tekshirib bo'lmasa — ruxsat."""
    channel = settings.channel_username
    if not channel:
        return True
    if _SUBSCRIBED.get(uid, 0) > time.time():
        return True
    try:
        m = await bot.get_chat_member(channel, uid)
    except Exception as e:  # bot kanalda admin bo'lmasa a'zolikni ko'ra olmaydi
        log.warning("Obunani tekshirib bo'lmadi (%s): %s", channel, e)
        return True
    ok = m.status in ("creator", "administrator", "member") or (m.status == "restricted" and getattr(m, "is_member", False))
    if ok:
        _SUBSCRIBED[uid] = time.time() + 600
    return ok


def app_url(**params) -> str:
    q = "&".join(f"{k}={v}" for k, v in params.items() if v)
    return f"{settings.base_url}/app" + (f"?{q}" if q else "")


def sub_keyboard(job_id: int, lang: str) -> InlineKeyboardMarkup:
    kb = InlineKeyboardBuilder()
    kb.button(text=tr(lang, "bot.btn_channel"), url=settings.channel_link)
    kb.button(text=tr(lang, "bot.btn_subscribed"), callback_data=f"vsub:{job_id}")
    kb.adjust(1)
    return kb.as_markup()


def video_keyboard(job: RenderJob, site: Site | None, lang: str) -> InlineKeyboardMarkup:
    kb = InlineKeyboardBuilder()
    kb.button(text=tr(lang, "bot.btn_share"), switch_inline_query=f"v{job.id}")
    p = job.payload.get("page") or {}
    card = (p.get("t") or {}).get("card_number")
    if (p.get("f") or {}).get("toyona") and card:
        kb.button(text=tr(lang, "bot.btn_copy_card"), copy_text=CopyTextButton(text=card.replace(" ", "")))
    https = settings.base_url.startswith("https://")
    if site and https and not job.guest_id:
        if site.config.get("site_slug"):
            kb.button(text=tr(lang, "bot.btn_open_site"), url=f"{settings.base_url}/s/{site.config['site_slug']}")
        else:
            kb.button(text=tr(lang, "bot.btn_site"), web_app=WebAppInfo(url=app_url(tosite=site.slug)))
        kb.button(text=tr(lang, "bot.btn_guests"), web_app=WebAppInfo(url=app_url(ev=site.slug)))
    kb.adjust(1)
    return kb.as_markup()


def thumb_path(job: RenderJob) -> Path | None:
    if not job.file_path:
        return None
    p = Path(job.file_path).with_suffix(".thumb.jpg")
    return p if p.exists() else None


def cover_path(job: RenderJob) -> Path | None:
    if not job.file_path:
        return None
    p = Path(job.file_path).with_suffix(".cover.jpg")
    return p if p.exists() else None


async def send_video(bot: Bot, job: RenderJob, chat_id: int | None = None) -> bool:
    """Tayyor videoni egasiga (yoki chat_id ga) yuboradi; file_id saqlanadi — qayta yuborishda render yo'q."""
    async with Session() as s:
        db_job = await s.get(RenderJob, job.id)
        site = await s.get(Site, db_job.site_id) if db_job.site_id else None
        user = await s.get(User, db_job.owner_id)
        lang = (user.lang if user else "") or "uz"
        page = db_job.payload.get("page") or {}
        guest = db_job.payload.get("guest")
        cap = video.caption(page, paid=not db_job.free, guest=guest)
        if guest:
            cap = f"👤 <b>{tr(lang, 'bot.guest_caption', name=guest)}</b>\n\n" + cap
        media = db_job.tg_file_id or (FSInputFile(db_job.file_path) if db_job.file_path and Path(db_job.file_path).exists() else None)
        if media is None:
            return False
        scale = settings.video_scale
        thumb = thumb_path(db_job) if not db_job.tg_file_id else None
        cover = cover_path(db_job) if not db_job.tg_file_id else None
        try:
            msg = await bot.send_video(
                chat_id or db_job.owner_id, video=media, caption=cap, parse_mode="HTML", supports_streaming=True,
                width=360 * scale, height=640 * scale, duration=settings.video_seconds,
                thumbnail=FSInputFile(thumb) if thumb else None, cover=FSInputFile(cover) if cover else None,
                reply_markup=video_keyboard(db_job, site, lang))
        except Exception:
            log.exception("Videoni yuborib bo'lmadi: job %s", db_job.id)
            return False
        if msg.video and not db_job.tg_file_id:
            db_job.tg_file_id = msg.video.file_id
        if chat_id is None or chat_id == db_job.owner_id:
            db_job.delivered = True
        await s.commit()
        if db_job.status_msg_id and not db_job.guest_id:
            try:
                await bot.delete_message(db_job.owner_id, db_job.status_msg_id)
            except Exception:
                pass
        if db_job.free and not db_job.guest_id and (chat_id is None or chat_id == db_job.owner_id):
            from .billing import quota
            q = await quota(s, user) if user else {"free_left": 0}
            note = tr(lang, "bot.free_left", n=q["free_left"]) if q["free_left"] else tr(lang, "bot.free_none", price=money(settings.video_price))
            try:
                await bot.send_message(db_job.owner_id, note)
            except Exception:
                pass
    return True


async def deliver(bot: Bot, job: RenderJob) -> None:
    """Render tugagach: bepul video — avval obuna; pullik va mehmon videolari — darhol."""
    lang = await user_lang(job.owner_id)
    if job.free and not job.guest_id and not await is_subscribed(bot, job.owner_id):
        try:
            await bot.send_message(job.owner_id, tr(lang, "bot.v_ready_sub", channel=settings.channel_username),
                                   reply_markup=sub_keyboard(job.id, lang))
        except Exception:
            log.exception("Obuna xabarini yuborib bo'lmadi")
        if job.status_msg_id:
            try:
                await bot.delete_message(job.owner_id, job.status_msg_id)
            except Exception:
                pass
        return
    await send_video(bot, job)


async def queue_position(job_id: int) -> int:
    """Navbatdagi o'rni: oldindagi kutayotgan oddiy videolar + hozir tayyorlanayotganlar + 1."""
    async with Session() as s:
        ahead = await s.scalar(select(func.count()).select_from(RenderJob).where(
            RenderJob.status == "queued", RenderJob.id < job_id, RenderJob.guest_id.is_(None)))
        busy = await s.scalar(select(func.count()).select_from(RenderJob).where(RenderJob.status == "rendering"))
    return (ahead or 0) + (busy or 0) + 1


async def status_text(job: RenderJob, lang: str) -> str:
    if job.status == "rendering":
        return tr(lang, "bot.v_progress", pct=job.progress)
    return tr(lang, "bot.v_queued", pos=await queue_position(job.id))


# ---------------------------------------------------------------- to'lovlar

def pay_keyboard(payment_id: int, amount: int, lang: str) -> InlineKeyboardMarkup:
    kb = InlineKeyboardBuilder()
    if settings.rahmat_url:
        kb.button(text=tr(lang, "bot.btn_pay", amount=money(amount)), url=settings.rahmat_url)
    kb.button(text=tr(lang, "bot.btn_paid"), callback_data=f"tpaid:{payment_id}")
    kb.adjust(1)
    return kb.as_markup()


async def send_payment_prompt(payment_id: int) -> None:
    """Balansni to'ldirish ko'rsatmasi: to'lash havolasi va «To'ladim» tugmasi."""
    from .db import Payment
    bot = BOT
    if not bot:
        return
    async with Session() as s:
        p = await s.get(Payment, payment_id)
        job = await s.get(RenderJob, p.job_id) if p.job_id else None
    lang = await user_lang(p.user_id)
    key = "bot.pay_video" if job else "bot.pay_topup"
    try:
        await bot.send_message(p.user_id, tr(lang, key, amount=money(p.amount)), reply_markup=pay_keyboard(p.id, p.amount, lang))
    except Exception:
        log.exception("To'lov ko'rsatmasini yuborib bo'lmadi")


async def run_awaiting(uid: int) -> int:
    """Balans to'ldirilgach, to'lovni kutib turgan videolarni navbatga qo'yadi."""
    from .billing import spend
    queued = []
    async with Session() as s:
        jobs = (await s.execute(select(RenderJob).where(RenderJob.owner_id == uid, RenderJob.status == "awaiting_payment")
                                .order_by(RenderJob.id))).scalars().all()
        for j in jobs:
            if not await spend(s, uid, j.price, "video", f"job:{j.id}"):
                break
            j.status = "queued"
            queued.append(j.id)
        await s.commit()
    for job_id in queued:
        from .videoapi import notify_queued
        await notify_queued(job_id)
    return len(queued)


async def site_paid_notice(site_id: int) -> None:
    """Sayt balansdan to'langanda egasiga toza havola yuboriladi."""
    bot = BOT
    if not bot:
        return
    from .bot import keyboards as kb
    async with Session() as s:
        site = await s.get(Site, site_id)
    lang = await user_lang(site.owner_id)
    try:
        await bot.send_message(site.owner_id, tr(lang, "bot.site_paid", url=site.url), reply_markup=kb.site_actions(site))
    except Exception:
        log.exception("Sayt xabarini yuborib bo'lmadi")
