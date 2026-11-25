"""Karta raqamiga o'tkazma: chekni AI o'qishi (soxta javob), avtomatik tasdiq qoidalari, qo'lda tekshiruv,
takroriy chek, bekor qilish va admin sozlamalari.

Ishga tushirish: python -m tests.test_cardpay
"""

import asyncio
import io
import json
import os
import tempfile
from datetime import timedelta, timezone

os.environ["DATABASE_URL"] = f"sqlite+aiosqlite:///{tempfile.mkdtemp()}/card.db"
os.environ["BOT_TOKEN"] = "123456:TEST"
os.environ["ADMIN_IDS"] = "1"

from app import llm, receipt, store, videobot  # noqa: E402
from app.bot import money  # noqa: E402
from app.db import Payment, Session, User, init_db, utcnow  # noqa: E402

TZ = timezone(timedelta(hours=5))
AI = {}  # keyingi AI javobi


async def fake_generate(tier, system, prompt, max_tokens, effort="medium", schema=None, provider=None, model=None, image=None):
    assert image and image[0] and image[1] in ("image/jpeg", "application/pdf")
    from types import SimpleNamespace
    return json.dumps(AI["r"]), SimpleNamespace(input_tokens=1500, output_tokens=80, model="test")


llm.generate = fake_generate


class Bot:
    def __init__(self):
        self.sent, self.photos = [], []

    async def send_message(self, chat_id, text, **kw):
        self.sent.append((chat_id, text, kw.get("reply_markup")))
        return Msg(self, chat_id, None)

    async def send_photo(self, chat_id, photo, caption="", **kw):
        self.photos.append((chat_id, caption, kw.get("reply_markup")))

    async def send_document(self, chat_id, doc, caption="", **kw):
        self.photos.append((chat_id, caption, kw.get("reply_markup")))

    async def get_file(self, file_id):
        from types import SimpleNamespace
        return SimpleNamespace(file_path=f"photos/{file_id}.jpg")

    async def download_file(self, path):
        return io.BytesIO(("IMG:" + path).encode())


class Msg:
    def __init__(self, bot, uid, file_id):
        from types import SimpleNamespace
        self.bot, self.from_user = bot, SimpleNamespace(id=uid)
        self.photo = [SimpleNamespace(file_id=file_id, file_size=1000)] if file_id else None
        self.document, self.text = None, None

    async def answer(self, text, **kw):
        return await self.bot.send_message(self.from_user.id, text, **kw)

    async def delete(self):
        pass


def ai(amount, minutes_ago=2, last4="3622", tid="T1", success=True, is_receipt=True, edited=False):
    at = (utcnow().replace(tzinfo=timezone.utc) - timedelta(minutes=minutes_ago)).astimezone(TZ)
    AI["r"] = {"is_receipt": is_receipt, "success": success, "amount": amount, "datetime": at.strftime("%Y-%m-%d %H:%M"),
               "recipient_last4": last4, "recipient_name": "BAKHROMOV DIYOR", "transaction_id": tid, "app": "Click",
               "edited_signs": edited}


async def balance(uid):
    async with Session() as s:
        return (await s.get(User, uid)).balance


async def pay(uid, amount, minutes_ago=10):
    async with Session() as s:
        p = Payment(user_id=uid, amount=amount)
        s.add(p)
        await s.commit()
    p = await money.card_payment(p.id, uid)
    async with Session() as s:  # to'lov biroz oldin ochilgan
        row = await s.get(Payment, p.id)
        row.created_at = utcnow() - timedelta(minutes=minutes_ago)
        await s.commit()
        return row


async def main() -> None:
    await init_db()
    bot = Bot()
    videobot.BOT = bot
    async with Session() as s:
        s.add_all([User(tg_id=10, first_name="Ali"), User(tg_id=11, first_name="Vali")])
        await s.commit()

    # sozlama: o'chirilgan bo'lsa karta usuli yo'q
    assert receipt.enabled(await receipt.config())  # standart: yoqilgan
    await receipt.save({"on": False})
    assert not receipt.enabled(await receipt.config())
    async with Session() as s:
        p0 = Payment(user_id=10, amount=1000)
        s.add(p0)
        await s.commit()
    assert await money.card_payment(p0.id, 10) is None
    cfg = await receipt.save({"on": True, "card": "9860020102803622", "owner": "Bakhromov Diyor", "auto_max": 300000})
    assert cfg["card"] == "9860 0201 0280 3622" and receipt.enabled(cfg)

    # 1) hammasi to'g'ri — avtomatik tasdiq, balans to'ladi, adminga xabar «bekor qilish» tugmasi bilan
    p = await pay(10, 29700)
    assert p.provider == "card"
    assert any("9860 0201 0280 3622" in t for _, t, _ in bot.sent), "karta ma'lumoti botga yuborilmadi"
    ai(29700)
    assert await money.process_receipt(Msg(bot, 10, "F1"), p) == "auto"
    assert await balance(10) == 29700
    async with Session() as s:
        row = await s.get(Payment, p.id)
        assert row.status == "approved" and row.admin_id == 0 and row.ext_id == "T1" and row.receipt == "F1" and row.receipt_hash
    assert bot.photos and "Avtomatik" in bot.photos[-1][1] and "trev:" in json.dumps(bot.photos[-1][2].model_dump())

    # 2) o'sha chek fayli qayta — takroriy
    p2 = await pay(10, 29700)
    assert await money.process_receipt(Msg(bot, 10, "F1"), p2) == "dup"

    # 3) boshqa fayl, lekin o'sha tranzaksiya raqami — qo'lda tekshiruvga
    ai(29700, tid="T1")
    assert await money.process_receipt(Msg(bot, 10, "F2"), p2) == "review"
    assert "oldin ishlatilgan" in bot.photos[-1][1] and "tok:" in json.dumps(bot.photos[-1][2].model_dump())
    async with Session() as s:
        assert (await s.get(Payment, p2.id)).status == "pending"
    assert await balance(10) == 29700

    # 4) summa mos emas / boshqa karta / eski chek / muvaffaqiyatsiz / tahrir belgisi — hammasi qo'lda
    for kw, word in [({"amount": 20000}, "summa mos emas"), ({"amount": 9900, "last4": "1111"}, "karta boshqa"),
                     ({"amount": 9900, "minutes_ago": 60 * 5}, "chek"), ({"amount": 9900, "success": False}, "muvaffaqiyatli"),
                     ({"amount": 9900, "edited": True}, "tahrir")]:
        px = await pay(11, 9900)
        amount = kw.pop("amount")
        ai(amount, tid=f"X{px.id}", **kw)
        assert await money.process_receipt(Msg(bot, 11, f"G{px.id}"), px) == "review", word
        assert word in bot.photos[-1][1], (word, bot.photos[-1][1])
    # chek to'lov ochilishidan oldingi vaqtda
    px = await pay(11, 9900, minutes_ago=1)
    ai(9900, minutes_ago=30, tid="OLD")
    assert await money.process_receipt(Msg(bot, 11, "H1"), px) == "review" and "oldingi" in bot.photos[-1][1]
    assert await balance(11) == 0

    # 5) chek emas — qayta so'raladi, adminga bormaydi
    n = len(bot.photos)
    px = await pay(11, 9900)
    ai(0, is_receipt=False, tid="")
    assert await money.process_receipt(Msg(bot, 11, "N1"), px) == "not_receipt" and len(bot.photos) == n

    # 6) qo'lda tasdiqlash ishlaydi (status pending)
    assert await money.decide_payment(bot, p2.id, True, 1) == "ok"
    assert await balance(10) == 59400

    # 7) chegaradan katta summa va kunlik limit — qo'lda
    await receipt.save({"auto_max": 50000})
    pb = await pay(10, 99000)
    ai(99000, tid="BIG")
    assert await money.process_receipt(Msg(bot, 10, "B1"), pb) == "review" and "chegaradan" in bot.photos[-1][1]
    await receipt.save({"auto_max": 300000, "daily_auto": 1})
    pl = await pay(10, 9900)
    ai(9900, tid="LIM")
    assert await money.process_receipt(Msg(bot, 10, "L1"), pl) == "review" and "limiti" in bot.photos[-1][1]
    await receipt.save({"daily_auto": 3})

    # 8) AI ishlamasa — qo'lda
    async def broken(*a, **kw):
        raise llm.LLMError("down")
    llm.generate = broken
    pa = await pay(11, 9900)
    assert await money.process_receipt(Msg(bot, 11, "A1"), pa) == "review" and "o'qiy olmadi" in bot.photos[-1][1]
    llm.generate = fake_generate

    # 9) soxta chek: avtomatik tasdiqlanganini bekor qilish — balansdan qaytariladi
    pr = await pay(11, 9900)
    ai(9900, tid="FAKE")
    assert await money.process_receipt(Msg(bot, 11, "R1"), pr) == "auto"
    assert await balance(11) == 9900
    assert await money.revert_payment(pr.id, 1) == "ok"
    assert await balance(11) == 0
    async with Session() as s:
        assert (await s.get(Payment, pr.id)).status == "rejected"
    assert await money.revert_payment(pr.id, 1) == "done"

    # 10) ism bo'yicha (karta raqami ko'rinmasa)
    assert receipt._name_ok("Bakhromov Diyor", "DIYOR BAXROMOV") and not receipt._name_ok("Bakhromov Diyor", "ALI VALIYEV")

    # 11) to'lov ko'rsatmasida karta tugmasi
    kb = videobot.pay_keyboard(5, 9900, "uz", card=True)
    assert "tcard:5" in json.dumps(kb.model_dump())

    store.forget()
    print("test_cardpay: OK")


if __name__ == "__main__":
    asyncio.run(main())
