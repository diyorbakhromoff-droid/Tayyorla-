import hashlib
import hmac
import logging

from fastapi import FastAPI, Form, HTTPException, Request
from fastapi.responses import HTMLResponse, RedirectResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field

from .config import MEDIA_DIR, ROOT, settings
from .db import Rsvp, Session, get_site
from .render import env, on_color, render_site
from .webapp import router as webapp_router

log = logging.getLogger(__name__)

app = FastAPI(docs_url=None, redoc_url=None)
app.mount("/static", StaticFiles(directory=ROOT / "static"), name="static")
app.mount("/media", StaticFiles(directory=MEDIA_DIR), name="media")
app.include_router(webapp_router)

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
        password = site.config.get("fields", {}).get("password")
        if password and request.cookies.get(f"u_{slug}") != _unlock_token(slug, password):
            c = site.config["colors"]
            return env.get_template("gate.html").render(
                slug=slug, c=c, on_primary=on_color(c["primary"]), name=site.config["fields"].get("name", ""),
                hint=site.config.get("texts", {}).get("password_hint"), error=request.query_params.get("e"),
            )
        is_owner_preview = request.query_params.get("owner") == "1"
        if site.paid and not is_owner_preview:
            site.views += 1
            first_view = site.views == 1
            await s.commit()
            if first_view and notify:
                await notify(site.owner_id, f"👀 Sahifangiz birinchi marta ochildi!\n{site.url}")
        return render_site(site, preview=not site.paid)


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
        await notify(site.owner_id, f"{icon} <b>{data.name}</b>{extra} — {'keladi' if going else 'kela olmaydi'}{note}")
    return {"ok": True}
