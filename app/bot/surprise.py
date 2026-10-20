"""Bot: saytni syurpriz sifatida belgilangan vaqtda (odatda 00:00 da) ochish."""

import re
from datetime import date

from aiogram import F, Router
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.types import CallbackQuery, InlineKeyboardMarkup, Message
from aiogram.utils.keyboard import InlineKeyboardBuilder

from ..db import Session, Site
from ..surprise import clean_unlock, human, locked_until, natural_date, parse_unlock
from . import keyboards as kb

router = Router()


class SurpriseIn(StatesGroup):
    waiting = State()


def surprise_keyboard(site: Site) -> InlineKeyboardMarkup:
    b = InlineKeyboardBuilder()
    d = natural_date(site.config)
    if d:
        b.button(text=f"📅 {d.day}.{d.month:02d}.{d.year} soat 00:00 da ochilsin", callback_data=f"surp:set:{site.id}:{d.isoformat()}")
    b.button(text="✍️ Boshqa sana yoki vaqt", callback_data=f"surp:ask:{site.id}")
    if locked_until(site.config):
        b.button(text="❌ Syurprizni o'chirish (darhol ochiq)", callback_data=f"surp:off:{site.id}")
    b.button(text="⬅️ Orqaga", callback_data=f"site:{site.id}")
    b.adjust(1)
    return b.as_markup()


async def _own_site(site_id: int, user_id: int) -> Site | None:
    async with Session() as s:
        site = await s.get(Site, site_id)
    return site if site and site.owner_id == user_id else None


async def _save_unlock(site_id: int, value: str | None) -> Site:
    async with Session() as s:
        site = await s.get(Site, site_id)
        cfg = dict(site.config)
        if value:
            cfg["unlock_at"] = value
        else:
            cfg.pop("unlock_at", None)
        site.config = cfg
        await s.commit()
    return site


def _done_text(site: Site) -> str:
    lock = locked_until(site.config)
    return (
        f"🎁 <b>Syurpriz yoqildi!</b>\n\n"
        f"Sayt <b>{human(lock)}</b> da ochiladi. Ungacha havolani ochgan odam sovg'a qutisi va taymerni ko'radi.\n\n"
        "💡 Havolani hoziroq yuborishingiz mumkin — u vaqt kelguncha sabrsizlik bilan kutadi 😄\n"
        "Siz o'zingiz saytni «👀 Saytni ochish» tugmasi orqali istalgan payt ko'ra olasiz."
    )


@router.callback_query(F.data.startswith("surprise:"))
async def surprise_menu(cb: CallbackQuery, state: FSMContext):
    await state.clear()
    site = await _own_site(int(cb.data.split(":")[1]), cb.from_user.id)
    if not site:
        return await cb.answer()
    lock = locked_until(site.config)
    status = f"Hozir: <b>{human(lock)}</b> da ochiladi ✅" if lock else "Hozir: sayt darhol ochiq."
    await cb.message.answer(
        "⏰ <b>Syurpriz ochilish</b>\n\n"
        "Havolani oldindan yuborasiz, lekin sayt aynan belgilangan vaqtda — masalan, tug'ilgan kuni soat 00:00 da ochiladi. "
        f"Ungacha sovg'a qutisi va orqaga sanoq ko'rinadi 🎁\n\n{status}",
        reply_markup=surprise_keyboard(site),
    )
    await cb.answer()


@router.callback_query(F.data.startswith("surp:set:"))
async def surprise_set(cb: CallbackQuery):
    _, _, site_id, day = cb.data.split(":")
    if not await _own_site(int(site_id), cb.from_user.id):
        return await cb.answer()
    value = clean_unlock(f"{day}T00:00")
    if not value:
        return await cb.answer("Bu vaqt o'tib ketgan", show_alert=True)
    site = await _save_unlock(int(site_id), value)
    await cb.message.answer(_done_text(site), reply_markup=kb.site_actions(site))
    await cb.answer("Yoqildi ✅")


@router.callback_query(F.data.startswith("surp:off:"))
async def surprise_off(cb: CallbackQuery):
    site_id = int(cb.data.split(":")[2])
    if not await _own_site(site_id, cb.from_user.id):
        return await cb.answer()
    site = await _save_unlock(site_id, None)
    await cb.message.answer("Syurpriz o'chirildi — sayt darhol ochiq ✅", reply_markup=kb.site_actions(site))
    await cb.answer()


@router.callback_query(F.data.startswith("surp:ask:"))
async def surprise_ask(cb: CallbackQuery, state: FSMContext):
    site_id = int(cb.data.split(":")[2])
    if not await _own_site(site_id, cb.from_user.id):
        return await cb.answer()
    await state.set_state(SurpriseIn.waiting)
    await state.update_data(site_id=site_id)
    await cb.message.answer(
        "📅 Sayt qachon ochilsin? Yozing:\n"
        "• <code>24.10.2026</code> — shu kuni soat 00:00 da\n"
        "• <code>24.10.2026 18:30</code> — aniq vaqtda"
    )
    await cb.answer()


@router.message(SurpriseIn.waiting, F.text & ~F.text.startswith("/"))
async def surprise_input(message: Message, state: FSMContext):
    m = re.fullmatch(r"\s*(\d{1,2})[./](\d{1,2})[./](\d{4})(?:\s+(\d{1,2})[:.](\d{2}))?\s*", message.text)
    value = None
    if m:
        try:
            d = date(int(m.group(3)), int(m.group(2)), int(m.group(1)))
            hh, mm = int(m.group(4) or 0), int(m.group(5) or 0)
            if hh < 24 and mm < 60:
                value = clean_unlock(f"{d.isoformat()}T{hh:02d}:{mm:02d}")
        except ValueError:
            value = None
    if not value:
        bad = m and parse_unlock(f"{m.group(3)}-{int(m.group(2)):02d}-{int(m.group(1)):02d}T00:00")
        hint = "Bu vaqt o'tib ketgan yoki juda uzoq (1 yildan ortiq)." if bad else "Sanani tushunmadim."
        return await message.answer(f"🙈 {hint} Masalan: <code>24.10.2026</code> yoki <code>24.10.2026 18:30</code>")
    site_id = (await state.get_data())["site_id"]
    await state.clear()
    if not await _own_site(site_id, message.from_user.id):
        return
    site = await _save_unlock(site_id, value)
    await message.answer(_done_text(site), reply_markup=kb.site_actions(site))
