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
from collections import Counter, defaultdict
from datetime import date, datetime, time, timedelta, timezone

from fastapi import APIRouter, Depends, Header, HTTPException, Query, Request
from fastapi.responses import HTMLResponse, RedirectResponse, Response
from pydantic import BaseModel, Field
from sqlalchemy import func, select, update

from . import track, video, videobot
from .catalog import SECTIONS, TEMPLATES, site_price, site_title
from .config import MEDIA_DIR, ROOT, settings
from . import nudges, songs, store
from .db import BalanceTx, Event, MusicTrack, Payment, RenderJob, Session, Site, Snapshot, Song, TrafficLink, User, utcnow
from .reminders import TZ, today
from .webapp import check_init_data

log = logging.getLogger(__name__)
router = APIRouter(prefix="/api/admin")
public = APIRouter()
STARTED = _time.time()

SPEND_KINDS = ("site", "upgrade", "video", "package", "song")
VIDEO_SECTIONS = {"toy": "To'y", "osh": "Osh", "gap": "Gap", "choy": "Choyxona", "tk": "Tug'ilgan kun"}
TIER_NAMES = {"standart": "Standart", "premium": "Premium", "vip": "VIP"}
SOURCE_GROUPS = {"": "Organik (to'g'ridan-to'g'ri)", "ref_": "Do'st taklifi (referal)", "r_": "Tabrik sahifasidan",
                 "other": "Boshqa havolalar"}
# Telegram/ijtimoiy tarmoqlar havola ko'rinishini (preview) olayotganda bosish sanalmaydi
BOT_UA = re.compile(r"bot|crawler|spider|preview|facebookexternalhit|whatsapp|slurp|curl|python", re.I)


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
async def whoami(uid: int = Depends(admin_uid)):
    """Panel ochilganda: kim kirdi va yuklab olish havolalari uchun qisqa muddatli kalit."""
    async with Session() as s:
        u = await s.get(User, uid)
    return {"id": uid, "name": u.first_name if u else "", "token": make_token(uid, hours=6), "bot": settings.bot_username,
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
    return {"app": app, "creators": site_owners | job_owners, "buyers": spenders | paid_sites | payers, "payers": payers}


async def collect(a: datetime, b: datetime, days: list[date] | None = None) -> dict:
    """[a, b) oralig'idagi ko'rsatkichlar; days berilsa kunlik qatorlar ham."""
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
            "failed": sum(1 for r in song_rows if r[3] == "failed"),
        },
        "money": {
            "topup": topup, "topups": len(pays), "payers": len(payers),
            "new_payers": sum(1 for uid, d in first_pay.items() if d and a <= d < b),
            "avg_check": round(topup / len(pays)) if pays else 0,
            "spent": sum(-t[1] for t in spend), "buyers": len({t[0] for t in spend}),
            "refunds": by_kind["refund"][1], "admin": by_kind["admin"][1] + by_kind["bonus"][1],
        },
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


@router.get("/sources")
async def sources(frm: str | None = Query(None, alias="from"), to: str | None = None, all_time: int = 0,
                  archived: int = 0, uid: int = Depends(admin_uid)):
    """Har bir manba bo'yicha: bosishlar, start, yangi foydalanuvchilar, ilovaga kirgan, yasagan, to'lagan, tushum."""
    if all_time:
        d1, d2 = date(2000, 1, 1), today()
    else:
        d1, d2 = parse_range(frm, to, default_days=30)
    a, b = utc_of(d1), utc_of(d2 + timedelta(days=1))
    async with Session() as s:
        links = (await s.execute(select(TrafficLink).order_by(TrafficLink.id.desc()))).scalars().all()
        users = (await s.execute(select(User.tg_id, User.ref).where(User.created_at >= a, User.created_at < b))).all()
        ev = (await s.execute(select(Event.kind, Event.src, Event.user_id).where(
            Event.created_at >= a, Event.created_at < b, Event.kind.in_(("click", "start")),
            Event.src.like("src_%") | (Event.kind == "click")))).all()
        ever = await _sets(s)
        paid_by = dict((await s.execute(select(Payment.user_id, func.sum(Payment.amount))
                                        .where(Payment.status == "approved").group_by(Payment.user_id))).all())
        spent_by = dict((await s.execute(select(BalanceTx.user_id, func.sum(-BalanceTx.amount))
                                         .where(BalanceTx.kind.in_(SPEND_KINDS)).group_by(BalanceTx.user_id))).all())
    names = {x.code: x.name for x in links}
    clicks = Counter(src for k, src, _ in ev if k == "click")
    starts = defaultdict(set)
    for k, src, u in ev:
        if k == "start" and u:
            starts[src[4:].lower()].add(u)
    groups = defaultdict(list)
    for tg_id, ref in users:
        groups[source_key(ref)].append(tg_id)

    def metrics(ids: list[int]) -> dict:
        ids = set(ids)
        bought = ids & ever["buyers"]
        return {"users": len(ids), "app": len(ids & ever["app"]), "created": len(ids & ever["creators"]),
                "bought": len(bought), "revenue": int(sum(paid_by.get(i, 0) or 0 for i in ids)),
                "spent": int(sum(spent_by.get(i, 0) or 0 for i in ids)), "conv": pct(len(bought), len(ids))}

    rows = []
    for x in links:
        if x.archived and not archived:
            continue
        m = metrics(groups.pop(f"src_{x.code}", []))
        m.update(clicks=clicks.get(x.code, 0), starts=len(starts.get(x.code, ())))
        cost = x.cost or 0
        m.update(cpu=round(cost / m["users"]) if cost and m["users"] else None,
                 cpb=round(cost / m["bought"]) if cost and m["bought"] else None,
                 roi=round(100 * (m["revenue"] - cost) / cost, 1) if cost else None)
        rows.append({"id": x.id, "code": x.code, "name": x.name, "note": x.note, "cost": cost, "archived": x.archived,
                     "share_pct": x.share_pct or 0, "created_at": x.created_at.isoformat() if x.created_at else None,
                     "urls": link_urls(x.code, x.share), **m})
    other = []
    for key in ("", "ref_", "r_", "other"):
        other.append({"key": key or "organic", "name": SOURCE_GROUPS[key], **metrics(groups.pop(key, []))})
    for key, ids in groups.items():  # o'chirilgan yoki noma'lum havolalar
        other.append({"key": key, "name": f"Havola: {key[4:]}", **metrics(ids)})
    return {"from": d1.isoformat() if not all_time else None, "to": d2.isoformat(), "links": rows, "groups": other}


@router.post("/links")
async def link_create(body: LinkIn, uid: int = Depends(admin_uid)):
    code = (body.code or "").strip().lower() or _slug(body.name) or secrets.token_hex(3)
    if not track.CODE_RE.match(code):
        raise HTTPException(400, "Kod faqat lotin harflari, raqam va _ dan iborat bo'lsin (2–24 belgi)")
    async with Session() as s:
        base, i = code, 2
        while await s.scalar(select(TrafficLink.id).where(TrafficLink.code == code)):
            if body.code:
                raise HTTPException(409, "Bu kod band, boshqasini tanlang")
            code = f"{base[:20]}_{i}"
            i += 1
        x = TrafficLink(code=code, name=body.name.strip(), cost=body.cost, note=body.note.strip(), created_by=uid)
        s.add(x)
        await s.commit()
    return {"id": x.id, "code": x.code, "urls": link_urls(x.code)}


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
            "created": len(site_owners | job_owners), "bought": bought, "conv": pct(bought, n),
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
             ("Yasadi", r["created"], "taklifnoma yoki video"), ("Sotib oldi", r["bought"], f"konversiya {r['conv']}%")]
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


@router.get("/payments")
async def payments(status: str = "pending", limit: int = Query(100, le=500), uid: int = Depends(admin_uid)):
    async with Session() as s:
        q = select(Payment).order_by(Payment.id.desc()).limit(limit)
        if status != "all":
            q = q.where(Payment.status == status)
        rows = (await s.execute(q)).scalars().all()
        users = await _user_map(s, [p.user_id for p in rows] + [p.admin_id for p in rows])
    out = []
    for p in rows:
        u = users.get(p.user_id)
        a = users.get(p.admin_id) if p.admin_id else None
        out.append({"id": p.id, "user_id": p.user_id, "name": u.first_name if u else "", "username": u.username if u else "",
                    "amount": p.amount, "status": p.status, "for_video": bool(p.job_id), "receipt": bool(p.receipt),
                    "provider": p.provider or "", "ext_id": p.ext_id or "",
                    "admin": (a.first_name if a else p.admin_id) if p.admin_id else None,
                    "created_at": p.created_at.isoformat() if p.created_at else None,
                    "decided_at": p.decided_at.isoformat() if p.decided_at else None})
    return {"payments": out}


class Decision(BaseModel):
    approve: bool


@router.post("/payments/{pid}")
async def payment_decide(pid: int, body: Decision, uid: int = Depends(admin_uid)):
    if not videobot.BOT:
        raise HTTPException(503, "Bot ishlamayapti")
    from .bot.money import decide_payment
    res = await decide_payment(videobot.BOT, pid, body.approve, uid)
    if res == "not_found":
        raise HTTPException(404)
    return {"ok": res == "ok", "already": res == "done"}


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


@router.get("/users")
async def users_list(q: str = "", sort: str = "new", page: int = Query(0, ge=0), uid: int = Depends(admin_uid)):
    size = 50
    async with Session() as s:
        stmt = select(User)
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
        names = await _link_names(s)
    return {"total": total, "page": page, "size": size,
            "users": [{**_user_out(u, names), "spent": int(spent.get(u.tg_id) or 0), "sites": nsites.get(u.tg_id, 0),
                       "videos": nvid.get(u.tg_id, 0)} for u in rows]}


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
    return {
        "user": _user_out(u, names), "invited": invited or 0,
        "sites": [{"slug": x.slug, "kind": x.kind, "title": site_title(x.config), "status": x.status, "views": x.views,
                   "tier": TIER_NAMES.get(x.config.get("tarif"), ""), "price": site_price(x.config) if x.kind == "site" else 0,
                   "url": x.url, "created_at": x.created_at.isoformat() if x.created_at else None} for x in sites],
        "videos": [{"charge": c, "status": st, "n": n} for c, st, n in jobs],
        "payments": [{"id": p.id, "amount": p.amount, "status": p.status, "created_at": p.created_at.isoformat() if p.created_at else None}
                     for p in pays],
        "tx": [{"amount": t.amount, "kind": t.kind, "ref": t.ref, "created_at": t.created_at.isoformat() if t.created_at else None}
               for t in txs],
        "activity": [{"kind": k, "last": d.isoformat() if d else None, "n": n} for k, d, n in last],
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
    button: bool = True


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
    if body.segment not in SEGMENTS or not body.text.strip():
        raise HTTPException(400, "Segment va matnni kiriting")
    if BROADCAST.get("running"):
        raise HTTPException(409, "Avvalgi tarqatma hali tugamagan")
    if not videobot.BOT:
        raise HTTPException(503, "Bot ishlamayapti")
    ids = await segment_ids(body.segment, body.code, uid)
    BROADCAST.clear()
    BROADCAST.update(running=True, total=len(ids), sent=0, failed=0, blocked=0, segment=SEGMENTS[body.segment],
                     started=utcnow().isoformat(), by=uid)
    asyncio.create_task(_run_broadcast(ids, body.text.strip(), body.button))
    return {"ok": True, "total": len(ids)}


async def _run_broadcast(ids: list[int], text: str, button: bool) -> None:
    from aiogram.exceptions import TelegramForbiddenError, TelegramRetryAfter
    from aiogram.types import InlineKeyboardButton, InlineKeyboardMarkup, WebAppInfo
    bot = videobot.BOT
    markup = None
    if button and settings.base_url.startswith("https://"):
        markup = InlineKeyboardMarkup(inline_keyboard=[[InlineKeyboardButton(text="✨ Ilovani ochish", web_app=WebAppInfo(url=f"{settings.base_url}/app"))]])
    blocked = []
    try:
        for uid in ids:
            for attempt in range(2):
                try:
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
            async with Session() as s:
                await s.execute(update(User).where(User.tg_id.in_(blocked)).values(blocked=True))
                await s.commit()
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
        "songs": {"on": settings.songs_on, "price": settings.song_price, "daily_previews": per_day, "per_user": per_user,
                  "previews_today": pv_today, "credits": await songs.credits(), "alert": settings.song_credit_alert},
    }


class SongLimitsIn(BaseModel):
    per_user: int = Field(ge=0, le=20)     # bir kishiga kuniga bepul namuna
    per_day: int = Field(ge=0, le=100_000)  # hamma uchun kuniga jami (0 — cheklovsiz)


@router.post("/song-limits")
async def song_limits(body: SongLimitsIn, uid: int = Depends(admin_uid)):
    await store.put("song_limits", {"per_user": body.per_user, "per_day": body.per_day})
    log.info("Qo'shiq namunasi limiti o'zgardi: kishiga %s, jami %s (admin %s)", body.per_user, body.per_day, uid)
    return {"ok": True, "per_user": body.per_user, "per_day": body.per_day}


# ---------------------------------------------------------------- progrev (eslatma xabarlari ketma-ketligi)

def _nudge_meta() -> dict:
    return {"seqs": [{"key": k, "name": nudges.SEQ_NAMES[k]} for k in nudges.SEQS],
            "targets": [{"key": k, "name": v} for k, v in nudges.TARGETS.items()],
            "placeholders": [{"key": k, "name": v} for k, v in nudges.PLACEHOLDERS.items()],
            "max_steps": nudges.MAX_STEPS, "grace_hours": nudges.GRACE_H, "defaults": nudges.DEFAULTS}


@router.get("/nudges")
async def nudges_get(uid: int = Depends(admin_uid)):
    return {"config": await nudges.config(), "stats": await nudges.stats(), **_nudge_meta()}


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

def _csv(name: str, header: list[str], rows) -> Response:
    buf = io.StringIO()
    buf.write("﻿")  # Excel o'zbekcha harflarni to'g'ri ochishi uchun
    w = csv.writer(buf, delimiter=";")
    w.writerow(header)
    w.writerows(rows)
    return Response(buf.getvalue(), media_type="text/csv; charset=utf-8",
                    headers={"Content-Disposition": f'attachment; filename="{name}"'})


def _ts(dt: datetime | None) -> str:
    return dt.replace(tzinfo=timezone.utc).astimezone(TZ).strftime("%Y-%m-%d %H:%M") if dt else ""


@router.get("/export/{what}.csv")
async def export(what: str, uid: int = Depends(admin_uid)):
    async with Session() as s:
        names = await _link_names(s)
        if what == "users":
            spent = dict((await s.execute(select(BalanceTx.user_id, func.sum(-BalanceTx.amount))
                                          .where(BalanceTx.kind.in_(SPEND_KINDS)).group_by(BalanceTx.user_id))).all())
            paid = dict((await s.execute(select(Payment.user_id, func.sum(Payment.amount))
                                         .where(Payment.status == "approved").group_by(Payment.user_id))).all())
            rows = (await s.execute(select(User).order_by(User.created_at))).scalars().all()
            return _csv("foydalanuvchilar.csv", ["id", "ism", "username", "til", "manba", "balans", "bonus", "to'lagan", "sarflagan",
                                                 "bloklagan", "qo'shilgan", "oxirgi faollik"],
                        [[u.tg_id, u.first_name, u.username, u.lang, source_label(u.ref, names), u.balance, u.bonus_videos,
                          int(paid.get(u.tg_id) or 0), int(spent.get(u.tg_id) or 0), "ha" if u.blocked else "",
                          _ts(u.created_at), _ts(u.last_seen)] for u in rows])
        if what == "payments":
            rows = (await s.execute(select(Payment).order_by(Payment.id))).scalars().all()
            return _csv("tolovlar.csv", ["id", "foydalanuvchi", "summa", "holat", "video uchun", "yaratilgan", "ko'rib chiqilgan", "admin"],
                        [[p.id, p.user_id, p.amount, p.status, "ha" if p.job_id else "", _ts(p.created_at), _ts(p.decided_at),
                          p.admin_id or ""] for p in rows])
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
