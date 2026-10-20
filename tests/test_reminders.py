"""Eslatmalar va syurpriz tekshiruvlari: python -m tests.test_reminders"""

import asyncio
import os
import tempfile
from datetime import date, datetime, timedelta

os.environ["DATABASE_URL"] = f"sqlite+aiosqlite:///{tempfile.mkdtemp()}/r.db"
os.environ["BOT_TOKEN"] = "123456:TEST"
os.environ["BASE_URL"] = "https://t.sslip.io"

from app.bot.people import parse_day  # noqa: E402
from app.db import Person, Session, init_db  # noqa: E402
from app.reminders import TZ, describe, next_occurrence, prefill_url, reminder_text, send_due  # noqa: E402
from app.surprise import clean_unlock, is_owner, locked_until, owner_token  # noqa: E402

P = lambda **kw: Person(owner_id=1, name=kw.pop("name", "Onam"), kind=kw.pop("kind", "birthday"), title="", **kw)  # noqa: E731

# --- sanalar
p = P(day=24, month=10, year=1971)
assert next_occurrence(p, date(2026, 10, 20)) == date(2026, 10, 24)
assert next_occurrence(p, date(2026, 10, 25)) == date(2027, 10, 24)
assert next_occurrence(p, date(2026, 10, 24)) == date(2026, 10, 24)
leap = P(day=29, month=2)
assert next_occurrence(leap, date(2026, 3, 1)) == date(2027, 2, 28)  # kabisa bo'lmagan yil
assert next_occurrence(leap, date(2027, 3, 1)) == date(2028, 2, 29)
assert "55 yosh" in describe(p, date(2026, 10, 20)) and "4 kun qoldi" in describe(p, date(2026, 10, 20))
assert "bugun" in describe(p, date(2026, 10, 24))
assert "55 yoshga to'ladi" in reminder_text(p, date(2026, 10, 24), 1)
assert "&lt;b&gt;" in describe(P(name="<b>x", day=1, month=1), date(2026, 1, 1))  # ism HTML dan tozalanadi
url = prefill_url(p, date(2026, 10, 24))
assert "s=tugilgan-kun" in url and "kimga=Onam" in url and "sana=2026-10-24" in url and "tugilgan_sana=1971-10-24" in url

assert parse_day("24.10") == (24, 10, None) and parse_day("24.10.1971") == (24, 10, 1971)
assert parse_day("29.02") == (29, 2, None) and parse_day("31.02") is None and parse_day("abc") is None
assert parse_day("24.10.2999") is None


# --- eslatma yuborish: faqat 7, 1, 0 kun qolganda va bir martadan
class Bot:
    def __init__(self):
        self.sent = []

    async def send_message(self, chat_id, text, reply_markup=None):
        self.sent.append((chat_id, text, reply_markup))


async def main():
    await init_db()
    async with Session() as s:
        s.add_all([P(day=24, month=10, year=1971), P(name="Akam", day=27, month=10), P(name="Do'st", day=15, month=12)])
        await s.commit()
    bot = Bot()
    assert await send_due(bot, date(2026, 10, 17)) == 1  # Onam: 7 kun
    assert await send_due(bot, date(2026, 10, 17)) == 0  # takror yuborilmaydi
    assert await send_due(bot, date(2026, 10, 18)) == 0
    assert await send_due(bot, date(2026, 10, 20)) == 1  # Akam: 7 kun
    assert await send_due(bot, date(2026, 10, 23)) == 1  # Onam: 1 kun
    assert await send_due(bot, date(2026, 10, 24)) == 1  # Onam: bugun
    texts = [t for _, t, _ in bot.sent]
    assert "Bir haftadan keyin" in texts[0] and "Ertaga" in texts[2] and "Bugun" in texts[3]
    btn = bot.sent[0][2].inline_keyboard[0][0]
    assert btn.web_app and "kimga=Onam" in btn.web_app.url
    assert await send_due(bot, date(2027, 10, 17)) == 1  # keyingi yil yana eslatadi

asyncio.run(main())

# --- syurpriz
now = datetime.now(TZ)
future = (now + timedelta(days=3)).strftime("%Y-%m-%dT%H:%M")
assert clean_unlock(future) == future
assert clean_unlock((now - timedelta(minutes=5)).strftime("%Y-%m-%dT%H:%M")) is None
assert clean_unlock((now + timedelta(days=400)).strftime("%Y-%m-%dT%H:%M")) is None
assert clean_unlock("hello") is None and clean_unlock(None) is None
assert locked_until({"unlock_at": future}) and locked_until({"unlock_at": "2020-01-01T00:00"}) is None
assert is_owner("abc", owner_token("abc")) and not is_owner("abc", "1") and not is_owner("abc", owner_token("xyz"))
print("✅ Eslatma va syurpriz tekshiruvlari o'tdi")
