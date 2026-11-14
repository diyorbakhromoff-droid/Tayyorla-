"""Admin paneldan o'zgartiriladigan sozlamalar: kalit -> JSON qiymat, bazada saqlanadi.

Qiymatlar qisqa vaqt xotirada turadi (har so'rovda bazaga bormaslik uchun); yozilganda darhol yangilanadi.
"""

import copy
import time

from .db import Session, Setting, utcnow

TTL = 20.0
_CACHE: dict[str, tuple[float, object]] = {}


async def get(key: str, default=None):
    hit = _CACHE.get(key)
    if hit and time.monotonic() - hit[0] < TTL:
        return copy.deepcopy(hit[1]) if hit[1] is not None else default
    async with Session() as s:
        row = await s.get(Setting, key)
    value = row.value if row else None
    _CACHE[key] = (time.monotonic(), value)
    return copy.deepcopy(value) if value is not None else default


async def put(key: str, value) -> None:
    async with Session() as s:
        row = await s.get(Setting, key)
        if row:
            row.value, row.updated_at = value, utcnow()
        else:
            s.add(Setting(key=key, value=value))
        await s.commit()
    _CACHE[key] = (time.monotonic(), copy.deepcopy(value))


def forget(key: str | None = None) -> None:
    """Testlar uchun: xotiradagi nusxani tashlaydi."""
    if key is None:
        _CACHE.clear()
    else:
        _CACHE.pop(key, None)
