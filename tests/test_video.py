"""Video taklifnoma, balans, obuna, mehmonlar va tadbir sahifasi tekshiruvlari: python -m tests.test_video"""

import asyncio
import os
import tempfile
from datetime import datetime
from pathlib import Path

TMP = tempfile.mkdtemp()
os.environ["DATABASE_URL"] = f"sqlite+aiosqlite:///{TMP}/video.db"
os.environ["BOT_TOKEN"] = "123456:TEST"
os.environ["ADMIN_IDS"] = "999"
os.environ["CHANNEL_ID"] = "https://t.me/tayyorlaai"
os.environ["BASE_URL"] = "https://tayyorla.test"

from aiogram import Bot, Dispatcher  # noqa: E402
from aiogram.client.default import DefaultBotProperties  # noqa: E402
from aiogram.client.session.base import BaseSession  # noqa: E402
from aiogram.types import (Audio, CallbackQuery, Chat, ChatMemberLeft, ChatMemberMember, File, InlineQuery,  # noqa: E402
                           Message, MessageId, PhotoSize, PreparedInlineMessage, Update, User, Video)
from fastapi import HTTPException  # noqa: E402
from sqlalchemy import select  # noqa: E402

from app import billing, events, i18n, renderer, video, videoapi, videobot, web, webapp  # noqa: E402
from app.bot import handlers  # noqa: E402
from app.catalog import clean_order, render_catalog  # noqa: E402
from app.config import settings  # noqa: E402
from app.db import Guest, MusicTrack, Payment, RenderJob, Rsvp, Session, Site, User as DbUser, init_db  # noqa: E402
from tests.test_webapp import sign  # noqa: E402

USER = User(id=501, is_bot=False, first_name="Diyor", language_code="uz")
FRIEND = User(id=601, is_bot=False, first_name="Ali", language_code="ru")
ADMIN = User(id=999, is_bot=False, first_name="Admin")
SUBSCRIBED: set[int] = set()


class FakeSession(BaseSession):
    def __init__(self):
        super().__init__()
        self.calls: list[tuple[str, object]] = []

    async def make_request(self, bot, method, timeout=None):
        name = type(method).__name__
        self.calls.append((name, method))
        chat = getattr(method, "chat_id", None) or 1
        if name in ("SendMessage", "EditMessageText"):
            return Message(message_id=len(self.calls), date=datetime.now(), chat=Chat(id=chat, type="private"), text=method.text).as_(bot)
        if name == "SendVideo":
            return Message(message_id=len(self.calls), date=datetime.now(), chat=Chat(id=chat, type="private"),
                           video=Video(file_id=f"vid{len(self.calls)}", file_unique_id="u", width=1080, height=1920, duration=20)).as_(bot)
        if name == "CopyMessage":
            return MessageId(message_id=1)
        if name == "GetChatMember":
            u = User(id=method.user_id, is_bot=False, first_name="x")
            return ChatMemberMember(user=u) if method.user_id in SUBSCRIBED else ChatMemberLeft(user=u)
        if name == "GetFile":
            return File(file_id=method.file_id, file_unique_id="f", file_path="music/x.mp3")
        if name == "SavePreparedInlineMessage":
            return PreparedInlineMessage(id="prep1", expiration_date=0)
        return True

    async def stream_content(self, *a, **k):
        yield b"ID3"

    async def close(self):
        pass

    def texts(self) -> list[str]:
        out = [getattr(m, "text", None) or getattr(m, "caption", None) for _, m in self.calls]
        return [t for t in out if t]

    def last(self, name: str):
        return next(m for n, m in reversed(self.calls) if n == name)


session = FakeSession()
bot = Bot("123456:TEST", session=session, default=DefaultBotProperties(parse_mode="HTML"))
videobot.BOT = bot
dp = Dispatcher()
dp.include_router(handlers.router)
upd = 0
notified = []


async def notify(chat_id, text):
    notified.append((chat_id, text))

web.notify = notify


def msg(user=USER, **kw) -> Message:
    return Message(message_id=1, date=datetime.now(), chat=Chat(id=user.id, type="private"), from_user=user, **kw)


async def send(text=None, user=USER, **kw):
    global upd
    upd += 1
    await dp.feed_update(bot, Update(update_id=upd, message=msg(user, text=text, **kw)))


async def click(data, user=USER):
    global upd
    upd += 1
    cq = CallbackQuery(id=str(upd), from_user=user, chat_instance="x", data=data, message=msg(user, text="..."))
    await dp.feed_update(bot, Update(update_id=upd, callback_query=cq))


async def code(coro) -> object:
    try:
        await coro
    except HTTPException as e:
        return e.status_code, e.detail
    return 200, None


U = sign({"id": 501, "first_name": "Diyor", "language_code": "uz"})
TOY = {"marosim": "nikoh", "kuyov": "Jasur", "kelin": "Malika", "sana": "2026-11-21", "ikki_kunlik": True, "sana2": "2026-11-22",
       "vaqt": "18:00", "joy": "«Navro‘z» to‘yxonasi", "manzil": "Toshkent", "xarita": "41.2856, 69.2034",
       "matn": "Sizni kutamiz", "imzo": "Karimovlar oilasi", "toyona": True, "karta": "8600 1234 5678 9012", "karta_egasi": "Malika"}


async def main():
    await init_db()

    # --- tekshirish va payload
    assert (await code(asyncio.sleep(0)))[0] == 200
    try:
        video.clean_data("toy", {"kuyov": "Jasur"}, strict=True)
        raise AssertionError("majburiy maydon tekshirilmadi")
    except HTTPException as e:
        assert e.detail == "required:kelin", e.detail
    data = video.clean_data("toy", TOY, strict=True)
    assert data["karta"] == "8600123456789012" and data["sana2"] == "2026-11-22"
    p = video.build_payload("v-atlas", data, "uz", guest="Aziz aka", site_url="https://x/s/a")
    assert p["t"]["date"] == "21–22-noyabr, 2026" and p["t"]["dear"] == "Hurmatli Aziz aka!" and p["f"]["two_day"]
    assert p["t"]["card_number"] == "8600 1234 5678 9012" and p["map"].startswith("https://yandex.uz/maps/?pt=69.2034,41.2856")
    assert p["qr"]["n"] >= 21 and p["f"]["free"]
    p_ru = video.build_payload("v-atlas", data, "ru", guest="Aziz aka")
    assert p_ru["t"]["name1"] == "Жасур" and p_ru["t"]["date"] == "21–22 ноября 2026" and p_ru["t"]["event"] == "Свадьба"
    assert video.build_payload("v-atlas", data, "cy")["t"]["venue"] == "«Наврўз» тўйхонаси"
    cap = video.caption(p, paid=False, guest="Aziz aka")
    assert "<code>8600 1234 5678 9012</code>" in cap and "@tayyorla_aibot" in cap and "Hurmatli Aziz aka!" in cap
    assert "@tayyorla_aibot" not in video.caption(p, paid=True)
    html = video.page_html("v-atlas", p, mode="render")
    assert "window.__TV" in html and "engine.js" in html and "</script>" in html
    assert video.render_hash(p, None) != video.render_hash(video.build_payload("v-atlas", data, "uz", guest="Ali"), None)

    # --- ochiq sahifa va meta
    meta = await videoapi.video_meta("ru")
    assert any(d["id"] == "v-atlas" for d in meta["designs"]) and meta["price"] == 9900 and meta["channel"] == "https://t.me/tayyorlaai"
    page = await videoapi.video_page("v-atlas", still=7000)
    assert '"mode": "still"' in page and '"t": 7000' in page

    # --- profil: til, kvota, referal havola
    me = await webapp.me(U)
    assert me["lang"] == "uz" and me["quota"]["free_left"] == 2 and me["balance"] == 0 and me["ref_link"].endswith("ref_501")

    # --- video yaratish: 2 ta bepul, keyin paywall
    body = videoapi.VideoIn(design="v-atlas", data=TOY, lang="uz")
    r1 = await videoapi.create_video(body, U)
    assert r1["status"] == "queued" and r1["charge"] == "free" and r1["need_sub"] and not r1["subscribed"], r1
    assert any("Navbatda" in t for t in session.texts())
    again = await videoapi.create_video(videoapi.VideoIn(design="v-atlas", data=TOY, lang="uz", site=r1["site"]), U)
    assert again["job"] == r1["job"], "bir xil video ikki marta navbatga qo'yilmaydi"
    r2 = await videoapi.create_video(videoapi.VideoIn(design="v-atlas", data={**TOY, "kimga": "Nodir"}, site=r1["site"]), U)
    assert r2["charge"] == "free" and r2["site"] == r1["site"] and r2["quota"]["free_left"] == 0
    st, detail = await code(videoapi.create_video(videoapi.VideoIn(design="v-atlas", data={**TOY, "kimga": "Ali"}), U))
    assert st == 402 and detail["code"] == "paywall" and detail["price"] == 9900

    # to'lovni kutib turgan video: chek -> admin tasdig'i -> navbat
    r3 = await videoapi.create_video(videoapi.VideoIn(design="v-atlas", data={**TOY, "kimga": "Ali"}, pay="wait"), U)
    assert r3["status"] == "awaiting_payment"
    assert "Video uchun to‘lov" in session.texts()[-1]
    await click(f"tpaid:{r3['payment']}")
    await send(photo=[PhotoSize(file_id="chek", file_unique_id="c", width=10, height=10)])
    assert "Chek qabul qilindi" in session.texts()[-1]
    async with Session() as s:
        assert (await s.get(Payment, r3["payment"])).status == "pending"
    await click(f"tok:{r3['payment']}", user=ADMIN)
    async with Session() as s:
        j3 = await s.get(RenderJob, r3["job"])
        u = await s.get(DbUser, 501)
    assert j3.status == "queued" and j3.charge == "paid" and u.balance == 0, (j3.status, u.balance)
    assert any("Balansingiz to‘ldirildi" in t for t in session.texts())
    assert not j3.payload["page"]["f"]["free"], "pullik videoda reklama yozuvi bo'lmaydi"

    # --- renderer: navbatdan olish va yetkazish (obuna sharti)
    job = await renderer.claim()
    assert job.id == r1["job"] and job.status == "rendering"
    fake = Path(TMP) / "v.mp4"
    fake.write_bytes(b"0")
    async with Session() as s:
        j = await s.get(RenderJob, job.id)
        j.status, j.file_path = "done", str(fake)
        await s.commit()
    await videobot.deliver(bot, j)
    assert "kanaliga obuna" in session.texts()[-1]
    await click(f"vsub:{j.id}")
    assert session.last("AnswerCallbackQuery").show_alert, "obunasiz video berilmaydi"
    SUBSCRIBED.add(501)
    await click(f"vsub:{j.id}")
    sent_video = session.last("SendVideo")
    assert "<code>8600 1234 5678 9012</code>" in sent_video.caption and sent_video.supports_streaming
    async with Session() as s:
        j = await s.get(RenderJob, job.id)
    assert j.delivered and j.tg_file_id.startswith("vid")
    assert "Bugungi bepul videolar tugadi" in session.texts()[-1]

    # aynan shu videoni qayta so'rasa — qayta yasalmaydi, file_id bilan yuboriladi
    n_jobs = len((await (await_session_all(RenderJob))))
    again = await videoapi.create_video(videoapi.VideoIn(design="v-atlas", data=TOY, lang="uz", site=r1["site"]), U)
    assert again["status"] == "sent" and len(await await_session_all(RenderJob)) == n_jobs
    assert session.last("SendVideo").video == j.tg_file_id

    # pullik videoda obuna so'ralmaydi
    async with Session() as s:
        j3 = await s.get(RenderJob, r3["job"])
        j3.status, j3.file_path = "done", str(fake)
        await s.commit()
    SUBSCRIBED.clear()
    await videobot.deliver(bot, j3)
    assert "@tayyorla_aibot" not in session.last("SendVideo").caption

    # inline ulashish va Mini App ulashish
    global upd
    upd += 1
    await dp.feed_update(bot, Update(update_id=upd, inline_query=InlineQuery(id="q1", from_user=USER, query=f"v{j.id}", offset="")))
    ans = session.last("AnswerInlineQuery")
    assert len(ans.results) == 1 and ans.results[0].video_file_id == j.tg_file_id and ans.is_personal
    assert (await videoapi.video_share(j.id, U))["id"] == "prep1"
    assert len((await videoapi.my_videos(U))["videos"]) == 3

    # --- tadbir: mehmonlar, paket, shaxsiy havola, javob, .ics
    slug = r1["site"]
    res = await videoapi_add_guests(slug, "Aziz aka\nNigora opa\n\naziz aka\nBobur; Kamola")
    assert res["added"] == 4 and res["skipped"] == 1
    ev = await events.event_detail(slug, U)
    assert ev["stats"]["invited"] == 4 and ev["has_video"] and len(ev["guests"]) == 4
    st, detail = await code(events.guest_videos(slug, U))
    assert st == 402 and detail["need"] == 39000 and detail["package"] == 15
    async with Session() as s:
        await billing.credit(s, 501, 50000, "topup", "test")
        await s.commit()
    gv = await events.guest_videos(slug, U)
    assert gv["queued"] == 4 and gv["charged"] == 39000
    assert (await events.guest_videos(slug, U))["queued"] == 0, "qayta bosilsa ikki marta yechilmaydi"
    async with Session() as s:
        u = await s.get(DbUser, 501)
        gjobs = (await s.execute(select(RenderJob).where(RenderJob.guest_id.is_not(None)))).scalars().all()
        aziz = (await s.execute(select(Guest).where(Guest.name == "Aziz aka"))).scalar_one()
    assert u.balance == 11000 and all(x.charge == "package" and not x.free for x in gjobs)
    assert {x.payload["guest"] for x in gjobs} == {"Aziz aka", "Nigora opa", "Bobur", "Kamola"}
    # oddiy video mehmon videolaridan oldin olinadi
    r4 = await videoapi.create_video(videoapi.VideoIn(design="v-atlas", data={**TOY, "kimga": "Sardor"}), U)
    assert r4["charge"] == "paid"
    assert (await renderer.claim()).id == r2["job"]
    assert (await renderer.claim()).id == r4["job"]
    assert (await renderer.claim()).guest_id is not None

    req = type("R", (), {"cookies": {}, "query_params": {"g": aziz.token}})()
    page = await web.show(slug, req)
    assert "Hurmatli Aziz aka!" in page and "Kela olasizmi, Aziz aka?" in page and "8600 1234 5678 9012" in page
    assert "/event.ics" in page and "calendar.google.com" in page
    async with Session() as s:
        assert (await s.get(Guest, aziz.id)).opened_at is not None
    await web.rsvp(slug, web.RsvpIn(attending="yes", guests=2, g=aziz.token))
    assert "Aziz aka" in notified[-1][1] and "2 kishi" in notified[-1][1]
    st, _ = await code(web.rsvp(slug, web.RsvpIn(attending="yes")))
    assert st == 400, "umumiy havolada ism majburiy"
    await web.rsvp(slug, web.RsvpIn(name="Qo'shni", attending="no"))
    ev = await events.event_detail(slug, U)
    assert ev["stats"]["yes"] == 1 and ev["stats"]["people"] == 2 and ev["stats"]["no"] == 1 and ev["stats"]["opened"] == 1
    assert next(g for g in ev["guests"] if g["name"] == "Aziz aka")["status"] == "yes"
    assert ev["answers"][0]["name"] == "Qo'shni"
    ics = (await events.event_ics(slug)).body.decode()
    assert ics.count("BEGIN:VEVENT") == 2 and "DTSTART:20261121T130000Z" in ics and "SUMMARY:Nikoh to‘yi — Jasur & Malika" in ics
    lst = await events.events_list(U)
    assert lst["events"][0]["slug"] in (slug, r4["site"])

    # --- katalog sayti: RSVP tugmalari serverga yuboradi (F11)
    cfg = clean_order({"template": "toy-klassik", "tarif": "standart", "data": {
        "kuyov": "A", "kelin": "B", "sana": "2027-05-01", "vaqt": "18:00", "manzil_nomi": "X", "manzil": "Y", "matn": "Z"}}, strict=True)
    paid = render_catalog(cfg, "abc", preview=False)
    assert "tyr-rsvp" in paid and '"/s/abc/rsvp"' in paid and "rsvp_havola" not in paid.split('site-config')[1][:2000]
    assert "tyr-rsvp" not in render_catalog(cfg, "abc", preview=True)
    async with Session() as s:
        s.add(Site(slug="kat1", owner_id=501, category=cfg["category"], config=cfg, status="paid"))
        await s.commit()
    await web.rsvp("kat1", web.RsvpIn(name="Mehmon 1", attending="yes", guests=3))
    assert "Mehmon 1" in notified[-1][1]
    async with Session() as s:
        assert (await s.execute(select(Rsvp).where(Rsvp.name == "Mehmon 1"))).scalar_one().guests == 3

    # --- referal: do'st taklif qilsa +1 bepul video
    await send("/start ref_501", user=FRIEND)
    async with Session() as s:
        inviter = await s.get(DbUser, 501)
        friend = await s.get(DbUser, 601)
    assert inviter.bonus_videos == 1 and friend.ref == "ref_501" and friend.lang == "ru"
    assert any("+1" in t for t in session.texts())

    # --- kirill tarjimasi AI siz
    tr_out = await videoapi.video_translate(videoapi.TranslateIn(section="toy", data=TOY, lang="cy"), U)
    assert tr_out["data"]["kuyov"] == "Жасур" and tr_out["data"]["imzo"] == "Каримовлар оиласи"

    # --- musiqa: admin bot orqali qo'shadi, ro'yxatda chiqadi
    await send(user=ADMIN, audio=Audio(file_id="aud1", file_unique_id="a", duration=180, title="Oq vals", performer="Tayyorla",
                                       mime_type="audio/mpeg", file_size=1000))
    await click("mus:t:toy", user=ADMIN)
    await click("mus:k:instr", user=ADMIN)
    tracks = (await videoapi.music_list())["tracks"]
    assert len(tracks) == 1 and tracks[0]["title"] == "Tayyorla — Oq vals" and tracks[0]["theme"] == "toy"
    A = sign({"id": 999, "first_name": "Admin"})
    assert (await code(videoapi.admin_music(U)))[0] == 403
    await videoapi.admin_music_edit(tracks[0]["id"], videoapi.TrackPatch(active=False, start=12), A)
    assert (await videoapi.music_list())["tracks"] == []
    body_m = videoapi.VideoIn(design="v-atlas", data={**TOY, "kimga": "Musiqa"}, music=videoapi.MusicIn(mode="lib", track=tracks[0]["id"]))
    async with Session() as s:
        assert await videoapi.resolve_music(s, body_m.music) is None, "o'chirilgan kuy ishlatilmaydi"

    # --- statistika
    stats = await videoapi.admin_stats(A)
    assert stats["users"]["total"] >= 2 and stats["queue"]["queued"] >= 1
    await send("/stats", user=ADMIN)
    assert "Statistika" in session.texts()[-1]
    pub = await videoapi.public_stats()
    assert pub["created"] >= 2

    # --- /broadcast: tasdiqlash so'raladi
    await send("/broadcast Yangi dizaynlar qo'shildi!", user=ADMIN)
    assert "Tasdiqlaysizmi" in session.texts()[-1]

    # --- hamyon
    w = await videoapi.wallet(U)
    assert w["balance"] == 1100 and any(t["kind"] == "package" for t in w["history"])
    # --- «avto» kartochka tili: matn yozuvi va interfeys tili
    assert video.resolve_lang("auto", {}, "ru") == "ru"
    assert video.resolve_lang("auto", {"kuyov": "Жасур", "kelin": "Малика"}, "cy") == "cy"
    assert video.resolve_lang("auto", {"kuyov": "Jasur"}, "ru") == "uz"
    assert video.resolve_lang("auto", {"kuyov": "Jasur"}, "en") == "en"
    assert video.resolve_lang("auto", {"matn": "Тӯйи мо"}, "uz") == "tg"
    assert video.resolve_lang("kk", {"kuyov": "Jasur"}, "ru") == "kk"
    print("✅ Video, balans va tadbir tekshiruvlari o'tdi")


async def await_session_all(model):
    async with Session() as s:
        return (await s.execute(select(model))).scalars().all()


async def videoapi_add_guests(slug, text):
    return await events.guests_add(slug, events.GuestsIn(text=text), U)


if __name__ == "__main__":
    asyncio.run(main())
