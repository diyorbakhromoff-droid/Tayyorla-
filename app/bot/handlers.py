import asyncio
import html
import logging
import re
import uuid
from collections import defaultdict

from aiogram import Bot, F, Router
from aiogram.enums import ChatAction
from aiogram.filters import Command, CommandStart
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.types import CallbackQuery, Message
from sqlalchemy import select

from .. import ai
from ..config import MEDIA_DIR, settings
from ..db import Rsvp, Session, Site, new_slug
from ..render import parse_date
from ..sites import CATEGORIES, PALETTES, build_config
from . import keyboards as kb

log = logging.getLogger(__name__)
router = Router()

MAX_PHOTOS = 10
MAX_FILE = 20 * 1024 * 1024  # Telegram Bot API yuklab olish chegarasi
_locks: dict[int, asyncio.Lock] = defaultdict(asyncio.Lock)


class Form(StatesGroup):
    step = State()
    ai_brief = State()


class Edit(StatesGroup):
    waiting = State()


class Pay(StatesGroup):
    receipt = State()


# ---------------------------------------------------------------- yordamchilar

async def save_media(bot: Bot, file_id: str, ext: str) -> str:
    name = f"{uuid.uuid4().hex}.{ext}"
    await bot.download(file_id, destination=MEDIA_DIR / name)
    return f"/media/{name}"


async def load_site(site_id: int, user_id: int) -> Site | None:
    async with Session() as s:
        site = await s.get(Site, site_id)
    if site and (site.owner_id == user_id or user_id in settings.admins):
        return site
    return None


def site_card(site: Site) -> str:
    cat = CATEGORIES[site.category]
    status = {"draft": "📝 Namuna (to'lanmagan)", "pending": "⏳ To'lov tekshirilmoqda", "paid": "✅ Faol"}[site.status]
    left = settings.max_edits - site.edits_used
    return (
        f"<b>{cat.title}</b>\n"
        f"Holati: {status}\n"
        f"🔗 {site.url}\n"
        f"✏️ Qolgan tahrirlar: {left}"
    )


def current_step(data: dict):
    return CATEGORIES[data["category"]].steps[data["idx"]]


async def ask(message: Message, state: FSMContext) -> None:
    data = await state.get_data()
    steps = CATEGORIES[data["category"]].steps
    if data["idx"] >= len(steps):
        await finish(message, state)
        return
    step = steps[data["idx"]]
    await state.set_state(Form.step)
    progress = f"<i>{data['idx'] + 1}/{len(steps)}</i>\n"
    markup = None
    if step.kind == "message":
        markup = kb.message_mode()
    elif step.kind == "photos":
        markup = kb.done("✅ Tayyor" if data["answers"].get("photos") else "⏭ Rasmsiz davom etish")
    elif step.kind == "palette":
        markup = kb.palettes()
    elif step.kind == "features":
        cat = CATEGORIES[data["category"]]
        enabled = data["answers"].setdefault("features", list(cat.default_features))
        await state.update_data(answers=data["answers"])
        markup = kb.features(data["category"], enabled)
    elif step.optional:
        markup = kb.skip()
    await message.answer(progress + step.prompt, reply_markup=markup)


async def answer_and_next(message: Message, state: FSMContext, value) -> None:
    data = await state.get_data()
    step = current_step(data)
    data["answers"][step.key] = value
    await state.update_data(answers=data["answers"], idx=data["idx"] + 1, msg_mode=None)
    await ask(message, state)


async def finish(message: Message, state: FSMContext) -> None:
    data = await state.get_data()
    await state.clear()
    cfg = build_config(data["category"], data["answers"])
    user = message.chat
    async with Session() as s:
        site = Site(slug=new_slug(), owner_id=user.id, owner_name=user.full_name or "", category=data["category"], config=cfg)
        s.add(site)
        await s.commit()
    await message.answer(
        "🎉 <b>Saytingiz tayyor!</b>\n\n"
        "Hozir u <b>namuna</b> holatida, ustida «NAMUNA» yozuvi bor. Ko'rib chiqing, "
        "biror joyini o'zgartirmoqchi bo'lsangiz «✏️ Tahrirlash» ni bosib, o'z so'zingiz bilan yozing.\n\n"
        "Hammasi yoqsa, to'lov qilib toza linkni oling va yaqiningizga yuboring 💌\n\n" + site_card(site),
        reply_markup=kb.site_actions(site),
    )


# ---------------------------------------------------------------- start / menyu

WELCOME = (
    "Assalomu alaykum, {name}! 👋\n\n"
    "<b>Tayyorla</b> — yaqinlaringiz uchun unutilmas tabrik saytlarini bir necha daqiqada tayyorlaydi:\n"
    "🎂 tug'ilgan kun tabriklari\n💍 to'y taklifnomalari\n💌 sevgi maktublari\n\n"
    "Konvert ochilishi, konfetti, musiqa, rasmlar, taymerlar va boshqa ko'plab sehrli elementlar bilan ✨\n\n"
    "Qaysi birini tayyorlaymiz?"
)


@router.message(CommandStart())
async def start(message: Message, state: FSMContext):
    await state.clear()
    await message.answer(WELCOME.format(name=html.escape(message.from_user.first_name or "")), reply_markup=kb.main_menu())


@router.callback_query(F.data == "home")
async def home(cb: CallbackQuery, state: FSMContext):
    await state.clear()
    await cb.message.answer("Qaysi saytni tayyorlaymiz?", reply_markup=kb.main_menu())
    await cb.answer()


@router.message(Command("help"))
async def help_cmd(message: Message):
    await message.answer(
        "ℹ️ <b>Qanday ishlaydi?</b>\n"
        "1. Sayt turini tanlang va savollarga javob bering.\n"
        "2. Namunani ko'ring, xohlasangiz o'z so'zingiz bilan tahrir qiling.\n"
        f"3. {kb.money(settings.price)} to'lab, toza linkni oling va ulashing.\n\n"
        "/start — bosh menyu\n/mysites — mening saytlarim"
    )


@router.callback_query(F.data.startswith("cat:"))
async def choose_category(cb: CallbackQuery, state: FSMContext):
    key = cb.data.split(":", 1)[1]
    cat = CATEGORIES[key]
    await state.clear()
    await state.update_data(category=key, idx=0, answers={})
    await cb.message.answer(cat.intro)
    await ask(cb.message, state)
    await cb.answer()


# ---------------------------------------------------------------- savollar

@router.callback_query(Form.step, F.data == "skip")
async def skip_step(cb: CallbackQuery, state: FSMContext):
    data = await state.get_data()
    step = current_step(data)
    if not step.optional:
        await cb.answer("Bu savol majburiy", show_alert=True)
        return
    await cb.answer()
    await answer_and_next(cb.message, state, None)


@router.message(Form.step, F.text & ~F.text.startswith("/"))
async def text_answer(message: Message, state: FSMContext):
    data = await state.get_data()
    step = current_step(data)
    text = message.text.strip()

    if step.kind == "message":
        if data.get("msg_mode") != "own":
            await message.answer("Avval tanlang: matnni AI yozsinmi yoki o'zingiz yozasizmi? 👇", reply_markup=kb.message_mode())
            return
        await answer_and_next(message, state, text[:3000])
    elif step.kind in ("photos", "music", "palette", "features"):
        await message.answer("Iltimos, yuqoridagi tugmalardan foydalaning 👆")
    elif step.kind == "number":
        if not text.isdigit() or not 0 < int(text) < 150:
            await message.answer("Iltimos, faqat raqam yozing (masalan: 25)")
            return
        await answer_and_next(message, state, text)
    elif step.kind == "date":
        if not parse_date(text):
            await message.answer("Sanani kun.oy.yil ko'rinishida yozing, masalan: 25.12.2026")
            return
        await answer_and_next(message, state, text)
    elif step.kind == "time":
        if not re.fullmatch(r"\d{1,2}[:.]\d{2}", text):
            await message.answer("Vaqtni soat:daqiqa ko'rinishida yozing, masalan: 18:00")
            return
        await answer_and_next(message, state, text.replace(".", ":"))
    else:
        await answer_and_next(message, state, text[:300])


@router.message(Form.step, F.location)
async def location_answer(message: Message, state: FSMContext):
    data = await state.get_data()
    if current_step(data).kind != "location":
        return
    data["answers"]["lat"] = str(message.location.latitude)
    data["answers"]["lon"] = str(message.location.longitude)
    await state.update_data(answers=data["answers"])
    await message.answer("📍 Joylashuv saqlandi. Endi manzilni so'z bilan ham yozing (masalan: «Yunusobod, Amir Temur 108»):")


# --- tabrik matni

@router.callback_query(Form.step, F.data == "msg:own")
async def msg_own(cb: CallbackQuery, state: FSMContext):
    await state.update_data(msg_mode="own")
    await cb.message.answer("✍️ Matnni yozib yuboring. Xatboshilarni yangi qatordan boshlashingiz mumkin.")
    await cb.answer()


@router.callback_query(Form.step, F.data == "msg:ai")
async def msg_ai(cb: CallbackQuery, state: FSMContext):
    await state.set_state(Form.ai_brief)
    await cb.message.answer(
        "✨ Ajoyib! Matn yanada samimiy chiqishi uchun qisqacha yozing:\n"
        "• u qanday inson (xarakteri, sevimli mashg'uloti)\n"
        "• birga o'tgan esda qolarli lahzalar\n"
        "• uslub: rasmiy, samimiy yoki hazilomuz\n\n"
        "Masalan: «Onam, juda mehribon, shirin taomlar pishiradi, samimiy uslubda bo'lsin»"
    )
    await cb.answer()


async def generate(message: Message, state: FSMContext, previous: str | None = None):
    data = await state.get_data()
    wait = await message.answer("✍️ Yozyapman, bir oz kuting...")
    await message.bot.send_chat_action(message.chat.id, ChatAction.TYPING)
    try:
        text = await ai.write_message(data["category"], data["answers"], data.get("brief", ""), previous)
    except Exception:
        log.exception("AI matn yozishda xato")
        await wait.edit_text("😔 Hozir matn yozib bo'lmadi. Qayta urinib ko'ring yoki o'zingiz yozing.", reply_markup=kb.message_mode())
        await state.set_state(Form.step)
        return
    await state.set_state(Form.step)
    await state.update_data(ai_text=text)
    await wait.edit_text(f"💬 <b>Variant:</b>\n\n{html.escape(text)}", reply_markup=kb.ai_review())


@router.message(Form.ai_brief, F.text)
async def ai_brief(message: Message, state: FSMContext):
    await state.update_data(brief=message.text[:1000])
    await generate(message, state)


@router.callback_query(Form.step, F.data == "ai:again")
async def ai_again(cb: CallbackQuery, state: FSMContext):
    await cb.answer()
    data = await state.get_data()
    await generate(cb.message, state, previous=data.get("ai_text"))


@router.callback_query(Form.step, F.data == "ai:ok")
async def ai_ok(cb: CallbackQuery, state: FSMContext):
    data = await state.get_data()
    await cb.answer("Saqlandi ✅")
    await cb.message.edit_reply_markup(reply_markup=None)
    await answer_and_next(cb.message, state, data.get("ai_text", ""))


# --- rasmlar va musiqa

@router.message(Form.step, F.photo)
async def photo_answer(message: Message, state: FSMContext):
    async with _locks[message.chat.id]:
        data = await state.get_data()
        if current_step(data).kind != "photos":
            await message.answer("Rasmlarni keyinroq, tegishli qadamda so'raymiz 🙂")
            return
        photos = data["answers"].setdefault("photos", [])
        if len(photos) >= MAX_PHOTOS:
            await message.answer(f"Ko'pi bilan {MAX_PHOTOS} ta rasm qo'shish mumkin.", reply_markup=kb.done())
            return
        photos.append(await save_media(message.bot, message.photo[-1].file_id, "jpg"))
        await state.update_data(answers=data["answers"])
        await message.answer(f"📸 {len(photos)} ta rasm qabul qilindi. Yana yuboring yoki «Tayyor» ni bosing.", reply_markup=kb.done())


@router.message(Form.step, F.audio | F.voice | F.document)
async def music_answer(message: Message, state: FSMContext):
    data = await state.get_data()
    if current_step(data).kind != "music":
        return
    media = message.audio or message.voice or message.document
    mime = getattr(media, "mime_type", "") or ""
    if message.document and not mime.startswith("audio/"):
        await message.answer("Bu audio fayl emas. Iltimos, mp3 yuboring.")
        return
    if (media.file_size or 0) > MAX_FILE:
        await message.answer("Fayl juda katta (20 MB dan oshmasin).")
        return
    ext = "ogg" if message.voice else ("m4a" if "mp4" in mime else "mp3")
    path = await save_media(message.bot, media.file_id, ext)
    await message.answer("🎵 Musiqa qabul qilindi!")
    await answer_and_next(message, state, path)


@router.callback_query(Form.step, F.data == "done")
async def step_done(cb: CallbackQuery, state: FSMContext):
    data = await state.get_data()
    step = current_step(data)
    await cb.answer()
    await cb.message.edit_reply_markup(reply_markup=None)
    if step.kind == "photos":
        await answer_and_next(cb.message, state, data["answers"].get("photos", []))
    elif step.kind == "features":
        await cb.message.answer("⏳ Saytingizni yig'yapman...")
        await answer_and_next(cb.message, state, data["answers"]["features"])


@router.callback_query(Form.step, F.data.startswith("pal:"))
async def palette_answer(cb: CallbackQuery, state: FSMContext):
    key = cb.data.split(":", 1)[1]
    await cb.answer(PALETTES[key]["title"])
    await cb.message.edit_text(f"🎨 Tanlandi: {PALETTES[key]['title']}")
    await answer_and_next(cb.message, state, key)


@router.callback_query(Form.step, F.data.startswith("feat:"))
async def feature_toggle(cb: CallbackQuery, state: FSMContext):
    key = cb.data.split(":", 1)[1]
    data = await state.get_data()
    enabled = data["answers"]["features"]
    if key in enabled:
        enabled.remove(key)
    else:
        enabled.append(key)
    await state.update_data(answers=data["answers"])
    await cb.message.edit_reply_markup(reply_markup=kb.features(data["category"], enabled))
    await cb.answer()


# ---------------------------------------------------------------- mening saytlarim

@router.message(Command("mysites"))
@router.callback_query(F.data == "my")
async def my_sites(event: Message | CallbackQuery, state: FSMContext):
    message = event.message if isinstance(event, CallbackQuery) else event
    await state.clear()
    async with Session() as s:
        sites = (await s.execute(select(Site).where(Site.owner_id == event.from_user.id).order_by(Site.id.desc()).limit(10))).scalars().all()
    if not sites:
        await message.answer("Sizda hali sayt yo'q. Keling, birinchisini yaratamiz! 👇", reply_markup=kb.main_menu())
    for site in sites:
        await message.answer(site_card(site), reply_markup=kb.site_actions(site))
    if isinstance(event, CallbackQuery):
        await event.answer()


@router.callback_query(F.data.startswith("site:"))
async def show_site(cb: CallbackQuery, state: FSMContext):
    await state.clear()
    site = await load_site(int(cb.data.split(":")[1]), cb.from_user.id)
    if site:
        await cb.message.answer(site_card(site), reply_markup=kb.site_actions(site))
    await cb.answer()


@router.callback_query(F.data.startswith("guests:"))
async def guests(cb: CallbackQuery):
    site = await load_site(int(cb.data.split(":")[1]), cb.from_user.id)
    if not site:
        return await cb.answer()
    async with Session() as s:
        rows = (await s.execute(select(Rsvp).where(Rsvp.site_id == site.id).order_by(Rsvp.id))).scalars().all()
    if not rows:
        await cb.message.answer("Hali hech kim javob bermadi. Linkni mehmonlarga yuboring 💌")
        return await cb.answer()
    yes = [r for r in rows if r.attending]
    lines = [f"📋 <b>Mehmonlar</b>: {len(yes)} ta oila, jami {sum(r.guests for r in yes)} kishi keladi\n"]
    for r in rows:
        lines.append(f"{'✅' if r.attending else '❌'} {html.escape(r.name)}" + (f" — {r.guests} kishi" if r.attending else ""))
    await cb.message.answer("\n".join(lines)[:4000])
    await cb.answer()


# ---------------------------------------------------------------- tahrirlash

@router.callback_query(F.data.startswith("edit:"))
async def edit_start(cb: CallbackQuery, state: FSMContext):
    site = await load_site(int(cb.data.split(":")[1]), cb.from_user.id)
    if not site:
        return await cb.answer()
    if site.edits_used >= settings.max_edits:
        return await cb.answer("Bepul tahrirlar tugadi", show_alert=True)
    await state.clear()
    await state.set_state(Edit.waiting)
    await state.update_data(site_id=site.id)
    await cb.message.answer(
        "✏️ <b>Tahrirlash rejimi</b>\n\n"
        "Nimani o'zgartirishni o'z so'zingiz bilan yozing. Masalan:\n"
        "• «Fonni och havorang qil, matnni kattaroq qil»\n"
        "• «Tabrik matniga buvisini ham qo'sh»\n"
        "• «Sarlavhani 'Eng aziz onajonim' deb o'zgartir»\n"
        "• «Taymerni olib tashla, ikkinchi rasmni o'chir»\n\n"
        "📸 Yangi rasm qo'shish uchun shunchaki rasm yuboring.",
        reply_markup=kb.edit_mode(),
    )
    await cb.answer()


@router.message(Edit.waiting, F.text & ~F.text.startswith("/"))
async def edit_request(message: Message, state: FSMContext):
    site_id = (await state.get_data())["site_id"]
    site = await load_site(site_id, message.from_user.id)
    if not site:
        return await state.clear()
    if site.edits_used >= settings.max_edits:
        await state.clear()
        return await message.answer("Bepul tahrirlar soni tugadi 🙏", reply_markup=kb.site_actions(site))
    wait = await message.answer("🪄 O'zgartiryapman, bir oz kuting...")
    await message.bot.send_chat_action(message.chat.id, ChatAction.TYPING)
    try:
        new_config, reply = await ai.apply_edit(site.config, message.text[:1500])
    except Exception:
        log.exception("AI tahrirda xato")
        return await wait.edit_text("😔 Hozir o'zgartirib bo'lmadi. Birozdan so'ng qayta urinib ko'ring.", reply_markup=kb.edit_mode())
    async with Session() as s:
        db_site = await s.get(Site, site.id)
        db_site.config = new_config
        db_site.edits_used += 1
        await s.commit()
        site = db_site
    left = settings.max_edits - site.edits_used
    await wait.edit_text(
        f"✅ {html.escape(reply)}\n\n🔗 {site.url}\n✏️ Qolgan tahrirlar: {left}\n\nYana nimadir o'zgartiramizmi? Yozing yoki tugating.",
        reply_markup=kb.edit_mode(),
    )


@router.message(Edit.waiting, F.photo)
async def edit_photo(message: Message, state: FSMContext):
    async with _locks[message.chat.id]:
        site_id = (await state.get_data())["site_id"]
        async with Session() as s:
            site = await s.get(Site, site_id)
            if not site or site.owner_id != message.from_user.id:
                return
            photos = list(site.config.get("photos", []))
            if len(photos) >= MAX_PHOTOS:
                return await message.answer(f"Ko'pi bilan {MAX_PHOTOS} ta rasm bo'lishi mumkin.")
            photos.append(await save_media(message.bot, message.photo[-1].file_id, "jpg"))
            cfg = dict(site.config, photos=photos)
            cfg["features"] = dict(cfg["features"], gallery=True)
            site.config = cfg
            await s.commit()
    await message.answer(f"📸 Rasm qo'shildi (jami {len(photos)} ta). Bu tahrir hisobiga kirmaydi.", reply_markup=kb.edit_mode())


@router.callback_query(F.data == "edit_done")
async def edit_done(cb: CallbackQuery, state: FSMContext):
    data = await state.get_data()
    await state.clear()
    site = await load_site(data.get("site_id", 0), cb.from_user.id)
    if site:
        await cb.message.answer(site_card(site), reply_markup=kb.site_actions(site))
    await cb.answer()


# ---------------------------------------------------------------- to'lov

@router.callback_query(F.data.startswith("buy:"))
async def buy(cb: CallbackQuery):
    site = await load_site(int(cb.data.split(":")[1]), cb.from_user.id)
    if not site:
        return await cb.answer()
    await cb.message.answer(
        f"💳 <b>To'lov: {kb.money(settings.price)}</b>\n\n"
        "1. «To'lash» tugmasini bosing va istalgan ilova (Click, Payme, Uzum va b.) orqali to'lang.\n"
        "2. To'lovdan so'ng «✅ To'ladim» ni bosing va chek skrinshotini yuboring.\n\n"
        "Tekshiruvdan so'ng toza link darhol sizga yuboriladi ✨",
        reply_markup=kb.pay(site.id),
    )
    await cb.answer()


@router.callback_query(F.data.startswith("paid:"))
async def paid(cb: CallbackQuery, state: FSMContext):
    site_id = int(cb.data.split(":")[1])
    await state.set_state(Pay.receipt)
    await state.update_data(site_id=site_id)
    await cb.message.answer("🧾 To'lov chekining skrinshotini yuboring:")
    await cb.answer()


@router.message(Pay.receipt, F.photo | F.document)
async def receipt(message: Message, state: FSMContext):
    site_id = (await state.get_data())["site_id"]
    await state.clear()
    async with Session() as s:
        site = await s.get(Site, site_id)
        if not site or site.owner_id != message.from_user.id:
            return
        site.status = "pending"
        await s.commit()
    user = message.from_user
    caption = (
        f"💰 <b>Yangi to'lov</b> #{site.id}\n"
        f"👤 {html.escape(user.full_name)} (@{user.username or '-'}, id {user.id})\n"
        f"📦 {CATEGORIES[site.category].title}\n💵 {kb.money(settings.price)}\n🔗 {site.url}"
    )
    for admin in settings.admins:
        try:
            await message.copy_to(admin)
            await message.bot.send_message(admin, caption, reply_markup=kb.admin_review(site.id))
        except Exception:
            log.exception("Adminga yuborib bo'lmadi: %s", admin)
    await message.answer("✅ Rahmat! Chek qabul qilindi. Tekshiruvdan so'ng link shu yerga keladi (odatda bir necha daqiqa) ⏳")


@router.message(Pay.receipt)
async def receipt_wrong(message: Message):
    await message.answer("Iltimos, chek skrinshotini rasm ko'rinishida yuboring 🧾")


@router.callback_query(F.data.startswith(("approve:", "reject:")))
async def admin_decision(cb: CallbackQuery):
    if cb.from_user.id not in settings.admins:
        return await cb.answer("Ruxsat yo'q", show_alert=True)
    action, site_id = cb.data.split(":")
    async with Session() as s:
        site = await s.get(Site, int(site_id))
        if not site:
            return await cb.answer("Topilmadi")
        if site.status == "paid":
            return await cb.answer("Allaqachon tasdiqlangan")
        site.status = "paid" if action == "approve" else "draft"
        await s.commit()
    if action == "approve":
        await cb.bot.send_message(
            site.owner_id,
            "🎉 <b>To'lov tasdiqlandi!</b>\n\n"
            f"Mana sizning saytingiz:\n{site.url}\n\n"
            "Linkni nusxalab, yaqiningizga yuboring 💌 U birinchi marta ochganda sizga xabar beramiz 👀",
            reply_markup=kb.site_actions(site),
        )
        await cb.message.edit_text(cb.message.html_text + "\n\n✅ <b>Tasdiqlandi</b>")
    else:
        await cb.bot.send_message(
            site.owner_id,
            "😔 To'lov tasdiqlanmadi. Agar to'lagan bo'lsangiz, chekni qayta yuboring yoki administratorga yozing.",
            reply_markup=kb.site_actions(site),
        )
        await cb.message.edit_text(cb.message.html_text + "\n\n❌ <b>Rad etildi</b>")
    await cb.answer()


# ---------------------------------------------------------------- admin

@router.message(Command("stats"))
async def stats(message: Message):
    if message.from_user.id not in settings.admins:
        return
    async with Session() as s:
        sites = (await s.execute(select(Site))).scalars().all()
    paid = [x for x in sites if x.paid]
    await message.answer(
        f"📊 Jami saytlar: {len(sites)}\n✅ To'langan: {len(paid)}\n"
        f"⏳ Kutilmoqda: {sum(x.status == 'pending' for x in sites)}\n"
        f"💵 Tushum: {kb.money(len(paid) * settings.price)}"
    )
