"""Balans: to'ldirish cheki, admin tasdig'i, saytni balansdan to'lash."""

import html
import logging

from aiogram import F, Router
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.types import CallbackQuery, Message
from aiogram.utils.keyboard import InlineKeyboardBuilder

from .. import billing, videobot
from ..catalog import site_price, site_title
from ..config import settings
from ..db import Payment, RenderJob, Session, Site, User, utcnow
from ..i18n import tr
from . import keyboards as kb

log = logging.getLogger(__name__)
router = Router()


class Topup(StatesGroup):
    receipt = State()


def admin_keyboard(payment_id: int):
    b = InlineKeyboardBuilder()
    b.button(text="✅ Tasdiqlash", callback_data=f"tok:{payment_id}")
    b.button(text="❌ Rad etish", callback_data=f"tno:{payment_id}")
    b.adjust(2)
    return b.as_markup()


@router.callback_query(F.data.startswith("tpaid:"))
async def topup_paid(cb: CallbackQuery, state: FSMContext):
    pid = int(cb.data.split(":")[1])
    async with Session() as s:
        p = await s.get(Payment, pid)
    if not p or p.user_id != cb.from_user.id or p.status == "approved":
        return await cb.answer()
    lang = await videobot.user_lang(cb.from_user.id)
    await state.set_state(Topup.receipt)
    await state.update_data(payment_id=pid)
    await cb.message.answer(tr(lang, "bot.send_receipt"))
    await cb.answer()


@router.message(Topup.receipt, F.photo | F.document)
async def topup_receipt(message: Message, state: FSMContext):
    pid = (await state.get_data()).get("payment_id")
    await state.clear()
    async with Session() as s:
        p = await s.get(Payment, pid)
        if not p or p.user_id != message.from_user.id:
            return
        p.status = "pending"
        job = await s.get(RenderJob, p.job_id) if p.job_id else None
        await s.commit()
    user = message.from_user
    what = "🎬 Video uchun" if job else "💰 Balansni to'ldirish"
    caption = (f"💳 <b>Yangi to'lov</b> #{p.id} — {what}\n"
               f"👤 {html.escape(user.full_name)} (@{user.username or '-'}, id {user.id})\n"
               f"💵 {videobot.money(p.amount)}")
    for admin in settings.admins:
        try:
            await message.copy_to(admin)
            await message.bot.send_message(admin, caption, reply_markup=admin_keyboard(p.id))
        except Exception:
            log.exception("Adminga yuborib bo'lmadi: %s", admin)
    lang = await videobot.user_lang(user.id)
    await message.answer(tr(lang, "bot.receipt_ok"))


@router.message(Topup.receipt)
async def topup_receipt_wrong(message: Message):
    lang = await videobot.user_lang(message.from_user.id)
    await message.answer(tr(lang, "bot.receipt_wrong"))


@router.callback_query(F.data.startswith(("tok:", "tno:")))
async def topup_decision(cb: CallbackQuery):
    if cb.from_user.id not in settings.admins:
        return await cb.answer("Ruxsat yo'q", show_alert=True)
    action, pid = cb.data.split(":")
    async with Session() as s:
        p = await s.get(Payment, int(pid))
        if not p:
            return await cb.answer("Topilmadi")
        if p.status in ("approved", "rejected"):
            return await cb.answer("Allaqachon ko'rib chiqilgan")
        p.status = "approved" if action == "tok" else "rejected"
        p.admin_id = cb.from_user.id
        p.decided_at = utcnow()
        if action == "tok":
            await billing.credit(s, p.user_id, p.amount, "topup", f"pay:{p.id}")
        await s.commit()
        user = await s.get(User, p.user_id)
    lang = (user.lang if user else "") or "uz"
    if action == "tok":
        await cb.bot.send_message(p.user_id, tr(lang, "bot.topup_done", amount=videobot.money(p.amount),
                                                balance=videobot.money(user.balance if user else p.amount)))
        n = await videobot.run_awaiting(p.user_id)
        if n:
            await cb.bot.send_message(p.user_id, tr(lang, "bot.queued_after_pay", n=n))
        await cb.message.edit_text(cb.message.html_text + "\n\n✅ <b>Tasdiqlandi</b>")
    else:
        await cb.bot.send_message(p.user_id, tr(lang, "bot.topup_rejected"))
        await cb.message.edit_text(cb.message.html_text + "\n\n❌ <b>Rad etildi</b>")
    await cb.answer()


@router.callback_query(F.data.startswith("sbal:"))
async def site_from_balance(cb: CallbackQuery):
    """Saytni balansdan to'lash (bot ichida)."""
    site_id = int(cb.data.split(":")[1])
    lang = await videobot.user_lang(cb.from_user.id)
    async with Session() as s:
        site = await s.get(Site, site_id)
        if not site or site.owner_id != cb.from_user.id:
            return await cb.answer()
        if site.paid:
            return await cb.answer("✅")
        if not await billing.spend(s, cb.from_user.id, site_price(site.config), "site", f"site:{site.slug}"):
            return await cb.answer(tr(lang, "bot.no_balance"), show_alert=True)
        site.status = "paid"
        await s.commit()
    await cb.message.answer(tr(lang, "bot.site_paid", url=site.url), reply_markup=kb.site_actions(site))
    await cb.answer()
    log.info("Sayt balansdan to'landi: %s (%s)", site.slug, site_title(site.config))
