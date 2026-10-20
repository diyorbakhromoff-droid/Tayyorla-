"""Bot: «📅 Yaqinlarim» — muhim sanalar ro'yxati va eslatmalar."""

import re
from datetime import date

from aiogram import F, Router
from aiogram.filters import Command
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.types import CallbackQuery, InlineKeyboardMarkup, Message
from aiogram.utils.keyboard import InlineKeyboardBuilder
from sqlalchemy import delete, func, select

from ..db import Person, ReminderLog, Session
from ..reminders import KINDS, describe, next_occurrence, today

router = Router()
MAX_PEOPLE = 50


class AddPerson(StatesGroup):
    name = State()
    kind = State()
    title = State()
    date = State()


def people_keyboard(people: list[Person]) -> InlineKeyboardMarkup:
    kb = InlineKeyboardBuilder()
    kb.button(text="➕ Yaqin insonni qo'shish", callback_data="p:add")
    for p in people:
        kb.button(text=f"🗑 {p.name[:24]} — {KINDS[p.kind][0]}", callback_data=f"p:del:{p.id}")
    kb.button(text="🏠 Bosh menyu", callback_data="home")
    kb.adjust(1)
    return kb.as_markup()


def kind_keyboard() -> InlineKeyboardMarkup:
    kb = InlineKeyboardBuilder()
    kb.button(text="🎂 Tug'ilgan kun", callback_data="p:kind:birthday")
    kb.button(text="💍 To'y yilligi", callback_data="p:kind:anniversary")
    kb.button(text="📌 Boshqa muhim sana", callback_data="p:kind:other")
    kb.button(text="✖️ Bekor qilish", callback_data="people")
    kb.adjust(1)
    return kb.as_markup()


def parse_day(text: str) -> tuple[int, int, int | None] | None:
    """«24.10», «24.10.1971», «24/10» kabi sanalarni (kun, oy, yil) ga aylantiradi."""
    m = re.fullmatch(r"\s*(\d{1,2})[./\-\s](\d{1,2})(?:[./\-\s](\d{4}))?\s*", text)
    if not m:
        return None
    d, mo = int(m.group(1)), int(m.group(2))
    y = int(m.group(3)) if m.group(3) else None
    try:
        date(y or 2000, mo, d)  # 2000 kabisa yili: 29-fevral ham o'tadi
    except ValueError:
        return None
    if y and not 1900 <= y <= today().year:
        return None
    return d, mo, y


async def list_people(user_id: int) -> list[Person]:
    ref = today()
    async with Session() as s:
        people = (await s.execute(select(Person).where(Person.owner_id == user_id))).scalars().all()
    return sorted(people, key=lambda p: next_occurrence(p, ref))


async def show_people(message: Message, user_id: int) -> None:
    people = await list_people(user_id)
    if not people:
        text = (
            "📅 <b>Yaqinlarim</b>\n\n"
            "Yaqinlaringizning tug'ilgan kunlari va muhim sanalarini qo'shing — men sizga "
            "<b>7 kun</b>, <b>1 kun</b> oldin va <b>o'sha kuni</b> eslataman. "
            "Eslatmadan bir bosishda tayyor tabrik sayti yaratasiz 🎁\n\n"
            "Hech qachon muhim kunni unutmaysiz!"
        )
    else:
        ref = today()
        lines = [describe(p, ref) for p in people]
        text = "📅 <b>Yaqinlarim</b> — eng yaqin sanalar:\n\n" + "\n".join(lines) + "\n\n🔔 7 kun, 1 kun oldin va o'sha kuni eslataman."
    await message.answer(text, reply_markup=people_keyboard(people))


@router.message(Command("yaqinlar"))
async def people_cmd(message: Message, state: FSMContext):
    await state.clear()
    await show_people(message, message.from_user.id)


@router.callback_query(F.data == "people")
async def people_cb(cb: CallbackQuery, state: FSMContext):
    await state.clear()
    await show_people(cb.message, cb.from_user.id)
    await cb.answer()


@router.callback_query(F.data == "p:add")
async def add_start(cb: CallbackQuery, state: FSMContext):
    async with Session() as s:
        count = await s.scalar(select(func.count()).select_from(Person).where(Person.owner_id == cb.from_user.id))
    if count >= MAX_PEOPLE:
        return await cb.answer(f"Ko'pi bilan {MAX_PEOPLE} ta sana qo'shish mumkin", show_alert=True)
    await state.set_state(AddPerson.name)
    await cb.message.answer("👤 Kim? Ismini yoki qanday ataysiz, shuni yozing.\nMasalan: <i>Onam</i>, <i>Madina</i>, <i>Akam Jasur</i>")
    await cb.answer()


@router.message(AddPerson.name, F.text & ~F.text.startswith("/"))
async def add_name(message: Message, state: FSMContext):
    await state.update_data(name=message.text.strip()[:100])
    await state.set_state(AddPerson.kind)
    await message.answer("Qanday sana?", reply_markup=kind_keyboard())


@router.callback_query(AddPerson.kind, F.data.startswith("p:kind:"))
async def add_kind(cb: CallbackQuery, state: FSMContext):
    kind = cb.data.split(":")[2]
    await state.update_data(kind=kind)
    if kind == "other":
        await state.set_state(AddPerson.title)
        await cb.message.answer("📌 Bu qanday sana? Masalan: <i>Tanishgan kunimiz</i>, <i>Ishga kirgan kuni</i>")
    else:
        await state.set_state(AddPerson.date)
        await cb.message.answer(
            "📅 Sanani yozing: <b>kun.oy</b> yoki <b>kun.oy.yil</b>\n"
            "Masalan: <code>24.10</code> yoki <code>24.10.1971</code>\n\n"
            "Yilni yozsangiz, necha yosh (yoki necha yil) bo'lishini ham aytib turaman."
        )
    await cb.answer()


@router.message(AddPerson.title, F.text & ~F.text.startswith("/"))
async def add_title(message: Message, state: FSMContext):
    await state.update_data(title=message.text.strip()[:100])
    await state.set_state(AddPerson.date)
    await message.answer("📅 Sanani yozing: <b>kun.oy</b> yoki <b>kun.oy.yil</b> (masalan: <code>14.02.2020</code>)")


@router.message(AddPerson.date, F.text & ~F.text.startswith("/"))
async def add_date(message: Message, state: FSMContext):
    parsed = parse_day(message.text)
    if not parsed:
        return await message.answer("Sanani tushunmadim 🙈 Shunday yozing: <code>24.10</code> yoki <code>24.10.1971</code>")
    d, mo, y = parsed
    data = await state.get_data()
    await state.clear()
    p = Person(owner_id=message.from_user.id, name=data["name"], kind=data["kind"], title=data.get("title", ""), day=d, month=mo, year=y)
    async with Session() as s:
        s.add(p)
        await s.commit()
    await message.answer(f"✅ Saqlandi!\n\n{describe(p, today())}\n\nO'z vaqtida eslataman 🔔")
    await show_people(message, message.from_user.id)


@router.callback_query(F.data.startswith("p:del:"))
async def delete_person(cb: CallbackQuery):
    pid = int(cb.data.split(":")[2])
    async with Session() as s:
        p = await s.get(Person, pid)
        if not p or p.owner_id != cb.from_user.id:
            return await cb.answer()
        name = p.name
        await s.execute(delete(ReminderLog).where(ReminderLog.person_id == pid))
        await s.delete(p)
        await s.commit()
    await cb.answer(f"{name} o'chirildi")
    await show_people(cb.message, cb.from_user.id)
