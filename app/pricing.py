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
DEFAULT_PROMO = {"on": True, "price": 39000, "hours": 12, "delay": 1}
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
    if not in_hours(await ncfg(), now.replace(tzinfo=timezone.utc).astimezone(TZ)):
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
            song.promo_until, song.promo_price = now + timedelta(hours=promo["hours"]), promo["price"]
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


async def loop(bot, interval: int = 600) -> None:
    await asyncio.sleep(90)
    while True:
        try:
            n = await offer_due(bot)
            if n:
                log.info("Chegirma taklifi: %s ta xabar", n)
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
