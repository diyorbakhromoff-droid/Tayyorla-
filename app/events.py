"""Tadbirlar: mehmonlar ro'yxati, shaxsiy havolalar va videolar, tadbir sahifasi, kalendar fayli (.ics)."""

import logging
import re
import secrets
from datetime import date, datetime, timedelta
from urllib.parse import quote, urlencode

from fastapi import APIRouter, Header, HTTPException
from fastapi.responses import Response
from pydantic import BaseModel, Field
from sqlalchemy import select

from . import billing, i18n, video, videobot
from .catalog import TEMPLATES
from .config import settings
from .db import Guest, RenderJob, Rsvp, Session, Site, User, utcnow
from .render import env
from .webapp import check_init_data

log = logging.getLogger(__name__)
router = APIRouter()

MAX_GUESTS = 300
TZ_OFFSET = timedelta(hours=5)  # Toshkent


def new_token() -> str:
    return secrets.token_urlsafe(12)[:16]


def guest_url(site: Site, g: Guest) -> str:
    return f"{site.url}?g={g.token}"


def event_section(site: Site) -> str:
    cfg = site.config or {}
    if cfg.get("engine") == "video":
        return cfg.get("section", "toy")
    return {"toy": "toy", "tugilgan-kun": "tk"}.get(TEMPLATES.get(cfg.get("template"), {}).get("section"), "")


def event_when(site: Site) -> tuple[date | None, date | None, str]:
    cfg = site.config or {}
    data = cfg.get("data", {})
    try:
        d1 = date.fromisoformat(data.get("sana") or "")
    except ValueError:
        return None, None, ""
    try:
        d2 = date.fromisoformat(data.get("sana2") or "") if data.get("sana2") else None
    except ValueError:
        d2 = None
    return d1, d2, data.get("vaqt") or "18:00"


async def load_event(s, slug: str, uid: int) -> Site:
    site = (await s.execute(select(Site).where(Site.slug == slug))).scalar_one_or_none()
    if not site or site.owner_id != uid:
        raise HTTPException(404)
    return site


async def event_sites(s, site: Site) -> list[int]:
    """Tadbirga bog'liq saytlar: video tadbir va undan yaratilgan interaktiv sayt."""
    ids = [site.id]
    linked = (site.config or {}).get("site_slug") or (site.config or {}).get("event_slug")
    if linked:
        other = (await s.execute(select(Site.id).where(Site.slug == linked, Site.owner_id == site.owner_id))).scalar_one_or_none()
        if other:
            ids.append(other)
    return ids


async def event_stats(s, site: Site) -> dict:
    ids = await event_sites(s, site)
    guests = (await s.execute(select(Guest).where(Guest.site_id == site.id))).scalars().all()
    rsvps = (await s.execute(select(Rsvp).where(Rsvp.site_id.in_(ids)))).scalars().all()
    yes = [r for r in rsvps if r.attending]
    return {"invited": len(guests), "opened": sum(1 for g in guests if g.opened_at),
            "yes": len(yes), "people": sum(r.guests or 1 for r in yes), "no": sum(1 for r in rsvps if not r.attending)}


def event_title(site: Site) -> tuple[str, str]:
    cfg = site.config or {}
    data = cfg.get("data", {})
    sec = event_section(site)
    if cfg.get("engine") == "video":
        title = video.event_title(sec, data, "uz")
    else:
        title = TEMPLATES.get(cfg.get("template"), {}).get("name", "")
    who = " & ".join(x for x in (data.get("kuyov"), data.get("kelin")) if x) or data.get("ism") or data.get("kimga") or ""
    return title, who


# ---------------------------------------------------------------- Mini App: tadbirlar

@router.get("/api/events")
async def events_list(x_init_data: str = Header("")):
    uid = int(check_init_data(x_init_data)["id"])
    async with Session() as s:
        sites = (await s.execute(select(Site).where(Site.owner_id == uid).order_by(Site.id.desc()).limit(60))).scalars().all()
        out = []
        for site in sites:
            cfg = site.config or {}
            if site.kind == "site" and (cfg.get("event_slug") or event_section(site) != "toy"):
                continue  # video tadbirga bog'langan sayt o'sha tadbir ichida ko'rinadi
            title, who = event_title(site)
            d1, d2, vaqt = event_when(site)
            out.append({"slug": site.slug, "kind": site.kind, "section": event_section(site), "title": title, "who": who,
                        "date": d1.isoformat() if d1 else None, "date2": d2.isoformat() if d2 else None, "time": vaqt,
                        "design": cfg.get("design") or cfg.get("template"), "paid": site.paid,
                        "site_slug": cfg.get("site_slug"), "stats": await event_stats(s, site)})
    return {"events": out}


@router.get("/api/events/{slug}")
async def event_detail(slug: str, x_init_data: str = Header("")):
    uid = int(check_init_data(x_init_data)["id"])
    async with Session() as s:
        site = await load_event(s, slug, uid)
        ids = await event_sites(s, site)
        guests = (await s.execute(select(Guest).where(Guest.site_id == site.id).order_by(Guest.id))).scalars().all()
        rsvps = {r.id: r for r in (await s.execute(select(Rsvp).where(Rsvp.site_id.in_(ids)).order_by(Rsvp.id))).scalars().all()}
        jobs = {j.id: j for j in (await s.execute(select(RenderJob).where(RenderJob.site_id == site.id))).scalars().all()}
        stats = await event_stats(s, site)
    cfg = site.config or {}
    linked_rsvp = {g.rsvp_id for g in guests if g.rsvp_id}
    title, who = event_title(site)
    d1, d2, vaqt = event_when(site)

    def guest_out(g: Guest) -> dict:
        r = rsvps.get(g.rsvp_id) if g.rsvp_id else None
        j = jobs.get(g.job_id) if g.job_id else None
        status = ("yes" if r.attending else "no") if r else ("opened" if g.opened_at else "invited")
        return {"id": g.id, "name": g.name, "url": guest_url(site, g), "status": status, "people": r.guests if r and r.attending else 0,
                "note": r.note if r else "", "video": j.status if j else None}

    return {
        "slug": site.slug, "kind": site.kind, "section": event_section(site), "title": title, "who": who,
        "date": d1.isoformat() if d1 else None, "date2": d2.isoformat() if d2 else None, "time": vaqt,
        "venue": cfg.get("data", {}).get("joy") or cfg.get("data", {}).get("manzil_nomi") or "",
        "url": site.url, "ics": f"{site.url}/event.ics", "site_slug": cfg.get("site_slug"), "paid": site.paid,
        "design": cfg.get("design"), "has_video": site.kind == "video",
        "package": {"size": cfg.get("package", 0), "paid": cfg.get("package_paid", 0)},
        "packages": [{"size": n, "price": p} for n, p in settings.packages],
        "guests": [guest_out(g) for g in guests],
        "answers": [{"name": r.name, "attending": r.attending, "people": r.guests, "note": r.note}
                    for rid, r in rsvps.items() if rid not in linked_rsvp],
        "videos": [{"id": j.id, "status": j.status, "delivered": j.delivered, "charge": j.charge}
                   for j in jobs.values() if not j.guest_id],
        "stats": stats, "plain_dear": bool(cfg.get("plain_dear")),
    }


class GuestsIn(BaseModel):
    text: str = Field(max_length=20000)
    plain: bool | None = None  # «Hurmatli» so'zisiz


def parse_names(text: str) -> list[str]:
    """Har qatorda (yoki «;» bilan) bitta ism; bo'sh qatorlar tashlanadi."""
    names = []
    for line in re.split(r"[\n;]+", text or ""):
        name = " ".join(line.replace("\t", " ").split()).strip(" ,.-–")
        if name:
            names.append(name[:120])
    return names


@router.post("/api/events/{slug}/guests")
async def guests_add(slug: str, body: GuestsIn, x_init_data: str = Header("")):
    uid = int(check_init_data(x_init_data)["id"])
    names = parse_names(body.text)
    async with Session() as s:
        site = await load_event(s, slug, uid)
        seen = {g.name.lower() for g in (await s.execute(select(Guest).where(Guest.site_id == site.id))).scalars().all()}
        existing = set(seen)
        new = []
        for n in names:  # takrorlar (katta-kichik harfdan qat'i nazar) tashlanadi
            if n.lower() not in seen:
                seen.add(n.lower())
                new.append(n)
        if len(existing) + len(new) > MAX_GUESTS:
            raise HTTPException(400, f"max_guests:{MAX_GUESTS}")
        for n in new:
            s.add(Guest(site_id=site.id, name=n, token=new_token()))
        if body.plain is not None:
            site.config = {**(site.config or {}), "plain_dear": bool(body.plain)}
        await s.commit()
    return {"added": len(new), "skipped": len(names) - len(new)}


@router.delete("/api/events/{slug}/guests/{gid}")
async def guest_delete(slug: str, gid: int, x_init_data: str = Header("")):
    uid = int(check_init_data(x_init_data)["id"])
    async with Session() as s:
        site = await load_event(s, slug, uid)
        g = await s.get(Guest, gid)
        if not g or g.site_id != site.id:
            raise HTTPException(404)
        await s.delete(g)
        await s.commit()
    return {"ok": True}


@router.post("/api/events/{slug}/guest-videos")
async def guest_videos(slug: str, x_init_data: str = Header("")):
    """Har bir mehmonga ismi yozilgan video: paket narxi balansdan yechiladi."""
    uid = int(check_init_data(x_init_data)["id"])
    async with Session() as s:
        site = await load_event(s, slug, uid)
        cfg = dict(site.config or {})
        if site.kind != "video" or not cfg.get("design"):
            raise HTTPException(400, "need_video")
        guests = (await s.execute(select(Guest).where(Guest.site_id == site.id).order_by(Guest.id))).scalars().all()
        if not guests:
            raise HTTPException(400, "no_guests")
        done_jobs = {j.guest_id for j in (await s.execute(select(RenderJob).where(
            RenderJob.site_id == site.id, RenderJob.guest_id.is_not(None), RenderJob.status.in_(("queued", "rendering", "done"))))).scalars().all()}
        todo = [g for g in guests if g.id not in done_jobs]
        if not todo:
            return {"queued": 0}
        cost = billing.package_cost(len(guests), cfg.get("package_paid", 0))
        if not cost:
            raise HTTPException(400, f"max_guests:{MAX_GUESTS}")
        size, price = cost
        if price and not await billing.spend(s, uid, price, "package", f"site:{slug}"):
            user = await s.get(User, uid)
            raise HTTPException(402, {"code": "paywall", "need": price, "package": size, "balance": user.balance if user else 0,
                                      "topups": settings.topups})
        cfg["package"] = size
        cfg["package_paid"] = cfg.get("package_paid", 0) + price
        site.config = cfg
        lang, data, music = cfg.get("lang", "uz"), cfg.get("data", {}), cfg.get("music")
        jobs = []
        for g in todo:
            page = video.build_payload(cfg["design"], data, lang, guest=g.name, free=False, site_url=guest_url(site, g),
                                       palette=cfg.get("palette", 0), plain_dear=bool(cfg.get("plain_dear")))
            j = RenderJob(owner_id=uid, site_id=site.id, guest_id=g.id, design=cfg["design"], lang=lang, charge="package",
                          payload={"page": page, "music": music, "guest": g.name}, hash=video.render_hash(page, music))
            s.add(j)
            jobs.append(j)
        await s.flush()
        await s.commit()
    bot = videobot.BOT
    if bot:
        lang_ui = await videobot.user_lang(uid)
        from .i18n import tr
        try:
            msg = await bot.send_message(uid, tr(lang_ui, "bot.guests_progress", done=0, total=len(jobs)))
            async with Session() as s:
                for j in jobs:
                    db_j = await s.get(RenderJob, j.id)
                    db_j.status_msg_id = msg.message_id
                await s.commit()
        except Exception:
            log.exception("Mehmon videolari xabarini yuborib bo'lmadi")
    return {"queued": len(jobs), "package": size, "charged": price}


# ---------------------------------------------------------------- tadbir sahifasi (mehmon ochadi)

def _utc(d: date, hhmm: str) -> datetime:
    h, m = (int(x) for x in (hhmm or "18:00").split(":")[:2])
    return datetime(d.year, d.month, d.day, h, m) - TZ_OFFSET


def calendar_links(site: Site, title: str, place: str, details: str) -> dict:
    d1, d2, vaqt = event_when(site)
    if not d1:
        return {}
    start = _utc(d1, vaqt)
    end = _utc(d2 or d1, vaqt) + timedelta(hours=4)
    fmt = "%Y%m%dT%H%M%SZ"
    q = urlencode({"action": "TEMPLATE", "text": title, "dates": f"{start.strftime(fmt)}/{end.strftime(fmt)}",
                   "location": place, "details": details}, quote_via=quote)
    return {"google": f"https://calendar.google.com/calendar/render?{q}", "ics": f"{site.url}/event.ics",
            "target": (d1.isoformat() + "T" + vaqt + ":00+05:00")}


def render_event_page(site: Site, guest: Guest | None) -> str:
    cfg = site.config or {}
    design_id = cfg.get("design")
    d = video.DESIGNS.get(design_id) or next(iter(video.DESIGNS.values()))
    lang = cfg.get("lang", "uz")
    payload = video.build_payload(d["id"], cfg.get("data", {}), lang, guest=guest.name if guest else None, free=True,
                                  site_url=site.url, palette=cfg.get("palette", 0), plain_dear=bool(cfg.get("plain_dear")))
    t, f = payload["t"], payload["f"]
    L = i18n.card(payload["lang"])
    title = f"{t['event']} — {t['names_line']}" if t["names_line"] != t["event"] else t["event"]
    place = ", ".join(x for x in (t["venue"], t["address"]) if x)
    cal = calendar_links(site, title, place, f"{t['message']}\n{site.url}".strip())
    fonts = d.get("fonts") or {"display": "Cormorant Garamond", "body": "Onest", "italic": True}
    return env.get_template("event.html").render(
        site=site, t=t, f=f, L=L, P=L["page"], vars=payload["vars"], fonts=fonts, lang=payload["html_lang"],
        cal=cal, map=payload["map"], guest=guest, rsvp_url=f"/s/{site.slug}/rsvp", bot=settings.bot_username,
        section=payload["section"], title=title)


def _ics_text(s: str) -> str:
    return (s or "").replace("\\", "\\\\").replace(";", "\\;").replace(",", "\\,").replace("\n", "\\n")


@router.get("/s/{slug}/event.ics")
async def event_ics(slug: str):
    async with Session() as s:
        site = (await s.execute(select(Site).where(Site.slug == slug))).scalar_one_or_none()
    if not site:
        raise HTTPException(404)
    cfg = site.config or {}
    data = cfg.get("data", {})
    d1, d2, vaqt = event_when(site)
    if not d1:
        raise HTTPException(404)
    title, who = event_title(site)
    summary = f"{title} — {who}" if who else title
    place = ", ".join(x for x in (data.get("joy") or data.get("manzil_nomi"), data.get("manzil")) if x)
    stamp = utcnow().strftime("%Y%m%dT%H%M%SZ")
    days = [d1] + ([d2] if d2 else [])
    lines = ["BEGIN:VCALENDAR", "VERSION:2.0", "PRODID:-//Tayyorla//Taklifnoma//UZ", "CALSCALE:GREGORIAN", "METHOD:PUBLISH"]
    for i, day in enumerate(days):
        start = _utc(day, vaqt)
        end = start + timedelta(hours=4)
        lines += ["BEGIN:VEVENT", f"UID:{slug}-{i + 1}@tayyorla", f"DTSTAMP:{stamp}",
                  f"DTSTART:{start.strftime('%Y%m%dT%H%M%SZ')}", f"DTEND:{end.strftime('%Y%m%dT%H%M%SZ')}",
                  f"SUMMARY:{_ics_text(summary)}", f"LOCATION:{_ics_text(place)}",
                  f"DESCRIPTION:{_ics_text((data.get('matn') or '') + chr(10) + site.url)}", f"URL:{site.url}",
                  "BEGIN:VALARM", "TRIGGER:-PT3H", "ACTION:DISPLAY", f"DESCRIPTION:{_ics_text(summary)}", "END:VALARM",
                  "END:VEVENT"]
    lines.append("END:VCALENDAR")
    body = "\r\n".join(lines) + "\r\n"
    return Response(body, media_type="text/calendar; charset=utf-8",
                    headers={"Content-Disposition": 'inline; filename="taklifnoma.ics"'})


async def find_guest(s, site: Site, token: str | None) -> Guest | None:
    """Shaxsiy havola tokeni: video tadbirdagi mehmon (sayt bog'langan bo'lsa ham)."""
    if not token or not re.fullmatch(r"[\w-]{8,32}", token):
        return None
    g = (await s.execute(select(Guest).where(Guest.token == token))).scalar_one_or_none()
    if not g:
        return None
    if g.site_id == site.id:
        return g
    event_slug = (site.config or {}).get("event_slug")
    if event_slug:
        ev = (await s.execute(select(Site).where(Site.slug == event_slug))).scalar_one_or_none()
        if ev and ev.id == g.site_id and ev.owner_id == site.owner_id:
            return g
    return None


async def mark_opened(s, g: Guest | None) -> None:
    if g and not g.opened_at:
        g.opened_at = utcnow()
        await s.commit()

