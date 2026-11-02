"""Faollik va trafik manbalari: /start, ilovaga kirish (kuniga bir marta) va reklama havolasi bosilishi.

Reklama havolasi: t.me/<bot>?start=src_<kod> (yoki kuzatuv havolasi /go/<kod>, u bosishlarni ham sanaydi).
Yangi foydalanuvchining birinchi manbasi users.ref ga yoziladi — sotuvlar shu bo'yicha manbaga bog'lanadi.
"""

import logging
import re
from datetime import date

from sqlalchemy import select

from .billing import day_start_utc
from .db import Event, Session
from .reminders import today

log = logging.getLogger(__name__)

SRC_PREFIX = "src_"
CODE_RE = re.compile(r"^[a-z0-9_]{2,24}$")
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
