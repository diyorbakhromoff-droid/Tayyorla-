"""Narxlar, qo'shiq paketlari va namunadan keyingi chegirma — admin paneldan boshqariladi.

- Asosiy narxlar (qo'shiq, video, sayt tariflari) bazada saqlanadi va `settings` ga qo'llanadi:
  ilova, bot va oferta sahifasi darhol yangi narxni ko'radi.
- Paket: N ta qo'shiq bir narxda. Sotib olinganda foydalanuvchiga N ta «qo'shiq krediti» yoziladi;
  keyingi qo'shiqlar shu kreditdan to'lanadi (pul yechilmaydi). Muddatsiz.
- Chegirma: namuna olib, sotib olmagan qo'shiqqa `delay` soatdan keyin bir marta beriladi,
  `hours` soat amal qiladi (bot xabari + ilovada vaqt sanog'i). Faqat bitta qo'shiq xaridiga.
"""

import asyncio
import logging
import uuid
from datetime import datetime, timedelta, timezone

from aiogram.types import InlineKeyboardButton, InlineKeyboardMarkup, WebAppInfo
from sqlalchemy import select, update

from . import billing, store
from .config import settings
from .db import BalanceTx, Session, Song, User, utcnow

log = logging.getLogger(__name__)

KEY = "pricing"
# narx kaliti -> settings maydoni
PRICE_KEYS = {"song": "song_price", "video": "video_price", "standart": "price_standart", "premium": "price_premium", "vip": "price_vip"}
BASE = {k: getattr(settings, a) for k, a in PRICE_KEYS.items()}  # .env dagi boshlang'ich qiymatlar
DEFAULT_PACKS = [
    {"n": 2, "price": 99000, "label": "", "on": True},
    {"n": 3, "price": 129000, "label": "Ommabop", "on": True},
    {"n": 5, "price": 189000, "label": "", "on": True},
    {"n": 10, "price": 349000, "label": "Eng foydali", "on": True},
]
DEFAULT_PROMO = {"on": True, "price": 39000, "hours": 12, "delay": 1, "reminders": [360, 120, 30]}  # eslatmalar: tugashiga necha daqiqa qolganda
FRESH_HOURS = 48  # shundan eski namunalarga chegirma taklif qilinmaydi (ishga tushganda eski mijozlarga yoppasiga ketmasin)
TZ = timezone(timedelta(hours=5))


class PriceError(ValueError):
    pass


def _int(v, lo: int, hi: int, name: str) -> int:
    try:
        n = int(v)
    except (TypeError, ValueError):
        raise PriceError(f"{name}: son kiriting")
    if not lo <= n <= hi:
        raise PriceError(f"{name}: {lo:,} — {hi:,} oralig'ida bo'lsin".replace(",", " "))
    return n


def clean(raw: dict | None) -> dict:
    """Bazadagi (yoki admin yuborgan) qiymatni tekshirib, to'liq konfiguratsiyaga aylantiradi."""
    raw = raw or {}
    prices = {**BASE, **{k: v for k, v in (raw.get("prices") or {}).items() if k in PRICE_KEYS}}
    prices = {k: _int(v, 1000, 10_000_000, k) for k, v in prices.items()}
    packs, seen = [], set()
    for p in raw.get("packs", DEFAULT_PACKS) or []:
        n = _int(p.get("n"), 2, 50, "Paket soni")
        if n in seen:
            raise PriceError(f"{n} talik paket ikki marta yozilgan")
        seen.add(n)
        packs.append({"n": n, "price": _int(p.get("price"), 1000, 10_000_000, f"{n} talik paket narxi"),
                      "label": str(p.get("label") or "").strip()[:20], "on": bool(p.get("on", True))})
    packs.sort(key=lambda x: x["n"])
    pr = {**DEFAULT_PROMO, **(raw.get("promo") or {})}
    promo = {"on": bool(pr["on"]), "price": _int(pr["price"], 1000, 10_000_000, "Chegirma narxi"),
             "hours": _int(pr["hours"], 1, 168, "Chegirma muddati"), "delay": _int(pr["delay"], 0, 72, "Taklif vaqti")}
    rem = sorted({_int(m, 5, 10080, "Eslatma vaqti") for m in (pr.get("reminders") or [])}, reverse=True)
    promo["reminders"] = [m for m in rem if m < promo["hours"] * 60][:5]  # muddatdan uzun eslatma ma'nosiz
    if promo["price"] >= prices["song"]:
        raise PriceError("Chegirma narxi qo'shiqning oddiy narxidan kichik bo'lishi kerak")
    return {"prices": prices, "packs": packs, "promo": promo}


async def config() -> dict:
    raw = await store.get(KEY, {})
    try:
        return clean(raw)
    except PriceError:
        log.exception("Narx sozlamalari buzilgan — standart qiymatlar ishlatiladi")
        return clean({})


def _apply(cfg: dict) -> None:
    for k, attr in PRICE_KEYS.items():
        setattr(settings, attr, cfg["prices"][k])


async def apply() -> dict:
    """Ishga tushganda: bazadagi narxlarni settings ga qo'yadi."""
    cfg = await config()
    _apply(cfg)
    return cfg


async def save(raw: dict) -> dict:
    cfg = clean(raw)
    await store.put(KEY, cfg)
    _apply(cfg)
    return cfg


def packs_public(cfg: dict) -> list[dict]:
    one = cfg["prices"]["song"]
    out = []
    for p in cfg["packs"]:
        if not p["on"]:
            continue
        each = p["price"] // p["n"]
        out.append({**p, "each": each, "off": max(0, round(100 - 100 * p["price"] / (one * p["n"])))})
    return out


def promo_of(song: Song, now: datetime | None = None) -> dict | None:
    """Faol chegirma: {"price", "until"} yoki None."""
    now = now or utcnow()
    if song.paid or not song.promo_until or not song.promo_price or song.promo_until <= now:
        return None
    return {"price": song.promo_price, "until": song.promo_until.replace(tzinfo=timezone.utc).isoformat()}


# ---------------------------------------------------------------- paketlar

async def buy_pack(s, uid: int, n: int) -> bool | None:
    """Paketni balansdan sotib oladi. None — bunday paket yo'q, False — balans yetmaydi."""
    cfg = await config()
    pack = next((p for p in cfg["packs"] if p["n"] == n and p["on"]), None)
    if not pack:
        return None
    if not await billing.spend(s, uid, pack["price"], "song_pack", f"pack:{n}:{uuid.uuid4().hex[:8]}"):
        return False
    await s.execute(update(User).where(User.tg_id == uid).values(song_credits=User.song_credits + n)
                    .execution_options(synchronize_session="fetch"))
    return True


async def pack_price(n: int) -> int | None:
    cfg = await config()
    pack = next((p for p in cfg["packs"] if p["n"] == n and p["on"]), None)
    return pack["price"] if pack else None


async def use_credit(s, uid: int, song: Song) -> bool:
    """Paketdagi bitta qo'shiqni ishlatadi (atomik). Kredit bo'lmasa False."""
    res = await s.execute(update(User).where(User.tg_id == uid, User.song_credits > 0)
                          .values(song_credits=User.song_credits - 1).execution_options(synchronize_session="fetch"))
    if res.rowcount != 1:
        return False
    s.add(BalanceTx(user_id=uid, amount=0, kind="song_credit", ref=f"song:{song.id}"))
    return True


# ---------------------------------------------------------------- chegirma: taklif qilish

def _keyboard(song: Song, price: int) -> InlineKeyboardMarkup:
    from .videobot import app_url, money
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text=f"🎧 Qo‘shiqni olish — {money(price)}", web_app=WebAppInfo(url=app_url(song=song.id)))],
        [InlineKeyboardButton(text="🎟 Qo‘shiq paketlari", web_app=WebAppInfo(url=app_url(song=song.id, packs=1)))],
    ])


async def offer_due(bot, now: datetime | None = None) -> int:
    """Chegirma vaqti kelgan qo'shiqlarga chegirma beradi va botga xabar yuboradi. Yuborilganlar soni."""
    cfg = await config()
    promo = cfg["promo"]
    if not promo["on"]:
        return 0
    now = now or utcnow()
    from .nudges import config as ncfg, in_hours
    hours = await ncfg()
    if not in_hours(hours, now.replace(tzinfo=timezone.utc).astimezone(TZ)):
        return 0  # kechasi yubormaymiz — ertalab davom etadi
    async with Session() as s:
        rows = (await s.execute(select(Song).where(
            Song.status == "preview_ready", Song.paid.is_(False), Song.promo_until.is_(None),
            Song.preview_at.is_not(None), Song.preview_at <= now - timedelta(hours=promo["delay"]),
            Song.preview_at >= now - timedelta(hours=FRESH_HOURS)).order_by(Song.id).limit(200))).scalars().all()
        picked = []
        seen_users = set()
        for song in rows:
            user = await s.get(User, song.owner_id)
            if not user or user.blocked or user.song_credits > 0 or song.owner_id in seen_users:
                continue
            seen_users.add(song.owner_id)  # bir odamga bir aylanishda bitta xabar
            song.promo_until, song.promo_price, song.promo_sent = _end_in_hours(now + timedelta(hours=promo["hours"]), hours, promo), promo["price"], 0
            picked.append((song, user))
        await s.commit()
    sent = 0
    for song, user in picked:
        if not bot:
            break
        until = song.promo_until.replace(tzinfo=timezone.utc).astimezone(TZ)
        day = "bugun" if until.date() == now.replace(tzinfo=timezone.utc).astimezone(TZ).date() else "ertaga"
        name = (user.first_name or "").strip()
        from .videobot import money
        text = (f"🎁 <b>{name + ', ' if name else ''}«{song.title or 'Qo‘shiq'}» qo‘shig‘ingiz sizni kutyapti!</b>\n\n"
                f"Faqat siz uchun {promo['hours']} soatlik chegirma:\n<s>{money(settings.song_price)}</s> → <b>{money(promo['price'])}</b>\n\n"
                f"⏳ Chegirma <b>{day} {until:%H:%M}</b> gacha amal qiladi. Keyin narx odatdagidek {money(settings.song_price)} bo‘ladi.")
        try:
            await bot.send_message(song.owner_id, text, reply_markup=_keyboard(song, promo["price"]))
            sent += 1
        except Exception:
            log.warning("Chegirma xabarini yuborib bo'lmadi: %s", song.owner_id)
        await asyncio.sleep(0.05)
    return sent


def _end_in_hours(end: datetime, hours: dict, promo: dict) -> datetime:
    """Chegirma tunda tugasa, eslatmalar yuborilmay qoladi: tugashni ertasi kuni ertalabga suramiz —
    eng birinchi eslatma ish vaqti boshlanganda chiqadigan qilib (masalan 9:00 + 6 soat = 15:00)."""
    loc = end.replace(tzinfo=timezone.utc).astimezone(TZ)
    h = loc.hour + loc.minute / 60
    if hours["from_hour"] <= h <= hours["to_hour"]:
        return end
    day = loc.date() if h < hours["from_hour"] else loc.date() + timedelta(days=1)
    first = max(promo["reminders"] or [0])
    start = datetime(day.year, day.month, day.day, hours["from_hour"], tzinfo=TZ) + timedelta(minutes=first)
    return start.astimezone(timezone.utc).replace(tzinfo=None)


def _left_text(minutes: int) -> str:
    if minutes < 60:
        return f"{max(5, minutes // 5 * 5)} daqiqa"
    h, m = divmod(minutes, 60)
    return f"{h} soat" + (f" {m} daqiqa" if m >= 10 and h < 3 else "")


def reminder_text(stage: int, last: bool, name: str, song: Song, left: int) -> str:
    from .videobot import money
    who = f"{name}, " if name else ""
    title = song.title or "Qo‘shiq"
    for_whom = f"{song.recipient} uchun qo‘shiq" if song.recipient else "Qo‘shig‘ingiz"
    reg, pr, lt = money(settings.song_price), money(song.promo_price), _left_text(left)
    if last:
        return (f"⚠️ <b>{who}oxirgi imkoniyat!</b>\n\nChegirma <b>{lt}dan keyin</b> tugaydi.\n"
                f"«{title}» hozir <b>{pr}</b> — keyin {reg} bo‘ladi.\n\nBir bosishda oling 👇")
    if stage == 0:
        return (f"⏰ <b>{who}chegirma tugashiga {lt} qoldi!</b>\n\n{for_whom} tayyor turibdi — «{title}».\n"
                f"Hozir <b>{pr}</b>, chegirma tugagach {reg}.")
    return (f"🔥 <b>Atigi {lt} qoldi!</b>\n\n{who}«{title}» qo‘shig‘ini hali ham <b>{pr}</b>ga olishingiz mumkin. "
            f"Yaqiningizni quvontiradigan sovg‘a bir bosishda tayyor bo‘ladi.\n\nKeyin narx {reg}ga qaytadi.")


async def remind_due(bot, now: datetime | None = None) -> int:
    """Chegirma tugashidan oldin eslatmalar (masalan 6 soat, 2 soat, 30 daqiqa qolganda). Yuborilganlar soni."""
    cfg = await config()
    stages = cfg["promo"]["reminders"]
    if not stages or not bot:
        return 0
    now = now or utcnow()
    from .nudges import config as ncfg, in_hours
    if not in_hours(await ncfg(), now.replace(tzinfo=timezone.utc).astimezone(TZ)):
        return 0
    jobs = []
    async with Session() as s:
        rows = (await s.execute(select(Song).where(
            Song.promo_until > now, Song.paid.is_(False), Song.status == "preview_ready",
            Song.promo_sent < len(stages)).order_by(Song.promo_until).limit(4000))).scalars().all()
        for song in rows:
            left = int((song.promo_until - now).total_seconds() // 60)
            due = [i for i, m in enumerate(stages) if left <= m]
            if not due or due[-1] < song.promo_sent:
                continue
            k = due[-1]  # o'tib ketgan bosqichlar qayta yuborilmaydi — eng so'nggisi
            user = await s.get(User, song.owner_id)
            song.promo_sent = k + 1
            if user and not user.blocked and user.song_credits <= 0:
                jobs.append((song, user, k, left))
        await s.commit()
    sent = 0
    for song, user, k, left in jobs:
        text = reminder_text(k, k == len(stages) - 1, (user.first_name or "").strip(), song, left)
        try:
            await bot.send_message(song.owner_id, text, reply_markup=_keyboard(song, song.promo_price))
            sent += 1
        except Exception:
            log.warning("Chegirma eslatmasini yuborib bo'lmadi: %s", song.owner_id)
        await asyncio.sleep(0.04)  # ~25 xabar/soniya — Telegram chegarasidan past
    return sent


async def loop(bot, interval: int = 180) -> None:
    await asyncio.sleep(90)
    while True:
        try:
            n = await offer_due(bot)
            r = await remind_due(bot)
            b = await backfill_due(bot)
            if n or r or b:
                log.info("Chegirma: %s ta taklif, %s ta eslatma, eski namunalarga %s ta", n, r, b)
        except Exception:
            log.exception("Chegirma tsiklida xato")
        await asyncio.sleep(interval)


async def stats() -> dict:
    """Admin uchun: nechta taklif, nechtasi chegirmada sotib oldi, tushum."""
    from sqlalchemy import func
    async with Session() as s:
        offered = await s.scalar(select(func.count()).select_from(Song).where(Song.promo_until.is_not(None))) or 0
        used, revenue = (await s.execute(select(func.count(), func.coalesce(func.sum(Song.price), 0)).where(
            Song.promo_until.is_not(None), Song.paid.is_(True), Song.price == Song.promo_price))).one()
        sold = dict((await s.execute(select(BalanceTx.ref, BalanceTx.amount).where(BalanceTx.kind == "song_pack"))).all())
    packs: dict[int, int] = {}
    for ref in sold:
        try:
            n = int(ref.split(":")[1])
        except (IndexError, ValueError):
            continue
        packs[n] = packs.get(n, 0) + 1
    return {"offered": offered, "used": used or 0, "revenue": int(revenue or 0), "packs_sold": packs}


# ---------------------------------------------------------------- eski namunalar: bir martalik chegirma tarqatmasi
# Admin yoqadi; har aylanishda (3 daqiqa) `batch` tadan, faqat progrev soatlarida yuboriladi.
# Har bir odamga bitta (eng oxirgi sotib olinmagan) qo'shiq bo'yicha, umrida bir marta.
BF_KEY = "promo_backfill"
BF_DEFAULT = {"on": False, "batch": 100, "sent": 0, "started": None, "finished": None}


async def backfill_state() -> dict:
    return {**BF_DEFAULT, **(await store.get(BF_KEY, {}) or {})}


def _bf_query(now: datetime):
    """Eski (48 soatdan oldingi) sotib olinmagan namunalar; chegirma olgan odamlar chiqarib tashlanadi."""
    had = select(Song.owner_id).where(Song.promo_until.is_not(None))
    return (select(Song, User).join(User, User.tg_id == Song.owner_id).where(
        Song.status == "preview_ready", Song.paid.is_(False), Song.promo_until.is_(None),
        (Song.preview_at.is_(None)) | (Song.preview_at < now - timedelta(hours=FRESH_HOURS)),
        Song.owner_id.not_in(had), User.blocked.is_(False), User.song_credits <= 0))


async def backfill_eligible(now: datetime | None = None) -> int:
    from sqlalchemy import func
    q = _bf_query(now or utcnow()).with_only_columns(func.count(func.distinct(Song.owner_id))).order_by(None)
    async with Session() as s:
        return await s.scalar(q) or 0


async def backfill_breakdown(now: datetime | None = None) -> dict:
    """Admin uchun: «nega shuncha kishi?» — sotib olinmagan qo'shiqlar odamlar bo'yicha qayerga tushadi."""
    from sqlalchemy import func
    now = now or utcnow()
    people = lambda *w: select(func.count(func.distinct(Song.owner_id))).where(Song.paid.is_(False), *w)  # noqa: E731
    old = (Song.preview_at.is_(None)) | (Song.preview_at < now - timedelta(hours=FRESH_HOURS))
    async with Session() as s:
        q = lambda x: s.scalar(x)  # noqa: E731
        out = {
            "songs_unpaid": await q(select(func.count()).select_from(Song).where(Song.paid.is_(False))) or 0,
            "people_unpaid": await q(people()) or 0,
            "people_ready": await q(people(Song.status == "preview_ready")) or 0,
            "people_fresh": await q(people(Song.status == "preview_ready", ~old)) or 0,
            "people_lyrics": await q(people(Song.status.in_(("lyrics", "failed")))) or 0,
            "people_promo": await q(select(func.count(func.distinct(Song.owner_id))).where(Song.promo_until.is_not(None))) or 0,
            "people_blocked": await q(people(Song.status == "preview_ready").join(User, User.tg_id == Song.owner_id).where(User.blocked.is_(True))) or 0,
        }
    out["eligible"] = await backfill_eligible(now)
    return out


async def backfill_set(on: bool, batch: int | None = None) -> dict:
    st = await backfill_state()
    if batch is not None:
        st["batch"] = _int(batch, 10, 500, "Bir martada nechta")
    if on and not st["on"]:
        st.update(on=True, started=utcnow().isoformat(), finished=None)
    elif not on:
        st["on"] = False
    await store.put(BF_KEY, st)
    return st


def backfill_text(name: str, song: Song, promo: dict, until: datetime, now: datetime) -> str:
    from .videobot import money
    loc = until.replace(tzinfo=timezone.utc).astimezone(TZ)
    day = "bugun" if loc.date() == now.replace(tzinfo=timezone.utc).astimezone(TZ).date() else "ertaga"
    who = f"{name}, " if name else ""
    whom = f"{song.recipient} uchun " if song.recipient else ""
    return (f"🎁 <b>{who}{whom}«{song.title or 'Qo‘shiq'}» qo‘shig‘ingizni eslaysizmi?</b>\n\n"
            f"Siz uning namunasini tinglagan edingiz. Endi to‘liq qo‘shiqni faqat siz uchun chegirmada olishingiz mumkin:\n"
            f"<s>{money(settings.song_price)}</s> → <b>{money(promo['price'])}</b>\n\n"
            f"⏳ Chegirma <b>{day} {loc:%H:%M}</b> gacha. Keyin narx odatdagidek {money(settings.song_price)} bo‘ladi.")


async def backfill_due(bot, now: datetime | None = None) -> int:
    st = await backfill_state()
    if not st["on"] or not bot:
        return 0
    cfg = await config()
    promo = cfg["promo"]
    now = now or utcnow()
    from .nudges import config as ncfg, in_hours
    hours = await ncfg()
    if not in_hours(hours, now.replace(tzinfo=timezone.utc).astimezone(TZ)):
        return 0
    picked = []
    async with Session() as s:
        rows = (await s.execute(_bf_query(now).order_by(Song.id.desc()).limit(st["batch"] * 4))).all()
        seen = set()
        for song, user in rows:
            if song.owner_id in seen:
                continue  # bir odamga — eng oxirgi qo'shig'i bo'yicha bitta taklif
            seen.add(song.owner_id)
            song.promo_until = _end_in_hours(now + timedelta(hours=promo["hours"]), hours, promo)
            song.promo_price, song.promo_sent = promo["price"], 0
            picked.append((song, user))
            if len(picked) >= st["batch"]:
                break
        await s.commit()
    from aiogram.exceptions import TelegramForbiddenError
    sent, blocked = 0, []
    for song, user in picked:
        try:
            await bot.send_message(song.owner_id, backfill_text((user.first_name or "").strip(), song, promo, song.promo_until, now),
                                   reply_markup=_keyboard(song, promo["price"]))
            sent += 1
        except TelegramForbiddenError:
            blocked.append(song.owner_id)
        except Exception:
            log.warning("Eski namuna chegirmasini yuborib bo'lmadi: %s", song.owner_id)
        await asyncio.sleep(0.05)
    if blocked:
        async with Session() as s:
            await s.execute(update(User).where(User.tg_id.in_(blocked)).values(blocked=True))
            await s.commit()
    st = await backfill_state()
    st["sent"] = st.get("sent", 0) + sent
    if not picked:
        st.update(on=False, finished=utcnow().isoformat())  # hammaga yuborildi — o'zi to'xtaydi
    await store.put(BF_KEY, st)
    return sent
