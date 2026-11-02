"""Admin paneli: kirish kaliti, statistika, trafik manbalari, sotuvlar va tarqatma segmentlari.

Ishga tushirish: python -m tests.test_admin
"""

import asyncio
import os
import tempfile
from datetime import timedelta

os.environ["DATABASE_URL"] = f"sqlite+aiosqlite:///{tempfile.mkdtemp()}/admin.db"
os.environ["BOT_TOKEN"] = "123456:TEST"
os.environ["ADMIN_IDS"] = "999"

from fastapi import HTTPException  # noqa: E402

from app import admin, track  # noqa: E402
from app.billing import credit, spend  # noqa: E402
from app.db import BalanceTx, Event, Payment, RenderJob, Session, Site, User, init_db, utcnow  # noqa: E402
from app.reminders import today  # noqa: E402

TPL = next(t for t in admin.TEMPLATES.values() if t.get("v2") and t["tier"] == "premium")


def rejects(fn) -> bool:
    try:
        fn()
    except HTTPException:
        return True
    return False


async def seed() -> None:
    now = utcnow()
    async with Session() as s:
        # 1 — reklama havolasidan kelib, sayt sotib olgan; 2 — havoladan kelib, faqat bepul video; 3 — organik, sayt yasab sotib olmagan
        s.add_all([User(tg_id=1, first_name="Ali", ref="src_insta1", created_at=now), User(tg_id=2, first_name="Vali", ref="src_insta1", created_at=now),
                   User(tg_id=3, first_name="Gani", created_at=now), User(tg_id=4, first_name="Eski", created_at=now - timedelta(days=40)),
                   User(tg_id=999, first_name="Admin", created_at=now - timedelta(days=60))])
        s.add_all([Event(user_id=1, kind="start", src="src_insta1"), Event(user_id=2, kind="start", src="src_insta1"),
                   Event(user_id=1, kind="app"), Event(user_id=2, kind="app"), Event(user_id=3, kind="app"),
                   Event(user_id=4, kind="app")])
        cfg = {"engine": "catalog", "template": TPL["id"], "tarif": "premium", "data": {"ism": "Madina"}}
        s.add_all([Site(slug="paid1", owner_id=1, category=TPL["section"], config=cfg, status="paid", kind="site"),
                   Site(slug="draft1", owner_id=3, category=TPL["section"], config=cfg, status="draft", kind="site")])
        s.add_all([RenderJob(owner_id=2, design="v-anor", payload={}, hash="a", charge="free", status="done"),
                   RenderJob(owner_id=3, design="v-anor", payload={}, hash="b", charge="paid", price=9900, status="awaiting_payment")])
        s.add(Payment(user_id=1, amount=59000, status="approved", decided_at=now))
        s.add(Payment(user_id=3, amount=9900, status="pending"))
        await s.commit()
        await credit(s, 1, 59000, "topup", "pay:1")
        assert await spend(s, 1, 59000, "site", "site:paid1")
        await s.commit()


async def main() -> None:
    await init_db()
    await seed()

    # kirish: imzoli kalit, muddati o'tgani va admin bo'lmagan foydalanuvchi rad etiladi
    tok = admin.make_token(999)
    assert admin.check_token(tok) == 999
    assert admin.check_token(tok[:-1] + ("0" if tok[-1] != "0" else "1")) is None
    assert admin.check_token(admin.make_token(999, hours=-1)) is None
    assert admin.admin_uid("", tok, "") == 999
    assert rejects(lambda: admin.admin_uid("", admin.make_token(5), ""))
    assert rejects(lambda: admin.admin_uid("", "", ""))

    assert track.src_code("src_Insta1") == "insta1" and track.src_code("ref_5") == "" and track.src_code("src_x y") == ""

    d = today().isoformat()
    ov = await admin.overview(frm=d, to=d, uid=999)
    c = ov["cur"]
    assert c["users"]["new"] == 3 and c["users"]["app_users"] == 4 and c["users"]["returning"] == 1, c["users"]
    assert c["sites"]["created"] == 2 and c["sites"]["unpaid"] == 1 and c["sites"]["sold"] == 1 and c["sites"]["sold_sum"] == 59000
    assert c["videos"]["free"] == 1 and c["videos"]["unpaid"] == 1
    assert c["money"]["topup"] == 59000 and c["money"]["new_payers"] == 1
    assert [f["n"] for f in c["funnel"]] == [3, 3, 3, 1], c["funnel"]
    assert ov["now"]["pending"] == 1 and sum(c["series"]["revenue"]) == 59000
    assert ov["prev"]["users"]["new"] == 0

    # trafik havolasi: yaratish, bosish, manba bo'yicha natijalar
    made = await admin.link_create(admin.LinkIn(name="Instagram reklama", code="insta1", cost=100000), uid=999)
    assert made["urls"]["bot"].endswith("?start=src_insta1") and made["urls"]["go"].endswith("/go/insta1")
    try:
        await admin.link_create(admin.LinkIn(name="X", code="insta1"), uid=999)
        raise AssertionError("band kod qabul qilindi")
    except HTTPException as e:
        assert e.status_code == 409
    auto = await admin.link_create(admin.LinkIn(name="Telegram kanal: Oila"), uid=999)
    assert auto["code"] == "telegram_kanal_o"

    class Req:
        method = "GET"
        headers = {"user-agent": "Mozilla/5.0 (iPhone)"}

    class BotReq:
        method = "GET"
        headers = {"user-agent": "TelegramBot (like TwitterBot)"}

    r = await admin.go("insta1", Req())
    assert r.status_code == 302 and "start=src_insta1" in r.headers["location"]
    await admin.go("insta1", BotReq())  # havola ko'rinishi sanalmaydi
    src = await admin.sources(frm=d, to=d, uid=999)
    row = next(x for x in src["links"] if x["code"] == "insta1")
    assert (row["clicks"], row["starts"], row["users"], row["app"], row["created"], row["bought"]) == (1, 2, 2, 2, 2, 1), row
    assert row["revenue"] == 59000 and row["cpu"] == 50000 and row["cpb"] == 100000 and row["roi"] == -41.0, row
    organic = next(x for x in src["groups"] if x["key"] == "organic")
    assert organic["users"] == 1 and organic["created"] == 1 and organic["bought"] == 0

    # hamkor hisoboti: maxfiy havola, faqat shu havola raqamlari, tushum faqat ruxsat bilan
    sh = await admin.link_share(row["id"], admin.ShareIn(enable=True), uid=999)
    rep_url = sh["urls"]["report"]
    assert rep_url and "/hisobot/" in rep_url
    key = rep_url.rsplit("/", 1)[1]
    page = (await admin.partner_report(key, d="7")).body.decode()
    assert "Instagram reklama" in page and "Tushum" not in page and "Ali" not in page and "Vali" not in page
    async with Session() as s:
        from app.db import TrafficLink
        x = (await s.execute(__import__("sqlalchemy").select(TrafficLink).where(TrafficLink.code == "insta1"))).scalar_one()
    rep = await admin.link_report(x, admin.utc_of(today()), admin.utc_of(today() + timedelta(days=1)), [today()])
    assert (rep["clicks"], rep["starts"], rep["users"], rep["app"], rep["created"], rep["bought"]) == (1, 2, 2, 2, 2, 1), rep
    assert rep["daily"][0] == {"day": today().isoformat(), "clicks": 1, "starts": 2, "users": 2}
    await admin.link_share(row["id"], admin.ShareIn(enable=True, revenue=True), uid=999)
    assert "59 000" in (await admin.partner_report(key, d="all")).body.decode()  # kalit o'zgarmadi, tushum ko'rinadi
    new_key = (await admin.link_share(row["id"], admin.ShareIn(enable=True, renew=True), uid=999))["urls"]["report"].rsplit("/", 1)[1]
    assert new_key != key and (await admin.partner_report(key)).status_code == 404
    await admin.link_share(row["id"], admin.ShareIn(enable=False), uid=999)
    assert (await admin.partner_report(new_key)).status_code == 404

    sl = await admin.sales(frm=d, to=d, uid=999)
    t = next(x for x in sl["templates"] if x["id"] == TPL["id"])
    assert t["created"] == 2 and t["paid"] == 1 and t["conv"] == 50.0
    assert [x["slug"] for x in sl["unpaid"]] == ["draft1"] and sl["unpaid"][0]["name"] == "Gani"

    pays = await admin.payments(status="pending", limit=100, uid=999)
    assert [p["user_id"] for p in pays["payments"]] == [3]

    # foydalanuvchi: qidiruv, kartochka, balansni tuzatish (manfiyga tushmaydi)
    found = await admin.users_list(q="ali", sort="new", page=0, uid=999)  # Ali va Vali
    ali = next(u for u in found["users"] if u["id"] == 1)
    assert found["total"] == 2 and ali["source"] == "Instagram reklama" and ali["spent"] == 59000 and ali["sites"] == 1
    assert (await admin.users_list(q="3", sort="new", page=0, uid=999))["users"][0]["name"] == "Gani"
    card = await admin.user_card(1, uid=999)
    assert card["sites"][0]["slug"] == "paid1" and card["tx"][0]["kind"] == "site"
    res = await admin.user_balance(3, admin.BalanceIn(amount=-5000, bonus=2), uid=999)
    assert res == {"balance": 0, "bonus": 2}
    res = await admin.user_balance(3, admin.BalanceIn(amount=10000, note="kompensatsiya"), uid=999)
    assert res["balance"] == 10000
    async with Session() as s:
        from sqlalchemy import select
        kinds = (await s.execute(select(BalanceTx.kind).where(BalanceTx.user_id == 3))).scalars().all()
    assert kinds == ["admin"]  # 0 dan pastga tushirilmagan, faqat qo'shilgani yozildi

    # tarqatma segmentlari
    seg = lambda k, code="": admin.segment_ids(k, code, 999)  # noqa: E731
    assert sorted(await seg("site_unpaid")) == [3]
    assert sorted(await seg("free_only")) == [2]
    assert sorted(await seg("never")) == [4, 999]
    assert sorted(await seg("src", "insta1")) == [1, 2]
    assert await seg("me") == [999]

    # ilovaga kirish kuniga bir marta yoziladi
    await track.app_open(50)
    await track.app_open(50)
    track._APP_DAY.clear()
    await track.app_open(50)
    async with Session() as s:
        from sqlalchemy import func, select
        n = await s.scalar(select(func.count()).select_from(Event).where(Event.user_id == 50, Event.kind == "app"))
    assert n == 1

    csv = await admin.export("users", uid=999)
    body = csv.body.decode("utf-8")
    assert body.startswith("﻿id;") and "Instagram reklama" in body
    sysinfo = await admin.system(uid=999)
    assert sysinfo["queue"]["awaiting_payment"] == 1 and sysinfo["tables"]["Foydalanuvchilar"] == 5

    page = (await admin.admin_page()).body.decode()
    assert "__V__" not in page and "/static/admin/admin.js?v=" in page
    print("✅ Admin paneli tekshiruvlari o'tdi")


asyncio.run(main())
