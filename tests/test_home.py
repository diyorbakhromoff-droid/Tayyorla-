"""Shaxsiy bosh sahifa va «javob qaytarish» tekshiruvlari: python -m tests.test_home"""

import asyncio
import os
import tempfile
from types import SimpleNamespace

DB = os.path.join(tempfile.mkdtemp(), "home.db")
os.environ["BOT_TOKEN"] = "123456:TEST"
os.environ["DATABASE_URL"] = f"sqlite+aiosqlite:///{DB}"

from fastapi import HTTPException  # noqa: E402

from app import web, webapp  # noqa: E402
from app.db import Session, Site, init_db  # noqa: E402
from tests.test_webapp import sign  # noqa: E402

ME = sign({"id": 101, "first_name": "Diyor"})
OTHER = sign({"id": 202, "first_name": "Ali"})


async def status(coro) -> int:
    try:
        await coro
    except HTTPException as e:
        return e.status_code
    return 200


async def main() -> None:
    await init_db()
    await init_db()  # ikkinchi marta ham xatosiz (migratsiya takrorlanmaydi)

    me = await webapp.me(ME)
    assert me["onboarded"] is False and me["name"] == "Diyor" and me["people"] == []

    body = webapp.OnboardIn(relations=["ona", "sevgili", "yo'q"], people=[
        webapp.PersonIn(name=" Gulnora ", relation="ona", day=12, month=3, year=1970),
        webapp.PersonIn(name="Madina", relation="sevgili", day=29, month=2),
    ])
    await webapp.onboard(body, ME)
    me = await webapp.me(ME)
    assert me["onboarded"] and me["relations"] == ["ona", "sevgili"], me["relations"]
    assert [p["name"] for p in me["people"]] and {p["name"] for p in me["people"]} == {"Gulnora", "Madina"}
    gul = next(p for p in me["people"] if p["name"] == "Gulnora")
    assert gul["emoji"] == "🌷" and gul["born"] == "1970-03-12" and gul["section"] == "tugilgan-kun"
    assert me["people"] == sorted(me["people"], key=lambda p: p["days_left"])

    assert await status(webapp.add_person(webapp.PersonIn(name="X", day=30, month=2), ME)) == 400
    assert await status(webapp.add_person(webapp.PersonIn(name="X", kind="nimadir", day=1, month=1), ME)) == 400
    added = await webapp.add_person(webapp.PersonIn(name="Sardor", relation="dost", kind="anniversary", day=1, month=6), ME)
    assert added["relation"] == "dost"
    assert await status(webapp.delete_person(added["id"], OTHER)) == 404, "begona odam o'chira olmaydi"
    assert await status(webapp.delete_person(added["id"], ME)) == 200
    assert await status(webapp.me("")) == 401

    # javob qaytarish
    sent = []

    async def notify(chat_id, text):
        sent.append((chat_id, text))

    web.notify = notify
    cfg = {"engine": "catalog", "template": "tk-tort", "tarif": "premium", "rang": 1, "category": "birthday",
           "data": {"kimga": "<b>Gulnora</b>", "sana": "2026-11-01"}, "photos": [], "music": None}
    async with Session() as s:
        draft = Site(slug="draft1", owner_id=101, owner_name="Diyor", category="birthday", config=cfg)
        paid = Site(slug="paid1", owner_id=101, owner_name='Diyor</b><script>', category="birthday", config=cfg, status="paid")
        s.add_all([draft, paid])
        await s.commit()
    req = SimpleNamespace(client=SimpleNamespace(host="1.2.3.4"))
    assert await status(web.react("draft1", web.ReactIn(emoji="❤️"), req)) == 404, "namunaga javob yo'q"
    assert await status(web.react("paid1", web.ReactIn(emoji="💩"), req)) == 400
    assert await status(web.react("paid1", web.ReactIn(emoji="🥹", message="  Rahmat   bolam <3 "), req)) == 200
    assert sent and sent[-1][0] == 101 and "&lt;b&gt;Gulnora" in sent[-1][1] and "Rahmat bolam &lt;3" in sent[-1][1]
    for _ in range(4):
        await web.react("paid1", web.ReactIn(emoji="❤️"), req)
    assert await status(web.react("paid1", web.ReactIn(emoji="❤️"), req)) == 429, "soatiga 5 tadan ortiq emas"

    me = await webapp.me(ME)
    assert me["stats"] == {"happy": 1, "views": 0, "reactions": 5}, me["stats"]
    assert me["messages"][0]["text"] == "Rahmat bolam <3" and len(me["messages"]) == 1
    assert "owner=" in me["sites"][0]["url"]

    # vidjet faqat to'langan sahifada, egasiga emas; ism xavfsiz
    async with Session() as s:
        site = await web.get_site(s, "paid1")
    page = web.with_react_widget("<html><body>x</body></html>", site)
    assert page.index("tyrR") < page.index("</body>") and "Diyor&lt;/b&gt;&lt;script&gt;ga" in page
    assert '"Diyor\\u003c/b\\u003e\\u003cscript\\u003e"' in page, "JS ichida ham xavfsiz"
    print("✅ Bosh sahifa va javoblar tekshiruvlari o'tdi")


asyncio.run(main())
