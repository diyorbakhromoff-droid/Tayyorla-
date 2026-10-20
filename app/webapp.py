"""Telegram Mini App: forma orqali sayt yaratish uchun API."""

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
from .catalog import TEMPLATES, catalog_meta, clean_order, render_catalog
from .config import MEDIA_DIR, ROOT, settings
from .db import Session, Site, new_slug
from .render import parse_date, render_site
from .sites import CATEGORIES, PALETTES, build_config

log = logging.getLogger(__name__)
router = APIRouter()

# main.py da o'rnatiladi: sayt yaratilganda egasiga botda xabar yuborish uchun
on_created = None

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

@router.get("/app", response_class=HTMLResponse)
async def app_page():
    return (ROOT / "templates" / "webapp.html").read_text(encoding="utf-8")


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
        site = Site(slug=new_slug(), owner_id=int(user["id"]), owner_name=name, category=cfg["category"], config=cfg)
        s.add(site)
        await s.commit()
    if on_created:
        await on_created(site)
    return {"url": site.url, "id": site.id}
