"""Balans: to'ldirish cheki, admin tasdig'i, saytni balansdan to'lash."""

import html
import logging
from datetime import timedelta

from aiogram import F, Router
from aiogram.filters import StateFilter
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.types import CallbackQuery, Message
from aiogram.utils.keyboard import InlineKeyboardBuilder

from .. import billing, receipt, videobot
from ..catalog import site_price, site_title
from ..config import settings
from sqlalchemy import func, select, update

from ..db import Payment, RenderJob, Session, Site, Song, User, utcnow
from ..i18n import tr
from . import keyboards as kb

log = logging.getLogger(__name__)
router = Router()


class Topup(StatesGroup):
    receipt = State()


OPEN = ("new", "pending")                    # hali ko'rib chiqilmagan to'lov


def admin_keyboard(payment_id: int):
    b = InlineKeyboardBuilder()
    b.button(text="✅ Tasdiqlash", callback_data=f"tok:{payment_id}")
    b.button(text="❌ Rad etish", callback_data=f"tno:{payment_id}")
    b.adjust(2)
    return b.as_markup()


@router.callback_query(F.data.startswith("tpaid:"))
async def topup_paid(cb: CallbackQuery, state: FSMContext):
    """Eski xabarlardagi «To'ladim» tugmasi: to'lov ko'rsatmasini qayta yuboramiz (Click yoki karta)."""
    await state.clear()
    pid = int(cb.data.split(":")[1])
    async with Session() as s:
        p = await s.get(Payment, pid)
    await cb.answer()
    if p and p.user_id == cb.from_user.id and p.status == "new":
        await videobot.send_payment_prompt(p.id)


# ---------------------------------------------------------------- karta raqamiga o'tkazma + chek

async def card_payment(pid: int, uid: int) -> Payment | None:
    """To'lovni «karta orqali» deb belgilaydi va karta ma'lumotini botga yuboradi (bot tugmasi va Mini App uchun)."""
    cfg = await receipt.config()
    if not receipt.enabled(cfg):
        return None
    async with Session() as s:
        p = await s.get(Payment, pid)
        if not p or p.user_id != uid or p.status not in OPEN:
            return None
        if p.provider != "card":
            p.provider, p.created_at = "card", utcnow()  # vaqt oynasi karta tanlangan paytdan hisoblanadi
            await s.commit()
    if videobot.BOT:
        lang = await videobot.user_lang(uid)
        try:
            await videobot.BOT.send_message(uid, tr(lang, "bot.card_info", card=cfg["card"], owner=html.escape(cfg["owner"]),
                                                    amount=videobot.money(p.amount)))
        except Exception:
            log.exception("Karta ma'lumotini yuborib bo'lmadi: %s", uid)
    return p


@router.callback_query(F.data.startswith("tcard:"))
async def topup_card(cb: CallbackQuery, state: FSMContext):
    p = await card_payment(int(cb.data.split(":")[1]), cb.from_user.id)
    if not p:
        return await cb.answer(tr(await videobot.user_lang(cb.from_user.id), "bot.card_closed"), show_alert=True)
    await state.set_state(Topup.receipt)
    await state.update_data(pid=p.id)
    await cb.answer()


async def _open_card_payment(uid: int, pid: int | None = None) -> Payment | None:
    since = utcnow() - timedelta(hours=receipt.OPEN_HOURS)
    async with Session() as s:
        q = select(Payment).where(Payment.user_id == uid, Payment.provider == "card", Payment.status.in_(OPEN),
                                  Payment.created_at >= since)
        if pid:
            q = q.where(Payment.id == pid)
        return (await s.execute(q.order_by(Payment.id.desc()).limit(1))).scalar_one_or_none()


def _receipt_media(message: Message):
    """(file_id, mime, hajm) — rasm yoki rasm/PDF hujjat; boshqa narsa bo'lsa None."""
    if message.photo:
        return message.photo[-1].file_id, "image/jpeg", message.photo[-1].file_size or 0
    d = message.document
    if d and (d.mime_type or "") in ("image/jpeg", "image/png", "image/webp", "application/pdf"):
        return d.file_id, d.mime_type, d.file_size or 0
    return None


async def _has_card_payment(message: Message) -> dict | bool:
    """Holatsiz rasm/chek: mijozda ochiq karta to'lovi bo'lsa — shu to'lovga chek sifatida olinadi."""
    if not _receipt_media(message):
        return False
    p = await _open_card_payment(message.from_user.id)
    return {"pay": p} if p else False


@router.message(Topup.receipt)
async def topup_receipt_state(message: Message, state: FSMContext):
    lang = await videobot.user_lang(message.from_user.id)
    if not _receipt_media(message):
        if message.text and message.text.startswith("/"):
            await state.clear()
            return await message.answer(tr(lang, "bot.card_cancel"))
        return await message.answer(tr(lang, "bot.card_need_photo"))
    data = await state.get_data()
    p = await _open_card_payment(message.from_user.id, data.get("pid")) or await _open_card_payment(message.from_user.id)
    await state.clear()
    if not p:
        return await message.answer(tr(lang, "bot.card_closed"))
    await process_receipt(message, p)


@router.message(StateFilter(None), F.photo | F.document, _has_card_payment)
async def topup_receipt_free(message: Message, pay: Payment):
    await process_receipt(message, pay)


async def process_receipt(message: Message, p: Payment) -> str:
    """Chekni tekshiradi. Natija: auto (avtomatik tasdiqlandi) | review (adminga) | dup | not_receipt | big."""
    bot, uid = message.bot, message.from_user.id
    lang = await videobot.user_lang(uid)
    file_id, mime, size = _receipt_media(message)
    if size > 10 * 1024 * 1024:
        await message.answer(tr(lang, "bot.card_need_photo"))
        return "big"
    try:
        f = await bot.get_file(file_id)
        data = (await bot.download_file(f.file_path)).read()
    except Exception:
        log.exception("Chekni yuklab bo'lmadi: %s", p.id)
        data = b""
    h = receipt.digest(data) if data else ""
    async with Session() as s:
        if h and await s.scalar(select(func.count()).select_from(Payment).where(Payment.receipt_hash == h, Payment.id != p.id)):
            await message.answer(tr(lang, "bot.card_dup"))
            return "dup"
    wait = await message.answer(tr(lang, "bot.card_checking"))
    r = await receipt.read(data, mime, uid) if data else None
    if r is not None and not r.get("is_receipt"):
        await _safe_delete(wait)
        await message.answer(tr(lang, "bot.card_not_receipt"))
        return "not_receipt"
    cfg = await receipt.config()
    async with Session() as s:
        cur = await s.get(Payment, p.id)
        if cur.status not in OPEN:  # shu orada admin ko'rib chiqqan
            await _safe_delete(wait)
            return "done"
        ok, why = await receipt.verify(cur, r, cfg)
        cur.receipt, cur.receipt_hash, cur.status = file_id, h, "pending"
        if r and r.get("transaction_id"):
            cur.ext_id = r["transaction_id"][:40]
        await s.commit()
        p = cur
    await _safe_delete(wait)
    user_line = await _user_line(uid)
    info = receipt.summary(r)
    if ok and await decide_payment(bot, p.id, True, 0) == "ok":
        log.info("Karta to'lovi #%s avtomatik tasdiqlandi (%s so'm)", p.id, p.amount)
        await _to_admins(bot, file_id, bool(message.photo), f"🤖 <b>Avtomatik tasdiqlandi</b> · karta\n#{p.id} · <b>{videobot.money(p.amount)}</b>\n"
                         f"{user_line}\n🧾 {html.escape(info, quote=False)}", revert_keyboard(p.id))
        return "auto"
    await message.answer(tr(lang, "bot.card_review"))
    reasons = "\n".join(f"• {html.escape(x, quote=False)}" for x in why) or "• tekshiruv kerak"
    await _to_admins(bot, file_id, bool(message.photo), f"🧾 <b>Karta cheki — tekshiring</b>\n#{p.id} · <b>{videobot.money(p.amount)}</b>\n"
                     f"{user_line}\n🧾 {html.escape(info, quote=False)}\n\nNega avtomatik emas:\n{reasons}", admin_keyboard(p.id))
    return "review"


async def _safe_delete(m) -> None:
    try:
        await m.delete()
    except Exception:
        pass


async def _user_line(uid: int) -> str:
    async with Session() as s:
        u = await s.get(User, uid)
    name = html.escape((u.first_name if u else "") or str(uid))
    return f"👤 <a href=\"tg://user?id={uid}\">{name}</a>" + (f" @{html.escape(u.username)}" if u and u.username else "") + f" · <code>{uid}</code>"


async def _to_admins(bot, file_id: str, is_photo: bool, caption: str, markup) -> None:
    for aid in settings.admins:
        try:
            if is_photo:
                await bot.send_photo(aid, file_id, caption=caption, reply_markup=markup)
            else:
                await bot.send_document(aid, file_id, caption=caption, reply_markup=markup)
        except Exception:
            try:
                await bot.send_message(aid, caption, reply_markup=markup)
            except Exception:
                log.exception("Chekni adminga yuborib bo'lmadi: %s", aid)


def revert_keyboard(payment_id: int):
    b = InlineKeyboardBuilder()
    b.button(text="↩️ Bekor qilish (soxta chek)", callback_data=f"trev:{payment_id}")
    return b.as_markup()


async def revert_payment(pid: int, admin_id: int) -> str:
    """Avtomatik tasdiqlangan karta to'lovini bekor qiladi: balansdan qaytarib yechadi.
    Natija: ok | spent (pul ishlatib bo'lingan — qolganini yechdik) | done | not_found."""
    async with Session() as s:
        p = await s.get(Payment, pid)
        if not p:
            return "not_found"
        if p.status != "approved" or p.provider != "card":
            return "done"
        user = await s.get(User, p.user_id)
        take = min(p.amount, max(0, user.balance if user else 0))
        if take and not await billing.spend(s, p.user_id, take, "revert", f"pay:{p.id}"):
            take = 0
        p.status, p.admin_id, p.decided_at = "rejected", admin_id, utcnow()
        await s.commit()
    lang = (user.lang if user else "") or "uz"
    try:
        if videobot.BOT:
            await videobot.BOT.send_message(p.user_id, tr(lang, "bot.card_reverted", amount=videobot.money(take)))
    except Exception:
        log.exception("Bekor qilish xabarini yuborib bo'lmadi: %s", p.user_id)
    return "ok" if take >= p.amount else "spent"


@router.callback_query(F.data.startswith("trev:"))
async def topup_revert(cb: CallbackQuery):
    if cb.from_user.id not in settings.admins:
        return await cb.answer("Ruxsat yo'q", show_alert=True)
    res = await revert_payment(int(cb.data.split(":")[1]), cb.from_user.id)
    if res in ("not_found", "done"):
        return await cb.answer("Topilmadi" if res == "not_found" else "Allaqachon bekor qilingan yoki ko'rib chiqilgan")
    mark = "\n\n↩️ <b>Bekor qilindi</b>" + ("" if res == "ok" else " — pulning bir qismi ishlatib bo'lingan, qolgani yechildi")
    await _mark(cb, mark)
    await cb.answer()


async def _mark(cb: CallbackQuery, mark: str) -> None:
    """Admin xabariga natija qo'shadi va tugmalarni olib tashlaydi (matnli yoki rasmli xabar)."""
    try:
        if cb.message.text is not None:
            await cb.message.edit_text(cb.message.html_text + mark)
        else:
            await cb.message.edit_caption(caption=(cb.message.html_text or "") + mark)
    except Exception:
        log.warning("Admin xabarini yangilab bo'lmadi")


async def decide_payment(bot, pid: int, approve: bool, admin_id: int) -> str:
    """To'lovni tasdiqlaydi yoki rad etadi (bot tugmasi va admin paneli uchun umumiy).
    Natija: ok | not_found | done (allaqachon ko'rib chiqilgan)."""
    async with Session() as s:
        # bitta atomik UPDATE: ikki admin (bot tugmasi va panel) bir vaqtda bossa ham pul faqat bir marta tushadi
        res = await s.execute(update(Payment).where(Payment.id == pid, Payment.status.in_(OPEN)).values(
            status="approved" if approve else "rejected", admin_id=admin_id, decided_at=utcnow()).execution_options(synchronize_session=False))
        if res.rowcount != 1:
            await s.rollback()
            return "done" if await s.get(Payment, pid) else "not_found"
        p = await s.get(Payment, pid)
        await s.refresh(p)
        if approve:
            await billing.credit(s, p.user_id, p.amount, "topup", f"pay:{p.id}")
        await s.commit()
        user = await s.get(User, p.user_id)
    if approve:
        await after_topup(bot, p, user)
        return "ok"
    lang = (user.lang if user else "") or "uz"
    try:
        await bot.send_message(p.user_id, tr(lang, "bot.topup_rejected"))
    except Exception:
        log.exception("To'lov natijasini foydalanuvchiga yuborib bo'lmadi: %s", p.user_id)
    return "ok"


async def after_topup(bot, p: Payment, user: User | None) -> None:
    """Balans to'ldirilgach (chek tasdig'i yoki Click): xabar, kutayotgan videolar, to'lov qilingan sayt."""
    lang = (user.lang if user else "") or "uz"
    try:
        if bot:
            await bot.send_message(p.user_id, tr(lang, "bot.topup_done", amount=videobot.money(p.amount),
                                                 balance=videobot.money(user.balance if user else p.amount)))
    except Exception:
        log.exception("To'lov natijasini foydalanuvchiga yuborib bo'lmadi: %s", p.user_id)
    if p.site_id:
        paid = False
        async with Session() as s:
            site = await s.get(Site, p.site_id)
            if site and site.owner_id == p.user_id and not site.paid and \
                    await billing.spend(s, p.user_id, site_price(site.config), "site", f"site:{site.slug}"):
                site.status = "paid"
                paid = True
            await s.commit()
        if paid:
            await videobot.site_paid_notice(p.site_id)
    if getattr(p, "pack", 0):
        from .. import pricing
        async with Session() as s:
            ok = await pricing.buy_pack(s, p.user_id, p.pack)
            await s.commit()
        if ok and bot:
            try:
                await bot.send_message(p.user_id, f"🎟 Qo‘shiq paketi faollashdi: hisobingizga {p.pack} ta qo‘shiq qo‘shildi. "
                                                  "Keyingi qo‘shiqlaringiz paketdan olinadi — pul yechilmaydi.")
            except Exception:
                log.exception("Paket xabarini yuborib bo'lmadi: %s", p.user_id)
    if getattr(p, "song_id", None):
        from .. import songs
        async with Session() as s:
            song = await s.get(Song, p.song_id)
            if song and song.owner_id == p.user_id and not song.paid and song.status not in ("preview_queued", "preview_gen"):
                await songs.pay(s, song, p.user_id)
            await s.commit()
        songs.wake()
    try:
        n = await videobot.run_awaiting(p.user_id)
        if n and bot:
            await bot.send_message(p.user_id, tr(lang, "bot.queued_after_pay", n=n))
    except Exception:
        log.exception("Kutayotgan videolarni ishga tushirib bo'lmadi: %s", p.user_id)


@router.callback_query(F.data.startswith(("tok:", "tno:")))
async def topup_decision(cb: CallbackQuery):
    if cb.from_user.id not in settings.admins:
        return await cb.answer("Ruxsat yo'q", show_alert=True)
    action, pid = cb.data.split(":")
    res = await decide_payment(cb.bot, int(pid), action == "tok", cb.from_user.id)
    if res == "not_found":
        return await cb.answer("Topilmadi")
    if res == "done":
        return await cb.answer("Allaqachon ko'rib chiqilgan")
    mark = "\n\n✅ <b>Tasdiqlandi</b>" if action == "tok" else "\n\n❌ <b>Rad etildi</b>"
    await _mark(cb, mark)
    await cb.answer()


@router.callback_query(F.data.startswith("sclick:"))
async def site_click(cb: CallbackQuery):
    """Saytni Click orqali to'lash: yetmagan summaga to'lov yoziladi, to'langach sayt o'zi faollashadi."""
    site_id = int(cb.data.split(":")[1])
    async with Session() as s:
        site = await s.get(Site, site_id)
        if not site or site.owner_id != cb.from_user.id:
            return await cb.answer()
        if site.paid:
            return await cb.answer("✅")
        user = await s.get(User, cb.from_user.id)
        amount = max(1000, site_price(site.config) - (user.balance if user else 0))
        p = Payment(user_id=cb.from_user.id, amount=amount, site_id=site.id)
        s.add(p)
        await s.commit()
    await videobot.send_payment_prompt(p.id)
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
