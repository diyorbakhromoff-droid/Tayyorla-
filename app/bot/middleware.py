"""Har bir foydalanuvchini users jadvalida yangilab boradi (oxirgi faollik) — /broadcast va statistika uchun."""

import time

from aiogram import BaseMiddleware

from .. import billing
from ..db import Session

_SEEN: dict[int, float] = {}
EVERY = 1800  # yarim soatda bir marta yozamiz


class TouchUser(BaseMiddleware):
    async def __call__(self, handler, event, data):
        user = getattr(event, "from_user", None)
        text = getattr(event, "text", None) or ""
        # /start o'zi yozadi (referal faqat birinchi yozuvda hisoblanadi)
        if user and not user.is_bot and not text.startswith("/start") and time.time() - _SEEN.get(user.id, 0) > EVERY:
            _SEEN[user.id] = time.time()
            try:
                async with Session() as s:
                    u, new = await billing.touch_user(s, user.id, user.first_name or "", user.username or "", user.language_code or "")
                    if new:
                        from ..i18n import from_telegram
                        u.lang = from_telegram(user.language_code)
                    await s.commit()
            except Exception:
                pass
        return await handler(event, data)
