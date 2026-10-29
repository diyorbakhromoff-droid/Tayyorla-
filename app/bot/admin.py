"""Admin vositalari: /stats, /broadcast va musiqa kutubxonasiga kuy qo'shish."""

import asyncio
import html
import logging
import uuid

from aiogram import Bot, F, Router
from aiogram.exceptions import TelegramForbiddenError, TelegramRetryAfter
from aiogram.filters import Command, CommandObject, StateFilter
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.types import CallbackQuery, Message
from aiogram.utils.keyboard import InlineKeyboardBuilder
from sqlalchemy import func, select, update

from ..config import MUSIC_DIR, settings
from ..db import MusicTrack, Session, User
from ..stats import summary
from ..videoapi import MUSIC_THEMES

log = logging.getLogger(__name__)
router = Router()

THEME_TITLES = {"toy": "💍 To'y", "osh": "🍚 Osh", "gap": "🌸 Gap", "choy": "🫖 Choyxona", "tk": "🎂 Tug'ilgan kun",
                "sevgi": "💌 Sevgi", "farzand": "👶 Farzand", "umumiy": "🎵 Umumiy"}
BROADCAST_RATE = 25  # Telegram chegarasi: sekundiga ~30 xabar


def is_admin(uid: int) -> bool:
    return uid in settings.admins


def money(n: int) -> str:
    return f"{n:,}".replace(",", " ") + " so'm"


# ---------------------------------------------------------------- /stats

@router.message(Command("stats"))
async def stats(message: Message):
    if not is_admin(message.from_user.id):
        return
    d = await summary()
    u, v, st, r, q = d["users"], d["videos"], d["sites"], d["revenue"], d["queue"]
    by_sec = ", ".join(f"{k}: {n}" for k, n in sorted(v["by_section"].items(), key=lambda x: -x[1])) or "—"
    by_charge = ", ".join(f"{k}: {n}" for k, n in v["by_charge"].items()) or "—"
    sites_sec = ", ".join(f"{k}: {n}" for k, n in sorted(st["by_section"].items(), key=lambda x: -x[1])) or "—"
    await message.answer(
        "📊 <b>Statistika</b>\n\n"
        f"👤 Foydalanuvchilar: {u['total']} (bugun +{u['today']}, 7 kunda +{u['week']})\n\n"
        f"🎬 Videolar: bugun {v['today']}, 7 kunda {v['week']}, mehmon videolari bugun {v['guest_today']}\n"
        f"   bo'limlar (30 kun): {by_sec}\n   to'lov turi: {by_charge}\n\n"
        f"🌐 Saytlar: {st['total']} (bugun {st['today']}), to'langan {st['paid']}\n   bo'limlar: {sites_sec}\n\n"
        f"💵 Balans to'ldirildi: {money(r['topups_total'])} (bugun {money(r['topups_today'])})\n"
        f"💵 Saytlar tushumi: {money(r['sites_total'])}\n"
        f"📈 Videodan to'lovga o'tganlar: {d['video_to_paid_pct']}%\n\n"
        f"⏳ Navbat: {q['queued']} kutmoqda, {q['rendering']} tayyorlanmoqda, bugun xato {q['failed_today']}"
    )


# ---------------------------------------------------------------- /broadcast

@router.message(Command("broadcast"))
async def broadcast_start(message: Message, command: CommandObject):
    """/broadcast matn — yoki biror xabarga javoban /broadcast (rasm, video ham bo'ladi)."""
    if not is_admin(message.from_user.id):
        return
    src = message.reply_to_message
    if not src and not (command.args or "").strip():
        return await message.answer("Ishlatish: xabarga javoban <code>/broadcast</code> yozing yoki <code>/broadcast matn</code>.")
    if not src:
        src = await message.answer(command.args.strip())
    async with Session() as s:
        n = await s.scalar(select(func.count()).select_from(User).where(User.blocked.is_(False)))
    b = InlineKeyboardBuilder()
    b.button(text=f"📣 {n} kishiga yuborish", callback_data=f"bc:go:{src.chat.id}:{src.message_id}")
    b.button(text="Bekor qilish", callback_data="bc:no")
    b.adjust(1)
    await message.answer(f"Shu xabar {n} ta foydalanuvchiga yuboriladi. Tasdiqlaysizmi?", reply_markup=b.as_markup())


@router.callback_query(F.data == "bc:no")
async def broadcast_cancel(cb: CallbackQuery):
    await cb.message.edit_text("Bekor qilindi.")
    await cb.answer()


@router.callback_query(F.data.startswith("bc:go:"))
async def broadcast_go(cb: CallbackQuery):
    if not is_admin(cb.from_user.id):
        return await cb.answer()
    _, _, chat_id, msg_id = cb.data.split(":")
    await cb.message.edit_text("📣 Yuborish boshlandi...")
    await cb.answer()
    asyncio.create_task(run_broadcast(cb.bot, cb.message.chat.id, cb.message.message_id, int(chat_id), int(msg_id)))


async def run_broadcast(bot: Bot, report_chat: int, report_msg: int, from_chat: int, msg_id: int) -> None:
    async with Session() as s:
        ids = (await s.execute(select(User.tg_id).where(User.blocked.is_(False)))).scalars().all()
    sent = failed = 0
    blocked = []
    for i, uid in enumerate(ids, 1):
        try:
            await bot.copy_message(uid, from_chat, msg_id)
            sent += 1
        except TelegramRetryAfter as e:
            await asyncio.sleep(e.retry_after + 1)
            try:
                await bot.copy_message(uid, from_chat, msg_id)
                sent += 1
            except Exception:
                failed += 1
        except TelegramForbiddenError:
            blocked.append(uid)
            failed += 1
        except Exception:
            failed += 1
        await asyncio.sleep(1 / BROADCAST_RATE)
        if i % 200 == 0:
            try:
                await bot.edit_message_text(f"📣 Yuborilmoqda: {i}/{len(ids)}", chat_id=report_chat, message_id=report_msg)
            except Exception:
                pass
    if blocked:
        async with Session() as s:
            await s.execute(update(User).where(User.tg_id.in_(blocked)).values(blocked=True))
            await s.commit()
    await bot.edit_message_text(f"✅ Tarqatma tugadi: {sent} ta yetdi, {failed} ta yetmadi ({len(blocked)} kishi botni bloklagan).",
                                chat_id=report_chat, message_id=report_msg)


# ---------------------------------------------------------------- musiqa kutubxonasi

class MusicAdd(StatesGroup):
    theme = State()
    kind = State()


@router.message(StateFilter(None), F.audio | F.document.mime_type.startswith("audio/"))
async def music_upload(message: Message, state: FSMContext):
    """Admin botga audio yuborsa — kuylar kutubxonasiga qo'shish taklif qilinadi."""
    if not is_admin(message.from_user.id):
        return
    media = message.audio or message.document
    if (media.file_size or 0) > 20 * 1024 * 1024:
        return await message.answer("Fayl juda katta (20 MB gacha).")
    title = ""
    if message.audio:
        title = " — ".join(x for x in (message.audio.performer, message.audio.title) if x)
    title = title or (getattr(media, "file_name", "") or "Kuy").rsplit(".", 1)[0]
    await state.set_state(MusicAdd.theme)
    await state.update_data(file_id=media.file_id, mime=media.mime_type or "", title=title[:100], caption=(message.caption or "")[:100])
    b = InlineKeyboardBuilder()
    for k in MUSIC_THEMES:
        b.button(text=THEME_TITLES[k], callback_data=f"mus:t:{k}")
    b.button(text="Bekor qilish", callback_data="mus:no")
    b.adjust(2)
    await message.answer(f"🎵 <b>{html.escape(title)}</b>\nKuylar kutubxonasiga qo'shamiz. Qaysi mavzu uchun?", reply_markup=b.as_markup())


@router.callback_query(F.data == "mus:no")
async def music_cancel(cb: CallbackQuery, state: FSMContext):
    await state.clear()
    await cb.message.edit_text("Bekor qilindi.")
    await cb.answer()


@router.callback_query(MusicAdd.theme, F.data.startswith("mus:t:"))
async def music_theme(cb: CallbackQuery, state: FSMContext):
    await state.update_data(theme=cb.data.split(":")[2])
    await state.set_state(MusicAdd.kind)
    b = InlineKeyboardBuilder()
    b.button(text="🎤 Qo'shiq (so'zli)", callback_data="mus:k:vocal")
    b.button(text="🎻 Cholg'u (so'zsiz)", callback_data="mus:k:instr")
    b.adjust(1)
    await cb.message.edit_text(cb.message.html_text + f"\n\nMavzu: {THEME_TITLES[cb.data.split(':')[2]]}\nTuri qanday?", reply_markup=b.as_markup())
    await cb.answer()


@router.callback_query(MusicAdd.kind, F.data.startswith("mus:k:"))
async def music_kind(cb: CallbackQuery, state: FSMContext):
    data = await state.get_data()
    await state.clear()
    ext = {"audio/mp4": "m4a", "audio/x-m4a": "m4a", "audio/ogg": "ogg", "audio/wav": "wav", "audio/x-wav": "wav", "audio/aac": "aac"}.get(data["mime"], "mp3")
    name = f"{uuid.uuid4().hex}.{ext}"
    await cb.bot.download(data["file_id"], destination=MUSIC_DIR / name)
    async with Session() as s:
        t = MusicTrack(title=data["caption"] or data["title"], theme=data["theme"], kind=cb.data.split(":")[2], file=f"/media/music/{name}")
        s.add(t)
        await s.commit()
    await cb.message.edit_text(
        f"✅ Kutubxonaga qo'shildi: <b>{html.escape(t.title)}</b> ({THEME_TITLES[t.theme]}, {'qo‘shiq' if t.kind == 'vocal' else 'cholg‘u'}).\n"
        "Nomini, boshlanish soniyasini yoki holatini Mini App → Profil → Admin panelidan o'zgartirasiz.")
    await cb.answer("✅")
