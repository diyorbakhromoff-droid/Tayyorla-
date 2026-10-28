import hashlib
import html
import re
import hmac
import logging
import time
from collections import defaultdict, deque

from fastapi import FastAPI, Form, HTTPException, Request
from fastapi.responses import HTMLResponse, RedirectResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field

from .config import MEDIA_DIR, ROOT, settings
from .db import Reaction, Rsvp, Session, get_site
from .catalog import CATALOG_DIR, render_catalog
from .render import env, on_color, render_site
from .surprise import human, is_owner, locked_until, recipient_name
from .webapp import router as webapp_router

log = logging.getLogger(__name__)

app = FastAPI(docs_url=None, redoc_url=None)
app.mount("/static", StaticFiles(directory=ROOT / "static"), name="static")
app.mount("/media", StaticFiles(directory=MEDIA_DIR), name="media")
app.mount("/katalog", StaticFiles(directory=CATALOG_DIR), name="katalog")
app.include_router(webapp_router)


def page_for(site, preview: bool) -> str:
    if site.config.get("engine") == "catalog":
        return render_catalog(site.config, site.slug, preview)
    return render_site(site, preview)

# Bot ishga tushganda o'rnatiladi: RSVP va ko'rishlar haqida egasiga xabar berish uchun
notify = None


def _norm(pw: str) -> str:
    return " ".join(pw.lower().split())


def _unlock_token(slug: str, password: str) -> str:
    return hmac.new(settings.bot_token.encode(), f"{slug}:{_norm(password)}".encode(), hashlib.sha256).hexdigest()[:32]


@app.get("/", response_class=HTMLResponse)
async def home():
    return f'<meta charset="utf-8"><div style="font:18px sans-serif;text-align:center;padding:20vh 20px">💌 <b>Tayyorla</b> — yaqinlaringiz uchun tabrik saytlari.<br><a href="https://t.me/{settings.bot_username}">Telegram bot orqali yarating</a></div>'


@app.get("/s/{slug}", response_class=HTMLResponse)
async def show(slug: str, request: Request):
    async with Session() as s:
        site = await get_site(s, slug)
        if not site:
            raise HTTPException(404)
        owner = is_owner(slug, request.query_params.get("owner"))
        lock = locked_until(site.config)
        if lock and not owner:
            return env.get_template("teaser.html").render(
                name=recipient_name(site.config), when=human(lock), target_iso=lock.isoformat())
        password = site.config.get("fields", {}).get("password")
        if password and not owner and request.cookies.get(f"u_{slug}") != _unlock_token(slug, password):
            c = site.config["colors"]
            return env.get_template("gate.html").render(
                slug=slug, c=c, on_primary=on_color(c["primary"]), name=site.config["fields"].get("name", ""),
                hint=site.config.get("texts", {}).get("password_hint"), error=request.query_params.get("e"),
            )
        if site.paid and not owner:
            site.views += 1
            first_view = site.views == 1
            await s.commit()
            if first_view and notify:
                await notify(site.owner_id, f"👀 Sahifangiz birinchi marta ochildi!\n{site.url}")
        page = page_for(site, preview=not site.paid)
        if site.paid and not owner:
            page = with_react_widget(page, site)
        return page


REACT_EMOJI = ("❤️", "🥹", "🥰", "🤗", "🔥")
_reacts: dict[str, deque] = defaultdict(deque)


def with_react_widget(page: str, site) -> str:
    """To'langan sahifaga «javob qaytarish» tugmasini qo'shadi."""
    from_name = (site.owner_name or "").split(" ")[0] or "Yuboruvchi"
    widget = env.get_template("react_widget.html").render(
        slug=site.slug, from_name=from_name, bot=settings.bot_username, delay=25000)
    i = page.rfind("</body>")
    return page[:i] + widget + page[i:] if i != -1 else page + widget


class ReactIn(BaseModel):
    emoji: str
    message: str = Field(default="", max_length=300)


@app.post("/s/{slug}/react")
async def react(slug: str, data: ReactIn, request: Request):
    if data.emoji not in REACT_EMOJI:
        raise HTTPException(400)
    # Bitta qurilmadan bitta saytga soatiga 5 tagacha javob
    calls = _reacts[f"{slug}:{request.client.host if request.client else ''}"]
    now = time.time()
    while calls and now - calls[0] > 3600:
        calls.popleft()
    if len(calls) >= 5:
        raise HTTPException(429)
    calls.append(now)
    async with Session() as s:
        site = await get_site(s, slug)
        if not site or not site.paid:
            raise HTTPException(404)
        msg = " ".join(data.message.split())
        s.add(Reaction(site_id=site.id, emoji=data.emoji, message=msg))
        await s.commit()
    if notify:
        who = html.escape(recipient_name(site.config) or "Tabriklagan odamingiz")
        text = f"{data.emoji} <b>{who}</b> sahifangizga javob qaytardi!"
        if msg:
            text += f"\n\n«{html.escape(msg)}»"
        await notify(site.owner_id, text + "\n\nYana kimnidir quvontiramizmi? /start")
    return {"ok": True}


@app.post("/s/{slug}/unlock")
async def unlock(slug: str, password: str = Form(...)):
    async with Session() as s:
        site = await get_site(s, slug)
    if not site:
        raise HTTPException(404)
    real = site.config.get("fields", {}).get("password") or ""
    if _norm(password) != _norm(real):
        return RedirectResponse(f"/s/{slug}?e=1", status_code=303)
    resp = RedirectResponse(f"/s/{slug}", status_code=303)
    resp.set_cookie(f"u_{slug}", _unlock_token(slug, real), max_age=60 * 60 * 24 * 365, httponly=True, samesite="lax")
    return resp


class RsvpIn(BaseModel):
    name: str = Field(min_length=1, max_length=100)
    attending: str
    guests: int = Field(default=1, ge=1, le=20)
    note: str = Field(default="", max_length=300)


@app.post("/s/{slug}/rsvp")
async def rsvp(slug: str, data: RsvpIn):
    async with Session() as s:
        site = await get_site(s, slug)
        if not site or not site.config.get("features", {}).get("rsvp"):
            raise HTTPException(404)
        if not site.paid:
            # Namunada mehmon javoblari saqlanmaydi
            return {"ok": True}
        going = data.attending == "yes"
        s.add(Rsvp(site_id=site.id, name=data.name.strip(), attending=going, guests=data.guests if going else 0, note=data.note.strip()))
        await s.commit()
    if notify:
        icon = "✅" if going else "❌"
        extra = f" ({data.guests} kishi)" if going else ""
        note = f"\n💬 {data.note}" if data.note else ""
        await notify(site.owner_id, f"{icon} <b>{html.escape(data.name)}</b>{extra} — {'keladi' if going else 'kela olmaydi'}{html.escape(note)}")
    return {"ok": True}


@app.post("/s/{slug}/anketa")
async def anketa(slug: str, request: Request):
    """VIP to'y taklifnomasidagi anketa javoblari (ism, keladi va qo'shimcha savollar)."""
    try:
        data = await request.json()
    except Exception:
        raise HTTPException(400)
    if not isinstance(data, dict):
        raise HTTPException(400)
    name = str(data.get("ism") or "").strip()[:100] or "Mehmon"
    going = data.get("keladi") == "ha"
    extra = {str(k)[:60]: str(v)[:200] for k, v in data.items() if k not in ("ism", "keladi")}
    guests = 1
    for v in extra.values():
        if v[:1].isdigit():
            guests = int(re.match(r"\d+", v).group())
            break
    async with Session() as s:
        site = await get_site(s, slug)
        if not site or site.config.get("engine") != "catalog":
            raise HTTPException(404)
        if not site.paid:
            return {"ok": True}
        note = "; ".join(f"{k}: {v}" for k, v in list(extra.items())[:10])
        s.add(Rsvp(site_id=site.id, name=name, attending=going, guests=guests if going else 0, note=note[:500]))
        await s.commit()
    if notify:
        icon = "✅" if going else "❌"
        await notify(site.owner_id, f"{icon} <b>{html.escape(name)}</b> — {'keladi' if going else 'kela olmaydi'}" + (f"\n📋 {html.escape(note)}" if note else ""))
    return {"ok": True}
