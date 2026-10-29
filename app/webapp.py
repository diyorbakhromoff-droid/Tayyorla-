"""Telegram Mini App: forma orqali sayt yaratish uchun API."""

import calendar
import hashlib
import hmac
import io
import json
import logging
import time
import uuid
from collections import defaultdict, deque
from types import SimpleNamespace
from urllib.parse import parse_qsl

from fastapi import APIRouter, File, Header, HTTPException, UploadFile
from fastapi.responses import HTMLResponse
from PIL import Image, ImageOps
from pydantic import BaseModel, Field

from . import ai
from sqlalchemy import delete, func, select

from . import billing, i18n, reminders
from .catalog import RELATIONS, TEMPLATES, catalog_meta, clean_order, render_catalog, site_price, site_title
from .config import MEDIA_DIR, ROOT, settings
from .db import Person, Reaction, ReminderLog, RenderJob, Session, Site, UserProfile, new_slug
from .surprise import owner_url, recipient_name
from .render import parse_date, render_site
from .sites import CATEGORIES, PALETTES, build_config

log = logging.getLogger(__name__)
router = APIRouter()

# main.py da o'rnatiladi: sayt yaratilganda egasiga botda xabar yuborish uchun
on_created = None
on_referral = None  # (taklif qilgan odam id, yangi do'st ismi)

MAX_PHOTO = 15 * 1024 * 1024
MAX_AUDIO = 20 * 1024 * 1024
AI_LIMIT = 15  # bir soatda bitta foydalanuvchi uchun AI matn so'rovlari
_ai_calls: dict[int, deque] = defaultdict(deque)


# ---------------------------------------------------------------- Telegram foydalanuvchisini tekshirish

def check_init_data(init_data: str, max_age: int = 24 * 3600) -> dict:
    """Telegram WebApp initData imzosini tekshiradi va foydalanuvchini qaytaradi."""
    if not init_data:
        raise HTTPException(401, "Telegram orqali oching")
    pairs = dict(parse_qsl(init_data, keep_blank_values=True))
    received = pairs.pop("hash", "")
    check_string = "\n".join(f"{k}={v}" for k, v in sorted(pairs.items()))
    secret = hmac.new(b"WebAppData", settings.bot_token.encode(), hashlib.sha256).digest()
    expected = hmac.new(secret, check_string.encode(), hashlib.sha256).hexdigest()
    if not hmac.compare_digest(expected, received):
        raise HTTPException(401, "Noto'g'ri imzo")
    if time.time() - int(pairs.get("auth_date", 0)) > max_age:
        raise HTTPException(401, "Sessiya eskirgan, ilovani qayta oching")
    return json.loads(pairs.get("user", "{}"))


def _rate_limit(user: dict) -> None:
    calls = _ai_calls[user.get("id", 0)]
    now = time.time()
    while calls and now - calls[0] > 3600:
        calls.popleft()
    if len(calls) >= AI_LIMIT:
        raise HTTPException(429, "Juda ko'p so'rov. Birozdan so'ng urinib ko'ring.")
    calls.append(now)


# ---------------------------------------------------------------- ma'lumotlarni tozalash

class SiteIn(BaseModel):
    category: str
    answers: dict = Field(default_factory=dict)


def clean_answers(category: str, raw: dict, strict: bool) -> dict:
    """Formadan kelgan javoblarni faqat ruxsat etilgan, tekshirilgan qiymatlarga keltiradi."""
    cat = CATEGORIES.get(category)
    if not cat:
        raise HTTPException(400, "Noma'lum kategoriya")
    out: dict = {}
    for step in cat.steps:
        v = raw.get(step.key)
        if step.kind == "photos":
            out["photos"] = [p for p in (v or []) if isinstance(p, str) and _own_media(p)][:10]
        elif step.kind == "music":
            out["music"] = v if isinstance(v, str) and _own_media(v) else None
        elif step.kind == "palette":
            out["palette"] = v if v in PALETTES else cat.default_palette
        elif step.kind == "features":
            out["features"] = [k for k in (v if isinstance(v, list) else cat.default_features) if k in cat.features]
        elif step.kind == "choice":
            out[step.key] = v if v in (step.options or {}) else None
        else:
            text = str(v).strip() if v not in (None, "") else ""
            limit = 3000 if step.kind == "message" else 1000 if step.key == "promises" else 300
            out[step.key] = text[:limit] or None
            if step.kind == "date" and text and not parse_date(text):
                raise HTTPException(400, f"Sana noto'g'ri: {text}")
        if strict and not step.optional and step.kind not in ("photos", "music", "palette", "features") and not out.get(step.key):
            raise HTTPException(400, f"To'ldirilmagan: {step.prompt.splitlines()[0]}")
    return out


def _own_media(path: str) -> bool:
    name = path.removeprefix("/media/")
    return path.startswith("/media/") and "/" not in name and (MEDIA_DIR / name).is_file()


# ---------------------------------------------------------------- sahifalar va API

APP_FILES = [ROOT / "templates" / "webapp.html", *sorted((ROOT / "static" / "app").glob("*")), *sorted((ROOT / "static" / "i18n").glob("*.json"))]


def app_version() -> str:
    """Mini App fayllari o'zgarsa Telegram keshidagi eski JS/CSS yangilanadi."""
    return str(int(max((f.stat().st_mtime for f in APP_FILES if f.exists()), default=0)))


@router.get("/app", response_class=HTMLResponse)
async def app_page():
    html = (ROOT / "templates" / "webapp.html").read_text(encoding="utf-8")
    return HTMLResponse(html.replace("__V__", app_version()), headers={"Cache-Control": "no-cache"})


@router.get("/api/categories")
async def categories():
    return {
        "categories": [
            {
                "key": c.key,
                "title": c.title,
                "intro": c.intro,
                "subtitle": c.subtitle,
                "steps": [{"key": s.key, "prompt": s.label or s.prompt, "kind": s.kind, "optional": s.optional, "options": s.options} for s in c.steps],
                "features": c.features,
                "default_features": c.default_features,
                "default_palette": c.default_palette,
            }
            for c in CATEGORIES.values()
        ],
        "palettes": PALETTES,
        "price": settings.price,
    }


@router.post("/api/upload")
async def upload(file: UploadFile = File(...), kind: str = "photo", x_init_data: str = Header("")):
    check_init_data(x_init_data)
    data = await file.read()
    if kind == "photo":
        if len(data) > MAX_PHOTO:
            raise HTTPException(413, "Rasm juda katta (15 MB gacha)")
        try:
            img = ImageOps.exif_transpose(Image.open(io.BytesIO(data))).convert("RGB")
        except Exception:
            raise HTTPException(400, "Bu rasm fayli emas")
        img.thumbnail((1600, 1600))
        name = f"{uuid.uuid4().hex}.jpg"
        img.save(MEDIA_DIR / name, "JPEG", quality=85, optimize=True)
    elif kind == "music":
        if len(data) > MAX_AUDIO:
            raise HTTPException(413, "Fayl juda katta (20 MB gacha)")
        ctype = file.content_type or ""
        ext = {"audio/mpeg": "mp3", "audio/mp3": "mp3", "audio/mp4": "m4a", "audio/x-m4a": "m4a", "audio/aac": "aac", "audio/ogg": "ogg", "audio/wav": "wav", "audio/x-wav": "wav"}.get(ctype)
        if not ext:
            raise HTTPException(400, "Bu audio fayl emas (mp3 yuboring)")
        name = f"{uuid.uuid4().hex}.{ext}"
        (MEDIA_DIR / name).write_bytes(data)
    else:
        raise HTTPException(400)
    return {"url": f"/media/{name}"}


class WriteIn(SiteIn):
    brief: str = Field(default="", max_length=1000)
    previous: str | None = Field(default=None, max_length=3000)


@router.post("/api/ai/write")
async def ai_write(body: WriteIn, x_init_data: str = Header("")):
    user = check_init_data(x_init_data)
    _rate_limit(user)
    answers = clean_answers(body.category, body.answers, strict=False)
    try:
        text = await ai.write_message(body.category, answers, body.brief, body.previous)
    except Exception:
        log.exception("Mini App: AI matn yozishda xato")
        raise HTTPException(502, "Hozir matn yozib bo'lmadi, qayta urinib ko'ring")
    return {"text": text}


@router.post("/api/preview", response_class=HTMLResponse)
async def preview(body: SiteIn, x_init_data: str = Header("")):
    check_init_data(x_init_data)
    cfg = build_config(body.category, clean_answers(body.category, body.answers, strict=False))
    return render_site(SimpleNamespace(slug="preview", config=cfg), preview=True)


@router.post("/api/sites")
async def create_site(body: SiteIn, x_init_data: str = Header("")):
    user = check_init_data(x_init_data)
    cfg = build_config(body.category, clean_answers(body.category, body.answers, strict=True))
    name = " ".join(filter(None, [user.get("first_name"), user.get("last_name")]))
    async with Session() as s:
        site = Site(slug=new_slug(), owner_id=int(user["id"]), owner_name=name, category=body.category, config=cfg)
        s.add(site)
        await s.commit()
    if on_created:
        await on_created(site)
    return {"url": site.url, "id": site.id}


# ---------------------------------------------------------------- tayyor shablonlar katalogi

class OrderIn(BaseModel):
    template: str
    tarif: str = "premium"
    rang: int = 1
    data: dict = Field(default_factory=dict)
    photos: list = Field(default_factory=list)
    music: str | None = None
    unlock_at: str | None = None
    event: str | None = None  # video tadbirdan yaratilayotgan sayt


@router.get("/api/catalog")
async def catalog():
    return catalog_meta()


@router.post("/api/catalog/preview", response_class=HTMLResponse)
async def catalog_preview(body: OrderIn, x_init_data: str = Header("")):
    check_init_data(x_init_data)
    return render_catalog(clean_order(body.model_dump(), strict=False), "preview", preview=True)


class CatalogWriteIn(BaseModel):
    template: str
    data: dict = Field(default_factory=dict)
    brief: str = Field(default="", max_length=1000)
    previous: str | None = Field(default=None, max_length=3000)


@router.post("/api/catalog/ai/write")
async def catalog_ai_write(body: CatalogWriteIn, x_init_data: str = Header("")):
    user = check_init_data(x_init_data)
    if body.template not in TEMPLATES:
        raise HTTPException(400, "Noma'lum shablon")
    _rate_limit(user)
    order = clean_order({"template": body.template, "tarif": "vip", "data": body.data}, strict=False)
    try:
        text = await ai.write_message(order["category"], order["data"], body.brief, body.previous)
    except Exception:
        log.exception("Mini App: AI matn yozishda xato")
        raise HTTPException(502, "Hozir matn yozib bo'lmadi, qayta urinib ko'ring")
    return {"text": text}


@router.post("/api/catalog/sites")
async def catalog_create(body: OrderIn, x_init_data: str = Header("")):
    user = check_init_data(x_init_data)
    cfg = clean_order(body.model_dump(), strict=True)
    name = " ".join(filter(None, [user.get("first_name"), user.get("last_name")]))
    async with Session() as s:
        event = None
        if body.event:
            event = (await s.execute(select(Site).where(Site.slug == body.event))).scalar_one_or_none()
            if not event or event.owner_id != int(user["id"]) or event.kind != "video":
                event = None
        if event:
            cfg["event_slug"] = event.slug
        site = Site(slug=new_slug(), owner_id=int(user["id"]), owner_name=name, category=cfg["category"], config=cfg)
        s.add(site)
        await s.flush()
        if event:
            event.config = {**event.config, "site_slug": site.slug}
        await s.commit()
    if on_created:
        await on_created(site)
    return {"url": site.url, "id": site.id, "slug": site.slug}


# ---------------------------------------------------------------- shaxsiy bosh sahifa: profil, yaqinlar, javoblar

MAX_PEOPLE = 50


def _person_out(p: Person, ref) -> dict:
    nxt = reminders.next_occurrence(p, ref)
    rel = RELATIONS.get(p.relation) or {}
    section = reminders.KIND_SECTION.get(p.kind, "tugilgan-kun")
    if p.kind == "birthday" and p.relation in ("sevgili", "jufti"):
        section = "sevgi" if p.relation == "sevgili" else "tugilgan-kun"
    return {
        "id": p.id, "name": p.name, "kind": p.kind, "title": p.title, "relation": p.relation,
        "emoji": rel.get("emoji") or reminders.KINDS[p.kind][0],
        "event": p.title if p.kind == "other" else reminders.KINDS[p.kind][1],
        "day": p.day, "month": p.month, "year": p.year,
        "date": nxt.isoformat(), "date_label": reminders.human_day(nxt),
        "days_left": (nxt - ref).days, "turns": reminders.years_on(p, nxt),
        "section": section,
        "born": reminders.occurrence(p.day, p.month, p.year).isoformat() if p.kind == "birthday" and p.year else None,
    }


def start_param(init_data: str) -> str:
    return dict(parse_qsl(init_data or "", keep_blank_values=True)).get("start_param", "")


@router.get("/api/me")
async def me(x_init_data: str = Header("")):
    user = check_init_data(x_init_data)
    uid = int(user["id"])
    ref = reminders.today()
    async with Session() as s:
        u, new = await billing.touch_user(s, uid, user.get("first_name", ""), user.get("username", ""), user.get("language_code", ""))
        inviter = None
        if new:
            u.lang = i18n.from_telegram(user.get("language_code"))
            inviter = await billing.apply_referral(s, u, start_param(x_init_data))
        await s.commit()
        quota = await billing.quota(s, u)
        n_videos = await s.scalar(select(func.count()).select_from(RenderJob).where(
            RenderJob.owner_id == uid, RenderJob.guest_id.is_(None), RenderJob.status.in_(("queued", "rendering", "done"))))
        prof = await s.get(UserProfile, uid)
        people = (await s.execute(select(Person).where(Person.owner_id == uid))).scalars().all()
        sites = (await s.execute(select(Site).where(Site.owner_id == uid).order_by(Site.id.desc()))).scalars().all()
        counts = dict((await s.execute(
            select(Reaction.site_id, func.count()).join(Site, Site.id == Reaction.site_id)
            .where(Site.owner_id == uid).group_by(Reaction.site_id))).all())
        latest = (await s.execute(
            select(Reaction, Site).join(Site, Site.id == Reaction.site_id)
            .where(Site.owner_id == uid, Reaction.message != "").order_by(Reaction.id.desc()).limit(5))).all()
    if inviter and on_referral:
        await on_referral(inviter, user.get("first_name", ""))
    out_people = sorted((_person_out(p, ref) for p in people), key=lambda x: x["days_left"])
    real_sites = [x for x in sites if x.kind == "site"]
    return {
        "id": uid,
        "name": user.get("first_name", ""),
        "lang": u.lang or i18n.from_telegram(user.get("language_code")),
        "admin": uid in settings.admins,
        "balance": u.balance, "bonus": u.bonus_videos, "quota": quota, "videos": n_videos,
        "ref_link": f"https://t.me/{settings.bot_username}?start=ref_{uid}",
        "channel": settings.channel_link,
        "onboarded": prof is not None,
        "relations": prof.relations if prof else [],
        "people": out_people,
        "sites": [
            {"slug": x.slug, "title": site_title(x.config), "url": owner_url(x), "paid": x.paid, "views": x.views,
             "reactions": counts.get(x.id, 0), "template": x.config.get("template"), "status": x.status,
             "tarif": x.config.get("tarif"), "price": site_price(x.config), "event": x.config.get("event_slug"),
             "to": recipient_name(x.config), "public": x.url}
            for x in real_sites[:30]
        ],
        "stats": {
            "happy": sum(1 for x in real_sites if x.paid) + (n_videos or 0),
            "views": sum(x.views for x in sites),
            "reactions": sum(counts.values()),
        },
        "messages": [{"emoji": r.emoji, "text": r.message, "title": site_title(st.config)} for r, st in latest],
    }


class PersonIn(BaseModel):
    name: str = Field(min_length=1, max_length=100)
    relation: str = ""
    kind: str = "birthday"
    title: str = Field(default="", max_length=100)
    day: int = Field(ge=1, le=31)
    month: int = Field(ge=1, le=12)
    year: int | None = Field(default=None, ge=1900, le=2100)


def _new_person(uid: int, p: PersonIn) -> Person:
    if p.kind not in reminders.KINDS:
        raise HTTPException(400, "Noma'lum sana turi")
    if p.day > calendar.monthrange(2024, p.month)[1]:  # 2024 kabisa yili: 29-fevral ham to'g'ri
        raise HTTPException(400, "Sana noto'g'ri")
    return Person(owner_id=uid, name=p.name.strip(), relation=p.relation if p.relation in RELATIONS else "",
                  kind=p.kind, title=p.title.strip() if p.kind == "other" else "", day=p.day, month=p.month, year=p.year)


class OnboardIn(BaseModel):
    relations: list[str] = Field(default_factory=list, max_length=len(RELATIONS))
    people: list[PersonIn] = Field(default_factory=list, max_length=10)


@router.post("/api/me/onboard")
async def onboard(body: OnboardIn, x_init_data: str = Header("")):
    user = check_init_data(x_init_data)
    uid = int(user["id"])
    rels = [r for r in dict.fromkeys(body.relations) if r in RELATIONS]
    new = [_new_person(uid, p) for p in body.people]
    async with Session() as s:
        prof = await s.get(UserProfile, uid)
        if prof:
            prof.relations = rels
        else:
            s.add(UserProfile(tg_id=uid, first_name=str(user.get("first_name", ""))[:100], relations=rels))
        count = await s.scalar(select(func.count()).select_from(Person).where(Person.owner_id == uid))
        s.add_all(new[: max(0, MAX_PEOPLE - count)])
        await s.commit()
    return {"ok": True}


@router.post("/api/people")
async def add_person(body: PersonIn, x_init_data: str = Header("")):
    uid = int(check_init_data(x_init_data)["id"])
    async with Session() as s:
        count = await s.scalar(select(func.count()).select_from(Person).where(Person.owner_id == uid))
        if count >= MAX_PEOPLE:
            raise HTTPException(400, f"Ko'pi bilan {MAX_PEOPLE} ta sana qo'shish mumkin")
        p = _new_person(uid, body)
        s.add(p)
        await s.commit()
    return _person_out(p, reminders.today())


@router.delete("/api/people/{pid}")
async def delete_person(pid: int, x_init_data: str = Header("")):
    uid = int(check_init_data(x_init_data)["id"])
    async with Session() as s:
        p = await s.get(Person, pid)
        if not p or p.owner_id != uid:
            raise HTTPException(404)
        await s.execute(delete(ReminderLog).where(ReminderLog.person_id == pid))
        await s.delete(p)
        await s.commit()
    return {"ok": True}
