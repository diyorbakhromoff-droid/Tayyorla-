"""«Yaqinlarim» kalendari: muhim sanalarni hisoblash va eslatma yuborish."""

import asyncio
import html
import logging
from datetime import date, datetime, timedelta, timezone
from urllib.parse import urlencode

from aiogram.types import InlineKeyboardMarkup, WebAppInfo
from aiogram.utils.keyboard import InlineKeyboardBuilder
from sqlalchemy import select

from .config import settings
from .db import Person, ReminderLog, Session

log = logging.getLogger(__name__)

TZ = timezone(timedelta(hours=5))  # O'zbekiston vaqti (yozgi vaqt yo'q)
REMIND_DAYS = (7, 1, 0)
SEND_FROM_HOUR = 9  # eslatmalar ertalab 9:00 dan keyin yuboriladi
MONTHS = ["yanvar", "fevral", "mart", "aprel", "may", "iyun", "iyul", "avgust", "sentabr", "oktabr", "noyabr", "dekabr"]
KINDS = {
    "birthday": ("🎂", "tug'ilgan kuni"),
    "anniversary": ("💍", "to'y yilligi"),
    "other": ("📌", ""),
}
# Eslatmadan Mini App ochilganda qaysi bo'lim tanlansin
KIND_SECTION = {"birthday": "tugilgan-kun", "anniversary": "sevgi"}


def today() -> date:
    return datetime.now(TZ).date()


def occurrence(day: int, month: int, year: int) -> date:
    """Berilgan yildagi sana. 29-fevral kabiy bo'lmagan yilda 28-fevralga tushadi."""
    try:
        return date(year, month, day)
    except ValueError:
        return date(year, month, 28)


def next_occurrence(p: Person, ref: date) -> date:
    d = occurrence(p.day, p.month, ref.year)
    return d if d >= ref else occurrence(p.day, p.month, ref.year + 1)


def years_on(p: Person, on: date) -> int | None:
    return on.year - p.year if p.year and on.year > p.year else None


def human_day(d: date) -> str:
    return f"{d.day}-{MONTHS[d.month - 1]}"


def event_name(p: Person) -> str:
    return html.escape(p.title) if p.kind == "other" else KINDS[p.kind][1]


def describe(p: Person, ref: date) -> str:
    nxt = next_occurrence(p, ref)
    left = (nxt - ref).days
    when = "bugun! 🎉" if left == 0 else "ertaga" if left == 1 else f"{left} kun qoldi"
    n = years_on(p, nxt)
    extra = ""
    if n and p.kind == "birthday":
        extra = f", {n} yosh"
    elif n and p.kind == "anniversary":
        extra = f", {n} yil"
    return f"{KINDS[p.kind][0]} <b>{html.escape(p.name)}</b> — {event_name(p)} {human_day(nxt)} ({when}{extra})"


def prefill_url(p: Person, on: date) -> str:
    params = {"kimga": p.name, "sana": on.isoformat()}
    if p.kind in KIND_SECTION:
        params["s"] = KIND_SECTION[p.kind]
    if p.kind == "birthday" and p.year:
        params["tugilgan_sana"] = occurrence(p.day, p.month, p.year).isoformat()
    return f"{settings.base_url}/app?{urlencode(params)}"


def reminder_text(p: Person, on: date, days_before: int) -> str:
    n = years_on(p, on)
    who = f"<b>{html.escape(p.name)}</b>"
    if p.kind == "birthday":
        what = f"{who}ning tug'ilgan kuni" + (f" — {n} yoshga to'ladi" if n else "")
    elif p.kind == "anniversary":
        what = f"{who} bilan to'y yilligingiz" + (f" — {n} yil" if n else "")
    else:
        what = f"{who}: {html.escape(p.title)}"
    if days_before == 0:
        return f"🎉 Bugun {what}!\n\nHali kech emas — 5 daqiqada chiroyli tabrik sayti tayyorlab, yuboring 💌"
    if days_before == 1:
        return f"⏰ Ertaga ({human_day(on)}) {what}.\n\nTabrik tayyormi? Hozir tayyorlab qo'ysangiz, ertaga ertalab yuborasiz 🎁"
    return f"📅 Bir haftadan keyin ({human_day(on)}) {what}.\n\nOldindan unutilmas tabrik tayyorlab qo'yamizmi? ✨"


def reminder_keyboard(p: Person, on: date) -> InlineKeyboardMarkup:
    kb = InlineKeyboardBuilder()
    if settings.base_url.startswith("https://"):
        kb.button(text="✨ Tabrik tayyorlash", web_app=WebAppInfo(url=prefill_url(p, on)))
    else:
        kb.button(text="✨ Tabrik tayyorlash", callback_data="home")
    kb.button(text="📅 Yaqinlarim", callback_data="people")
    kb.adjust(1)
    return kb.as_markup()


async def send_due(bot, ref: date) -> int:
    """Bugun yuborilishi kerak bo'lgan eslatmalarni yuboradi. Yuborilganlar soni qaytadi."""
    sent = 0
    async with Session() as s:
        people = (await s.execute(select(Person))).scalars().all()
        done = {(r.person_id, r.occurs_on, r.days_before) for r in (await s.execute(select(ReminderLog))).scalars().all()}
        for p in people:
            nxt = next_occurrence(p, ref)
            days_before = (nxt - ref).days
            key = (p.id, nxt.isoformat(), days_before)
            if days_before not in REMIND_DAYS or key in done:
                continue
            try:
                await bot.send_message(p.owner_id, reminder_text(p, nxt, days_before), reply_markup=reminder_keyboard(p, nxt))
                sent += 1
            except Exception:
                log.exception("Eslatma yuborilmadi: person %s", p.id)
            # Xato bo'lsa ham qayd qilamiz: botni bloklagan foydalanuvchiga qayta-qayta urinmaslik uchun
            s.add(ReminderLog(person_id=p.id, occurs_on=nxt.isoformat(), days_before=days_before))
        await s.commit()
    return sent


async def reminder_loop(bot, interval: int = 600) -> None:
    while True:
        try:
            now = datetime.now(TZ)
            if now.hour >= SEND_FROM_HOUR:
                n = await send_due(bot, now.date())
                if n:
                    log.info("Eslatmalar yuborildi: %s", n)
        except Exception:
            log.exception("Eslatmalar tsiklida xato")
        await asyncio.sleep(interval)
