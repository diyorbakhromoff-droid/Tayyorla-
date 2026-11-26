"""Reklama manbasi bo'yicha kesim (TZ 4-band): havola nomlash qoidasi, kuzatuv havolasi (bosish), kunlik reklama xarajati
(so'm va dollar, kurs), «Trafik manbalari»ning yangi ustunlari (odamlar bo'yicha, birinchi manba), ROI (AI xarajati bilan),
blok foizi, kampaniya bo'yicha jami, kogorta (1/3/7 kun), sinov akkauntlari, CSV va tezlik.

Ishga tushirish: python -m tests.test_adstats
PostgreSQL da tekshirish (bo'sh baza kerak): TEST_DATABASE_URL=postgresql+asyncpg://… python -m tests.test_adstats
"""

import asyncio
import os
import tempfile
import time
from datetime import timedelta

os.environ["DATABASE_URL"] = os.environ.get("TEST_DATABASE_URL") or f"sqlite+aiosqlite:///{tempfile.mkdtemp()}/adstats.db"
os.environ["BOT_TOKEN"] = "123456:TEST"
os.environ["ADMIN_IDS"] = "999"
os.environ["BASE_URL"] = "https://example.uz"

from fastapi import HTTPException  # noqa: E402
from pydantic import ValidationError  # noqa: E402
from sqlalchemy import func, insert, inspect, select  # noqa: E402

from app import admin, adstats, costs, songflow, store, track  # noqa: E402
from app.db import AdSpend, BalanceTx, CostLog, Event, Payment, Session, Site, User, engine, init_db, utcnow  # noqa: E402
from app.reminders import today  # noqa: E402

IG_IOS = ("Mozilla/5.0 (iPhone; CPU iPhone OS 17_1 like Mac OS X) AppleWebKit/605.1.15 (KHTML, like Gecko) Mobile/15E148 "
          "Instagram 309.0.0.28.110 (iPhone14,5; iOS 17_1; ru_RU; ru-RU; scale=3.00; 1170x2532; 539012345)")
IG_ANDROID = ("Mozilla/5.0 (Linux; Android 13; SM-A515F Build/TP1A.220624.014; wv) AppleWebKit/537.36 (KHTML, like Gecko) Version/4.0 "
              "Chrome/119.0.6045.163 Mobile Safari/537.36 Instagram 309.0.0.40.113 Android (33/13; 420dpi; 1080x2186; samsung; SM-A515F)")


class Req:
    def __init__(self, ua: str, method: str = "GET"):
        self.method, self.headers = method, {"user-agent": ua}


async def rejects(coro, code: int) -> str:
    try:
        await coro
    except HTTPException as e:
        assert e.status_code == code, (e.status_code, e.detail)
        return str(e.detail)
    raise AssertionError(f"{code} kutilgan edi")


def csv_lines(resp) -> list[str]:
    return resp.body.decode().lstrip("﻿").strip().split("\r\n")


async def main() -> None:
    logging_quiet()
    await init_db()
    await init_db()  # qayta ishga tushirish xavfsiz: yangi jadval bir marta yaratiladi
    async with engine.connect() as conn:
        assert "ad_spend" in await conn.run_sync(lambda c: inspect(c).get_table_names())
    await costs.save_rates({"usd_som": 12500})

    # ------------------------------------------------------------ 1) nomlash qoidasi: kampaniya_video_lending
    assert adstats.parse_code("qoshiq_v3_l1") == {"campaign": "qoshiq", "video": "v3", "landing": "l1"}
    assert adstats.parse_code("yangi_yil_v2_l12") == {"campaign": "yangi_yil", "video": "v2", "landing": "l12"}
    assert adstats.parse_code("qoshiq_v3") == {"campaign": "qoshiq", "video": "v3", "landing": ""}  # lendingsiz, to'g'ridan-to'g'ri botga
    for legacy in ("insta_noyabr", "telegram_kanal_o", "insta1", "toy_vip"):
        assert adstats.parse_code(legacy)["campaign"] == "", legacy
    assert adstats.compose_code("Qoshiq", "3", "1") == "qoshiq_v3_l1" and adstats.compose_code("yangi yil", "v2", "") == "yangi_yil_v2"
    a = await admin.link_create(admin.LinkIn(name="Qo'shiq: 3-video, 1-lending", campaign="Qoshiq", video="3", landing="l1"), uid=999)
    assert a["code"] == "qoshiq_v3_l1" and a["campaign"] == "qoshiq" and a["urls"]["go"] == "https://example.uz/go/qoshiq_v3_l1"
    assert a["urls"]["bot"].endswith("?start=src_qoshiq_v3_l1")
    assert "band" in await rejects(admin.link_create(admin.LinkIn(name="X", campaign="qoshiq", video="v3", landing="1"), uid=999), 409)
    b = await admin.link_create(admin.LinkIn(name="Qo'shiq: 3-video, 2-lending", campaign="qoshiq", video="v3", landing="2"), uid=999)
    c = await admin.link_create(admin.LinkIn(name="Tabrik 1-video", campaign="tabrik", video="1", landing="1"), uid=999)
    assert (b["code"], c["code"]) == ("qoshiq_v3_l2", "tabrik_v1_l1")
    assert "Video raqami" in await rejects(admin.link_create(admin.LinkIn(name="X", campaign="qoshiq", video="reels"), uid=999), 400)
    assert "Lending" in await rejects(admin.link_create(admin.LinkIn(name="X", campaign="qoshiq", video="4", landing="xx"), uid=999), 400)
    assert "24" in await rejects(admin.link_create(admin.LinkIn(name="X", campaign="juda_uzun_kampaniya_nomi", video="1"), uid=999), 400)
    old = await admin.link_create(admin.LinkIn(name="Instagram noyabr", code="insta_noyabr", cost=500000), uid=999)  # eski usul ham ishlaydi
    assert old["code"] == "insta_noyabr" and old["campaign"] == ""

    # ------------------------------------------------------------ 2) kuzatuv havolasi: Instagram ichidagi brauzer sanaladi, robotlar yo'q
    for ua in (IG_IOS, IG_ANDROID):
        r = await admin.go("qoshiq_v3_l1", Req(ua))
        assert r.status_code == 302 and r.headers["location"].endswith("?start=src_qoshiq_v3_l1")  # lending kodi botga Start parametri bilan
    await admin.go("qoshiq_v3_l1", Req("facebookexternalhit/1.1 (+http://www.facebook.com/externalhit_uatext.php)"))
    await admin.go("qoshiq_v3_l1", Req(IG_IOS, method="HEAD"))

    # ------------------------------------------------------------ 3) kunlik xarajat: so'm, dollar (kurs bilan), bir kun — bitta yozuv
    t0 = today()
    day = lambda n: (t0 - timedelta(days=n)).isoformat()  # noqa: E731
    put = lambda link, d, amount, cur="som": admin.link_spend_put(link["id"], admin.SpendIn(day=d, amount=amount, currency=cur), uid=999)  # noqa: E731
    r = await put(a, day(15), 200000)
    assert r["saved"]["updated"] is False and r["total"] == 200000 and r["usd_som"] == 12500
    r = await put(a, day(15), 300000)  # shu kun qayta kiritildi — yangilanadi
    assert r["saved"]["updated"] is True and len(r["rows"]) == 1 and r["total"] == 300000
    r = await put(a, day(10), 20, "usd")
    assert r["saved"]["som"] == 250000 and r["saved"]["rate"] == 12500 and r["rows"][0]["day"] == day(10)  # yangisi tepada
    await put(a, day(30), 999999)  # tanlangan davrdan tashqarida
    await put(b, day(10), 100000)
    await put(c, day(1), 50000)
    tmp = await put(c, day(2), 7000)
    r = await admin.link_spend_drop(c["id"], tmp["saved"]["id"], uid=999)
    assert [x["day"] for x in r["rows"]] == [day(1)]
    await rejects(admin.link_spend_drop(c["id"], tmp["saved"]["id"], uid=999), 404)
    await rejects(admin.link_spend_drop(b["id"], r["rows"][0]["id"], uid=999), 404)  # boshqa havolaning yozuvi
    assert "Kelajak" in await rejects(put(a, (t0 + timedelta(days=1)).isoformat(), 1000), 400)
    await rejects(put(a, "2026-13-01", 1000), 400)
    await rejects(admin.link_spend(12345, uid=999), 404)
    for bad in ({"amount": 0}, {"amount": -5}, {"currency": "eur"}):
        try:
            admin.SpendIn(**{"day": day(1), "amount": 1000, "currency": "som", **bad})
            raise AssertionError(f"qabul qilindi: {bad}")
        except ValidationError:
            pass
    await costs.save_rates({"usd_som": 13000})  # kurs o'zgardi: oldin kiritilgan kun o'z kursida qoladi
    assert next(x for x in (await admin.link_spend(a["id"], uid=999))["rows"] if x["currency"] == "usd")["som"] == 250000
    await costs.save_rates({"usd_som": 12500})

    # ------------------------------------------------------------ 4) odamlar va ularning harakatlari
    now = utcnow()
    at = lambda d=0, h=0: now - timedelta(days=d) + timedelta(hours=h)  # noqa: E731
    A, B, OLD = "src_qoshiq_v3_l1", "src_qoshiq_v3_l2", "src_Insta_Noyabr"  # eski bot havolasi katta harf bilan yozilgan bo'lishi mumkin
    await track.set_test_ids(["107"])
    async with Session() as s:
        s.add_all([
            User(tg_id=101, first_name="A1", ref=A, created_at=at(15)), User(tg_id=102, first_name="A2", ref=A, created_at=at(15)),
            User(tg_id=103, first_name="A3", ref=A, created_at=at(15)), User(tg_id=104, first_name="A4", ref=A, created_at=at(15), blocked=True),
            User(tg_id=105, first_name="A5", ref=A, created_at=at(2), blocked=True),
            User(tg_id=106, first_name="A6", ref=A, created_at=at(25)),       # davrdan oldin kelgan, davrda yana Start bosgan
            User(tg_id=107, first_name="Sinov", ref=A, created_at=at(3)),     # sinov akkaunt
            User(tg_id=999, first_name="Admin", ref=A, created_at=at(1)),     # admin
            User(tg_id=201, first_name="B1", ref=B, created_at=at(10)), User(tg_id=202, first_name="B2", ref=B, created_at=at(10)),
            User(tg_id=301, first_name="O1", ref=OLD, created_at=at(5)),
            User(tg_id=401, first_name="Org", ref="", created_at=at(5)), User(tg_id=402, first_name="Do'st", ref="ref_401", created_at=at(4)),
            User(tg_id=501, first_name="Del", ref="src_ochirilgan", created_at=at(3)),
        ])
        ev = []
        for uid, kinds, when in ((101, ("start", "app", "sample_played", "buy_click", "pay_open"), at(15)),
                                 (102, ("start", "app", "sample_played", "buy_click", "pay_open"), at(15)),
                                 (103, ("sample_played",), at(15)), (105, ("start",), at(2)), (106, ("start",), at(1)),
                                 (107, ("start", "sample_played", "buy_click", "pay_open"), at(3)), (999, ("start", "sample_played"), at(1)),
                                 (201, ("start", "sample_played"), at(10)), (401, ("sample_played",), at(5))):
            src = (A if uid < 200 or uid == 999 else B) if "start" in kinds else ""
            ev += [{"user_id": uid, "kind": k, "src": src if k == "start" else "", "ref": "", "created_at": when} for k in kinds]
        ev.append({"user_id": 102, "kind": "start", "src": A, "ref": "", "created_at": at(14)})  # ikkinchi Start — odam bitta
        await s.execute(insert(Event), ev)
        pays = [(101, 69000, at(15, 2)), (102, 69000, at(13)), (103, 59000, at(10)), (104, 149000, at(5)), (107, 69000, at(3)),
                (301, 100000, at(5, 1))]
        s.add_all([Payment(user_id=u, amount=amt, status="approved", purpose="song", created_at=t, decided_at=t) for u, amt, t in pays])
        s.add(Payment(user_id=105, amount=69000, status="new", purpose="song", created_at=at(2)))
        s.add_all([BalanceTx(user_id=101, amount=-69000, kind="song", created_at=at(15, 2)),
                   BalanceTx(user_id=202, amount=-69000, kind="song", created_at=at(10, -1) + timedelta(hours=2))])  # bonus balansdan
        s.add(Site(slug="b2site", owner_id=201, category="tk", config={}, status="draft", kind="site"))
        s.add_all([CostLog(user_id=101, kind="music", purpose="song_preview", units_in=100),
                   CostLog(user_id=104, kind="ai", purpose="lyrics", units_in=100000, units_out=10000, model="x-unknown"),
                   CostLog(user_id=107, kind="music", purpose="song_preview", units_in=500)])  # sinov akkaunt — sanalmaydi
        await s.commit()
    r_ = await costs.rates()
    ai_a = costs.som_of("music", 100, 0, r_) + costs.som_of("ai", 100000, 10000, r_, "x-unknown")
    assert round(ai_a) == 4125 + 7500

    # ------------------------------------------------------------ 5) «Trafik manbalari»: yangi ustunlar, kampaniya bo'yicha
    frm, to = day(19), t0.isoformat()
    d = await admin.sources(frm=frm, to=to, uid=999)
    rows = {x["code"]: x for x in d["links"]}
    x = rows["qoshiq_v3_l1"]
    assert (x["clicks"], x["starts"], x["users"], x["app"]) == (2, 4, 5, 2), x  # Start: 101, 102, 105, 106 (106 eski odam)
    assert (x["played"], x["buy_click"], x["pay_open"], x["bought"], x["revenue"]) == (3, 2, 2, 4, 346000), x
    assert (x["spend"], x["spend_src"], x["spend_days"], x["cost"]) == (550000, "daily", 2, 0), x
    assert (x["cps"], x["cpu"], x["cpb"], x["ai_cost"]) == (137500, 110000, 137500, 11625), x
    assert x["roi"] == round(100 * (346000 - 550000 - ai_a) / 550000, 1) == -39.2, x["roi"]
    assert (x["blocked"], x["block_pct"]) == (2, 40.0)
    assert (x["d1"], x["d3"], x["d7"], x["young"], x["d1_pct"], x["d7_pct"], x["bought_pct"]) == (1, 2, 3, 1, 20.0, 60.0, 80.0), x
    assert (x["campaign"], x["video"], x["landing"]) == ("qoshiq", "v3", "l1")
    y = rows["qoshiq_v3_l2"]
    assert (y["starts"], y["users"], y["played"], y["bought"], y["revenue"], y["created"]) == (1, 2, 1, 1, 0, 1), y
    assert (y["spend"], y["cps"], y["cpb"], y["roi"], y["d1"]) == (100000, 100000, 100000, -100.0, 1), y
    z = rows["tabrik_v1_l1"]
    assert (z["users"], z["spend"], z["roi"], z["cps"], z["block_pct"]) == (0, 50000, -100.0, None, 0.0), z
    o = rows["insta_noyabr"]  # kunlik yozuv yo'q — eski umumiy narx; ref katta harf bilan bo'lsa ham shu havolaga tushadi
    assert (o["users"], o["spend"], o["spend_src"], o["revenue"], o["roi"], o["campaign"]) == (1, 500000, "total", 100000, -80.0, ""), o
    assert [c_["key"] for c_ in d["campaigns"]] == ["tabrik", "qoshiq", ""]
    q = next(c_ for c_ in d["campaigns"] if c_["key"] == "qoshiq")
    assert q["links"] == [a["id"], b["id"]] and q["label"] == "qoshiq"
    assert (q["users"], q["starts"], q["clicks"], q["bought"], q["revenue"], q["spend"], q["played"]) == (7, 5, 2, 5, 346000, 650000, 4), q
    assert (q["cps"], q["cpb"], q["d1"], q["d3"], q["d7"], q["young"], q["block_pct"]) == (130000, 130000, 2, 3, 4, 1, 28.6), q
    assert q["roi"] == round(100 * (346000 - 650000 - ai_a) / 650000, 1)
    assert next(c_ for c_ in d["campaigns"] if c_["key"] == "")["label"] == adstats.NO_CAMPAIGN
    g = {x_["key"]: x_ for x_ in d["groups"]}
    assert (g["organic"]["users"], g["organic"]["played"], g["ref_"]["users"], g["src_ochirilgan"]["users"]) == (1, 1, 1, 1), g
    assert g["src_ochirilgan"]["name"] == "Havola: ochirilgan" and all(x_["spend"] == 0 and x_["roi"] is None for x_ in d["groups"])
    assert d["excluded"] == 2 and d["usd_som"] == 12500 and d["since"]["played"] is None and d["from"] == frm

    # butun davr: davrdan oldin kelgan 106 ham, davrdan tashqaridagi xarajat ham
    al = {x_["code"]: x_ for x_ in (await admin.sources(all_time=1, uid=999))["links"]}
    assert al["qoshiq_v3_l1"]["users"] == 6 and al["qoshiq_v3_l1"]["spend"] == 300000 + 250000 + 999999
    # boshqa davr: kunlik yozuvi bor havolada shu davrda xarajat yo'q — 0 (eski umumiy narxga qaytmaydi)
    one = {x_["code"]: x_ for x_ in (await admin.sources(frm=day(3), to=day(3), uid=999))["links"]}
    assert one["qoshiq_v3_l1"]["spend"] == 0 and one["qoshiq_v3_l1"]["roi"] is None and one["insta_noyabr"]["spend"] == 500000

    # arxivdagi havola ko'rinmaydi va «Boshqa manbalar»ga ham tushmaydi
    await admin.link_edit(b["id"], admin.LinkPatch(archived=True), uid=999)
    d2 = await admin.sources(frm=frm, to=to, uid=999)
    assert "qoshiq_v3_l2" not in {x_["code"] for x_ in d2["links"]} and all(x_["key"] != B for x_ in d2["groups"])
    assert next(c_ for c_ in d2["campaigns"] if c_["key"] == "qoshiq")["users"] == 5
    assert "qoshiq_v3_l2" in {x_["code"] for x_ in (await admin.sources(frm=frm, to=to, archived=1, uid=999))["links"]}
    await admin.link_edit(b["id"], admin.LinkPatch(archived=False), uid=999)

    # hisob boshlangan sana panelga chiqadi
    cfg = await songflow.config()
    cfg["since"] = "2026-11-20T10:00:00"
    await store.put(songflow.KEY, cfg)
    assert (await admin.sources(frm=frm, to=to, uid=999))["since"]["played"] == "2026-11-20T10:00:00"

    # ------------------------------------------------------------ 6) CSV: jadval, kogorta, kunlik xarajatlar
    lines = csv_lines(await admin.export("sources", frm=frm, to=to, uid=999))
    assert lines[0].startswith("tur;kampaniya;kod;nomi;video;lending;bosish;start bosgan odamlar;yangi odamlar")
    assert "namunani eshitdi;«sotib olish»ni bosdi;to'lov oynasini ochdi;sotib oldi" in lines[0] and lines[0].endswith("xarajat qayerdan")
    assert lines[1].startswith("Kampaniya (jami);tabrik;;;;;0;0;0") and lines[2].startswith("Havola;tabrik;tabrik_v1_l1;Tabrik 1-video;v1;l1;")
    assert lines[3].startswith("Kampaniya (jami);qoshiq;;;;;2;5;7;")
    row = next(ln for ln in lines if ln.startswith("Havola;qoshiq;qoshiq_v3_l1;"))
    assert ";2;4;5;2;" in row and ";346000;550000;137500;110000;137500;11625;-39,2;2;40,0;kunlik yozuvlar" in row, row
    assert any(ln.startswith("Havola;;insta_noyabr;Instagram noyabr;;;") and ln.endswith("umumiy «Reklama narxi»") for ln in lines)
    assert any(ln.startswith("Manba;;organic;Organik") for ln in lines) and not any("Kampaniya (jami);;" in ln for ln in lines)
    lines = csv_lines(await admin.export("sourcecohort", frm=frm, to=to, uid=999))
    assert lines[0].endswith("hozirgacha sotib oldi;hozirgacha, %;7 kuni hali to'lmagan (yaqinda kelgan)")
    assert "Havola;qoshiq;qoshiq_v3_l1;Qo'shiq: 3-video, 1-lending;v3;l1;5;1;20,0;2;40,0;3;60,0;4;80,0;1" in lines
    assert "Kampaniya (jami);qoshiq;;;;;7;2;28,6;3;42,9;4;57,1;5;71,4;1" in lines
    lines = csv_lines(await admin.export("adspend", frm=frm, to=to, uid=999))
    assert lines[0] == "sana;havola kodi;havola nomi;summa;valyuta;dollar kursi;so'mda" and len(lines) == 5
    assert f"{day(10)};qoshiq_v3_l1;Qo'shiq: 3-video, 1-lending;20;$;12500;250000" in lines
    assert f"{day(15)};qoshiq_v3_l1;Qo'shiq: 3-video, 1-lending;300000;so'm;;300000" in lines
    assert len(csv_lines(await admin.export("adspend", all_time=1, uid=999))) == 6

    # ------------------------------------------------------------ 7) tezlik: 12 ming odam, 30 havola, minglab hodisa — sahifa < 3 s
    codes = [f"perf{i}_v1_l1" for i in range(30)]
    async with Session() as s:
        users = [{"tg_id": 1_000_000 + i, "first_name": "", "username": "", "language_code": "", "lang": "uz", "lang_set": False,
                  "ref": f"src_{codes[i % 30]}" if i % 4 else "", "balance": 0, "bonus_videos": 0, "song_credits": 0, "blocked": i % 7 == 0,
                  "created_at": at(i % 20), "last_seen": now} for i in range(12000)]
        for i in range(0, len(users), 4000):
            await s.execute(insert(User), users[i:i + 4000])
        evs = [{"user_id": 1_000_000 + i, "kind": k, "src": f"src_{codes[i % 30]}" if k == "start" else "", "ref": "", "created_at": at(i % 20)}
               for i in range(12000) for k in ("start", "app", "sample_played", "buy_click", "pay_open")[:1 + i % 5]]
        for i in range(0, len(evs), 5000):
            await s.execute(insert(Event), evs[i:i + 5000])
        await s.execute(insert(Payment), [{"user_id": 1_000_000 + i, "amount": 69000, "status": "approved", "purpose": "song",
                                           "created_at": at(i % 20), "decided_at": at(i % 20, 5)} for i in range(0, 12000, 9)])
        await s.execute(insert(CostLog), [{"user_id": 1_000_000 + i, "kind": "music", "purpose": "song_preview", "units_in": 40}
                                          for i in range(0, 12000, 3)])
        await s.commit()
    for i, code in enumerate(codes):
        await admin.link_create(admin.LinkIn(name=f"Perf {i}", code=code), uid=999)
    t1 = time.time()
    big = await admin.sources(frm=frm, to=to, uid=999)
    await admin.sources(all_time=1, uid=999)
    took = time.time() - t1
    assert sum(x_["users"] for x_ in big["links"] if x_["code"].startswith("perf")) == 9000 and took < 3, took
    assert len(big["campaigns"]) == 33  # 30 ta perf + qoshiq + tabrik + qoidasiz havolalar guruhi
    async with Session() as s:
        assert await s.scalar(select(func.count()).select_from(AdSpend)) == 5

    store.forget()
    print(f"test_adstats: OK (12 ming odam: davr va butun davr {took:.2f} s)")


def logging_quiet() -> None:
    import logging
    logging.basicConfig(level=logging.WARNING)


if __name__ == "__main__":
    asyncio.run(main())
