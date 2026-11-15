"""Xavfsizlik limitlari: urinishlar limiti, parol terish, CSV formula himoyasi.

Ishga tushirish: python -m tests.test_security
"""

import os
import tempfile

os.environ["DATABASE_URL"] = f"sqlite+aiosqlite:///{tempfile.mkdtemp()}/sec.db"
os.environ["BOT_TOKEN"] = "123456:TEST"

from app import admin, web  # noqa: E402

# bitta kalit uchun limitdan oshganda to'xtatadi, boshqa kalitga ta'sir qilmaydi
assert not any(web.too_many("t:a", 3) for _ in range(3))
assert web.too_many("t:a", 3)
assert not web.too_many("t:b", 3)

# RSVP: bitta qurilmadan bitta saytga soatiga 20 ta javob
assert not any(web.rsvp_spam("s1", None) for _ in range(20))
assert web.rsvp_spam("s1", None)

# CSV: =, +, -, @ bilan boshlangan matn formula bo'lib ochilmaydi, sonlar o'zgarmaydi
body = admin._csv("x.csv", ["a", "b", "c"], [["=HYPERLINK(1)", -5000, "@cmd"], ["oddiy", 7, "+998"]]).body.decode()
assert "'=HYPERLINK(1)" in body and ";-5000;" in body and "'@cmd" in body and "'+998" in body and "oddiy" in body, body
print("✅ Xavfsizlik tekshiruvlari o'tdi")
