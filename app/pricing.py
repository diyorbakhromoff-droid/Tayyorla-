"""Narxlar, qo'shiq paketlari va namunadan keyingi chegirma — admin paneldan boshqariladi.

- Asosiy narxlar (qo'shiq, video, sayt tariflari) bazada saqlanadi va `settings` ga qo'llanadi:
  ilova, bot va oferta sahifasi darhol yangi narxni ko'radi.
- Paket: N ta qo'shiq bir narxda. Sotib olinganda foydalanuvchiga N ta «qo'shiq krediti» yoziladi;
  keyingi qo'shiqlar shu kreditdan to'lanadi (pul yechilmaydi). Muddatsiz.
- Chegirma: namuna olib, sotib olmagan qo'shiqqa `delay` soatdan keyin bir marta beriladi,
  `hours` soat amal qiladi (bot xabari + ilovada vaqt sanog'i). Faqat bitta qo'shiq xaridiga.
- Aksiya (masalan «Barakali juma»): admin yoqadi, tugash vaqtigacha har bir odamga BITTA qo'shiq aksiya narxida.
  Aksiya paytida avtomatik chegirma xabarlari (taklif, eslatma, eski namunalar) to'xtab turadi, keyin davom etadi.
"""

import asyncio
import logging
import uuid
from datetime import datetime, timedelta, timezone

from aiogram.types import InlineKeyboardButton, InlineKeyboardMarkup, WebAppInfo
from sqlalchemy import String, cast, func, insert, literal, select, update

from . import billing, control, store, track
from .config import settings
from .db import BalanceTx, Event, NudgeLog, Payment, Session, Song, User, utcnow

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
# aksiya: id va since ni server o'zi qo'yadi (har yoqilishda yangi id — «bir kishiga bitta» keyingi aksiyada qaytadan boshlanadi)
DEFAULT_SALE = {"on": False, "id": "", "name": "Barakali juma", "price": 19000, "until": None, "since": None}
EV_SALE = "sale_buy"             # aksiya narxida sotib oldi: ref = sale:<id>, num = narx, meta = {"song": id}
SALE_GRACE = timedelta(hours=2)  # aksiya tugaguncha ochilgan to'lovning puli kechikib tushsa ham — shuncha vaqt aksiya narxi


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
    # chegirma A/B (statistika TZ, 5-band): standart o'chiq; yoqilsa taklif qilinadiganlarning teng yarmi (app/control.py: arm)
    # ikkinchi narxni oladi. since — oxirgi marta yoqilgan vaqt (panel voronkani shundan beri ko'rsatadi)
    ab_raw = raw.get("ab") or {}
    ab = {"on": bool(ab_raw.get("on")), "price": 0, "since": ab_raw.get("since") if isinstance(ab_raw.get("since"), str) else None}
    if ab_raw.get("price") not in (None, "", 0):
        ab["price"] = _int(ab_raw.get("price"), 1000, 10_000_000, "Ikkinchi chegirma narxi")
    if ab["on"]:
        if not ab["price"]:
            raise PriceError("A/B uchun ikkinchi chegirma narxini kiriting")
        if ab["price"] >= prices["song"]:
            raise PriceError("Ikkinchi chegirma narxi qo'shiqning oddiy narxidan kichik bo'lishi kerak")
        if ab["price"] == promo["price"]:
            raise PriceError("Ikkinchi chegirma narxi birinchisidan farq qilsin")
    return {"prices": prices, "packs": packs, "promo": promo, "ab": ab, "sale": _clean_sale(raw.get("sale"), prices["song"])}


def _when(v) -> datetime | None:
    """ISO vaqt → UTC, vaqt zonasisiz (bazadagi kabi). Zonasiz qiymat UTC deb olinadi; admin paneli «+05:00» bilan yuboradi."""
    if not v:
        return None
    if isinstance(v, datetime):
        d = v
    else:
        try:
            d = datetime.fromisoformat(str(v).strip().replace("Z", "+00:00"))
        except ValueError:
            raise PriceError("Aksiya tugash vaqti noto'g'ri")
    return d.astimezone(timezone.utc).replace(tzinfo=None) if d.tzinfo else d


def _iso(d: datetime | None) -> str | None:
    return d.isoformat(timespec="seconds") if d else None


def _clean_sale(raw, song_price: int) -> dict:
    sr = {**DEFAULT_SALE, **(raw if isinstance(raw, dict) else {})}
    sale = {"on": bool(sr["on"]), "id": str(sr["id"] or "")[:16],
            "name": " ".join(str(sr["name"] or "").split())[:40] or DEFAULT_SALE["name"],
            "price": _int(sr["price"], 1000, 10_000_000, "Aksiya narxi"),
            "until": _iso(_when(sr["until"])), "since": _iso(_when(sr["since"]))}
    if sale["on"]:
        if sale["price"] >= song_price:
            raise PriceError("Aksiya narxi qo'shiqning oddiy narxidan kichik bo'lishi kerak")
        if not sale["until"]:
            raise PriceError("Aksiya tugash vaqtini kiriting")
    return sale


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
    old = await config()
    raw = dict(raw or {})
    if not isinstance(raw.get("ab"), dict):  # A/B yuborilmagan (eski so'rov) — avvalgisi qoladi
        raw["ab"] = old["ab"]
    elif raw["ab"].get("on") and not old["ab"]["on"]:
        raw["ab"] = {**raw["ab"], "since": utcnow().isoformat(timespec="seconds")}
    else:
        raw["ab"] = {**raw["ab"], "since": old["ab"]["since"]}
    raw["sale"] = _sale_change(old["sale"], raw.get("sale"), utcnow())
    cfg = clean(raw)
    await store.put(KEY, cfg)
    _apply(cfg)
    return cfg


def default_until(now: datetime) -> datetime:
    """Aksiya tugashi (standart): bugun 23:59, Toshkent vaqti."""
    loc = now.replace(tzinfo=timezone.utc).astimezone(TZ).replace(hour=23, minute=59, second=0, microsecond=0)
    return loc.astimezone(timezone.utc).replace(tzinfo=None)


def _sale_change(old: dict, new, now: datetime) -> dict:
    """Admin yuborgan aksiya: id va since faqat serverda. Aksiya yoqilsa (o'chiq yoki muddati o'tgan aksiya qayta yoqilsa) —
    yangi id: shu aksiyada har kim yana bitta qo'shiqni aksiya narxida oladi. Yangi yoki o'zgargan tugash vaqti kelajakda bo'lsin."""
    if not isinstance(new, dict):  # aksiya yuborilmagan (eski so'rov) — avvalgisi qoladi
        return old
    out = {**old, **{k: new[k] for k in ("on", "name", "price", "until") if k in new}, "id": old["id"], "since": old["since"]}
    if not out.get("on"):
        return out
    until = _when(out.get("until")) or default_until(now)
    fresh = sale_of({"sale": old}, now) is None
    if (fresh or until != _when(old["until"])) and until <= now:
        raise PriceError("Aksiya tugash vaqti kelajakda bo'lsin")
    out["until"] = _iso(until)
    if fresh:
        out["id"], out["since"] = uuid.uuid4().hex[:8], _iso(now.replace(microsecond=0))
    return out


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


# ---------------------------------------------------------------- aksiya (bir kunlik: «Barakali juma»)

def sale_of(cfg: dict, now: datetime | None = None) -> dict | None:
    """Faol aksiya (yoqilgan va tugash vaqti kelmagan) yoki None."""
    sale = cfg.get("sale") or {}
    until = _when(sale.get("until"))
    if not sale.get("on") or not sale.get("id") or not until or until <= (now or utcnow()):
        return None
    return sale


async def sale_used(s, uid: int, sale_id: str) -> bool:
    """Shu aksiyada qo'shiqni aksiya narxida olganmi (bir kishiga bitta)."""
    return await s.scalar(select(Event.id).where(Event.user_id == uid, Event.kind == EV_SALE, Event.ref == f"sale:{sale_id}")
                          .limit(1)) is not None


async def sale_quote(s, uid: int, song: Song | None = None, now: datetime | None = None) -> dict | None:
    """Shu odamga amaldagi aksiya: {"id", "name", "price", "until"} yoki None. Aksiya faol bo'lsa — bu aksiyada hali
    qo'shiq olmagan odamga. Aksiya tugagach SALE_GRACE ichida — faqat shu qo'shiq uchun aksiya davomida ochilgan to'lov
    (Payment.song_id) bo'lsa: pul aksiya tugashidan keyin tushsa ham mijoz ko'rgan narxda sotib olinadi."""
    sale = (await config())["sale"]
    until = _when(sale["until"])
    if not sale["on"] or not sale["id"] or not until:
        return None
    now = now or utcnow()
    if until <= now:
        if song is None or now >= until + SALE_GRACE:
            return None
        since = _when(sale["since"]) or until - timedelta(days=1)
        paid_for = await s.scalar(select(Payment.id).where(Payment.user_id == uid, Payment.song_id == song.id,
                                                           Payment.created_at >= since, Payment.created_at < until).limit(1))
        if paid_for is None:
            return None
    if await sale_used(s, uid, sale["id"]):
        return None
    return {"id": sale["id"], "name": sale["name"], "price": sale["price"], "until": until.replace(tzinfo=timezone.utc).isoformat()}


async def log_sale(s, uid: int, sale: dict, song: Song, price: int) -> None:
    """Aksiya narxida xarid — to'lov bilan bitta tranzaksiyada (shu hodisa «bir kishiga bitta» ni ta'minlaydi).
    src — odamning trafik manbasi (track.event dagi kabi)."""
    await s.execute(insert(Event).values(
        user_id=uid, kind=EV_SALE, ref=f"sale:{sale['id']}", num=price, meta={"song": song.id}, created_at=utcnow(),
        src=func.coalesce(select(User.ref).where(User.tg_id == uid).scalar_subquery(), "")))


async def sale_stats(sale: dict) -> dict:
    """Admin uchun: shu aksiyada aksiya narxida nechta kishi sotib oldi va tushum."""
    if not sale.get("id"):
        return {"buyers": 0, "revenue": 0}
    async with Session() as s:
        n, rev = (await s.execute(select(func.count(func.distinct(Event.user_id)), func.coalesce(func.sum(Event.num), 0)).where(
            Event.kind == EV_SALE, Event.ref == f"sale:{sale['id']}"))).one()
    return {"buyers": int(n or 0), "revenue": int(rev or 0)}


MONTHS_UZ = ["yanvar", "fevral", "mart", "aprel", "may", "iyun", "iyul", "avgust", "sentabr", "oktabr", "noyabr", "dekabr"]


def _until_text(until: datetime, now: datetime) -> str:
    """«bugun 23:59», «ertaga 12:00» yoki «30-noyabr 23:59» (Toshkent vaqti)."""
    loc, today = until.replace(tzinfo=timezone.utc).astimezone(TZ), now.replace(tzinfo=timezone.utc).astimezone(TZ).date()
    day = "bugun" if loc.date() == today else "ertaga" if loc.date() == today + timedelta(days=1) else f"{loc.day}-{MONTHS_UZ[loc.month - 1]}"
    return f"{day} {loc:%H:%M}"


def sale_announcement(cfg: dict, now: datetime | None = None) -> str:
    """Tarqatma uchun tayyor e'lon matni (oddiy matn — tarqatma HTML siz yuboriladi). Admin tekshirib, o'zi yuboradi."""
    from .videobot import money
    now = now or utcnow()
    sale = cfg["sale"]
    name = sale["name"]
    title = name if any(w in name.lower() for w in ("chegirma", "aksiya")) else f"{name} chegirmasi"
    when = _until_text(_when(sale["until"]) or default_until(now), now)
    day = "Bugun" if when.startswith("bugun") else "Hozir"
    return (f"🎉 {title}!\n\n"
            f"Yaqiningizga uning ismi va sizning tilaklaringiz bilan yozilgan shaxsiy qo‘shiq sovg‘a qiling.\n"
            f"{day} narxi {money(cfg['prices']['song'])} emas — atigi {money(sale['price'])}.\n\n"
            f"⏳ Faqat {when} gacha, har bir kishiga bitta qo‘shiq.\n\n"
            f"👇 Pastdagi tugmani bosing va qo‘shiqni hoziroq tayyorlang.")


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

def _keyboard(song: Song, price: int, m: str = "", uid: int | None = None) -> InlineKeyboardMarkup:
    """m — xabar kaliti (offer.0, bf.0, rem.1): berilsa tugma havolasiga bosishni sanaydigan belgi qo'shiladi (app/track.py).
    Mijoz ko'radigan tugma o'zgarmaydi."""
    from .videobot import app_url, money
    mark = (lambda u: track.click_url(u, m, uid)) if m and uid else (lambda u: u)
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text=f"🎧 Qo‘shiqni olish — {money(price)}", web_app=WebAppInfo(url=mark(app_url(song=song.id))))],
        [InlineKeyboardButton(text="🎟 Qo‘shiq paketlari", web_app=WebAppInfo(url=mark(app_url(song=song.id, packs=1))))],
    ])


async def msg_log(uid: int, seq: str, step: int, song_id: int, status: str, reason: str = "", arm: str = "",
                  at: datetime | None = None) -> None:
    """Chegirma xabari jurnalga (nudge_log, seq = offer | bf | rem): progrev xabarlari bilan bir xil statistika uchun."""
    try:
        async with Session() as s:
            s.add(NudgeLog(user_id=uid, seq=seq, step=step, ref=f"song:{song_id}", status=status, reason=reason, arm=arm,
                           created_at=at or utcnow()))
            await s.commit()
    except Exception:
        log.exception("Chegirma xabarini jurnalga yozib bo'lmadi")


async def _send(bot, uid: int, text: str, markup) -> str:
    """sent | blocked | error. Bloklagan bo'lsa — bayroq va blok vaqti (bot_block hodisasi)."""
    from aiogram.exceptions import TelegramForbiddenError
    try:
        await bot.send_message(uid, text, reply_markup=markup)
        return "sent"
    except TelegramForbiddenError:
        await track.mark_blocked(uid, "promo")
        return "blocked"
    except Exception:
        return "error"


async def _offer_skips(s, now: datetime, promo: dict) -> None:
    """Taklif vaqti kelgan, lekin egasi botni bloklagan yoki paketi bor qo'shiqlar: har biri jurnalga bir marta
    «o'tkazib yuborildi» bo'lib yoziladi. Taklif navbatidan ular SQL ning o'zida chiqariladi (avval Python da tashlab
    ketilardi va 200 talik navbatni egallab turishi mumkin edi); blokdan chiqsa yoki paket tugasa — taklif odatdagidek boradi."""
    logged = select(NudgeLog.id).where(NudgeLog.seq == "offer", NudgeLog.ref == literal("song:") + cast(Song.id, String))
    rows = (await s.execute(select(Song.id, Song.owner_id, User.blocked).join(User, User.tg_id == Song.owner_id).where(
        *_offer_conds(now, promo), (User.blocked.is_(True)) | (User.song_credits > 0), ~logged.exists()).limit(500))).all()
    for sid, uid, blk in rows:
        s.add(NudgeLog(user_id=uid, seq="offer", step=0, ref=f"song:{sid}", status="skipped", reason="blocked" if blk else "pack", created_at=now))


def _offer_conds(now: datetime, promo: dict) -> list:
    return [Song.status == "preview_ready", Song.paid.is_(False), Song.promo_until.is_(None), Song.preview_at.is_not(None),
            Song.preview_at <= now - timedelta(hours=promo["delay"]), Song.preview_at >= now - timedelta(hours=FRESH_HOURS)]


def offer_price(cfg: dict, uid: int) -> tuple[int, str]:
    """Shu odamga taklif qilinadigan chegirma narxi va A/B guruhi (A/B o'chiq bo'lsa guruh bo'sh).
    A — asosiy chegirma narxi, B — ikkinchi narx; guruh id dan (control.arm) — bir odam doim bir guruhda."""
    ab = cfg.get("ab") or {}
    if not ab.get("on") or not ab.get("price"):
        return cfg["promo"]["price"], ""
    arm = control.arm(uid)
    return (ab["price"] if arm == "b" else cfg["promo"]["price"]), arm


async def offer_due(bot, now: datetime | None = None) -> int:
    """Chegirma vaqti kelgan qo'shiqlarga chegirma beradi va botga xabar yuboradi. Yuborilganlar soni."""
    cfg = await config()
    promo = cfg["promo"]
    if not promo["on"]:
        return 0
    now = now or utcnow()
    if sale_of(cfg, now):
        return 0  # aksiya paytida 39 000 lik taklif aksiyaga zid — aksiya tugagach davom etadi
    from .nudges import config as ncfg, in_hours
    hours = await ncfg()
    if not in_hours(hours, now.replace(tzinfo=timezone.utc).astimezone(TZ)):
        return 0  # kechasi yubormaymiz — ertalab davom etadi
    ctl = await control.config()
    async with Session() as s:
        q = select(Song, User).join(User, User.tg_id == Song.owner_id).where(
            *_offer_conds(now, promo), User.blocked.is_(False), User.song_credits <= 0)
        skip_ctl = control.member_sql(ctl, User.tg_id, User.created_at)
        if skip_ctl is not None:
            q = q.where(~skip_ctl)  # nazorat guruhi chegirma olmaydi
        rows = (await s.execute(q.order_by(Song.id).limit(200))).all()
        picked = []
        seen_users = set()
        for song, user in rows:
            if song.owner_id in seen_users:
                continue
            seen_users.add(song.owner_id)  # bir odamga bir aylanishda bitta xabar
            price, arm = offer_price(cfg, user.tg_id)
            song.promo_until, song.promo_price, song.promo_sent = _end_in_hours(now + timedelta(hours=promo["hours"]), hours, promo), price, 0
            picked.append((song, user, arm))
        await _offer_skips(s, now, promo)
        await s.commit()
    sent = 0
    for song, user, arm in picked:
        if not bot:
            break
        until = song.promo_until.replace(tzinfo=timezone.utc).astimezone(TZ)
        day = "bugun" if until.date() == now.replace(tzinfo=timezone.utc).astimezone(TZ).date() else "ertaga"
        name = (user.first_name or "").strip()
        from .videobot import money
        text = (f"🎁 <b>{name + ', ' if name else ''}«{song.title or 'Qo‘shiq'}» qo‘shig‘ingiz sizni kutyapti!</b>\n\n"
                f"Faqat siz uchun {promo['hours']} soatlik chegirma:\n<s>{money(settings.song_price)}</s> → <b>{money(song.promo_price)}</b>\n\n"
                f"⏳ Chegirma <b>{day} {until:%H:%M}</b> gacha amal qiladi. Keyin narx odatdagidek {money(settings.song_price)} bo‘ladi.")
        st = await _send(bot, song.owner_id, text, _keyboard(song, song.promo_price, "offer.0", song.owner_id))
        if st == "sent":
            sent += 1
            await log_event(song.owner_id, EV_OFFER, song.id)
        else:
            log.warning("Chegirma xabarini yuborib bo'lmadi: %s", song.owner_id)
        await msg_log(song.owner_id, "offer", 0, song.id, "sent" if st == "sent" else "failed", "" if st == "sent" else st, arm, now)
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
    if sale_of(cfg, now):
        return 0  # aksiya paytida to'xtab turadi
    from .nudges import config as ncfg, in_hours
    if not in_hours(await ncfg(), now.replace(tzinfo=timezone.utc).astimezone(TZ)):
        return 0
    hours = await ncfg()
    jobs = []
    async with Session() as s:
        rows = (await s.execute(select(Song).where(
            Song.promo_until > now, Song.paid.is_(False), Song.status == "preview_ready",
            Song.promo_sent < len(stages)).order_by(Song.promo_until).limit(4000))).scalars().all()
        users = {u.tg_id: u for u in (await s.execute(select(User).where(
            User.tg_id.in_({x.owner_id for x in rows} or {0})))).scalars().all()}
        for song in rows:
            left = int((song.promo_until - now).total_seconds() // 60)
            due = [i for i, m in enumerate(stages) if left <= m]
            if not due or due[-1] < song.promo_sent:
                continue
            k = due[-1]  # o'tib ketgan bosqichlar qayta yuborilmaydi — eng so'nggisi
            user = users.get(song.owner_id)
            arm = await _arm_of(s, song)
            for j in range(song.promo_sent, k):  # o'tib ketgan bosqichlar: vaqti tunga to'g'ri kelgan bo'lsa — «tungi vaqt»
                at = (song.promo_until - timedelta(minutes=stages[j])).replace(tzinfo=timezone.utc).astimezone(TZ)
                s.add(NudgeLog(user_id=song.owner_id, seq="rem", step=j + 1, ref=f"song:{song.id}", status="skipped",
                               reason="late" if in_hours(hours, at) else "night", arm=arm, created_at=now))
            song.promo_sent = k + 1
            if user and not user.blocked and user.song_credits <= 0:
                jobs.append((song, user, k, left, arm))
            else:
                s.add(NudgeLog(user_id=song.owner_id, seq="rem", step=k + 1, ref=f"song:{song.id}", status="skipped",
                               reason="pack" if user and not user.blocked else "blocked", arm=arm, created_at=now))
        await s.commit()
    sent = 0
    for song, user, k, left, arm in jobs:
        text = reminder_text(k, k == len(stages) - 1, (user.first_name or "").strip(), song, left)
        st = await _send(bot, song.owner_id, text, _keyboard(song, song.promo_price, f"rem.{k + 1}", song.owner_id))
        if st == "sent":
            sent += 1
            await log_event(song.owner_id, EV_REMIND, song.id, f":{k + 1}")
        else:
            log.warning("Chegirma eslatmasini yuborib bo'lmadi: %s", song.owner_id)
        await msg_log(song.owner_id, "rem", k + 1, song.id, "sent" if st == "sent" else "failed", "" if st == "sent" else st, arm, now)
        await asyncio.sleep(0.04)  # ~25 xabar/soniya — Telegram chegarasidan past
    return sent


async def _arm_of(s, song: Song) -> str:
    """Eslatma qaysi A/B guruhidagi taklifga tegishli: shu qo'shiq taklifi jurnalda qaysi guruh bilan yozilgan."""
    return await s.scalar(select(NudgeLog.arm).where(NudgeLog.ref == f"song:{song.id}", NudgeLog.seq.in_(("offer", "bf")),
                                                     NudgeLog.status == "sent").order_by(NudgeLog.id.desc()).limit(1)) or ""


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


# ---------------------------------------------------------------- kunlik hisobot (admin)
EV_OFFER, EV_BACKFILL, EV_REMIND, EV_BUY = "promo_offer", "promo_bf", "promo_rem", "promo_buy"
EV_KINDS = (EV_OFFER, EV_BACKFILL, EV_REMIND, EV_BUY)


async def log_event(uid: int, kind: str, song_id: int, extra: str = "", s=None) -> None:
    """Chegirma hodisasi (src = qo'shiq id). s berilsa — o'sha tranzaksiyaga qo'shiladi."""
    ev = Event(user_id=uid, kind=kind, src=f"{song_id}{extra}"[:32])
    if s is not None:
        s.add(ev)
        return
    async with Session() as s2:
        s2.add(ev)
        await s2.commit()


async def daily(days: int = 14, now: datetime | None = None) -> list[dict]:
    """Oxirgi `days` kun (Toshkent vaqti), yangisi tepada: nechta kishiga taklif, eski namunalarga, eslatma, xarid va tushum."""
    now = now or utcnow()
    today = now.replace(tzinfo=timezone.utc).astimezone(TZ).date()
    start = datetime(today.year, today.month, today.day, tzinfo=TZ) - timedelta(days=days - 1)
    start = start.astimezone(timezone.utc).replace(tzinfo=None)
    async with Session() as s:
        rows = (await s.execute(select(Event.kind, Event.user_id, Event.src, Event.created_at).where(
            Event.kind.in_(EV_KINDS), Event.created_at >= start))).all()
        bought = [int(r[2].split(":")[0]) for r in rows if r[0] == EV_BUY and r[2].split(":")[0].isdigit()]
        prices = dict((await s.execute(select(Song.id, Song.price).where(Song.id.in_(bought or [0])))).all())
    out = {}
    for i in range(days):
        d = today - timedelta(days=i)
        out[d] = {"day": d.isoformat(), "offer": set(), "bf": set(), "rem": 0, "buy": 0, "revenue": 0}
    for kind, uid, src, at in rows:
        row = out.get(at.replace(tzinfo=timezone.utc).astimezone(TZ).date())
        if not row:
            continue
        if kind == EV_OFFER:
            row["offer"].add(uid)
        elif kind == EV_BACKFILL:
            row["bf"].add(uid)
        elif kind == EV_REMIND:
            row["rem"] += 1
        elif kind == EV_BUY:
            row["buy"] += 1
            sid = src.split(":")[0]
            row["revenue"] += prices.get(int(sid), 0) if sid.isdigit() else 0
    return [{**r, "offer": len(r["offer"]), "bf": len(r["bf"])} for r in out.values()]


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


def _bf_query(now: datetime, ctl: dict | None = None):
    """Eski (48 soatdan oldingi) sotib olinmagan namunalar; chegirma olgan odamlar va nazorat guruhi chiqarib tashlanadi."""
    had = select(Song.owner_id).where(Song.promo_until.is_not(None))
    q = (select(Song, User).join(User, User.tg_id == Song.owner_id).where(
        Song.status == "preview_ready", Song.paid.is_(False), Song.promo_until.is_(None),
        (Song.preview_at.is_(None)) | (Song.preview_at < now - timedelta(hours=FRESH_HOURS)),
        Song.owner_id.not_in(had), User.blocked.is_(False), User.song_credits <= 0))
    member = control.member_sql(ctl or {}, User.tg_id, User.created_at)
    return q if member is None else q.where(~member)


async def backfill_eligible(now: datetime | None = None) -> int:
    from sqlalchemy import func
    q = _bf_query(now or utcnow(), await control.config()).with_only_columns(func.count(func.distinct(Song.owner_id))).order_by(None)
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
    if sale_of(cfg, now):
        return 0  # aksiya paytida to'xtab turadi (holati saqlanadi — aksiya tugagach davom etadi)
    from .nudges import config as ncfg, in_hours
    hours = await ncfg()
    if not in_hours(hours, now.replace(tzinfo=timezone.utc).astimezone(TZ)):
        return 0
    picked = []
    async with Session() as s:
        rows = (await s.execute(_bf_query(now, await control.config()).order_by(Song.id.desc()).limit(st["batch"] * 4))).all()
        seen = set()
        for song, user in rows:
            if song.owner_id in seen:
                continue  # bir odamga — eng oxirgi qo'shig'i bo'yicha bitta taklif
            seen.add(song.owner_id)
            song.promo_until = _end_in_hours(now + timedelta(hours=promo["hours"]), hours, promo)
            price, arm = offer_price(cfg, user.tg_id)
            song.promo_price, song.promo_sent = price, 0
            picked.append((song, user, arm))
            if len(picked) >= st["batch"]:
                break
        await s.commit()
    sent = 0
    for song, user, arm in picked:
        res = await _send(bot, song.owner_id, backfill_text((user.first_name or "").strip(), song, {**promo, "price": song.promo_price},
                                                            song.promo_until, now),
                          _keyboard(song, song.promo_price, "bf.0", song.owner_id))
        if res == "sent":
            sent += 1
            await log_event(song.owner_id, EV_BACKFILL, song.id)
        elif res == "error":
            log.warning("Eski namuna chegirmasini yuborib bo'lmadi: %s", song.owner_id)
        await msg_log(song.owner_id, "bf", 0, song.id, "sent" if res == "sent" else "failed", "" if res == "sent" else res, arm, now)
        await asyncio.sleep(0.05)
    st = await backfill_state()
    st["sent"] = st.get("sent", 0) + sent
    if not picked:
        st.update(on=False, finished=utcnow().isoformat())  # hammaga yuborildi — o'zi to'xtaydi
    await store.put(BF_KEY, st)
    return sent
