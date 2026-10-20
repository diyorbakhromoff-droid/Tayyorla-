"""Syurpriz ochilish: sayt belgilangan vaqtgacha (masalan, tug'ilgan kun 00:00) yopiq turadi."""

import hashlib
import hmac
import re
from datetime import date, datetime, timedelta

from .config import settings
from .reminders import MONTHS, TZ


def owner_token(slug: str) -> str:
    """Sayt egasining maxfiy kaliti: yopiq saytni ham ko'ra oladi, ko'rishlar hisobiga kirmaydi."""
    return hmac.new(settings.bot_token.encode(), f"owner:{slug}".encode(), hashlib.sha256).hexdigest()[:20]


def owner_url(site) -> str:
    return f"{site.url}?owner={owner_token(site.slug)}"


def is_owner(slug: str, token: str | None) -> bool:
    return bool(token) and hmac.compare_digest(token, owner_token(slug))


def parse_unlock(value) -> datetime | None:
    """«2026-10-24T00:00» ko'rinishidagi O'zbekiston vaqtini o'qiydi."""
    if not isinstance(value, str):
        return None
    m = re.fullmatch(r"(\d{4}-\d{2}-\d{2})[T ](\d{1,2}):(\d{2})", value.strip())
    if not m:
        return None
    try:
        d = date.fromisoformat(m.group(1))
        return datetime(d.year, d.month, d.day, int(m.group(2)), int(m.group(3)), tzinfo=TZ)
    except ValueError:
        return None


def clean_unlock(value) -> str | None:
    """Kelajakdagi (1 yil ichidagi) ochilish vaqtini qaytaradi, aks holda None."""
    dt = parse_unlock(value)
    now = datetime.now(TZ)
    if not dt or dt <= now or dt > now + timedelta(days=366):
        return None
    return dt.strftime("%Y-%m-%dT%H:%M")


def locked_until(config: dict) -> datetime | None:
    dt = parse_unlock(config.get("unlock_at"))
    return dt if dt and dt > datetime.now(TZ) else None


def human(dt: datetime) -> str:
    return f"{dt.day}-{MONTHS[dt.month - 1]}, soat {dt:%H:%M}"


def natural_date(config: dict) -> date | None:
    """Saytdagi asosiy sana (tug'ilgan kun, to'y...) kelajakda bo'lsa — shu kuni 00:00 da ochish taklif qilinadi."""
    raw = (config.get("data") or {}).get("sana") if config.get("engine") == "catalog" else (config.get("fields") or {}).get("date")
    if not raw:
        return None
    from .render import parse_date
    try:
        d = date.fromisoformat(raw)
    except ValueError:
        d = parse_date(raw)
    return d if d and d > datetime.now(TZ).date() else None


def recipient_name(config: dict) -> str:
    if config.get("engine") == "catalog":
        data = config.get("data") or {}
        if data.get("kuyov"):
            return "Aziz mehmon"
        return data.get("kimga") or ""
    f = config.get("fields") or {}
    if f.get("groom"):
        return "Aziz mehmon"
    return f.get("name") or f.get("parents") or ""
