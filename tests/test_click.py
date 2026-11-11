"""Click SHOP API: imzo, Prepare/Complete, takroriy va xato so'rovlar, balans va saytning avtomatik to'lanishi.

Ishga tushirish: python -m tests.test_click
"""

import asyncio
import hashlib
import json
import os
import tempfile

os.environ["DATABASE_URL"] = f"sqlite+aiosqlite:///{tempfile.mkdtemp()}/click.db"
os.environ["BOT_TOKEN"] = "123456:TEST"
os.environ["CLICK_SERVICE_ID"] = "777"
os.environ["CLICK_MERCHANT_ID"] = "555"
os.environ["CLICK_MERCHANT_USER_ID"] = "1"
os.environ["CLICK_SECRET_KEY"] = "test-secret"

from app import click  # noqa: E402
from app.catalog import site_price  # noqa: E402
from app.db import Payment, Session, Site, User, init_db  # noqa: E402

SECRET = "test-secret"


def form(pid, amount, trans="9001", action=0, prepare_id=None, error=0):
    f = {"click_trans_id": trans, "service_id": "777", "click_paydoc_id": "1", "merchant_trans_id": str(pid),
         "amount": amount, "action": str(action), "error": str(error), "error_note": "Success", "sign_time": "2026-11-11 10:00:00"}
    if prepare_id is not None:
        f["merchant_prepare_id"] = str(prepare_id)
    raw = f["click_trans_id"] + f["service_id"] + SECRET + f["merchant_trans_id"] + \
        (f["merchant_prepare_id"] if prepare_id is not None else "") + f["amount"] + f["action"] + f["sign_time"]
    f["sign_string"] = hashlib.md5(raw.encode()).hexdigest()
    return f


async def main() -> None:
    await init_db()
    async with Session() as s:
        s.add(User(tg_id=10, first_name="Ali"))
        cfg = {"engine": "catalog", "template": "x", "tarif": "premium", "data": {}}
        site = Site(slug="clk1", owner_id=10, category="toy", config=cfg, status="draft", kind="site")
        s.add(site)
        await s.flush()
        price = site_price(site.config)
        s.add_all([Payment(user_id=10, amount=29700), Payment(user_id=10, amount=price, site_id=site.id), Payment(user_id=10, amount=9900)])
        await s.commit()

    url = click.pay_url(1, 29700)
    assert url.startswith("https://my.click.uz/services/pay?") and "service_id=777" in url and "merchant_id=555" in url
    assert "transaction_param=1" in url and "amount=29700.00" in url

    class Req:
        def __init__(self, f):
            self.f = f

        async def form(self):
            return self.f

    class Resp:
        def __init__(self, r):
            self.r = r

        def json(self):
            return json.loads(self.r.body)

    async def post(path, f):
        return Resp(await (click.prepare if path == "prepare" else click.complete)(Req(f)))

    if True:

        # imzo, summa, topilmagan buyurtma, noto'g'ri action
        bad = form(1, "29700.00"); bad["sign_string"] = "0" * 32
        assert (await post("prepare", bad)).json()["error"] == -1
        assert (await post("prepare", form(1, "100.00"))).json()["error"] == -2
        assert (await post("prepare", form(99, "29700.00"))).json()["error"] == -5
        assert (await post("prepare", form(1, "29700.00", action=1))).json()["error"] == -3
        miss = form(1, "29700.00"); miss.pop("sign_time")
        assert (await post("prepare", miss)).json()["error"] == -8

        # muvaffaqiyatli oqim
        r = (await post("prepare", form(1, "29700.00"))).json()
        assert r["error"] == 0 and r["merchant_prepare_id"] == 1 and r["click_trans_id"] == "9001", r
        assert (await post("complete", form(1, "29700.00", trans="9999", action=1, prepare_id=1))).json()["error"] == -6
        r = (await post("complete", form(1, "29700.00", action=1, prepare_id=1))).json()
        assert r["error"] == 0 and r["merchant_confirm_id"] == 1, r
        # takroriy complete pulni ikki marta qo'shmaydi
        assert (await post("complete", form(1, "29700.00", action=1, prepare_id=1))).json()["error"] == -4
        assert (await post("prepare", form(1, "29700.00", trans="9002"))).json()["error"] == -4
        async with Session() as s:
            assert (await s.get(User, 10)).balance == 29700
            assert (await s.get(Payment, 1)).status == "approved"

        # sayt uchun to'lov: balans to'ladi va sayt o'zi faollashadi (bot bo'lmasa ham)
        assert (await post("prepare", form(2, f"{price}.00", trans="9100"))).json()["error"] == 0
        assert (await post("complete", form(2, f"{price}.00", trans="9100", action=1, prepare_id=2))).json()["error"] == 0
        async with Session() as s:
            assert (await s.get(Site, 1)).status == "paid"
            assert (await s.get(User, 10)).balance == 29700  # sayt narxi yechildi

        # Click tomonida xato bo'lsa — bekor qilinadi, balansga tegmaydi
        assert (await post("prepare", form(3, "9900.00", trans="9200"))).json()["error"] == 0
        assert (await post("complete", form(3, "9900.00", trans="9200", action=1, prepare_id=3, error=-5017))).json()["error"] == -9
        assert (await post("prepare", form(3, "9900.00", trans="9201"))).json()["error"] == -9
        async with Session() as s:
            assert (await s.get(Payment, 3)).status == "cancelled" and (await s.get(User, 10)).balance == 29700
    print("✅ Click tekshiruvlari o'tdi")


asyncio.run(main())
