"""Admin paneli API'si (/admin sahifasi): statistika, trafik manbalari, sotuvlar, to'lovlar, foydalanuvchilar, tarqatma.

Kirish: Telegram ichida initData (X-Init-Data) yoki botdagi /admin buyrug'i bergan imzoli havola (X-Admin-Token, ?t=).
"""

import asyncio
import csv
from html import escape as html_escape
import hashlib
import hmac
import io
import logging
import re
import secrets
import shutil
import time as _time
from collections import defaultdict
from datetime import date, datetime, time, timedelta, timezone

from fastapi import APIRouter, Depends, File, Header, HTTPException, Query, Request, UploadFile
from fastapi.responses import HTMLResponse, RedirectResponse, Response
from pydantic import BaseModel, Field
from sqlalchemy import func, select

from . import track, video, videobot
from .catalog import SECTIONS, TEMPLATES, site_price, site_title
from .config import MEDIA_DIR, ROOT, settings
from . import adstats, costs, funnel, msgstats, nudges, payflow, paysurvey, songflow, songs, store
from .db import BalanceTx, Event, MusicTrack, Payment, RenderJob, Session, Site, Snapshot, Song, TrafficLink, User, utcnow
from .reminders import TZ, today
from .webapp import check_init_data

log = logging.getLogger(__name__)
router = APIRouter(prefix="/api/admin")
public = APIRouter()
STARTED = _time.time()

SPEND_KINDS = ("site", "upgrade", "video", "package", "song", "song_pack")
VIDEO_SECTIONS = {"toy": "To'y", "osh": "Osh", "gap": "Gap", "choy": "Choyxona", "tk": "Tug'ilgan kun"}
TIER_NAMES = {"standart": "Standart", "premium": "Premium", "vip": "VIP"}
SOURCE_GROUPS = {"": "Organik (to'g'ridan-to'g'ri)", "ref_": "Do'st taklifi (referal)", "r_": "Tabrik sahifasidan",
                 "other": "Boshqa havolalar"}
BOT_UA = track.BOT_UA  # havola ko'rinishini (preview) olayotgan robotlar — bosish sanalmaydi


# ---------------------------------------------------------------- kirish

def make_token(uid: int, hours: int = 24) -> str:
    exp = int(_time.time()) + hours * 3600
    sig = hmac.new(settings.bot_token.encode(), f"adm:{uid}:{exp}".encode(), hashlib.sha256).hexdigest()[:32]
    return f"{uid}.{exp}.{sig}"


def check_token(token: str) -> int | None:
    try:
        uid, exp, sig = token.split(".")
        good = hmac.new(settings.bot_token.encode(), f"adm:{uid}:{exp}".encode(), hashlib.sha256).hexdigest()[:32]
        if hmac.compare_digest(good, sig) and int(exp) > _time.time():
            return int(uid)
    except (ValueError, AttributeError):
        pass
    return None


def admin_uid(x_init_data: str = Header(""), x_admin_token: str = Header(""), t: str = Query("")) -> int:
    uid = check_token(x_admin_token or t) if (x_admin_token or t) else None
    if uid is None:
        if not x_init_data:
            raise HTTPException(401, "Botda /admin buyrug'ini yuboring va havola orqali kiring")
        uid = int(check_init_data(x_init_data)["id"])
    if uid not in settings.admins:
        raise HTTPException(403, "admin_only")
    return uid


@router.get("/whoami")
async def whoami(uid: int = Depends(admin_uid), x_admin_token: str = Header(""), t: str = Query("")):
    """Panel ochilganda: kim kirdi va yuklab olish havolalari uchun qisqa muddatli kalit.
    Kalit bilan kirilgan bo'lsa yangisi berilmaydi (aks holda sizib chiqqan kalitni cheksiz uzaytirish mumkin edi):
    yangi kalitni faqat Telegram imzosi (initData) bilan kirgan admin oladi."""
    async with Session() as s:
        u = await s.get(User, uid)
    token = (x_admin_token or t) or make_token(uid, hours=6)
    return {"id": uid, "name": u.first_name if u else "", "token": token, "bot": settings.bot_username,
            "base": settings.base_url, "channel": settings.channel_username}


# ---------------------------------------------------------------- vaqt oralig'i

def utc_of(d: date) -> datetime:
    return datetime.combine(d, time(0), TZ).astimezone(timezone.utc).replace(tzinfo=None)


def local_day(dt: datetime) -> date:
    return dt.replace(tzinfo=timezone.utc).astimezone(TZ).date()


def parse_range(frm: str | None, to: str | None, default_days: int = 7) -> tuple[date, date]:
    t = today()
    try:
        d2 = date.fromisoformat(to) if to else t
        d1 = date.fromisoformat(frm) if frm else d2 - timedelta(days=default_days - 1)
    except ValueError:
        raise HTTPException(400, "Sana YYYY-MM-DD ko'rinishida bo'lsin")
    if d1 > d2:
        d1, d2 = d2, d1
    if (d2 - d1).days > 731:
        d1 = d2 - timedelta(days=731)
    return d1, d2


def day_uz(d: date) -> str:
    return d.strftime("%d.%m.%Y")


def pct(a: float, b: float) -> float:
    return round(100 * a / b, 1) if b else 0.0


# ---------------------------------------------------------------- kanal obunachilari

_CHANNEL: dict = {"at": 0.0, "n": None}


async def channel_count() -> int | None:
    if not settings.channel_username.startswith("@") or not videobot.BOT:
        return None
    if _time.time() - _CHANNEL["at"] < 600:
        return _CHANNEL["n"]
    try:
        n = await videobot.BOT.get_chat_member_count(settings.channel_username)
    except Exception:
        log.warning("Kanal obunachilarini olib bo'lmadi")
        n = _CHANNEL["n"]
    _CHANNEL.update(at=_time.time(), n=n)
    if n is not None:
        await snapshot("channel", n)
    return n


async def snapshot(key: str, value: int) -> None:
    """Bugungi qiymatni yozadi (kuniga bitta yozuv, oxirgisi saqlanadi)."""
    day = today().isoformat()
    async with Session() as s:
        row = (await s.execute(select(Snapshot).where(Snapshot.day == day, Snapshot.key == key))).scalar_one_or_none()
        if row:
            row.value = value
        else:
            s.add(Snapshot(day=day, key=key, value=value))
        await s.commit()


# ---------------------------------------------------------------- umumiy ko'rsatkichlar

async def _sets(s) -> dict:
    """Butun tarix bo'yicha: kim ilovaga kirgan, kim nimadir yaratgan, kim pul sarflagan/to'lagan."""
    app = set((await s.execute(select(Event.user_id).where(Event.kind == "app").distinct())).scalars().all())
    site_owners = set((await s.execute(select(Site.owner_id).where(Site.kind == "site").distinct())).scalars().all())
    job_owners = set((await s.execute(select(RenderJob.owner_id).where(RenderJob.guest_id.is_(None)).distinct())).scalars().all())
    spenders = set((await s.execute(select(BalanceTx.user_id).where(BalanceTx.kind.in_(SPEND_KINDS)).distinct())).scalars().all())
    paid_sites = set((await s.execute(select(Site.owner_id).where(Site.status == "paid").distinct())).scalars().all())
    payers = set((await s.execute(select(Payment.user_id).where(Payment.status == "approved").distinct())).scalars().all())
    songers = set((await s.execute(select(Song.owner_id).distinct())).scalars().all())
    song_buyers = set((await s.execute(select(Song.owner_id).where(Song.paid.is_(True)).distinct())).scalars().all())
    return {"app": app, "creators": site_owners | job_owners, "buyers": spenders | paid_sites | payers, "payers": payers,
            "songers": songers, "song_buyers": song_buyers}


async def collect(a: datetime, b: datetime, days: list[date] | None = None) -> dict:
    """[a, b) oralig'idagi ko'rsatkichlar; days berilsa kunlik qatorlar ham."""
    excl = await track.excluded_ids()
    async with Session() as s:
        users = (await s.execute(select(User.tg_id, User.created_at, User.ref).where(User.created_at >= a, User.created_at < b))).all()
        total_users = await s.scalar(select(func.count()).select_from(User).where(User.created_at < b))
        events = (await s.execute(select(Event.user_id, Event.kind, Event.created_at)
                                  .where(Event.created_at >= a, Event.created_at < b, Event.kind.in_(("start", "app"))))).all()
        sites = (await s.execute(select(Site.owner_id, Site.status, Site.created_at, Site.config)
                                 .where(Site.kind == "site", Site.created_at >= a, Site.created_at < b))).all()
        txs = (await s.execute(select(BalanceTx.user_id, BalanceTx.amount, BalanceTx.kind, BalanceTx.created_at)
                               .where(BalanceTx.created_at >= a, BalanceTx.created_at < b))).all()
        jobs = (await s.execute(select(RenderJob.owner_id, RenderJob.guest_id, RenderJob.charge, RenderJob.status, RenderJob.created_at)
                                .where(RenderJob.created_at >= a, RenderJob.created_at < b))).all()
        pays = (await s.execute(select(Payment.user_id, Payment.amount, Payment.decided_at)
                                .where(Payment.status == "approved", Payment.decided_at >= a, Payment.decided_at < b))).all()
        song_rows = (await s.execute(select(Song.owner_id, Song.previews, Song.paid, Song.status)
                                     .where(Song.created_at >= a, Song.created_at < b))).all()
        first_pay = dict((await s.execute(select(Payment.user_id, func.min(Payment.decided_at))
                                          .where(Payment.status == "approved").group_by(Payment.user_id))).all())
        ever = await _sets(s) if days is not None else None
        cost = await costs.summary(s, a, b)
        song_fails = await songflow.failed_counts(s, a, b, excl)

    new_ids = {u[0] for u in users}
    app_ev = [e for e in events if e[1] == "app"]
    start_ev = [e for e in events if e[1] == "start"]
    own = [j for j in jobs if j[1] is None]
    spend = [t for t in txs if t[2] in SPEND_KINDS]
    by_kind = defaultdict(lambda: [0, 0])
    for t in txs:
        by_kind[t[2]][0] += 1
        by_kind[t[2]][1] += abs(t[1])
    active = ({e[0] for e in events if e[0]} | new_ids | {x[0] for x in sites} | {j[0] for j in own} | {t[0] for t in spend})
    topup = sum(p[1] for p in pays)
    payers = {p[0] for p in pays}
    sites_paid_cohort = sum(1 for x in sites if x[1] == "paid")
    out = {
        "users": {
            "new": len(new_ids), "total": total_users or 0, "active": len(active),
            "returning": len(active - new_ids),
            "app_users": len({e[0] for e in app_ev}), "app_opens": len(app_ev),
            "starts": len(start_ev), "start_users": len({e[0] for e in start_ev}),
        },
        "sites": {
            "created": len(sites), "paid_of_created": sites_paid_cohort, "unpaid": len(sites) - sites_paid_cohort,
            "conv": pct(sites_paid_cohort, len(sites)),
            "sold": by_kind["site"][0], "sold_sum": by_kind["site"][1],
            "upgrades": by_kind["upgrade"][0], "upgrades_sum": by_kind["upgrade"][1],
            "creators": len({x[0] for x in sites}),
        },
        "videos": {
            "free": sum(1 for j in own if j[2] == "free" and j[3] == "done"),
            "bonus": sum(1 for j in own if j[2] == "bonus" and j[3] == "done"),
            "paid": sum(1 for j in own if j[2] == "paid" and j[3] == "done"),
            "unpaid": sum(1 for j in own if j[3] == "awaiting_payment"),
            "failed": sum(1 for j in jobs if j[3] == "failed"),
            "guest": sum(1 for j in jobs if j[1] is not None and j[3] == "done"),
            "free_users": len({j[0] for j in own if j[2] in ("free", "bonus") and j[3] == "done"}),
            "paid_sum": by_kind["video"][1] - by_kind["refund"][1],
            "packages": by_kind["package"][0], "packages_sum": by_kind["package"][1],
        },
        "songs": {
            "created": len(song_rows), "previews": sum(r[1] or 0 for r in song_rows),
            "paid_of_created": sum(1 for r in song_rows if r[2]), "conv": pct(sum(1 for r in song_rows if r[2]), len(song_rows)),
            "sold": by_kind["song"][0], "sold_sum": by_kind["song"][1],
            # xatolar hodisalardan sanaladi (sample_failed, song_failed): namuna xatosida qo'shiq holati «she'r»ga qaytadi,
            # to'liq qo'shiq xatosi qayta urinilganda o'chadi — shuning uchun holat bo'yicha sanash doim 0 ko'rsatar edi
            **song_fails,
        },
        "money": {
            "topup": topup, "topups": len(pays), "payers": len(payers),
            "new_payers": sum(1 for uid, d in first_pay.items() if d and a <= d < b),
            "avg_check": round(topup / len(pays)) if pays else 0,
            "spent": sum(-t[1] for t in spend), "buyers": len({t[0] for t in spend}),
            "refunds": by_kind["refund"][1], "admin": by_kind["admin"][1] + by_kind["bonus"][1],
        },
        # bizning tashqi xarajatimiz (ElevenLabs, Claude) — taxminiy, admin kiritgan narxlar bo'yicha
        "costs": {"total": cost["total"], "song": cost["song"], "other": cost["other"],
                  "demo_n": cost["demo_n"], "demo_som": cost["demo_som"],
                  "song_profit": by_kind["song"][1] - cost["song"]},
    }
    if ever is not None:
        cohort = new_ids
        opened = cohort & ever["app"]
        created = cohort & ever["creators"]
        bought = cohort & ever["buyers"]
        out["funnel"] = [
            {"key": "new", "label": "Yangi foydalanuvchilar", "n": len(cohort)},
            {"key": "app", "label": "Ilovani ochdi", "n": len(opened)},
            {"key": "created", "label": "Taklifnoma yoki video yasadi", "n": len(created)},
            {"key": "bought", "label": "Pul to'ladi", "n": len(bought)},
        ]
        free_ever = {j[0] for j in own if j[2] in ("free", "bonus") and j[3] == "done"}
        out["videos"]["free_to_paid"] = pct(len(free_ever & ever["buyers"]), len(free_ever))
        idx = {d: i for i, d in enumerate(days)}
        series = {k: [0] * len(days) for k in ("new_users", "app_users", "starts", "sites", "sites_paid", "videos_free",
                                                "videos_paid", "revenue", "spent")}
        app_days = defaultdict(set)

        def bump(key, dt, n=1):
            i = idx.get(local_day(dt)) if dt else None
            if i is not None:
                series[key][i] += n

        for u in users:
            bump("new_users", u[1])
        for e in app_ev:
            app_days[local_day(e[2])].add(e[0])
        for d, ids in app_days.items():
            if d in idx:
                series["app_users"][idx[d]] = len(ids)
        for e in start_ev:
            bump("starts", e[2])
        for x in sites:
            bump("sites", x[2])
        for t in txs:
            if t[2] == "site":
                bump("sites_paid", t[3])
            if t[2] in SPEND_KINDS:
                bump("spent", t[3], -t[1])
        for j in own:
            if j[3] == "done":
                bump("videos_free" if j[2] in ("free", "bonus") else "videos_paid", j[4])
        for p in pays:
            bump("revenue", p[2], p[1])
        out["series"] = {"days": [d.isoformat() for d in days], **series}
    return out


SPEND_LABELS = {"site": "Taklifnoma (sayt)", "upgrade": "Tarifni oshirish", "video": "Video taklifnoma",
                "package": "Mehmonlarga video paketi", "song": "Shaxsiy qo'shiq", "song_pack": "Qo'shiq paketi"}


@router.get("/spend")
async def spend_report(frm: str | None = Query(None, alias="from"), to: str | None = None, uid: int = Depends(admin_uid)):
    """«Xizmatlarga sarflandi» tafsiloti: qaysi xizmatlarga, kim, va pul qayerdan kelgan
    (haqiqiy to'lov yoki admin/bonus bergan balans). Balans bitta hamyon bo'lgani uchun avval to'langan pul
    sarflangan deb hisoblanadi (FIFO), qolgani admin/bonus balansidan."""
    d1, d2 = parse_range(frm, to)
    a, b = utc_of(d1), utc_of(d2 + timedelta(days=1))
    async with Session() as s:
        txs = (await s.execute(select(BalanceTx).where(BalanceTx.kind.in_(SPEND_KINDS), BalanceTx.created_at >= a, BalanceTx.created_at < b)
                               .order_by(BalanceTx.created_at, BalanceTx.id))).scalars().all()
        ids = sorted({t.user_id for t in txs})
        paid = dict((await s.execute(select(BalanceTx.user_id, func.sum(BalanceTx.amount)).where(
            BalanceTx.kind == "topup", BalanceTx.user_id.in_(ids or [0])).group_by(BalanceTx.user_id))).all())
        gifts = dict((await s.execute(select(BalanceTx.user_id, func.sum(BalanceTx.amount)).where(
            BalanceTx.kind.in_(("admin", "bonus")), BalanceTx.amount > 0, BalanceTx.user_id.in_(ids or [0])).group_by(BalanceTx.user_id))).all())
        # xaridorlarning davr oxirigacha bo'lgan butun balans tarixi — pul manbasini vaqt bo'yicha kuzatish uchun
        history = (await s.execute(select(BalanceTx).where(BalanceTx.user_id.in_(ids or [0]), BalanceTx.created_at < b)
                                   .order_by(BalanceTx.created_at, BalanceTx.id))).scalars().all()
        users = {u.tg_id: u for u in (await s.execute(select(User).where(User.tg_id.in_(ids or [0])))).scalars().all()}
        names = await _link_names(s)
        slugs = {t.ref.split(":", 1)[1] for t in txs if t.ref.startswith("site:")}
        song_ids = {int(t.ref.split(":", 1)[1]) for t in txs if t.ref.startswith("song:") and t.ref.split(":", 1)[1].isdigit()}
        job_ids = {int(t.ref.split(":", 1)[1]) for t in txs if t.ref.startswith("job:") and t.ref.split(":", 1)[1].isdigit()}
        site_rows = {x.slug: x for x in (await s.execute(select(Site).where(Site.slug.in_(slugs or {""})))).scalars().all()}
        song_rows = {x.id: x for x in (await s.execute(select(Song).where(Song.id.in_(song_ids or {0})))).scalars().all()}
        job_rows = {j.id: j for j in (await s.execute(select(RenderJob).where(RenderJob.id.in_(job_ids or {0})))).scalars().all()}
        job_sites = {x.id: x for x in (await s.execute(select(Site).where(Site.id.in_({j.site_id for j in job_rows.values() if j.site_id} or {0})))).scalars().all()}

    def detail(t: BalanceTx) -> tuple[str, str]:
        kind, _, key = t.ref.partition(":")
        if kind == "site" and key in site_rows:
            x = site_rows[key]
            return site_title(x.config), x.url
        if kind == "song" and key.isdigit() and int(key) in song_rows:
            g = song_rows[int(key)]
            return g.title or (f"{g.recipient} uchun" if g.recipient else f"Qo'shiq #{g.id}"), ""
        if kind == "job" and key.isdigit() and int(key) in job_rows:
            j = job_rows[int(key)]
            x = job_sites.get(j.site_id)
            return (f"{site_title(x.config)} · video" if x else f"Video #{j.id}"), (x.url if x else "")
        return t.ref or "—", ""

    # balansni ikki «cho'ntak» deb yuritamiz: to'langan pul va admin/bonus puli. Xarid avval to'langan puldan yechiladi,
    # qaytarilgan pul (refund) to'langan cho'ntakka qaytadi, admin ayirishi avval sovg'a cho'ntagidan olinadi.
    real_of: dict[int, int] = {}
    pools = defaultdict(lambda: [0, 0])  # user -> [to'langan, sovg'a]
    for h in history:
        pool = pools[h.user_id]
        if h.kind in SPEND_KINDS:
            amt = -h.amount
            r = min(amt, max(0, pool[0]))
            pool[0] -= r
            pool[1] -= amt - r
            real_of[h.id] = r
        elif h.kind in ("topup", "refund"):
            pool[0] += h.amount
        elif h.amount > 0:
            pool[1] += h.amount
        else:
            g = min(-h.amount, max(0, pool[1]))
            pool[1] -= g
            pool[0] -= -h.amount - g
    items, per_user, per_kind = [], defaultdict(lambda: {"spent": 0, "real": 0, "n": 0}), defaultdict(lambda: {"n": 0, "sum": 0, "real": 0})
    for t in txs:
        amt = -t.amount
        real = real_of.get(t.id, 0)
        title, url = detail(t)
        u = users.get(t.user_id)
        items.append({"created_at": t.created_at.isoformat() if t.created_at else None, "user_id": t.user_id,
                      "user": (u.first_name if u else "") or str(t.user_id), "kind": t.kind, "label": SPEND_LABELS.get(t.kind, t.kind),
                      "amount": amt, "real": real, "title": title, "url": url})
        pu, pk = per_user[t.user_id], per_kind[t.kind]
        pu["spent"] += amt; pu["real"] += real; pu["n"] += 1
        pk["n"] += 1; pk["sum"] += amt; pk["real"] += real
    total = sum(i["amount"] for i in items)
    real_total = sum(i["real"] for i in items)
    return {
        "from": d1.isoformat(), "to": d2.isoformat(), "total": total, "count": len(items), "buyers": len(per_user),
        "real": real_total, "gift": total - real_total,
        "kinds": sorted([{"kind": k, "label": SPEND_LABELS.get(k, k), **v} for k, v in per_kind.items()], key=lambda r: -r["sum"]),
        "users": sorted([{**_user_out(users[i], names), **v, "gift": v["spent"] - v["real"], "paid_life": int(paid.get(i) or 0),
                          "gift_life": int(gifts.get(i) or 0)} for i, v in per_user.items() if i in users], key=lambda r: -r["spent"]),
        "items": items[::-1][:300],
    }


@router.get("/costs")
async def costs_report(frm: str | None = Query(None, alias="from"), to: str | None = None, uid: int = Depends(admin_uid)):
    """Taxminiy tashqi xarajatlar: nima uchun, qancha (soniya/token/kredit) va so'mda; qo'shiqlar o'zini oqlayaptimi."""
    d1, d2 = parse_range(frm, to)
    a, b = utc_of(d1), utc_of(d2 + timedelta(days=1))
    r = await costs.rates()
    async with Session() as s:
        sm = await costs.summary(s, a, b, r)
        sold = (await s.execute(select(func.count(), func.coalesce(func.sum(-BalanceTx.amount), 0)).where(
            BalanceTx.kind == "song", BalanceTx.created_at >= a, BalanceTx.created_at < b))).one()
        created = await s.scalar(select(func.count()).select_from(Song).where(Song.created_at >= a, Song.created_at < b))
    revenue = int(sold[1] or 0)
    return {"from": d1.isoformat(), "to": d2.isoformat(), "rates": r, **sm,
            "songs": {"created": created or 0, "sold": sold[0], "revenue": revenue, "cost": sm["song"], "profit": revenue - sm["song"],
                      "cost_per_sold": round(sm["song"] / sold[0]) if sold[0] else 0}}


class CostRatesIn(BaseModel):
    usd_som: float | None = None
    credits_per_sec: float | None = None
    usd_per_1k_credits: float | None = None
    ai_in_per_m: float | None = None
    ai_out_per_m: float | None = None


@router.post("/costs/rates")
async def costs_rates(body: CostRatesIn, uid: int = Depends(admin_uid)):
    return {"rates": await costs.save_rates(body.model_dump())}


@router.get("/overview")
async def overview(frm: str | None = Query(None, alias="from"), to: str | None = None, uid: int = Depends(admin_uid)):
    d1, d2 = parse_range(frm, to)
    n = (d2 - d1).days + 1
    days = [d1 + timedelta(days=i) for i in range(n)]
    a, b = utc_of(d1), utc_of(d2 + timedelta(days=1))
    cur = await collect(a, b, days)
    prev = await collect(utc_of(d1 - timedelta(days=n)), a)
    async with Session() as s:
        pending = (await s.execute(select(func.count(), func.coalesce(func.sum(Payment.amount), 0))
                                   .where(Payment.status == "pending"))).one()
        blocked = await s.scalar(select(func.count()).select_from(User).where(User.blocked.is_(True)))
        queue = await s.scalar(select(func.count()).select_from(RenderJob).where(RenderJob.status.in_(("queued", "rendering"))))
        snaps = (await s.execute(select(Snapshot.day, Snapshot.value).where(
            Snapshot.key == "channel", Snapshot.day >= (d1 - timedelta(days=1)).isoformat(), Snapshot.day <= d2.isoformat()))).all()
    chan = await channel_count()
    snap = dict(snaps)
    chan_series = [snap.get(d) for d in cur["series"]["days"]]
    before = snap.get((d1 - timedelta(days=1)).isoformat())
    known = [v for v in chan_series if v is not None]
    return {
        "from": d1.isoformat(), "to": d2.isoformat(), "days": n, "cur": cur, "prev": prev,
        "now": {"pending": pending[0], "pending_sum": int(pending[1] or 0), "blocked": blocked or 0, "queue": queue or 0,
                "channel": chan, "channel_name": settings.channel_username,
                "channel_growth": (known[-1] - (before if before is not None else known[0])) if known else None},
        "channel_series": chan_series,
    }


# ---------------------------------------------------------------- trafik manbalari

class LinkIn(BaseModel):
    name: str = Field(min_length=1, max_length=100)
    code: str = Field("", max_length=24)
    cost: int = Field(0, ge=0, le=10**10)
    note: str = Field("", max_length=255)
    # nomlash qoidasi kampaniya_video_lending (qoshiq_v3_l1): berilsa, kod shulardan yig'iladi
    campaign: str = Field("", max_length=24)
    video: str = Field("", max_length=8)
    landing: str = Field("", max_length=8)


class LinkPatch(BaseModel):
    name: str | None = Field(None, min_length=1, max_length=100)
    cost: int | None = Field(None, ge=0, le=10**10)
    note: str | None = Field(None, max_length=255)
    archived: bool | None = None
    share_pct: int | None = Field(None, ge=0, le=100)


def _slug(name: str) -> str:
    tr = str.maketrans({"ʻ": "", "’": "", "'": "", "`": "", "ʼ": "", " ": "_", "-": "_"})
    base = re.sub(r"[^a-z0-9_]", "", name.lower().translate(tr))
    return re.sub(r"_+", "_", base).strip("_")[:16]


def link_urls(code: str, share: str = "") -> dict:
    return {"bot": f"https://t.me/{settings.bot_username}?start={track.SRC_PREFIX}{code}",
            "go": f"{settings.base_url}/go/{code}",
            "report": f"{settings.base_url}/hisobot/{share}" if share else None}


def source_key(ref: str) -> str:
    ref = ref or ""
    if not ref:
        return ""
    if ref.startswith("src_"):
        return ref
    if ref.startswith("ref_"):
        return "ref_"
    if ref.startswith("r_"):
        return "r_"
    return "other"


def source_label(ref: str, names: dict | None = None) -> str:
    k = source_key(ref)
    if k.startswith("src_"):
        return (names or {}).get(k[4:]) or f"Havola: {k[4:]}"
    return SOURCE_GROUPS[k]


async def sources_data(frm: str | None, to: str | None, all_time: int = 0, archived: int = 0) -> dict:
    """«Trafik manbalari» (statistika TZ, 4-band): har bir havola va havolasiz manba bo'yicha shu davrda kelgan ODAMLAR
    (birinchi manbasi — users.ref) va ularning keyingi harakatlari, reklama xarajati, narxlar, ROI, blok va kogorta.
    Hammasi bir necha GROUP BY so'rovda (app/adstats.py); havolalar kampaniya bo'yicha guruhlanadi."""
    if all_time:
        d1, d2, a = None, today(), None
    else:
        d1, d2 = parse_range(frm, to, default_days=30)
        a = utc_of(d1)
    b = utc_of(d2 + timedelta(days=1))
    excl = await track.excluded_ids()
    async with Session() as s:
        links = (await s.execute(select(TrafficLink).order_by(TrafficLink.id.desc()))).scalars().all()
        data = await adstats.by_source(s, a, b, excl, SPEND_KINDS)
        ai = await adstats.ai_by_source(s, a, b, excl)
        starts, clicks = await adstats.starts_clicks(s, a, b, excl)
        spend, spend_days, daily = await adstats.spend_totals(s, d1, d2)
    rows = []
    for x in links:
        key = f"src_{x.code}"
        m = {**adstats.empty(), **data.pop(key, {})}  # arxivdagi havola odamlari «Boshqa manbalar»ga ham tushmaydi
        if x.archived and not archived:
            continue
        m.update(starts=starts.get(x.code, 0), clicks=clicks.get(x.code, 0), ai_cost=ai.get(key, 0.0))
        # xarajat: kunlik yozuvlar bo'lsa — shu davrdagilari yig'indisi; umuman bo'lmasa — eski umumiy «Reklama narxi»
        if x.id in daily:
            cost, how = spend.get(x.id, 0), "daily"
        else:
            cost, how = x.cost or 0, ("total" if x.cost else None)
        rows.append({"id": x.id, "code": x.code, "name": x.name, "note": x.note, "cost": x.cost or 0, "archived": x.archived,
                     "spend_src": how, "spend_days": spend_days.get(x.id, 0),
                     "share_pct": x.share_pct or 0, "created_at": x.created_at.isoformat() if x.created_at else None,
                     "urls": link_urls(x.code, x.share), **adstats.parse_code(x.code), **adstats.derive(m, cost)})
    camps: dict[str, dict] = {}
    for r in rows:
        c = camps.setdefault(r["campaign"], {"key": r["campaign"], "label": r["campaign"] or adstats.NO_CAMPAIGN, "rows": [],
                                             "t": adstats.empty()})
        c["rows"].append(r)
        adstats.add_into(c["t"], r)
    campaigns = []
    for key in [k for k in camps if k] + ([""] if "" in camps else []):  # eng yangi kampaniya tepada, qoidasiz havolalar oxirida
        c = camps[key]
        t = c["t"]
        campaigns.append({"key": key, "label": c["label"], "links": [r["id"] for r in sorted(c["rows"], key=lambda r: r["code"])],
                          **adstats.derive(t, t["spend"])})
    other = []
    for key in ("", "ref_", "r_", "other"):
        m = {**adstats.empty(), **data.pop(key, {}), "ai_cost": ai.get(key, 0.0)}
        other.append({"key": key or "organic", "name": SOURCE_GROUPS[key], **adstats.derive(m, 0)})
    for key, m in data.items():  # o'chirilgan yoki noma'lum havolalar
        m = {**adstats.empty(), **m, "ai_cost": ai.get(key, 0.0)}
        other.append({"key": key, "name": f"Havola: {key[4:]}", **adstats.derive(m, 0)})
    return {"from": d1.isoformat() if d1 else None, "to": d2.isoformat(), "links": rows, "campaigns": campaigns, "groups": other,
            "since": await adstats.since_notes(), "usd_som": await adstats.usd_rate(), "excluded": len(excl)}


@router.get("/sources")
async def sources(frm: str | None = Query(None, alias="from"), to: str | None = None, all_time: int = 0,
                  archived: int = 0, uid: int = Depends(admin_uid)):
    """Har bir manba bo'yicha: bosish, start, yangi odamlar, ilovaga kirgan, yasagan, namunani eshitgan, «sotib olish» va to'lov
    oynasi, sotib olgan, tushum, reklama xarajati, start va xaridor narxi, ROI, blok foizi va kogorta (1/3/7 kun)."""
    return await sources_data(frm, to, all_time, archived)


@router.post("/links")
async def link_create(body: LinkIn, uid: int = Depends(admin_uid)):
    explicit = bool(body.code or body.campaign or body.video or body.landing)
    if body.campaign or body.video or body.landing:
        try:
            code = adstats.compose_code(body.campaign, body.video, body.landing)
        except ValueError as e:
            raise HTTPException(400, str(e))
    else:
        code = (body.code or "").strip().lower() or _slug(body.name) or secrets.token_hex(3)
    if not track.CODE_RE.match(code):
        raise HTTPException(400, "Kod faqat lotin harflari, raqam va _ dan iborat bo'lsin (2–24 belgi)")
    async with Session() as s:
        base, i = code, 2
        while await s.scalar(select(TrafficLink.id).where(TrafficLink.code == code)):
            if explicit:
                raise HTTPException(409, "Bu kod band, boshqasini tanlang")
            code = f"{base[:20]}_{i}"
            i += 1
        x = TrafficLink(code=code, name=body.name.strip(), cost=body.cost, note=body.note.strip(), created_by=uid)
        s.add(x)
        await s.commit()
    return {"id": x.id, "code": x.code, "urls": link_urls(x.code), **adstats.parse_code(x.code)}


# ---------------------------------------------------------------- kunlik reklama xarajati (har bir havola uchun)

class SpendIn(BaseModel):
    day: str = Field(min_length=10, max_length=10)  # YYYY-MM-DD (Toshkent)
    amount: float = Field(gt=0, le=10**11)
    currency: str = Field("som", pattern="^(som|usd)$")


async def _link_or_404(link_id: int) -> TrafficLink:
    async with Session() as s:
        x = await s.get(TrafficLink, link_id)
    if not x:
        raise HTTPException(404)
    return x


@router.get("/links/{link_id}/spend")
async def link_spend(link_id: int, uid: int = Depends(admin_uid)):
    """Havolaning kunlik xarajatlari (yangisi tepada), dollar kursi va eski umumiy «Reklama narxi»."""
    x = await _link_or_404(link_id)
    rows = await adstats.spend_list(link_id)
    return {"id": x.id, "code": x.code, "name": x.name, "cost": x.cost or 0, "rows": rows, "total": sum(r["som"] for r in rows),
            "usd_som": await adstats.usd_rate()}


@router.post("/links/{link_id}/spend")
async def link_spend_put(link_id: int, body: SpendIn, uid: int = Depends(admin_uid)):
    """Bir kunlik xarajat (so'm yoki dollar). Shu kun uchun yozuv bo'lsa — yangilanadi."""
    await _link_or_404(link_id)
    try:
        d = date.fromisoformat(body.day)
    except ValueError:
        raise HTTPException(400, "Sana YYYY-MM-DD ko'rinishida bo'lsin")
    if d > today() or d < date(2020, 1, 1):
        raise HTTPException(400, "Kelajakdagi yoki juda eski sana kiritib bo'lmaydi")
    try:
        saved = await adstats.spend_put(link_id, d, body.amount, body.currency, uid)
    except ValueError as e:
        raise HTTPException(400, str(e))
    log.info("Reklama xarajati kiritildi (admin %s): havola %s, %s, %s so'm", uid, link_id, saved["day"], saved["som"])
    return {"saved": saved, **(await link_spend(link_id, uid))}


@router.delete("/links/{link_id}/spend/{spend_id}")
async def link_spend_drop(link_id: int, spend_id: int, uid: int = Depends(admin_uid)):
    if not await adstats.spend_drop(link_id, spend_id):
        raise HTTPException(404)
    log.info("Reklama xarajati o'chirildi (admin %s): havola %s, yozuv %s", uid, link_id, spend_id)
    return await link_spend(link_id, uid)


@router.patch("/links/{link_id}")
async def link_edit(link_id: int, body: LinkPatch, uid: int = Depends(admin_uid)):
    async with Session() as s:
        x = await s.get(TrafficLink, link_id)
        if not x:
            raise HTTPException(404)
        for k, v in body.model_dump(exclude_none=True).items():
            setattr(x, k, v.strip() if isinstance(v, str) else v)
        await s.commit()
    return {"ok": True}


class ShareIn(BaseModel):
    enable: bool = True
    renew: bool = False


@router.post("/links/{link_id}/share")
async def link_share(link_id: int, body: ShareIn, uid: int = Depends(admin_uid)):
    """Hamkor (kanal egasi) uchun faqat shu havola natijalari ko'rinadigan maxfiy hisobot sahifasi."""
    async with Session() as s:
        x = await s.get(TrafficLink, link_id)
        if not x:
            raise HTTPException(404)
        if not body.enable:
            x.share = ""
        elif body.renew or not x.share:
            x.share = secrets.token_urlsafe(18)[:24]
        await s.commit()
    return {"urls": link_urls(x.code, x.share)}


async def link_report(x: TrafficLink, a: datetime, b: datetime, days: list[date]) -> dict:
    """Bitta havolaning natijalari: bosish, start, yangi foydalanuvchilar va ularning keyingi harakatlari."""
    ref = f"{track.SRC_PREFIX}{x.code}"
    async with Session() as s:
        cohort = select(User.tg_id).where(User.ref == ref, User.created_at >= a, User.created_at < b)
        users = (await s.execute(select(User.tg_id, User.created_at).where(User.ref == ref, User.created_at >= a,
                                                                           User.created_at < b))).all()
        clicks = (await s.execute(select(Event.created_at).where(Event.kind == "click", Event.src == x.code,
                                                                 Event.created_at >= a, Event.created_at < b))).scalars().all()
        starts = (await s.execute(select(Event.user_id, Event.created_at).where(Event.kind == "start", Event.src == ref,
                                                                                Event.created_at >= a, Event.created_at < b))).all()
        app = await s.scalar(select(func.count(func.distinct(Event.user_id))).where(Event.kind == "app", Event.user_id.in_(cohort)))
        site_owners = set((await s.execute(select(Site.owner_id).where(Site.kind == "site", Site.owner_id.in_(cohort)).distinct())).scalars().all())
        job_owners = set((await s.execute(select(RenderJob.owner_id).where(RenderJob.guest_id.is_(None),
                                                                            RenderJob.owner_id.in_(cohort)).distinct())).scalars().all())
        spenders = set((await s.execute(select(BalanceTx.user_id).where(BalanceTx.kind.in_(SPEND_KINDS),
                                                                         BalanceTx.user_id.in_(cohort)).distinct())).scalars().all())
        payers = set((await s.execute(select(Payment.user_id).where(Payment.status == "approved", Payment.user_id.in_(cohort)).distinct())).scalars().all())
        songers = await s.scalar(select(func.count(func.distinct(Song.owner_id))).where(Song.owner_id.in_(cohort))) or 0
        song_buyers = await s.scalar(select(func.count(func.distinct(Song.owner_id))).where(Song.owner_id.in_(cohort), Song.paid.is_(True))) or 0
        # tushum: shu havoladan kelgan barcha odamlarning (qachon kelganidan qat'i nazar) shu davrdagi tasdiqlangan to'lovlari
        pays = (await s.execute(select(Payment.amount, Payment.decided_at).where(
            Payment.status == "approved", Payment.decided_at >= a, Payment.decided_at < b,
            Payment.user_id.in_(select(User.tg_id).where(User.ref == ref))))).all()
    idx = {d: i for i, d in enumerate(days)}
    daily = [{"day": d.isoformat(), "clicks": 0, "starts": 0, "users": 0, "revenue": 0} for d in days]
    for amount, t in pays:
        if t and (i := idx.get(local_day(t))) is not None:
            daily[i]["revenue"] += amount
    for t in clicks:
        if (i := idx.get(local_day(t))) is not None:
            daily[i]["clicks"] += 1
    seen = set()
    for u, t in starts:
        if (i := idx.get(local_day(t))) is not None and (u, i) not in seen:
            seen.add((u, i))
            daily[i]["starts"] += 1
    for _, t in users:
        if (i := idx.get(local_day(t))) is not None:
            daily[i]["users"] += 1
    n = len(users)
    bought = len(spenders | payers)
    return {"clicks": len(clicks), "starts": len({u for u, _ in starts}), "users": n, "app": app or 0,
            "created": len(site_owners | job_owners), "songs": songers, "song_bought": song_buyers, "bought": bought, "conv": pct(bought, n),
            "revenue": int(sum(p[0] for p in pays)), "payments": len(pays), "daily": daily}


REPORT_PERIODS = {"month": "Bu oy", "prev": "O'tgan oy", "7": "7 kun", "30": "30 kun", "90": "90 kun", "all": "Hammasi"}


def report_range(d: str, t: date, since: date) -> tuple[date, date]:
    if d == "month":
        return t.replace(day=1), t
    if d == "prev":
        end = t.replace(day=1) - timedelta(days=1)
        return end.replace(day=1), end
    if d == "all":
        return max(since, t - timedelta(days=365)), t
    return t - timedelta(days=int(d) - 1), t


@public.get("/hisobot/{share}", response_class=HTMLResponse)
async def partner_report(share: str, d: str = "30"):
    """Hamkor hisobot sahifasi: kirish uchun faqat maxfiy havola kerak, shaxsiy ma'lumot ko'rsatilmaydi."""
    if not share or len(share) < 16:
        raise HTTPException(404)
    async with Session() as s:
        x = (await s.execute(select(TrafficLink).where(TrafficLink.share == share))).scalar_one_or_none()
    if not x:
        return HTMLResponse("<!doctype html><meta charset=utf-8><meta name=viewport content='width=device-width'>"
                            "<p style='font:16px sans-serif;padding:40px 20px;text-align:center'>Bu hisobot havolasi o'chirilgan yoki noto'g'ri.</p>",
                            status_code=404)
    d = d if d in REPORT_PERIODS else "month"
    t = today()
    start, end = report_range(d, t, min(local_day(x.created_at), t) if x.created_at else t)
    days = [start + timedelta(days=i) for i in range((end - start).days + 1)]
    r = await link_report(x, datetime(2000, 1, 1) if d == "all" else utc_of(start), utc_of(end + timedelta(days=1)), days)
    share = round(r["revenue"] * (x.share_pct or 0) / 100)
    span = "butun davr" if d == "all" else (day_uz(start) if start == end else f"{day_uz(start)} — {day_uz(end)}")
    e = html_escape
    num = lambda v: f"{v:,}".replace(",", " ")  # noqa: E731
    chips = "".join(f'<a class="chip" href="?d={k}" aria-pressed="{str(k == d).lower()}">{v}</a>' for k, v in REPORT_PERIODS.items())
    cards = [("Bosish", r["clicks"], "havolani ochganlar"), ("Start", r["starts"], "botda start bosganlar"),
             ("Yangi foydalanuvchi", r["users"], "botga birinchi marta kelganlar"), ("Ilovaga kirdi", r["app"], "yangi kelganlardan"),
             ("Yasadi", r["created"], "taklifnoma yoki video"), ("Qo'shiq tayyorladi", r["songs"], f"{r['song_bought']} tasi sotib oldi"),
             ("Sotib oldi", r["bought"], f"konversiya {r['conv']}%")]
    money = [("Tushum", f"{num(r['revenue'])} so'm", f"{r['payments']} ta to'lov, shu davrda")]
    if x.share_pct:
        money.append((f"Sizning ulushingiz ({x.share_pct}%)", f"{num(share)} so'm", "tushumdan hisoblangan"))
    top = max([1] + [x2["clicks"] for x2 in r["daily"]] + [x2["users"] for x2 in r["daily"]])
    rows = "".join(
        f'<tr><td class="num">{e(row["day"][8:10])}.{e(row["day"][5:7])}.{e(row["day"][:4])}</td><td class="r num">{num(row["clicks"])}</td>'
        f'<td class="r num">{num(row["starts"])}</td><td class="r num"><b>{num(row["users"])}</b>'
        f'<div class="mini-bar"><i style="width:{100 * row["users"] / top:.1f}%"></i></div></td>'
        f'<td class="r num">{num(row["revenue"]) + " so&#39;m" if row["revenue"] else "—"}</td></tr>'
        for row in reversed(r["daily"]) if row["clicks"] or row["starts"] or row["users"] or row["revenue"])
    v = str(int((ROOT / "static" / "admin" / "admin.css").stat().st_mtime))
    page = f"""<!doctype html><html lang="uz"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1"><meta name="robots" content="noindex, nofollow"><meta name="referrer" content="no-referrer">
<title>{e(x.name)} — Tayyorla hisoboti</title><link rel="stylesheet" href="/static/fonts/fonts.css"><link rel="stylesheet" href="/static/admin/admin.css?v={v}">
</head><body class="report"><main>
<div class="brand-line"><span class="ikat" aria-hidden="true"></span><span>Tayyorla · hamkor hisoboti</span></div>
<div class="head"><div><h1>{e(x.name)}</h1><p>@{e(settings.bot_username)} botiga shu havola orqali kelganlar. Raqamlar avtomatik yangilanadi.</p></div></div>
<div class="period" role="group" aria-label="Davr">{chips}</div>
<p class="muted" style="margin-top:10px">{e(span)}</p>
<section class="blk"><div class="report-money">{"".join(f'<div><b>{e(val)}</b><span>{e(lbl)}</span><small>{e(h)}</small></div>' for lbl, val, h in money)}</div></section>
<section class="blk"><div class="report-grid">{"".join(f'<div><b>{num(val)}</b><span>{e(lbl)}</span><small>{e(h)}</small></div>' for lbl, val, h in cards)}</div></section>
<section class="blk"><div class="bh"><h2>Kunlar bo'yicha</h2></div>
<div class="tbl-wrap"><table><thead><tr><th>Sana</th><th class="r">Bosish</th><th class="r">Start</th><th class="r">Yangi foydalanuvchi</th><th class="r">Tushum</th></tr></thead>
<tbody>{rows or '<tr><td colspan="5" class="empty">Bu davrda hali hech kim kelmagan</td></tr>'}</tbody></table></div></section>
<p class="muted" style="font-size:12.5px;margin-top:18px">«Yangi foydalanuvchi» — botga birinchi marta aynan shu havola orqali kirganlar. «Yasadi» va «Sotib oldi» — ular keyinchalik qilgan ishlar.
«Tushum» — shu havola orqali kelgan odamlar tanlangan davrda to'lagan va tasdiqlangan pul (qachon kelganidan qat'i nazar). Shaxsiy ma'lumotlar ko'rsatilmaydi.</p>
</main></body></html>"""
    return HTMLResponse(page, headers={"Cache-Control": "no-store", "X-Robots-Tag": "noindex", "Referrer-Policy": "no-referrer"})


@public.api_route("/go/{code}", methods=["GET", "HEAD"])
async def go(code: str, request: Request):
    """Kuzatuv havolasi: bosishni sanaydi va botga yo'naltiradi (havola tekshiruvchilar va preview sanalmaydi)."""
    code = code.lower()[:24]
    if (request.method == "GET" and track.CODE_RE.match(code)
            and not BOT_UA.search(request.headers.get("user-agent", ""))):
        await track.log_event("click", None, code)
    return RedirectResponse(f"https://t.me/{settings.bot_username}?start={track.SRC_PREFIX}{code}", status_code=302)


# ---------------------------------------------------------------- sotuvlar

@router.get("/sales")
async def sales(frm: str | None = Query(None, alias="from"), to: str | None = None, uid: int = Depends(admin_uid)):
    d1, d2 = parse_range(frm, to, default_days=30)
    a, b = utc_of(d1), utc_of(d2 + timedelta(days=1))
    async with Session() as s:
        sites = (await s.execute(select(Site.id, Site.slug, Site.owner_id, Site.owner_name, Site.status, Site.config, Site.created_at, Site.views)
                                 .where(Site.kind == "site", Site.created_at >= a, Site.created_at < b).order_by(Site.id.desc()))).all()
        jobs = (await s.execute(select(RenderJob.design, RenderJob.charge, RenderJob.status, RenderJob.payload["page"]["section"].as_string())
                                .where(RenderJob.guest_id.is_(None), RenderJob.created_at >= a, RenderJob.created_at < b))).all()
        langs = (await s.execute(select(User.lang, func.count()).group_by(User.lang))).all()
        owners = await _user_map(s, [x[2] for x in sites if x[4] != "paid"][:100])
    tpl = defaultdict(lambda: {"created": 0, "paid": 0, "revenue": 0})
    sec = defaultdict(lambda: {"created": 0, "paid": 0, "revenue": 0})
    tier = defaultdict(lambda: {"created": 0, "paid": 0, "revenue": 0})
    for _id, slug, owner, oname, status, cfg, created, views in sites:
        tid = cfg.get("template") or cfg.get("category") or "?"
        t = TEMPLATES.get(tid, {})
        for bucket in (tpl[tid], sec[t.get("section") or cfg.get("category") or "?"], tier[cfg.get("tarif") or "eski"]):
            bucket["created"] += 1
            if status == "paid":
                bucket["paid"] += 1
                bucket["revenue"] += site_price(cfg)
    top = []
    for tid, m in tpl.items():
        t = TEMPLATES.get(tid, {})
        top.append({"id": tid, "name": t.get("name") or tid, "section": SECTIONS.get(t.get("section"), t.get("section") or "—"),
                    "tier": TIER_NAMES.get(t.get("tier"), "—"), "thumb": f"/katalog/thumb/{tid}.jpg" if t.get("v2") else "", **m, "conv": pct(m["paid"], m["created"])})
    top.sort(key=lambda x: (-x["paid"], -x["created"]))
    vid = defaultdict(lambda: {"free": 0, "paid": 0, "unpaid": 0, "total": 0})
    vsec = defaultdict(lambda: {"free": 0, "paid": 0, "unpaid": 0, "total": 0})
    for design, charge, status, section in jobs:
        key = "unpaid" if status == "awaiting_payment" else ("paid" if charge in ("paid", "package") else "free")
        if status not in ("done", "awaiting_payment"):
            continue
        for bucket in (vid[design], vsec[section or "?"]):
            bucket[key] += 1
            bucket["total"] += 1
    designs = [{"id": k, "name": video.DESIGNS.get(k, {}).get("name", k),
                "section": VIDEO_SECTIONS.get(video.DESIGNS.get(k, {}).get("section"), "—"), **m}
               for k, m in vid.items()]
    designs.sort(key=lambda x: -x["total"])
    unpaid = []
    for _id, slug, owner, oname, status, cfg, created, views in sites:
        if status == "paid" or len(unpaid) >= 100:
            continue
        u = owners.get(owner)
        unpaid.append({"slug": slug, "title": site_title(cfg), "owner": owner, "name": (u.first_name if u else oname) or "",
                       "username": u.username if u else "", "tier": TIER_NAMES.get(cfg.get("tarif"), "—"),
                       "price": site_price(cfg), "status": status, "created_at": created.isoformat() if created else None,
                       "url": f"{settings.base_url}/s/{slug}"})
    return {
        "from": d1.isoformat(), "to": d2.isoformat(), "templates": top,
        "sections": [{"key": k, "name": SECTIONS.get(k, k), **m, "conv": pct(m["paid"], m["created"])} for k, m in sec.items()],
        "tiers": [{"key": k, "name": TIER_NAMES.get(k, "Eski shablonlar"), **m} for k, m in tier.items()],
        "designs": designs,
        "video_sections": [{"key": k, "name": VIDEO_SECTIONS.get(k, k), **m} for k, m in vsec.items()],
        "langs": sorted(({"lang": k or "uz", "n": n} for k, n in langs), key=lambda x: -x["n"]),
        "unpaid": unpaid,
    }


# ---------------------------------------------------------------- to'lovlar

async def _user_map(s, ids) -> dict:
    ids = {i for i in ids if i}
    if not ids:
        return {}
    return {u.tg_id: u for u in (await s.execute(select(User).where(User.tg_id.in_(ids)))).scalars().all()}


def _pay_range(frm, to, all_time: int = 0, default_all: bool = False) -> tuple[datetime | None, datetime, date | None, date]:
    """To'lovlar bo'limi davri: (boshi yoki None — butun davr, oxiri, birinchi va oxirgi kun).
    default_all — sana berilmaganda butun davr olinadi (aks holda oxirgi 7 kun)."""
    frm, to = (x if isinstance(x, str) and x else None for x in (frm, to))
    if all_time or (default_all and not frm and not to):
        return None, utc_of(today() + timedelta(days=1)), None, today()
    d1, d2 = parse_range(frm, to)
    return utc_of(d1), utc_of(d2 + timedelta(days=1)), d1, d2


@router.get("/payments")
async def payments(status: str = "pending", limit: int = Query(100, le=500), frm: str | None = Query(None, alias="from"),
                   to: str | None = None, all_time: int = 0, uid: int = Depends(admin_uid)):
    """To'lov urinishlari: «nima uchun» va «qaysi qadamda to'xtadi» bilan. Davr berilsa — shu davrda ochilganlar;
    «Chekni tekshirish» (pending) har doim to'liq chiqadi — bu ish navbati, davrga bog'liq emas."""
    excl = await track.excluded_ids()
    async with Session() as s:
        q = select(Payment).order_by(Payment.id.desc()).limit(limit)
        if status != "all":
            q = q.where(Payment.status == status)
        t1, t2, _, _ = _pay_range(frm, to, all_time, default_all=True)
        if status != "pending" and t1:
            q = q.where(Payment.created_at >= t1, Payment.created_at < t2)
        rows = (await s.execute(q)).scalars().all()
        users = await _user_map(s, [p.user_id for p in rows] + [p.admin_id for p in rows])
        steps = await payflow.load_steps(s, ids=[p.id for p in rows])  # hamma qatorlar uchun bitta so'rov
    out = []
    for p in rows:
        u = users.get(p.user_id)
        a = users.get(p.admin_id) if p.admin_id else None
        out.append({"id": p.id, "user_id": p.user_id, "name": u.first_name if u else "", "username": u.username if u else "",
                    "amount": p.amount, "status": p.status, "for_video": bool(p.job_id), "receipt": bool(p.receipt),
                    "provider": p.provider or "", "ext_id": p.ext_id or "",
                    "auto": p.admin_id == 0 and p.status == "approved",
                    "admin": (a.first_name if a else p.admin_id) if p.admin_id else None,
                    "created_at": p.created_at.isoformat() if p.created_at else None,
                    "decided_at": p.decided_at.isoformat() if p.decided_at else None,
                    "test": p.user_id in excl, **payflow.describe(p, steps.get(p.id, {}))})
    return {"payments": out, "limit": limit}


# ---------------------------------------------------------------- to'lov bosqichi statistikasi (xulosa, so'rov, sinov akkauntlari)

async def _paystats_settings() -> dict:
    cfg = await payflow.config()
    hours = await nudges.config()
    return {"survey_on": cfg["survey_on"], "click_track": cfg["click_track"],
            "click_tracked": bool(cfg["click_track"] and settings.click_on and settings.base_url.startswith("https://")),
            "test_ids": await track.test_ids(), "admins": sorted(settings.admins),
            "delay_min": paysurvey.DELAY_MIN, "from_hour": hours["from_hour"], "to_hour": hours["to_hour"]}


@router.get("/paystats")
async def paystats(frm: str | None = Query(None, alias="from"), to: str | None = None, all_time: int = 0,
                   uid: int = Depends(admin_uid)):
    """«To'lovlar» bo'limi tepasidagi xulosa: oynani ochgan odamlar, to'laganlar ulushi, qaysi qadamda to'xtashgani,
    takroriy urinishlar, to'lovgacha vaqt, balans to'ldirib sotib olmaganlar va «nega to'lamadingiz» javoblari."""
    a, b, d1, d2 = _pay_range(frm, to, all_time)
    out = await payflow.summary(a, b, SPEND_KINDS)
    return {"from": d1.isoformat() if d1 else None, "to": d2.isoformat(), **out, "settings": await _paystats_settings()}


class PayStatsIn(BaseModel):
    survey_on: bool | None = None
    click_track: bool | None = None
    test_ids: str | None = Field(None, max_length=4000)  # Telegram id lar: vergul, bo'sh joy yoki yangi qator bilan


@router.post("/paystats/settings")
async def paystats_save(body: PayStatsIn, uid: int = Depends(admin_uid)):
    cfg = await payflow.save({"survey_on": body.survey_on, "click_track": body.click_track})
    if body.test_ids is not None:
        if re.search(r"[^\d\s,;]", body.test_ids):
            raise HTTPException(400, "Faqat Telegram id raqamlarini kiriting (vergul yoki bo'sh joy bilan ajrating)")
        await track.set_test_ids(re.findall(r"\d+", body.test_ids))
    log.info("To'lov statistikasi sozlamasi o'zgardi (admin %s): so'rov=%s, kuzatuv=%s", uid, cfg["survey_on"], cfg["click_track"])
    return {"ok": True, "settings": await _paystats_settings()}


@router.post("/paystats/survey-test")
async def paystats_survey_test(uid: int = Depends(admin_uid)):
    """Adminning o'ziga «nega to'lamadingiz» savolining namunasi (javobi statistikaga yozilmaydi)."""
    if not videobot.BOT:
        raise HTTPException(503, "Bot ishlamayapti")
    try:
        await paysurvey.send_test(videobot.BOT, uid)
    except Exception as e:
        log.exception("So'rov namunasini yuborib bo'lmadi")
        raise HTTPException(502, f"Yuborib bo'lmadi: {e}")
    return {"ok": True}


# ---------------------------------------------------------------- voronka (qo'shiq, sayt, video) va namunasiz qolganlar

def _funnel_args(product: str, mode: str, src: str) -> tuple[str, str, str]:
    if product not in funnel.SPECS:
        raise HTTPException(400, "Noma'lum mahsulot")
    return product, mode if mode in funnel.MODES else "cohort", (src if isinstance(src, str) else "")[:40]


async def _source_options() -> list[dict]:
    """Manba filtri uchun ro'yxat: reklama havolalari va havolasiz guruhlar."""
    async with Session() as s:
        links = (await s.execute(select(TrafficLink.code, TrafficLink.name, TrafficLink.archived)
                                 .order_by(TrafficLink.archived, TrafficLink.id.desc()))).all()
    return ([{"key": "", "label": "Barcha manbalar"}]
            + [{"key": f"src_{code}", "label": name + (" (arxivda)" if arch else "")} for code, name, arch in links]
            + [{"key": k or "organic", "label": v} for k, v in SOURCE_GROUPS.items()])


@router.get("/funnel")
async def funnel_report(product: str = "song", mode: str = "cohort", src: str = "", frm: str | None = Query(None, alias="from"),
                        to: str | None = None, all_time: int = 0, uid: int = Depends(admin_uid)):
    """Voronka: qadamlar ketma-ket, ODAMLAR soni bilan. mode=cohort — shu davrda kelgan yangi odamlar keyin nima qilgani,
    mode=period — shu davrdagi harakatlar. Qo'shiq uchun «Namunasiz qolganlar» bo'linishi ham qaytadi."""
    product, mode, src = _funnel_args(product, mode, src)
    a, b, d1, d2 = _pay_range(frm, to, all_time)
    out = await funnel.report(product, a, b, mode, src)
    if product == "song":
        out["nosample"] = await funnel.nosample(a, b, mode, src)
    return {"from": d1.isoformat() if d1 else None, "to": d2.isoformat(), **out,
            "products": [{"key": k, "label": v["label"]} for k, v in funnel.SPECS.items()], "sources": await _source_options()}


async def _funnel_people(product, mode, src, step, group, a, b, limit: int | None = 200) -> dict:
    d = await (funnel.nosample_people(a, b, mode, src, group, limit) if group else funnel.people(product, a, b, mode, src, step, limit))
    async with Session() as s:
        names = await _link_names(s)
    for r in d["rows"]:
        r["source"] = source_label(r["ref"], names)
    return d


@router.get("/funnel/people")
async def funnel_people(product: str = "song", mode: str = "cohort", src: str = "", step: str = "", group: str = "",
                        frm: str | None = Query(None, alias="from"), to: str | None = None, all_time: int = 0,
                        uid: int = Depends(admin_uid)):
    """Tushib qolganlar ro'yxati: step — shu qadamda to'xtaganlar; group — namunasiz qolganlarning bitta guruhi."""
    product, mode, src = _funnel_args(product, mode, src)
    a, b, _, _ = _pay_range(frm, to, all_time)
    return await _funnel_people(product, mode, src, step, group, a, b)


class SongAlertIn(BaseModel):
    alert_on: bool | None = None
    alert_pct: int | None = Field(None, ge=1, le=100)
    alert_min: int | None = Field(None, ge=1, le=1000)


@router.post("/songflow/settings")
async def songflow_save(body: SongAlertIn, uid: int = Depends(admin_uid)):
    """Qo'shiq xatolari bo'yicha adminlarga Telegram ogohlantirish: yoqish/o'chirish va chegaralar."""
    cfg = await songflow.save(body.model_dump())
    log.info("Qo'shiq ogohlantirishi sozlamasi o'zgardi (admin %s): yoqilgan=%s, chegara %s%%", uid, cfg["alert_on"], cfg["alert_pct"])
    return {"ok": True, "alert": {"on": cfg["alert_on"], "pct": cfg["alert_pct"], "min": cfg["alert_min"]}}


@router.post("/songflow/alert-test")
async def songflow_alert_test(uid: int = Depends(admin_uid)):
    if not videobot.BOT:
        raise HTTPException(503, "Bot ishlamayapti")
    try:
        await songflow.alert_test(videobot.BOT, uid)
    except Exception as e:
        log.exception("Sinov ogohlantirishini yuborib bo'lmadi")
        raise HTTPException(502, f"Yuborib bo'lmadi: {type(e).__name__}")
    return {"ok": True}


class Decision(BaseModel):
    approve: bool


@router.post("/payments/{pid}")
async def payment_decide(pid: int, body: Decision, uid: int = Depends(admin_uid)):
    if not videobot.BOT:
        raise HTTPException(503, "Bot ishlamayapti")
    from .bot.money import decide_payment
    if body.approve:
        async with Session() as s:
            p = await s.get(Payment, pid)
        if p and p.status == "new":
            raise HTTPException(409, "Mijoz hali to'lamagan — bu to'lovni tasdiqlab bo'lmaydi")
    res = await decide_payment(videobot.BOT, pid, body.approve, uid)
    if res == "not_found":
        raise HTTPException(404)
    return {"ok": res == "ok", "already": res == "done"}


class CardPayIn(BaseModel):
    on: bool | None = None
    card: str | None = Field(None, max_length=30)
    owner: str | None = Field(None, max_length=60)
    auto: bool | None = None
    auto_max: int | None = Field(None, ge=0, le=10_000_000)
    window_min: int | None = Field(None, ge=10, le=24 * 60)
    daily_auto: int | None = Field(None, ge=0, le=50)


@router.get("/cardpay")
async def cardpay_get(uid: int = Depends(admin_uid)):
    from . import receipt
    cfg = await receipt.config()
    return {**cfg, "enabled": receipt.enabled(cfg)}


@router.post("/cardpay")
async def cardpay_set(body: CardPayIn, uid: int = Depends(admin_uid)):
    from . import receipt
    cfg = await receipt.save(body.model_dump())
    if cfg["on"] and not receipt.enabled(cfg):
        raise HTTPException(400, "Karta raqami 16 xonali bo'lishi kerak")
    return {**cfg, "enabled": receipt.enabled(cfg)}


@router.post("/payments/{pid}/revert")
async def payment_revert(pid: int, uid: int = Depends(admin_uid)):
    """Avtomatik tasdiqlangan karta to'lovini bekor qilish (soxta chek)."""
    from .bot.money import revert_payment
    res = await revert_payment(pid, uid)
    if res == "not_found":
        raise HTTPException(404)
    if res == "done":
        raise HTTPException(409, "Bu to'lovni bekor qilib bo'lmaydi")
    return {"ok": True, "partial": res == "spent"}


@router.get("/payments/{pid}/receipt")
async def payment_receipt(pid: int, uid: int = Depends(admin_uid)):
    async with Session() as s:
        p = await s.get(Payment, pid)
    if not p or not p.receipt or not videobot.BOT:
        raise HTTPException(404)
    try:
        f = await videobot.BOT.get_file(p.receipt)
        buf = await videobot.BOT.download_file(f.file_path)
    except Exception:
        raise HTTPException(404, "Chekni Telegramdan olib bo'lmadi")
    ext = (f.file_path or "").rsplit(".", 1)[-1].lower()
    mime = {"jpg": "image/jpeg", "jpeg": "image/jpeg", "png": "image/png", "webp": "image/webp", "pdf": "application/pdf"}.get(ext, "application/octet-stream")
    return Response(buf.read(), media_type=mime, headers={"Cache-Control": "private, max-age=3600"})


# ---------------------------------------------------------------- foydalanuvchilar

def _user_out(u: User, names: dict | None = None) -> dict:
    return {"id": u.tg_id, "name": u.first_name, "username": u.username, "lang": u.lang, "balance": u.balance,
            "bonus": u.bonus_videos, "blocked": u.blocked, "ref": u.ref, "source": source_label(u.ref, names),
            "created_at": u.created_at.isoformat() if u.created_at else None,
            "last_seen": u.last_seen.isoformat() if u.last_seen else None}


async def _link_names(s) -> dict:
    return dict((await s.execute(select(TrafficLink.code, TrafficLink.name))).all())


USER_FILTERS = {
    "played": "Namuna eshitgan",
    "payopen": "To'lov oynasini ochib, to'lamagan",
    "idle": "Balansi bor, lekin xarid qilmagan",
    "blocked": "Botni bloklagan",
}


def _user_filter(flt: str) -> list:
    """Foydalanuvchilar filtri (statistika TZ, 6-band): bazaning o'zida EXISTS bilan."""
    from sqlalchemy import exists
    ev = lambda kind: exists().where(Event.user_id == User.tg_id, Event.kind == kind)  # noqa: E731
    if flt == "played":
        return [ev("sample_played")]
    if flt == "payopen":
        return [ev("pay_open"), ~ev("pay_success")]
    if flt == "idle":
        return [User.balance > 0, ~exists().where(BalanceTx.user_id == User.tg_id, BalanceTx.kind.in_(SPEND_KINDS))]
    if flt == "blocked":
        return [User.blocked.is_(True)]
    return []


async def _song_counts_all(s) -> dict:
    from sqlalchemy import case as _case
    rows = (await s.execute(select(Song.owner_id, func.count(), func.sum(_case((Song.paid.is_(True), 1), else_=0)))
                            .group_by(Song.owner_id))).all()
    return {o: (n, int(p or 0)) for o, n, p in rows}


async def _song_counts(s, ids) -> dict:
    """Odam -> (qo'shiqlar soni, sotib olinganlari) — bitta so'rov."""
    from sqlalchemy import case as _case
    rows = (await s.execute(select(Song.owner_id, func.count(), func.sum(_case((Song.paid.is_(True), 1), else_=0)))
                            .where(Song.owner_id.in_(list(ids) or [0])).group_by(Song.owner_id))).all()
    return {o: (n, int(p or 0)) for o, n, p in rows}


@router.get("/users")
async def users_list(q: str = "", sort: str = "new", page: int = Query(0, ge=0), flt: str = "", uid: int = Depends(admin_uid)):
    size = 50
    async with Session() as s:
        stmt = select(User).where(*_user_filter(flt))
        q = q.strip().lstrip("@")
        if q:
            like = f"%{q.lower()}%"
            cond = func.lower(User.first_name).like(like) | func.lower(User.username).like(like) | (User.ref == q)
            if q.isdigit():
                cond = cond | (User.tg_id == int(q))
            stmt = stmt.where(cond)
        order = {"new": User.created_at.desc(), "seen": User.last_seen.desc(), "balance": User.balance.desc()}.get(sort, User.created_at.desc())
        total = await s.scalar(select(func.count()).select_from(stmt.subquery()))
        rows = (await s.execute(stmt.order_by(order).offset(page * size).limit(size))).scalars().all()
        ids = [u.tg_id for u in rows]
        spent = dict((await s.execute(select(BalanceTx.user_id, func.sum(-BalanceTx.amount))
                                      .where(BalanceTx.kind.in_(SPEND_KINDS), BalanceTx.user_id.in_(ids or [0])).group_by(BalanceTx.user_id))).all())
        nsites = dict((await s.execute(select(Site.owner_id, func.count()).where(Site.kind == "site", Site.owner_id.in_(ids or [0]))
                                       .group_by(Site.owner_id))).all())
        nvid = dict((await s.execute(select(RenderJob.owner_id, func.count()).where(
            RenderJob.guest_id.is_(None), RenderJob.status == "done", RenderJob.owner_id.in_(ids or [0])).group_by(RenderJob.owner_id))).all())
        nsongs = await _song_counts(s, ids)
        names = await _link_names(s)
    return {"total": total, "page": page, "size": size, "filters": [{"key": k, "label": v} for k, v in USER_FILTERS.items()],
            "users": [{**_user_out(u, names), "spent": int(spent.get(u.tg_id) or 0), "sites": nsites.get(u.tg_id, 0),
                       "videos": nvid.get(u.tg_id, 0), "songs": nsongs.get(u.tg_id, (0, 0))[0],
                       "songs_paid": nsongs.get(u.tg_id, (0, 0))[1]} for u in rows]}


@router.get("/users/{user_id}")
async def user_card(user_id: int, uid: int = Depends(admin_uid)):
    async with Session() as s:
        u = await s.get(User, user_id)
        if not u:
            raise HTTPException(404)
        sites = (await s.execute(select(Site).where(Site.owner_id == user_id).order_by(Site.id.desc()).limit(50))).scalars().all()
        jobs = (await s.execute(select(RenderJob.charge, RenderJob.status, func.count()).where(
            RenderJob.owner_id == user_id, RenderJob.guest_id.is_(None)).group_by(RenderJob.charge, RenderJob.status))).all()
        pays = (await s.execute(select(Payment).where(Payment.user_id == user_id).order_by(Payment.id.desc()).limit(30))).scalars().all()
        txs = (await s.execute(select(BalanceTx).where(BalanceTx.user_id == user_id).order_by(BalanceTx.id.desc()).limit(50))).scalars().all()
        last = (await s.execute(select(Event.kind, func.max(Event.created_at), func.count()).where(Event.user_id == user_id)
                                .group_by(Event.kind))).all()
        invited = await s.scalar(select(func.count()).select_from(User).where(User.ref == f"ref_{user_id}"))
        names = await _link_names(s)
        song_rows = (await s.execute(select(Song).where(Song.owner_id == user_id).order_by(Song.id.desc()).limit(30))).scalars().all()
    return {
        "user": _user_out(u, names), "invited": invited or 0,
        "sites": [{"slug": x.slug, "kind": x.kind, "title": site_title(x.config), "status": x.status, "views": x.views,
                   "tier": TIER_NAMES.get(x.config.get("tarif"), ""), "price": site_price(x.config) if x.kind == "site" else 0,
                   "url": x.url, "created_at": x.created_at.isoformat() if x.created_at else None} for x in sites],
        "videos": [{"charge": c, "status": st, "n": n} for c, st, n in jobs],
        # qo'shiqlar: namuna — imzolangan havola (ilova pleeridagi kabi), to'langanlari — to'liq fayl
        "songs": [{"id": x.id, "title": x.title or "Qo'shiq", "recipient": x.recipient, "status": x.status, "paid": x.paid,
                   "price": x.price or 0, "style": songs.STYLES.get(x.style, ("",))[0], "lyrics": (x.lyrics or "")[:3000],
                   "preview": songs.preview_url(x), "files": [v.get("file") for v in (x.variants or []) if v.get("file")] if x.paid else [],
                   "created_at": x.created_at.isoformat() if x.created_at else None} for x in song_rows],
        "payments": [{"id": p.id, "amount": p.amount, "status": p.status, "created_at": p.created_at.isoformat() if p.created_at else None}
                     for p in pays],
        "tx": [{"amount": t.amount, "kind": t.kind, "ref": t.ref, "created_at": t.created_at.isoformat() if t.created_at else None}
               for t in txs],
        "activity": [{"kind": k, "last": d.isoformat() if d else None, "n": n} for k, d, n in last],
        "history": await msgstats.history(user_id),  # hodisalar va olgan xabarlari, yangisi tepada (statistika TZ, 6-band)
    }


class BalanceIn(BaseModel):
    amount: int = Field(ge=-10**8, le=10**8)
    bonus: int = Field(0, ge=-100, le=100)
    note: str = Field("", max_length=60)
    notify: bool = False


@router.post("/users/{user_id}/balance")
async def user_balance(user_id: int, body: BalanceIn, uid: int = Depends(admin_uid)):
    """Balansni qo'lda tuzatish (+/-) va bonus videolar. Har bir o'zgarish balans tarixiga «admin» bo'lib yoziladi."""
    if not body.amount and not body.bonus:
        raise HTTPException(400, "Summa yoki bonus kiriting")
    async with Session() as s:
        u = await s.get(User, user_id)
        if not u:
            raise HTTPException(404)
        if body.amount:
            amount = max(body.amount, -u.balance)  # balans manfiyga tushmaydi
            if amount:
                u.balance += amount
                s.add(BalanceTx(user_id=user_id, amount=amount, kind="admin", ref=f"adm:{uid}:{body.note}"[:64]))
        if body.bonus:
            u.bonus_videos = max(0, u.bonus_videos + body.bonus)
        await s.commit()
        balance, bonus, lang = u.balance, u.bonus_videos, u.lang or "uz"
    if body.notify and body.amount > 0 and videobot.BOT:
        try:
            from .i18n import tr
            await videobot.BOT.send_message(user_id, tr(lang, "bot.topup_done", amount=videobot.money(body.amount),
                                                        balance=videobot.money(balance)))
        except Exception:
            log.warning("Balans xabarini yuborib bo'lmadi: %s", user_id)
    return {"balance": balance, "bonus": bonus}


class MessageIn(BaseModel):
    text: str = Field(min_length=1, max_length=3500)


@router.post("/users/{user_id}/message")
async def user_message(user_id: int, body: MessageIn, uid: int = Depends(admin_uid)):
    if not videobot.BOT:
        raise HTTPException(503, "Bot ishlamayapti")
    try:
        await videobot.BOT.send_message(user_id, body.text, parse_mode=None)
    except Exception as e:
        raise HTTPException(400, f"Yuborilmadi: {type(e).__name__}")
    return {"ok": True}


# ---------------------------------------------------------------- tarqatma (segment bo'yicha)

SEGMENTS = {
    "all": "Barcha faol foydalanuvchilar",
    "active7": "So'nggi 7 kunda faol bo'lganlar",
    "sleep30": "30 kundan beri kirmaganlar",
    "site_unpaid": "Taklifnoma yasab, sotib olmaganlar",
    "free_only": "Faqat bepul video qilganlar (hech narsa sotib olmagan)",
    "never": "Hali hech narsa yasamaganlar",
    "src": "Tanlangan trafik manbasidan kelganlar",
    "me": "Faqat o'zim (sinov)",
}
BROADCAST: dict = {"running": False}


async def segment_ids(segment: str, code: str, uid: int) -> list[int]:
    if segment == "me":
        return [uid]
    now = utcnow()
    async with Session() as s:
        base = select(User.tg_id).where(User.blocked.is_(False))
        if segment == "active7":
            base = base.where(User.last_seen >= now - timedelta(days=7))
        elif segment == "sleep30":
            base = base.where(User.last_seen < now - timedelta(days=30))
        elif segment == "src":
            base = base.where(User.ref == f"src_{code}")
        ids = list((await s.execute(base)).scalars().all())
        if segment in ("site_unpaid", "free_only", "never"):
            ever = await _sets(s)
            if segment == "site_unpaid":
                draft = set((await s.execute(select(Site.owner_id).where(Site.kind == "site", Site.status != "paid").distinct())).scalars().all())
                ids = [i for i in ids if i in draft and i not in ever["buyers"]]
            elif segment == "free_only":
                free = set((await s.execute(select(RenderJob.owner_id).where(
                    RenderJob.guest_id.is_(None), RenderJob.charge.in_(("free", "bonus")), RenderJob.status == "done").distinct())).scalars().all())
                ids = [i for i in ids if i in free and i not in ever["buyers"]]
            else:
                ids = [i for i in ids if i not in ever["creators"]]
    return ids


class BroadcastIn(BaseModel):
    segment: str
    code: str = ""
    text: str = Field("", max_length=3500)
    button: bool | str = True                 # "none" | "app" | "song" (eski so'rov: true — «Ilovani ochish», false — tugmasiz)
    button_text: str = Field("", max_length=64)  # tugma yozuvi; bo'sh — standart
    media: str = Field("", max_length=200)   # Telegram file_id (/broadcast/media dan)
    kind: str = Field("", max_length=8)      # photo | video


# tarqatma tugmasi: yozuv (standart) va ilova manzili. song — ilovada yangi qo'shiq oynasi (core.js: route, ?song=new)
BC_BUTTONS = {"app": ("✨ Ilovani ochish", "/app"), "song": ("🎵 Qo‘shiq tayyorlash", "/app?song=new")}


def _btn_key(button) -> str:
    if isinstance(button, bool):
        return "app" if button else "none"
    return str(button or "none").strip().lower()


def broadcast_markup(button, text: str = ""):
    """Tarqatma xabari ostidagi tugma (Mini App ochadi) yoki None. Telegram web_app uchun faqat https manzil qabul qiladi."""
    from aiogram.types import InlineKeyboardButton, InlineKeyboardMarkup, WebAppInfo
    key = _btn_key(button)
    if key not in BC_BUTTONS or not settings.base_url.startswith("https://"):
        return None
    label, path = BC_BUTTONS[key]
    return InlineKeyboardMarkup(inline_keyboard=[[InlineKeyboardButton(
        text=" ".join((text or "").split())[:64] or label, web_app=WebAppInfo(url=f"{settings.base_url}{path}"))]])


CAPTION_MAX = 1024                            # Telegram: rasm/video izohi chegarasi
MEDIA_MAX = {"photo": 10 * 1024 * 1024, "video": 20 * 1024 * 1024}  # Caddy 25 MB gacha o'tkazadi


@router.post("/broadcast/media")
async def broadcast_media(file: UploadFile = File(...), uid: int = Depends(admin_uid)):
    """Rasm yoki videoni Telegramga yuklaydi (adminning o'ziga namuna sifatida yuboriladi) va file_id qaytaradi.
    Tarqatmada fayl qayta yuklanmaydi — hammaga shu file_id bilan yuboriladi."""
    from aiogram.types import BufferedInputFile
    if not videobot.BOT:
        raise HTTPException(503, "Bot ishlamayapti")
    ct = (file.content_type or "").lower()
    kind = "photo" if ct in ("image/jpeg", "image/png", "image/webp") else "video" if ct in ("video/mp4", "video/quicktime") else ""
    if not kind:
        raise HTTPException(400, "Faqat rasm (JPG, PNG, WEBP) yoki video (MP4, MOV)")
    data = await file.read(MEDIA_MAX[kind] + 1)
    if len(data) > MEDIA_MAX[kind]:
        raise HTTPException(413, f"Fayl juda katta: {'rasm 10' if kind == 'photo' else 'video 20'} MB gacha")
    inp = BufferedInputFile(data, filename=(file.filename or ("media.jpg" if kind == "photo" else "media.mp4"))[:60])
    try:
        if kind == "photo":
            m = await videobot.BOT.send_photo(uid, inp, caption="🖼 Tarqatma uchun yuklandi")
            fid = m.photo[-1].file_id
        else:
            m = await videobot.BOT.send_video(uid, inp, caption="🎬 Tarqatma uchun yuklandi", supports_streaming=True)
            fid = (m.video or m.document or m.animation).file_id
    except Exception as e:
        log.warning("Tarqatma faylini yuklab bo'lmadi: %s", e)
        raise HTTPException(400, "Telegram faylni qabul qilmadi. Boshqa formatda yoki kichikroq qilib yuklang.")
    return {"media": fid, "kind": kind}


@router.post("/broadcast/count")
async def broadcast_count(body: BroadcastIn, uid: int = Depends(admin_uid)):
    if body.segment not in SEGMENTS:
        raise HTTPException(400)
    return {"n": len(await segment_ids(body.segment, body.code, uid))}


@router.get("/broadcast")
async def broadcast_state(uid: int = Depends(admin_uid)):
    return {"segments": [{"key": k, "name": v} for k, v in SEGMENTS.items()], "state": BROADCAST}


@router.post("/broadcast")
async def broadcast_start(body: BroadcastIn, uid: int = Depends(admin_uid)):
    if body.segment not in SEGMENTS or not (body.text.strip() or body.media):
        raise HTTPException(400, "Segment va matn (yoki rasm/video) kiriting")
    if body.media and body.kind not in ("photo", "video"):
        raise HTTPException(400, "Fayl turi noma'lum")
    if body.media and len(body.text.strip()) > CAPTION_MAX:
        raise HTTPException(400, f"Rasm/video bilan matn {CAPTION_MAX} belgidan oshmasin (hozir {len(body.text.strip())})")
    if _btn_key(body.button) not in ("none", *BC_BUTTONS):
        raise HTTPException(400, "Tugma turi noma'lum")
    if BROADCAST.get("running"):
        raise HTTPException(409, "Avvalgi tarqatma hali tugamagan")
    if not videobot.BOT:
        raise HTTPException(503, "Bot ishlamayapti")
    ids = await segment_ids(body.segment, body.code, uid)
    BROADCAST.clear()
    BROADCAST.update(running=True, total=len(ids), sent=0, failed=0, blocked=0, segment=SEGMENTS[body.segment],
                     started=utcnow().isoformat(), by=uid)
    asyncio.create_task(_run_broadcast(ids, body.text.strip(), body.button, body.media, body.kind, body.button_text))
    return {"ok": True, "total": len(ids)}


async def _run_broadcast(ids: list[int], text: str, button: bool | str, media: str = "", kind: str = "", button_text: str = "") -> None:
    from aiogram.exceptions import TelegramForbiddenError, TelegramRetryAfter
    bot = videobot.BOT
    markup = broadcast_markup(button, button_text)
    blocked = []
    try:
        for uid in ids:
            for attempt in range(2):
                try:
                    if media and kind == "photo":
                        await bot.send_photo(uid, media, caption=text or None, parse_mode=None, reply_markup=markup)
                    elif media:
                        await bot.send_video(uid, media, caption=text or None, parse_mode=None, reply_markup=markup,
                                             supports_streaming=True)
                    else:
                        await bot.send_message(uid, text, parse_mode=None, reply_markup=markup)
                    BROADCAST["sent"] += 1
                    break
                except TelegramRetryAfter as e:
                    if attempt:
                        BROADCAST["failed"] += 1
                    else:
                        await asyncio.sleep(e.retry_after + 1)
                except TelegramForbiddenError:
                    blocked.append(uid)
                    BROADCAST["failed"] += 1
                    BROADCAST["blocked"] += 1
                    break
                except Exception:
                    BROADCAST["failed"] += 1
                    break
            await asyncio.sleep(1 / 25)
        if blocked:
            await track.mark_blocked(blocked, "broadcast")  # bayroq va blok vaqti (bot_block hodisasi)
    finally:
        BROADCAST.update(running=False, finished=utcnow().isoformat())


# ---------------------------------------------------------------- tizim

@router.get("/system")
async def system(uid: int = Depends(admin_uid)):
    now = utcnow()
    day = now - timedelta(days=1)
    async with Session() as s:
        cnt = lambda m, *w: s.scalar(select(func.count()).select_from(m).where(*w))  # noqa: E731
        queue = {k: await cnt(RenderJob, RenderJob.status == k) for k in ("queued", "rendering", "awaiting_payment")}
        queue["done_24h"] = await cnt(RenderJob, RenderJob.status == "done", RenderJob.created_at >= day)
        queue["failed_24h"] = await cnt(RenderJob, RenderJob.status == "failed", RenderJob.created_at >= day)
        oldest = await s.scalar(select(func.min(RenderJob.created_at)).where(RenderJob.status == "queued"))
        done = (await s.execute(select(RenderJob.started_at, RenderJob.finished_at).where(
            RenderJob.status == "done", RenderJob.started_at.is_not(None), RenderJob.finished_at.is_not(None))
            .order_by(RenderJob.id.desc()).limit(50))).all()
        errors = (await s.execute(select(RenderJob.id, RenderJob.design, RenderJob.error, RenderJob.created_at)
                                  .where(RenderJob.status == "failed").order_by(RenderJob.id.desc()).limit(10))).all()
        tables = {"Foydalanuvchilar": await cnt(User), "Saytlar va tadbirlar": await cnt(Site), "Videolar": await cnt(RenderJob),
                  "To'lovlar": await cnt(Payment), "Hodisalar": await cnt(Event), "Kuylar": await cnt(MusicTrack, MusicTrack.active.is_(True)),
                  "Qo'shiqlar": await cnt(Song)}
        pv_today = await songs.previews_today(s)
    per_user, per_day = await songs.limits()
    times = [(f - st).total_seconds() for st, f in done if f and st and f >= st]
    disk = shutil.disk_usage(MEDIA_DIR)
    return {
        "queue": queue, "oldest_wait_min": round((now - oldest).total_seconds() / 60) if oldest else 0,
        "avg_render_s": round(sum(times) / len(times)) if times else None,
        "errors": [{"id": i, "design": d, "error": (e or "")[:300], "at": c.isoformat() if c else None} for i, d, e, c in errors],
        "tables": tables, "disk": {"free_gb": round(disk.free / 2**30, 1), "total_gb": round(disk.total / 2**30, 1)},
        "uptime_h": round((_time.time() - STARTED) / 3600, 1), "bot": bool(videobot.BOT),
        "prices": {"standart": settings.price_standart, "premium": settings.price_premium, "vip": settings.price_vip,
                   "video": settings.video_price, "free_per_day": settings.free_videos_per_day},
        "music": await music_info(),
        "ai": await ai_info(),
        "song_limits": await songs.user_limits(),
        # qo'shiq namunasi va to'liq qo'shiq: tayyorlash vaqti, xatolar sababi bilan, qayta urinishlar, ogohlantirish
        "songflow": await songflow.system(),
        "songs": {"on": settings.songs_on, "price": settings.song_price, "daily_previews": per_day, "per_user": per_user,
                  "previews_today": pv_today, "credits": await songs.credits(), "alert": settings.song_credit_alert},
    }


class SongLimitsIn(BaseModel):
    per_user: int = Field(ge=0, le=20)     # bir kishiga kuniga bepul namuna
    per_day: int = Field(ge=0, le=100_000)  # hamma uchun kuniga jami (0 — cheklovsiz)
    pv_total: int | None = Field(default=None, ge=0, le=1000)  # bir kishiga jami bepul namuna (0 — cheklovsiz)
    ly_day: int | None = Field(default=None, ge=0, le=100)     # bir kishiga kuniga she'r yozish
    ly_total: int | None = Field(default=None, ge=0, le=1000)  # bir kishiga jami she'r yozish (0 — cheklovsiz)


@router.post("/song-limits")
async def song_limits(body: SongLimitsIn, uid: int = Depends(admin_uid)):
    cur = await store.get("song_limits") or {}
    cur.update({"per_user": body.per_user, "per_day": body.per_day})
    for k in ("pv_total", "ly_day", "ly_total"):
        if getattr(body, k) is not None:
            cur[k] = getattr(body, k)
    await store.put("song_limits", cur)
    log.info("Qo'shiq namunasi limiti o'zgardi: kishiga %s, jami %s (admin %s)", body.per_user, body.per_day, uid)
    return {"ok": True, "per_user": body.per_user, "per_day": body.per_day}


# ---------------------------------------------------------------- musiqa xizmati: ElevenLabs yoki Google Lyria

async def music_info() -> dict:
    cfg = await songs.music_cfg()
    return {"provider": await songs.provider(), "wanted": cfg.get("provider", settings.song_provider), "lang": cfg.get("lang", "uz"),
            "mix": cfg.get("mix", songs.MIX_DEFAULT), "remix": await songs.remix_state(),
            "lyria_key": bool(settings.gemini_key), "eleven_key": bool(settings.elevenlabs_api_key)}


@router.post("/song-remix")
async def song_remix(body: dict, uid: int = Depends(admin_uid)):
    """Mavjud namuna va qo'shiqlarni joriy «ovoz va musiqa balansi» bilan qayta ishlash (fonda). on=false — to'xtatish."""
    from . import store
    st = await songs.remix_state()
    if body.get("on"):
        alive = songs.REMIX_TASK.get("t") is not None and not songs.REMIX_TASK["t"].done()
        if not alive:  # server qayta ishga tushgan bo'lsa, «ishlayapti» belgisi eskirgan — yangidan boshlaymiz
            songs.REMIX_TASK["t"] = asyncio.create_task(songs.remix_all())
            await asyncio.sleep(0.3)
    else:
        await store.put(songs.REMIX_KEY, {**st, "running": False})
    return await music_info()


async def google_key_rejected(key: str) -> bool:
    """Kalitni Google'da bepul tekshiradi (modellar ro'yxati). Faqat Google aniq rad etsa True; tarmoq xatosida — False."""
    import aiohttp
    try:
        async with aiohttp.ClientSession(timeout=aiohttp.ClientTimeout(total=15)) as http:
            async with http.get("https://generativelanguage.googleapis.com/v1beta/models?pageSize=1",
                                headers={"x-goog-api-key": key}) as r:
                if r.status in (400, 401, 403):
                    log.warning("Google kalitni rad etdi: %s %s", r.status, (await r.text())[:300])
                    return True
                return False
    except Exception:
        log.warning("Google kalitini tekshirib bo'lmadi (tarmoq)")
        return False


class MusicIn(BaseModel):
    provider: str | None = Field(default=None, pattern="^(elevenlabs|lyria)$")
    lang: str | None = Field(default=None, pattern="^(uz|en)$")
    mix: str | None = Field(default=None, pattern="^(off|soft|strong)$")
    gemini_key: str | None = Field(default=None, max_length=1000)  # bo'sh satr — kalitni o'chirish


@router.post("/song-provider")
async def music_save(body: MusicIn, uid: int = Depends(admin_uid)):
    cfg = await songs.music_cfg()
    if body.gemini_key is not None:
        k = "".join(body.gemini_key.split())  # nusxalashda qo'shilgan bo'sh joy va qator ko'chishlari
        # Google kalitlari turli ko'rinishda bo'ladi (AIza..., AQ. ...) — faqat bo'sh joysiz oddiy belgilar va uzunlik tekshiriladi
        if k and not re.fullmatch(r"[\x21-\x7e]{20,400}", k):
            raise HTTPException(400, f"Kalit noto'g'ri ko'rinishda ({len(k)} belgi). Google AI Studio'dagi kalitni to'liq nusxalab qo'ying")
        if k and await google_key_rejected(k):
            raise HTTPException(400, "Google bu kalitni qabul qilmadi. AI Studio'dan kalitni qayta nusxalab qo'ying")
        cfg["gemini_key"] = k
    if body.provider:
        cfg["provider"] = body.provider
    if body.lang:
        cfg["lang"] = body.lang
    if body.mix:
        cfg["mix"] = body.mix
    await store.put(songs.MUSIC_KEY, cfg)
    await songs.music_cfg()
    log.info("Musiqa xizmati sozlamasi o'zgardi: %s, til %s, Lyria kaliti %s (admin %s)",
             cfg.get("provider"), cfg.get("lang"), "bor" if cfg.get("gemini_key") else "yo'q", uid)
    return await music_info()


@router.post("/song-provider/test")
async def music_test(uid: int = Depends(admin_uid)):
    """Lyria sinovi: bitta to'liq qo'shiq (≈ $0.08) — fonda tayyorlanib, adminga botda yuboriladi."""
    if not settings.gemini_key:
        raise HTTPException(400, "Avval Lyria kalitini kiriting")
    asyncio.create_task(songs.lyria_test(uid))
    return {"ok": True}


# ---------------------------------------------------------------- AI xizmati: Anthropic yoki Gemini, asosiy va yengil model

async def ai_info() -> dict:
    from . import llm
    cfg = await llm.config()
    provider, _ = await llm.active("main")
    return {"provider": provider, "wanted": cfg["provider"], "gemini_key": bool(settings.gemini_key),
            "anthropic_key": bool(settings.anthropic_api_key), "anthropic": cfg["anthropic"], "gemini": cfg["gemini"],
            "models": {p: [{"id": m, "name": n, "in": i, "out": o} for m, (n, i, o) in ms.items()] for p, ms in llm.MODELS.items()}}


class AIConfigIn(BaseModel):
    provider: str | None = Field(default=None, pattern="^(anthropic|gemini)$")
    anthropic: dict[str, str] | None = None
    gemini: dict[str, str] | None = None


@router.post("/ai")
async def ai_save(body: AIConfigIn, uid: int = Depends(admin_uid)):
    from . import llm
    cfg = await llm.save(body.provider, {"anthropic": body.anthropic or {}, "gemini": body.gemini or {}})
    log.info("AI xizmati o'zgardi: %s (admin %s)", cfg, uid)
    return await ai_info()


class AITestIn(BaseModel):
    provider: str = Field(pattern="^(anthropic|gemini)$")
    model: str = Field(max_length=40)


@router.post("/ai/test")
async def ai_test(body: AITestIn, uid: int = Depends(admin_uid)):
    """Tanlangan model bilan bitta qisqa o'zbekcha tabrik — sifat va narxni solishtirish uchun."""
    from . import ai, costs, llm
    if body.model not in llm.MODELS.get(body.provider, {}):
        raise HTTPException(400, "Noma'lum model")
    if body.provider == "gemini" and not settings.gemini_key:
        raise HTTPException(400, "Avval «Musiqa xizmati» bo'limida Google kalitini kiriting")
    started = _time.time()
    prompt = ("Matn turi: onaga tug'ilgan kun tabrigi.\nMa'lumotlar: {\"ism\": \"Dilnoza opa\", \"xarakter\": \"mehribon, g'amxo'r, hazilkash\", "
              "\"xotira\": \"har tong choy damlab kutadi\"}\nFoydalanuvchi istagi: samimiy va ta'sirli bo'lsin")
    try:
        text, usage = await llm.generate("main", ai.WRITER_SYSTEM, prompt, 8000, "medium", provider=body.provider, model=body.model)
    except llm.LLMError as e:
        raise HTTPException(502, f"Model javob bermadi: {e}")
    await costs.log_ai(usage, "ai_test")
    som = costs.som_of("ai", usage.input_tokens, usage.output_tokens, await costs.rates(), body.model)
    return {"text": text, "model": body.model, "seconds": round(_time.time() - started, 1),
            "tokens_in": usage.input_tokens, "tokens_out": usage.output_tokens, "som": round(som)}


# ---------------------------------------------------------------- progrev (eslatma xabarlari ketma-ketligi)

def _nudge_meta() -> dict:
    return {"seqs": [{"key": k, "name": nudges.SEQ_NAMES[k]} for k in nudges.SEQS],
            "targets": [{"key": k, "name": v} for k, v in nudges.TARGETS.items()],
            "placeholders": [{"key": k, "name": v} for k, v in nudges.PLACEHOLDERS.items()],
            "max_steps": nudges.MAX_STEPS, "grace_hours": nudges.GRACE_H, "defaults": nudges.DEFAULTS}


@router.get("/nudges")
async def nudges_get(uid: int = Depends(admin_uid)):
    cfg = await nudges.config()
    return {"config": cfg, "stats": await nudges.stats(), "diagnose": nudges.diagnose(cfg), **_nudge_meta()}


@router.get("/msgstats")
async def msgstats_get(frm: str | None = Query(None, alias="from"), to: str | None = None, all_time: int = 0, src: str = "",
                       uid: int = Depends(admin_uid)):
    """«Progrev» bo'limi: har bir progrev va chegirma xabaridan keyin odamlar nima qilgani (statistika TZ, 5-band)."""
    a, b, d1, d2 = _pay_range(frm, to, all_time)
    out = await msgstats.report(a, b, (src if isinstance(src, str) else "")[:40], SPEND_KINDS)
    return {"from": d1.isoformat() if d1 else None, "to": d2.isoformat(), **out, "sources": await _source_options()}


@router.get("/blocks")
async def blocks_get(frm: str | None = Query(None, alias="from"), to: str | None = None, all_time: int = 0, src: str = "",
                     uid: int = Depends(admin_uid)):
    """Bloklar hisoboti: kunlar, manba, blokdan oldingi oxirgi xabar, Start bosgandan blokgacha vaqt (statistika TZ, 5-band)."""
    a, b, d1, d2 = _pay_range(frm, to, all_time)
    out = await msgstats.blocks(a, b, (src if isinstance(src, str) else "")[:40])
    async with Session() as s:
        names = await _link_names(s)
    for x in out["by_source"]:
        x["label"] = source_label(x["key"], names)
    return {"from": d1.isoformat() if d1 else None, "to": d2.isoformat(), **out}


@router.get("/control")
async def control_get(uid: int = Depends(admin_uid)):
    """Nazorat guruhi: sozlama va ikki guruhning sotuv va blok foizi yonma-yon (statistika TZ, 5-band)."""
    return await msgstats.control_compare(SPEND_KINDS)


class ControlIn(BaseModel):
    on: bool | None = None
    pct: int | None = Field(None, ge=1, le=50)


@router.post("/control")
async def control_save(body: ControlIn, uid: int = Depends(admin_uid)):
    from . import control
    try:
        cfg = await control.save(body.on, body.pct)
    except ValueError as e:
        raise HTTPException(400, str(e))
    log.info("Nazorat guruhi sozlamasi o'zgardi (admin %s): yoqilgan=%s, %s%%", uid, cfg["on"], cfg["pct"])
    return await msgstats.control_compare(SPEND_KINDS)


class NudgesIn(BaseModel):
    config: dict


@router.post("/nudges")
async def nudges_save(body: NudgesIn, uid: int = Depends(admin_uid)):
    try:
        cfg = await nudges.save(body.config)
    except nudges.ConfigError as e:
        raise HTTPException(400, str(e))
    log.info("Progrev sozlamasi o'zgardi (admin %s): yoqilgan=%s", uid, cfg["on"])
    return {"ok": True, "config": cfg}


class NudgeTestIn(BaseModel):
    seq: str
    step: int = Field(ge=0, le=20)
    text: str = Field("", max_length=3500)
    button: str = Field("", max_length=40)
    target: str = "app"


@router.post("/nudges/test")
async def nudges_test(body: NudgeTestIn, uid: int = Depends(admin_uid)):
    """Adminning o'ziga namuna: oynadagi (hali saqlanmagan) matn bilan."""
    if body.seq not in nudges.SEQS or not body.text.strip():
        raise HTTPException(400, "Matnni kiriting")
    if not videobot.BOT:
        raise HTTPException(503, "Bot ishlamayapti")
    try:
        await nudges.send_test(videobot.BOT, uid, body.seq, body.step, {"text": body.text, "button": body.button, "target": body.target})
    except Exception as e:
        log.exception("Progrev namunasini yuborib bo'lmadi")
        raise HTTPException(502, f"Yuborib bo'lmadi: {e}")
    return {"ok": True}


# ---------------------------------------------------------------- CSV eksport

_NEG_NUM = re.compile(r"^-\d+(?:,\d+)?$")


def _csv(name: str, header: list[str], rows) -> Response:
    buf = io.StringIO()
    buf.write("﻿")  # Excel o'zbekcha harflarni to'g'ri ochishi uchun
    w = csv.writer(buf, delimiter=";")
    w.writerow(header)
    # foydalanuvchi kiritgan matn Excel'da formula bo'lib ishlamasin (=, +, -, @ bilan boshlansa); manfiy son (ROI −39,2) — son bo'lib qoladi
    w.writerows([[f"'{v}" if isinstance(v, str) and v[:1] in ("=", "+", "-", "@", "\t", "\r") and not _NEG_NUM.match(v) else v
                  for v in row] for row in rows])
    return Response(buf.getvalue(), media_type="text/csv; charset=utf-8",
                    headers={"Content-Disposition": f'attachment; filename="{name}"'})


def _ts(dt: datetime | None) -> str:
    return dt.replace(tzinfo=timezone.utc).astimezone(TZ).strftime("%Y-%m-%d %H:%M") if dt else ""


def _mins(sec) -> str:
    return "" if sec is None else str(round(sec / 60, 1)).replace(".", ",")


def _paystats_rows(d: dict) -> list[list]:
    """Xulosa bloklari bitta jadval ko'rinishida: bo'lim, ko'rsatkich, odamlar, to'laganlar, foiz."""
    t, rp, tm, sv = d["total"], d["repeat"], d["time"], d["survey"]
    rows = [["Jami", "To'lov oynasini ochgan odamlar", t["people"], t["paid"], t["conv"]],
            ["Jami", "Urinishlar (yozuvlar)", t["attempts"], t["paid_attempts"], pct(t["paid_attempts"], t["attempts"])],
            ["Jami", "Summa tanlash oynasini ko'rganlar", d["sheet"]["people"], "", ""],
            ["Jami", "…shundan summani tanlab, to'lov oynasini ochganlar", d["sheet"]["chose"], "", pct(d["sheet"]["chose"], d["sheet"]["people"])]]
    for name, key in (("Mahsulot", "by_product"), ("Usul", "by_method"), ("Summa", "by_amount"), ("Kun", "by_day")):
        rows += [[name, x["label"], x["people"], x["paid"], x["conv"]] for x in d[key]]
    rows.append(["To'xtagan qadam", "Usul tanlamadi", d["stops"]["none"], "", pct(d["stops"]["none"], t["people"])])
    for m, name in (("click", "To'xtagan qadam: Click"), ("card", "To'xtagan qadam: karta")):
        st = d["stops"][m]
        rows += [[name, x["label"], x["n"], "", pct(x["n"], st["people"])] for x in st["steps"]]
    rows += [["Takroriy urinishlar", x["label"], x["n"], "", pct(x["n"], t["people"])] for x in rp["dist"]]
    rows += [["Takroriy urinishlar", "Bir odamga o'rtacha urinish", str(rp["avg"]).replace(".", ","), "", ""],
             ["Takroriy urinishlar", "Bir necha marta urinib, to'lamaganlar", rp["multi_unpaid"], "", ""],
             ["To'lovgacha vaqt (daqiqa)", "O'rtacha", _mins(tm["avg_s"]), tm["n"], ""],
             ["To'lovgacha vaqt (daqiqa)", "Mediana", _mins(tm["median_s"]), tm["n"], ""],
             ["To'lovgacha vaqt (daqiqa)", "Click: mediana", _mins(tm["click"]["median_s"]), tm["click"]["n"], ""],
             ["To'lovgacha vaqt (daqiqa)", "Karta: mediana", _mins(tm["card"]["median_s"]), tm["card"]["n"], ""],
             ["Balans to'ldirib, sotib olmaganlar", "Odamlar", d["idle"]["people"], d["idle"]["payers"], pct(d["idle"]["people"], d["idle"]["payers"])],
             ["Balans to'ldirib, sotib olmaganlar", "Qoldiq balans, so'm", d["idle"]["balance"], "", ""],
             ["«Nega to'lamadingiz» so'rovi", "Yuborildi", sv["sent"], sv["answered"], sv["answer_rate"]]]
    rows += [["«Nega to'lamadingiz» so'rovi", x["label"], x["n"], "", x["pct"]] for x in sv["answers"]]
    return [[str(v).replace(".", ",") if isinstance(v, float) else v for v in row] for row in rows]  # Excel uchun o'nlik vergul


def _funnel_rows(d: dict) -> list[list]:
    rows = [[i, x["label"], x["event"], x["n"], "" if x["pct"] is None else x["pct"], x["of_first"], "" if x["lost"] is None else x["lost"],
             x["exact"], _mins((x["time"] or {}).get("avg_s")), _mins((x["time"] or {}).get("median_s")), (x["time"] or {}).get("n", ""),
             _ts(datetime.fromisoformat(x["since"])) if x["since"] else ""] for i, x in enumerate(d["steps"], 1)]
    rows += [["", f"↳ {x['label']}", x["key"], "", "", "", "", x["n"], "", "", "",
              _ts(datetime.fromisoformat(x["since"])) if x["since"] else ""] for x in d["side"]]
    rows += [["", f"Vaqt: {x['label']}", "", "", "", "", "", "", _mins(x["avg_s"]), _mins(x["median_s"]), x["n"], ""] for x in d["spans"]]
    return [[str(v).replace(".", ",") if isinstance(v, float) else v for v in row] for row in rows]


def _cell(v):
    """CSV katakchasi: bo'sh qiymat — bo'sh, o'nlik son — vergul bilan (Excel)."""
    return "" if v is None else (str(v).replace(".", ",") if isinstance(v, float) else v)


SOURCE_COLS = [("clicks", "bosish"), ("starts", "start bosgan odamlar"), ("users", "yangi odamlar"), ("app", "ilovaga kirdi"),
               ("created", "sayt/video yasadi"), ("songs", "qo'shiq tayyorladi"), ("played", "namunani eshitdi"),
               ("buy_click", "«sotib olish»ni bosdi"), ("pay_open", "to'lov oynasini ochdi"), ("bought", "sotib oldi"),
               ("conv", "konversiya, %"), ("revenue", "tushum, so'm"), ("spend", "xarajat, so'm"), ("cps", "start narxi, so'm"),
               ("cpu", "bir kishi narxi, so'm"), ("cpb", "xaridor narxi, so'm"), ("ai_cost", "AI va musiqa xarajati, so'm"),
               ("roi", "ROI, %"), ("blocked", "bloklagan"), ("block_pct", "blok foizi, %")]
COHORT_COLS = [("users", "kelgan odamlar"), ("d1", "1 kun ichida sotib oldi"), ("d1_pct", "1 kun, %"), ("d3", "3 kun ichida"),
               ("d3_pct", "3 kun, %"), ("d7", "7 kun ichida"), ("d7_pct", "7 kun, %"), ("bought", "hozirgacha sotib oldi"),
               ("bought_pct", "hozirgacha, %"), ("young", "7 kuni hali to'lmagan (yaqinda kelgan)")]


def _source_lines(d: dict) -> list[tuple]:
    """Jadval tartibida: kampaniya jami, uning havolalari; oxirida havolasiz manbalar. (tur, kampaniya, kod, nomi, video, lending, qator)."""
    by_id = {r["id"]: r for r in d["links"]}
    out = []
    for c in d["campaigns"]:
        if c["key"]:
            out.append(("Kampaniya (jami)", c["key"], "", "", "", "", c))
        out += [("Havola", c["key"], by_id[i]["code"], by_id[i]["name"], by_id[i]["video"], by_id[i]["landing"], by_id[i]) for i in c["links"]]
    out += [("Manba", "", g["key"], g["name"], "", "", g) for g in d["groups"] if g["users"]]
    return out


async def _sources_export(what: str, frm: str | None, to: str | None, all_time: int) -> Response:
    if what == "adspend":
        d1, d2 = (None, today()) if all_time else parse_range(frm, to, default_days=30)
        return _csv("reklama_xarajati.csv", ["sana", "havola kodi", "havola nomi", "summa", "valyuta", "dollar kursi", "so'mda"],
                    [[day, code, name, _cell(adstats.amount_of(amount)), adstats.CURRENCIES.get(cur, cur), rate or "", som]
                     for day, code, name, amount, cur, rate, som in await adstats.spend_export(d1, d2)])
    d = await sources_data(frm, to, all_time)
    head = ["tur", "kampaniya", "kod", "nomi", "video", "lending"]
    if what == "sourcecohort":
        return _csv("manba_kogorta.csv", head + [h for _, h in COHORT_COLS],
                    [[*line[:6], *(_cell(line[6].get(k)) for k, _ in COHORT_COLS)] for line in _source_lines(d)])
    how = {"daily": "kunlik yozuvlar", "total": "umumiy «Reklama narxi»"}
    return _csv("trafik_manbalari.csv", head + [h for _, h in SOURCE_COLS] + ["xarajat qayerdan"],
                [[*line[:6], *(_cell(line[6].get(k)) for k, _ in SOURCE_COLS), how.get(line[6].get("spend_src"), "")]
                 for line in _source_lines(d)])


@router.get("/export/{what}.csv")
async def export(what: str, frm: str | None = Query(None, alias="from"), to: str | None = None, all_time: int = 0,
                 product: str = "song", mode: str = "cohort", src: str = "", step: str = "", group: str = "", flt: str = "",
                 uid: int = Depends(admin_uid)):
    if what in ("sources", "sourcecohort", "adspend"):  # «Trafik manbalari»: davr shu bo'limdagidek (standart — 30 kun)
        return await _sources_export(what, frm, to, all_time)
    a, b, _, _ = _pay_range(frm, to, all_time, default_all=True)  # davr berilmasa — butun tarix (eski tugmalar shunday ishlaydi)
    if what in ("funnel", "funnelpeople", "nosample"):
        product, mode, src = _funnel_args(product, mode, src)
        if what == "funnel":
            return _csv(f"voronka_{product}.csv", ["#", "qadam", "hodisa", "odamlar (yetib kelgan)", "oldingi qadamdan o'tdi, %", "boshidan, %",
                                                   "tushib qoldi", "shu hodisa yozilgan odamlar", "oldingi qadamdan beri o'rtacha (daqiqa)",
                                                   "mediana (daqiqa)", "vaqt hisoblangan odamlar", "hisob boshlangan (Toshkent)"],
                        _funnel_rows(await funnel.report(product, a, b, mode, src)))
        if what == "funnelpeople":
            d = await _funnel_people(product, mode, src, step, group, a, b, limit=None)
            return _csv("voronka_odamlar.csv", ["id", "ism", "username", "manba", "qayerda to'xtadi", "qachon (Toshkent)", "bloklagan", "oxirgi faollik"],
                        [[x["id"], x["name"], x["username"], x["source"], d["label"], _ts(datetime.fromisoformat(x["at"])) if x["at"] else "",
                          "ha" if x["blocked"] else "", _ts(datetime.fromisoformat(x["last_seen"])) if x["last_seen"] else ""] for x in d["rows"]])
        d = await funnel.nosample(a, b, mode, src)
        rows = [["She'ri tayyor odamlar", "", d["lyrics"], "", ""], ["Namunasi bor", "", d["with_sample"], "", ""],
                ["Namunasiz sotib olgan", "", d["bought"], "", ""], ["Namunasiz qolganlar", "", d["none"], "", ""]]
        for g in d["groups"]:
            rows.append([g["label"], g["about"], g["n"], str(g["pct"]).replace(".", ","), g["todo"]])
            rows += [[f"↳ {x['label']}", "", x["n"], "", ""] for x in g["sub"]]
        return _csv("namunasiz_qolganlar.csv", ["guruh", "ta'rifi", "odamlar", "ulushi, %", "nima qilinadi"], rows)
    if what == "sampletime":
        d = await songflow.system(days=90)
        return _csv("namuna_vaqti.csv", ["kun", "so'raldi", "tayyor bo'ldi", "xato", "xato ulushi, %", "o'rtacha kutish (soniya)",
                                         "eng uzun kutish (soniya)", "vaqti yozilgan namunalar"],
                    [[x["day"], x["asked"], x["ready"], x["failed"], str(x["fail_pct"]).replace(".", ","), "" if x["avg_s"] is None else x["avg_s"],
                      "" if x["max_s"] is None else x["max_s"], x["timed"]] for x in d["by_day"]])
    if what == "songerrors":
        cond = [Event.kind.in_(("sample_failed", "song_failed")), Event.created_at < b]
        if a:
            cond.append(Event.created_at >= a)
        async with Session() as s:
            rows = (await s.execute(select(Event.created_at, Event.kind, Event.ref, Event.user_id, Event.meta).where(*cond)
                                    .order_by(Event.id.desc()).limit(20000))).all()
        return _csv("qoshiq_xatolari.csv", ["vaqt (Toshkent)", "turi", "qo'shiq", "foydalanuvchi", "sabab", "xato matni", "eski yozuvdan tiklangan"],
                    [[_ts(at), songflow.KIND_LABELS.get(kind, kind), ref[5:], user, songflow.REASONS.get((meta or {}).get("r"), songflow.REASONS["unknown"]),
                      (meta or {}).get("e") or "", "ha" if (meta or {}).get("bf") else ""] for at, kind, ref, user, meta in rows])
    if what == "discount":
        d = await msgstats.discount_funnel(a, b)
        return _csv("chegirma_voronkasi.csv", ["guruh", "chegirma narxi", "qadam", "odamlar", "oldingi qadamdan, %", "taklifdan, %"],
                    [[x["label"], x["price"] or "", st["label"], st["n"], _cell(st["pct"]), _cell(st["of_first"])]
                     for x in d["arms"] for st in x["steps"]])
    if what == "control":
        d = await msgstats.control_compare(SPEND_KINDS)
        return _csv("nazorat_guruhi.csv", ["guruh", "odamlar", "progrev/chegirma olgan", "sotib oldi", "sotib oldi, %", "bloklagan",
                                           "blok, %", "to'lagan pul, so'm", "bir kishiga, so'm"],
                    [[g["label"], g["users"], g["got"], g["bought"], _cell(g["bought_pct"]), g["blocked"], _cell(g["blocked_pct"]),
                      g["revenue"], g["arpu"]] for g in d["groups"]])
    if what == "blocks":
        d = await msgstats.blocks(a, b, (src if isinstance(src, str) else "")[:40])
        async with Session() as s:
            names = await _link_names(s)
        rows = [["Jami", "Hozir botni bloklab turganlar", d["blocked_now"], _cell(d["blocked_pct"])],
                ["Jami", "Shu davrda bloklagan (vaqti yozilgan)", d["in_period"], ""],
                ["Jami", "Bloklagan, vaqti noma'lum (hisob boshlanishidan oldin)", d["unknown"], ""]]
        rows += [["Kun", x["day"], x["n"], ""] for x in d["by_day"]]
        rows += [["Manba (shu davrda kelganlar)", f"{source_label(x['key'], names)} — {x['users']} kishidan", x["blocked"], _cell(x["pct"])]
                 for x in d["by_source"]]
        rows += [["Blokdan oldingi oxirgi xabar", x["label"], x["n"], _cell(x["pct"])] for x in d["last_msg"]]
        sb = d["start_to_block"]
        rows += [["Start bosgandan blokgacha", lbl, sb[k], _cell(sb[f"{k}_pct"])]
                 for k, lbl in (("h1", "1 soat ichida"), ("d1", "1 kun ichida"), ("later", "keyinroq"))]
        return _csv("bloklar.csv", ["bo'lim", "ko'rsatkich", "odamlar", "foiz"], rows)
    if what in ("msgstats", "msgskips"):
        d = await msgstats.report(a, b, (src if isinstance(src, str) else "")[:40], SPEND_KINDS)
        if what == "msgstats":
            return _csv("xabarlar_natijasi.csv", ["xabar", "kalit", "yuborildi (yetdi)", "yetmadi", "tugmani bosdi", "tugma, %",
                                                  "ilovaga qaytdi (24 soat)", "qaytdi, %", "sotib oldi (48 soat)", "sotib oldi, %",
                                                  "blokladi (24 soat)", "blok, %", "o'tkazib yuborildi"],
                        [[x["label"], x["key"], x["sent"], x["failed"], x["clicked"], _cell(x["pct"]["clicked"]), x["returned"],
                          _cell(x["pct"]["returned"]), x["bought"], _cell(x["pct"]["bought"]), x["blocked"], _cell(x["pct"]["blocked"]),
                          x["skipped"]] for x in d["rows"]])
        return _csv("otkazib_yuborilganlar.csv", ["xabar", "kalit", "holat", "sabab", "odamlar"],
                    [[x["label"], x["key"], holat, r["label"], r["n"]] for x in d["rows"]
                     for holat, items in (("o'tkazib yuborildi", x["skips"]), ("yetmadi", x["fails"])) for r in items])
    if what == "paystats":
        d = await payflow.summary(a, b, SPEND_KINDS)
        return _csv("tolov_xulosa.csv", ["bo'lim", "ko'rsatkich", "odamlar", "to'laganlar", "foiz"], _paystats_rows(d))
    if what == "payidle":
        excl = await track.excluded_ids()
        async with Session() as s:
            idle = await payflow.idle(s, a, b, excl, SPEND_KINDS, limit=None)
        return _csv("balans_toldirib_olmaganlar.csv", ["id", "ism", "username", "to'lagan", "oxirgi to'lov", "qoldiq balans"],
                    [[x["id"], x["name"], x["username"], x["paid_sum"], _ts(datetime.fromisoformat(x["last_paid_at"])) if x["last_paid_at"] else "",
                      x["balance"]] for x in idle["rows"]])
    if what == "paywhy":
        return _csv("nega_tolamadingiz.csv", ["foydalanuvchi", "ism", "username", "javob", "to'lov", "vaqt"],
                    [[x["user_id"], x["name"], x["username"], x["answer"], x["payment"], _ts(x["at"])]
                     for x in await paysurvey.answers_list(a, b)])
    async with Session() as s:
        names = await _link_names(s)
        if what == "users":
            spent = dict((await s.execute(select(BalanceTx.user_id, func.sum(-BalanceTx.amount))
                                          .where(BalanceTx.kind.in_(SPEND_KINDS)).group_by(BalanceTx.user_id))).all())
            paid = dict((await s.execute(select(Payment.user_id, func.sum(Payment.amount))
                                         .where(Payment.status == "approved").group_by(Payment.user_id))).all())
            rows = (await s.execute(select(User).where(*_user_filter(flt)).order_by(User.created_at))).scalars().all()
            nsongs = await _song_counts_all(s)
            return _csv("foydalanuvchilar.csv", ["id", "ism", "username", "til", "manba", "balans", "bonus", "to'lagan", "sarflagan",
                                                 "qo'shiqlar", "sotib olingan qo'shiqlar", "bloklagan", "qo'shilgan", "oxirgi faollik"],
                        [[u.tg_id, u.first_name, u.username, u.lang, source_label(u.ref, names), u.balance, u.bonus_videos,
                          int(paid.get(u.tg_id) or 0), int(spent.get(u.tg_id) or 0), nsongs.get(u.tg_id, (0, 0))[0],
                          nsongs.get(u.tg_id, (0, 0))[1], "ha" if u.blocked else "", _ts(u.created_at), _ts(u.last_seen)] for u in rows])
        if what == "payments":
            q = select(Payment).order_by(Payment.id)
            cond = [Payment.created_at >= a, Payment.created_at < b] if a else None
            if cond:
                q = q.where(*cond)
            rows = (await s.execute(q)).scalars().all()
            steps = await payflow.load_steps(s, cond=cond)
            excl = await track.excluded_ids()
            out = []
            for p in rows:
                d = payflow.describe(p, steps.get(p.id, {}))
                line = " → ".join(f"{x['label']} {_ts(datetime.fromisoformat(x['at']))[11:]}" for x in d["timeline"])
                out.append([p.id, p.user_id, p.amount, p.status, "ha" if p.job_id else "", _ts(p.created_at), _ts(p.decided_at),
                            p.admin_id or "", d["purpose_label"], d["method_label"], d["step_label"], _mins(d["took_s"]), line,
                            "ha" if p.user_id in excl else ""])
            return _csv("tolovlar.csv", ["id", "foydalanuvchi", "summa", "holat", "video uchun", "yaratilgan", "ko'rib chiqilgan", "admin",
                                         "nima uchun", "usul", "qaysi qadamda to'xtadi", "to'lovgacha (daqiqa)", "qadamlar (Toshkent vaqti)",
                                         "sinov akkaunt"], out)
        if what == "sites":
            rows = (await s.execute(select(Site).where(Site.kind == "site").order_by(Site.id))).scalars().all()
            return _csv("taklifnomalar.csv", ["slug", "egasi", "nomi", "shablon", "tarif", "narx", "holat", "ko'rishlar", "yaratilgan"],
                        [[x.slug, x.owner_id, site_title(x.config), x.config.get("template", ""), x.config.get("tarif", ""),
                          site_price(x.config), x.status, x.views, _ts(x.created_at)] for x in rows])
    raise HTTPException(404)


# ---------------------------------------------------------------- sahifa

@public.get("/admin", response_class=HTMLResponse)
async def admin_page():
    files = [ROOT / "templates" / "admin.html", *sorted((ROOT / "static" / "admin").glob("*"))]
    v = str(int(max((f.stat().st_mtime for f in files if f.exists()), default=0)))
    html = (ROOT / "templates" / "admin.html").read_text(encoding="utf-8").replace("__V__", v)
    return HTMLResponse(html, headers={"Cache-Control": "no-cache", "X-Robots-Tag": "noindex", "Referrer-Policy": "no-referrer"})


# ---------------------------------------------------------------- narxlar, paketlar, chegirma

@router.get("/pricing")
async def pricing_get(uid: int = Depends(admin_uid)):
    from . import pricing
    cfg = await pricing.config()
    return {**cfg, "packs_public": pricing.packs_public(cfg), "stats": await pricing.stats(), "daily": await pricing.daily(14),
            "backfill": {**await pricing.backfill_state(), **await pricing.backfill_breakdown()}, **await _sale_info(cfg)}


async def _sale_info(cfg: dict) -> dict:
    """«Narxlar» → «Aksiya»: faolmi va shu aksiyada aksiya narxida nechta kishi sotib oldi."""
    from . import pricing
    return {"sale_active": pricing.sale_of(cfg) is not None, "sale_stats": await pricing.sale_stats(cfg["sale"])}


@router.get("/pricing/sale/announce")
async def sale_announce(uid: int = Depends(admin_uid)):
    """«E'lon tayyorlash»: «Xabar yuborish» sahifasini to'ldirish uchun tayyor matn, tugma va segment. Yuborilmaydi —
    admin tekshiradi, rasm qo'shadi, «Faqat o'zim (sinov)» bilan sinaydi va o'zi yuboradi."""
    from . import pricing
    cfg = await pricing.config()
    if not pricing.sale_of(cfg):
        raise HTTPException(400, "Avval aksiyani yoqing va saqlang — e'lon faol aksiya uchun tayyorlanadi")
    return {"text": pricing.sale_announcement(cfg), "button": "song", "button_text": BC_BUTTONS["song"][0], "segment": "all"}


@router.get("/discount")
async def discount_get(frm: str | None = Query(None, alias="from"), to: str | None = None, all_time: int = 0,
                       uid: int = Depends(admin_uid)):
    """«Narxlar»: chegirma voronkasi har A/B guruhi bo'yicha (statistika TZ, 5-band)."""
    from . import pricing
    a, b, d1, d2 = _pay_range(frm, to, all_time)
    cfg = await pricing.config()
    return {"from": d1.isoformat() if d1 else None, "to": d2.isoformat(), **await msgstats.discount_funnel(a, b), "ab": cfg["ab"],
            "promo_price": cfg["promo"]["price"]}


class BackfillIn(BaseModel):
    on: bool
    batch: int | None = None


@router.post("/pricing/backfill")
async def pricing_backfill(body: BackfillIn, uid: int = Depends(admin_uid)):
    from . import pricing
    try:
        st = await pricing.backfill_set(body.on, body.batch)
    except pricing.PriceError as e:
        raise HTTPException(400, str(e))
    return {**st, **await pricing.backfill_breakdown()}


@router.post("/pricing")
async def pricing_save(body: dict, uid: int = Depends(admin_uid)):
    from . import pricing
    try:
        cfg = await pricing.save(body)
    except pricing.PriceError as e:
        raise HTTPException(400, str(e))
    return {**cfg, "packs_public": pricing.packs_public(cfg), "stats": await pricing.stats(),
            "backfill": {**await pricing.backfill_state(), **await pricing.backfill_breakdown()}, **await _sale_info(cfg)}
