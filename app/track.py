"""Faollik va trafik manbalari: /start, ilovaga kirish (kuniga bir marta) va reklama havolasi bosilishi.

Reklama havolasi: t.me/<bot>?start=src_<kod> (yoki kuzatuv havolasi /go/<kod>, u bosishlarni ham sanaydi).
Yangi foydalanuvchining birinchi manbasi users.ref ga yoziladi — sotuvlar shu bo'yicha manbaga bog'lanadi.

Voronka hodisalari (statistika TZ): event() — bitta INSERT, alohida sessiya, xato chaqiruvchiga chiqmaydi.
Har bir hodisada: foydalanuvchi, vaqt (bazada UTC; panelda Toshkent vaqti), manba (users.ref), obyekt
(ref: pay:<id>, song:<id>...), son (num) va qisqa qo'shimcha ma'lumot (meta).
Eski hodisa nomlari o'zgarmagan: TZ dagi bot_start = "start", app_open = "app".
"""

import hashlib
import hmac
import logging
import re
from datetime import date, datetime

from sqlalchemy import func, insert, select, update

from . import store
from .billing import day_start_utc
from .config import settings
from .db import Event, Session, User, utcnow
from .reminders import today

log = logging.getLogger(__name__)

SRC_PREFIX = "src_"
CODE_RE = re.compile(r"^[a-z0-9_]{2,24}$")
# Telegram/ijtimoiy tarmoqlar havola ko'rinishini (preview) olayotganda bosish sanalmaydi
BOT_UA = re.compile(r"bot|crawler|spider|preview|facebookexternalhit|whatsapp|slurp|curl|python", re.I)
_APP_DAY: dict[int, date] = {}


def src_code(param: str) -> str:
    """«src_kod» dan kodni ajratadi (boshqa parametrlarda bo'sh)."""
    if param and param.startswith(SRC_PREFIX):
        code = param[len(SRC_PREFIX):].lower()
        if CODE_RE.match(code):
            return code
    return ""


async def log_event(kind: str, user_id: int | None = None, src: str = "") -> None:
    try:
        async with Session() as s:
            s.add(Event(user_id=user_id, kind=kind, src=(src or "")[:32]))
            await s.commit()
    except Exception:
        log.exception("Hodisani yozib bo'lmadi: %s", kind)


async def event(kind: str, user_id: int | None = None, ref: str = "", num: int | None = None, meta: dict | None = None,
                src: str | None = None, at: datetime | None = None) -> bool:
    """Voronka hodisasini yozadi: event("pay_open", uid, ref="pay:15", num=69000, meta={"p": "song"}).

    Bot va ilovani sekinlashtirmaydi: bitta INSERT, chaqiruvchining tranzaksiyasiga aralashmaydi va hech qachon
    xato qaytarmaydi (yozib bo'lmasa — faqat jurnalga va False). src berilmasa foydalanuvchining manbasi (users.ref)
    o'sha INSERT ning ichida olinadi — alohida so'rov yo'q."""
    try:
        if src is None and user_id:
            src_value = func.coalesce(select(User.ref).where(User.tg_id == user_id).scalar_subquery(), "")
        else:
            src_value = (src or "")[:32]
        async with Session() as s:
            await s.execute(insert(Event).values(user_id=user_id, kind=kind[:24], src=src_value, ref=(ref or "")[:24],
                                                 num=num, meta=meta or None, created_at=at or utcnow()))
            await s.commit()
        return True
    except Exception:
        log.exception("Hodisani yozib bo'lmadi: %s", kind)
        return False


# Mini App o'zi yuboradigan hodisalar (POST /api/track): faqat shu ro'yxatdagilar qabul qilinadi.
# Qo'shiq voronkasi hodisalari qo'shimcha tekshiriladi (qo'shiq o'ziniki ekani, qiymatlar) — app/songflow.py: client_event()
SONG_CLIENT_KINDS = {"song_open", "sample_played", "buy_click", "song_shared", "sample_limit"}
CLIENT_KINDS = {"pay_sheet"} | SONG_CLIENT_KINDS


def clean_meta(raw) -> dict | None:
    """Ilovadan kelgan qo'shimcha ma'lumot: bir nechta qisqa kalit va oddiy qiymatlar."""
    if not isinstance(raw, dict):
        return None
    out = {}
    for k, v in list(raw.items())[:6]:
        if isinstance(v, bool) or isinstance(v, int):
            out[str(k)[:12]] = v
        elif isinstance(v, str) and v:
            out[str(k)[:12]] = v[:40]
    return out or None


# ---------------------------------------------------------------- statistikadan chiqariladigan akkauntlar

STATS_KEY = "stats"  # store: {"exclude_ids": [...]} — admin paneldan kiritiladigan sinov akkauntlari


def _ids(raw) -> list[int]:
    out: list[int] = []
    for x in raw or []:
        try:
            n = int(str(x).strip())
        except ValueError:
            continue
        if n > 0 and n not in out:
            out.append(n)
    return out[:200]


async def test_ids() -> list[int]:
    """Admin panelda kiritilgan sinov akkauntlari (Telegram id)."""
    return _ids((await store.get(STATS_KEY) or {}).get("exclude_ids"))


async def set_test_ids(raw) -> list[int]:
    cfg = await store.get(STATS_KEY) or {}
    cfg["exclude_ids"] = _ids(raw)
    await store.put(STATS_KEY, cfg)
    return cfg["exclude_ids"]


async def excluded_ids() -> set[int]:
    """Statistikada sanalmaydigan akkauntlar: adminlar (.env dagi ADMIN_IDS) va sinov akkauntlari ro'yxati."""
    return set(settings.admins) | set(await test_ids())


async def app_open(uid: int, src: str = "") -> None:
    """Ilovaga kirish: bir foydalanuvchi uchun kuniga bitta yozuv."""
    d = today()
    if _APP_DAY.get(uid) == d:
        return
    if len(_APP_DAY) > 200_000:
        _APP_DAY.clear()
    _APP_DAY[uid] = d
    try:
        async with Session() as s:
            seen = await s.scalar(select(Event.id).where(Event.user_id == uid, Event.kind == "app",
                                                         Event.created_at >= day_start_utc()).limit(1))
            if not seen:
                s.add(Event(user_id=uid, kind="app", src=(src or "")[:32]))
                await s.commit()
    except Exception:
        log.exception("Ilovaga kirishni yozib bo'lmadi")


# ---------------------------------------------------------------- botni bloklash (statistika TZ, 5-band)
# users.blocked — vaqtsiz bayroq. Blok aniqlangan payt alohida hodisa sifatida yoziladi: «xabardan keyin 24 soat ichida
# blokladi», «Start bosgandan blokgacha» va «kunlar bo'yicha bloklar» shu vaqt bilan hisoblanadi.
#   bot_block   — botni bloklagani aniqlandi. meta.via: update — Telegram o'zi xabar berdi (my_chat_member, aniq vaqt);
#                 qolganlari — xabar yuborishda «Forbidden» qaytdi (nudge, promo, survey, song, broadcast) — aniqlangan vaqt
#   bot_unblock — blokdan chiqardi (Telegram xabari yoki yana botga yozdi / ilovani ochdi — billing.touch_user)
BLOCK, UNBLOCK = "bot_block", "bot_unblock"


async def mark_blocked(ids, via: str) -> int:
    """Botni bloklaganlar: users.blocked = True va har biriga bot_block hodisasi — faqat hali bloklanmagan deb turganlarga
    (takroriy aniqlash hodisani ko'paytirmaydi). Xato chaqiruvchiga chiqmaydi. Nechta odam yangi bloklangani qaytadi."""
    ids = sorted({int(i) for i in ([ids] if isinstance(ids, int) else ids or []) if i})
    if not ids:
        return 0
    try:
        async with Session() as s:
            fresh = (await s.execute(select(User.tg_id, User.ref).where(User.tg_id.in_(ids), User.blocked.is_(False)))).all()
            await s.execute(update(User).where(User.tg_id.in_(ids)).values(blocked=True))
            now = utcnow()
            for uid, ref in fresh:
                s.add(Event(user_id=uid, kind=BLOCK, src=(ref or "")[:32], meta={"via": via[:12]}, created_at=now))
            await s.commit()
        return len(fresh)
    except Exception:
        log.exception("Blokni yozib bo'lmadi")
        return 0


async def mark_unblocked(uid: int, via: str) -> None:
    """Telegram «blokdan chiqardi» deb xabar berdi: bayroq olinadi va bot_unblock yoziladi (bloklangan deb turgan bo'lsa)."""
    try:
        async with Session() as s:
            u = await s.get(User, uid)
            if u and u.blocked:
                u.blocked = False
                s.add(Event(user_id=uid, kind=UNBLOCK, src=(u.ref or "")[:32], meta={"via": via[:12]}))
                await s.commit()
    except Exception:
        log.exception("Blokdan chiqishni yozib bo'lmadi")


# ---------------------------------------------------------------- xabardagi tugma bosildi (msg_click)
# Progrev va chegirma tugmalari Mini App'ni ochadi (WebApp tugmasi) — Telegram bosilganini botga aytmaydi. Shuning uchun
# tugma havolasiga imzolangan belgi qo'shiladi: /app?song=12&mt=song.2_123456_<imzo>. Mini App sahifasi so'ralganda server
# belgini tekshiradi va «msg_click» hodisasini yozadi (ref = n:<xabar>: n:song.2, n:offer.0, n:rem.1).
# Mijoz uchun hech narsa o'zgarmaydi: tugma yozuvi va ochiladigan sahifa o'sha-o'sha, ilova noma'lum parametrga qaramaydi.
CLICK = "msg_click"
_MSG_RE = re.compile(r"^[a-z]{2,6}\.\d{1,2}$")


def _click_sig(m: str, uid: int) -> str:
    return hmac.new(settings.bot_token.encode(), f"mc:{m}:{uid}".encode(), hashlib.sha256).hexdigest()[:12]


def click_token(m: str, uid: int) -> str:
    """m — xabar kaliti «ketma-ketlik.qadam»: song.2, new.0, offer.0, bf.0, rem.1."""
    return f"{m}_{uid}_{_click_sig(m, uid)}"


def click_url(url: str, m: str, uid: int) -> str:
    return f"{url}{'&' if '?' in url else '?'}mt={click_token(m, uid)}"


def parse_click(token: str) -> tuple[str, int] | None:
    try:
        m, uid, sig = (token or "")[:60].rsplit("_", 2)
        uid_i = int(uid)
    except ValueError:
        return None
    if not _MSG_RE.match(m) or uid_i <= 0 or not hmac.compare_digest(_click_sig(m, uid_i), sig):
        return None
    return m, uid_i


async def msg_click(token: str) -> bool:
    """Mini App xabardagi tugma orqali ochildi: imzo to'g'ri bo'lsa hodisa yoziladi (bitta INSERT, xato chiqmaydi)."""
    got = parse_click(token)
    if not got:
        return False
    m, uid = got
    return await event(CLICK, uid, f"n:{m}")
