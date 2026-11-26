"""Faollik va trafik manbalari: /start, ilovaga kirish (kuniga bir marta) va reklama havolasi bosilishi.

Reklama havolasi: t.me/<bot>?start=src_<kod> (yoki kuzatuv havolasi /go/<kod>, u bosishlarni ham sanaydi).
Yangi foydalanuvchining birinchi manbasi users.ref ga yoziladi — sotuvlar shu bo'yicha manbaga bog'lanadi.

Voronka hodisalari (statistika TZ): event() — bitta INSERT, alohida sessiya, xato chaqiruvchiga chiqmaydi.
Har bir hodisada: foydalanuvchi, vaqt (bazada UTC; panelda Toshkent vaqti), manba (users.ref), obyekt
(ref: pay:<id>, song:<id>...), son (num) va qisqa qo'shimcha ma'lumot (meta).
Eski hodisa nomlari o'zgarmagan: TZ dagi bot_start = "start", app_open = "app".
"""

import logging
import re
from datetime import date, datetime

from sqlalchemy import func, insert, select

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
