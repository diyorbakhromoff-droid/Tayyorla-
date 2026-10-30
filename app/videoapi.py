"""Mini App API: video taklifnoma, musiqa kutubxonasi, hamyon (balans) va admin paneli."""

import logging
import time
import uuid
from datetime import timedelta

from aiogram.types import InlineQueryResultCachedVideo
from fastapi import APIRouter, File, Form, Header, HTTPException, Query, UploadFile
from fastapi.responses import HTMLResponse, Response
from pydantic import BaseModel, Field
from sqlalchemy import func, select

from . import ai, billing, i18n, video, videobot
from .config import MEDIA_DIR, MUSIC_DIR, settings
from .db import BalanceTx, MusicTrack, Payment, RenderJob, Session, Site, User, new_slug, utcnow
from .webapp import _rate_limit, check_init_data

log = logging.getLogger(__name__)
router = APIRouter()

MUSIC_THEMES = ["toy", "osh", "gap", "choy", "tk", "sevgi", "farzand", "umumiy"]
MAX_MUSIC = 25 * 1024 * 1024
AUDIO_EXT = {"audio/mpeg": "mp3", "audio/mp3": "mp3", "audio/mp4": "m4a", "audio/x-m4a": "m4a", "audio/aac": "aac",
             "audio/ogg": "ogg", "audio/wav": "wav", "audio/x-wav": "wav"}


def _uid(x_init_data: str) -> tuple[int, dict]:
    user = check_init_data(x_init_data)
    return int(user["id"]), user


def _admin(x_init_data: str) -> int:
    uid, _ = _uid(x_init_data)
    if uid not in settings.admins:
        raise HTTPException(403, "admin_only")
    return uid


# ---------------------------------------------------------------- jonli ko'rinish sahifasi

@router.get("/video/{design_id}", response_class=HTMLResponse)
async def video_page(design_id: str, lang: str = "uz", still: int | None = None, autoplay: int = 1, palette: int = 0):
    if design_id not in video.DESIGNS:
        raise HTTPException(404)
    payload = video.demo_payload(design_id, i18n.norm_lang(lang))
    if palette:
        d = video.DESIGNS[design_id]
        payload = video.build_payload(design_id, video.DEMO[d["section"]], i18n.norm_lang(lang), guest=video.DEMO_GUEST,
                                      site_url=f"{settings.base_url}/s/demo", palette=palette)
    mode = "still" if still is not None else "live"
    return video.page_html(design_id, payload, mode=mode, t=max(0, min(20000, still or 0)), autoplay=bool(autoplay))


@router.get("/api/video/meta")
async def video_meta(lang: str = "uz"):
    lang = i18n.norm_lang(lang)
    designs = []
    for d in video.DESIGNS.values():
        designs.append({
            "id": d["id"], "section": d["section"], "name": d["name"], "new": d.get("new", False),
            "desc": d["desc"].get(lang) or d["desc"]["uz"],
            "palettes": [{"name": p["name"], "swatch": [p["vars"].get("--bg"), p["vars"].get("--accent"), p["vars"].get("--accent2")]}
                         for p in d.get("palettes", [])],
            "thumb": f"/katalog/video/thumb/{d['id']}.jpg", "page": f"/video/{d['id']}",
        })
    fields = {}
    for sec in video.SECTIONS:
        spec = {**video.COMMON_FIELDS, **video.SECTION_FIELDS[sec]}
        fields[sec] = [{"key": k, "kind": kind, "limit": lim, "required": k in video.REQUIRED[sec]} for k, (kind, lim) in spec.items()
                       if not (sec == "gap" and k in ("ikki_kunlik", "sana2"))]
    return {
        "sections": video.SECTIONS, "designs": designs, "events": video.EVENT_KEYS, "fields": fields, "demo": video.DEMO,
        "langs": [{"key": k, "name": v} for k, v in i18n.LANG_NAMES.items()],
        "price": settings.video_price, "free_per_day": settings.free_videos_per_day, "topups": settings.topups,
        "packages": [{"size": n, "price": p} for n, p in settings.packages],
        "channel": settings.channel_link, "channel_name": settings.channel_username, "bot": settings.bot_username,
        "seconds": settings.video_seconds, "event_names": i18n.card(lang)["events"],
    }


class PayloadIn(BaseModel):
    design: str
    data: dict = Field(default_factory=dict)
    lang: str = "auto"
    palette: int = 0
    guest: str | None = Field(default=None, max_length=60)
    ui: str | None = None  # Mini App tili: «avto» tilni aniqlashda yordam beradi
    probe: dict | None = None  # ko'rinishda namunaviy qiymatlar bo'lsa, til faqat foydalanuvchi yozgani bo'yicha aniqlanadi


@router.post("/api/video/payload")
async def video_payload(body: PayloadIn, x_init_data: str = Header("")):
    check_init_data(x_init_data)
    d = video.design(body.design)
    data = video.clean_data(d["section"], body.data, strict=False)
    probe = video.clean_data(d["section"], body.probe, strict=False) if body.probe is not None else data
    return video.build_payload(body.design, data, video.resolve_lang(body.lang, probe, body.ui), guest=body.guest or data.get("kimga"),
                               free=True, site_url=f"{settings.base_url}/s/preview", palette=body.palette)


# ---------------------------------------------------------------- video yaratish

class MusicIn(BaseModel):
    mode: str = "none"  # lib | own | none
    track: int | None = None
    url: str | None = None
    start: float = Field(default=0, ge=0, le=1800)


class VideoIn(PayloadIn):
    music: MusicIn | None = None
    site: str | None = None  # mavjud tadbirni yangilash
    pay: str = "auto"  # auto | wait (bepul tugagan bo'lsa to'lovni kutib turadi)
    topup: int | None = Field(default=None, ge=0, le=10_000_000)  # wait: balansga shu summa tushadi, video narxi undan yechiladi


async def resolve_music(s, m: MusicIn | None) -> dict | None:
    if not m or m.mode == "none":
        return None
    if m.mode == "lib" and m.track:
        t = await s.get(MusicTrack, m.track)
        if t and t.active:
            return {"file": t.file, "start": t.start if not m.start else m.start, "track": t.id}
        return None
    if m.mode == "own" and video.own_media(m.url):
        return {"file": m.url, "start": m.start}
    return None


async def _event_site(s, uid: int, name: str, slug: str | None) -> Site:
    if slug:
        site = (await s.execute(select(Site).where(Site.slug == slug))).scalar_one_or_none()
        if site and site.owner_id == uid and site.kind == "video":
            return site
    site = Site(slug=new_slug(), owner_id=uid, owner_name=name, category="video", kind="video", config={}, status="draft")
    s.add(site)
    await s.flush()
    return site


async def notify_queued(job_id: int) -> None:
    bot = videobot.BOT
    if not bot:
        return
    async with Session() as s:
        job = await s.get(RenderJob, job_id)
        user = await s.get(User, job.owner_id)
        lang = (user.lang if user else "") or "uz"
        try:
            msg = await bot.send_message(job.owner_id, await videobot.status_text(job, lang))
            job.status_msg_id = msg.message_id
            await s.commit()
        except Exception:
            log.exception("Navbat xabarini yuborib bo'lmadi")


@router.post("/api/video")
async def create_video(body: VideoIn, x_init_data: str = Header("")):
    uid, tg = _uid(x_init_data)
    d = video.design(body.design)
    data = video.clean_data(d["section"], body.data, strict=True)
    name = " ".join(filter(None, [tg.get("first_name"), tg.get("last_name")]))
    async with Session() as s:
        user, _ = await billing.touch_user(s, uid, tg.get("first_name", ""), tg.get("username", ""), tg.get("language_code", ""))
        lang = video.resolve_lang(body.lang, data, body.ui or user.lang)
        recent = await s.scalar(select(func.count()).select_from(RenderJob).where(
            RenderJob.owner_id == uid, RenderJob.guest_id.is_(None), RenderJob.created_at >= utcnow() - timedelta(hours=1)))
        if recent >= settings.video_max_per_hour:
            raise HTTPException(429, "too_many_videos")
        site = await _event_site(s, uid, name, body.site)
        music = await resolve_music(s, body.music)
        site.config = {"engine": "video", "section": d["section"], "design": body.design, "palette": body.palette,
                       "lang": lang, "data": data, "music": music, **{k: v for k, v in (site.config or {}).items()
                                                                    if k in ("site_slug", "package", "package_paid")}}
        guest = data.get("kimga")
        common = dict(guest=guest, site_url=site.url, palette=body.palette)
        p_free = video.build_payload(body.design, data, lang, free=True, **common)
        p_paid = video.build_payload(body.design, data, lang, free=False, **common)
        h_free, h_paid = video.render_hash(p_free, music), video.render_hash(p_paid, music)

        # xuddi shu video navbatda turgan bo'lsa — ikkinchi marta yasamaymiz
        pending = (await s.execute(select(RenderJob).where(
            RenderJob.owner_id == uid, RenderJob.hash.in_((h_free, h_paid)),
            RenderJob.status.in_(("queued", "rendering", "awaiting_payment"))).order_by(RenderJob.id.desc()))).scalars().first()
        if pending:
            out = {"status": pending.status, "job": pending.id, "charge": pending.charge, "channel": settings.channel_link,
                   "need_sub": pending.free and bool(settings.channel_username), "subscribed": True,
                   "site": (await s.get(Site, pending.site_id)).slug if pending.site_id else site.slug,
                   "quota": await billing.quota(s, user)}
            await s.rollback()
            out["position"] = await videobot.queue_position(out["job"])
            return out

        # aynan shu video avval yasalgan bo'lsa — qayta yasamasdan yuboramiz
        cached = (await s.execute(select(RenderJob).where(
            RenderJob.owner_id == uid, RenderJob.hash.in_((h_free, h_paid)), RenderJob.status == "done",
            RenderJob.tg_file_id != "").order_by((RenderJob.hash == h_paid).desc(), RenderJob.id.desc()))).scalars().first()
        if cached and cached.delivered:
            await s.commit()
            if videobot.BOT:
                await videobot.send_video(videobot.BOT, cached)
            return {"status": "sent", "job": cached.id, "site": site.slug}

        charge = await billing.take_video_charge(s, user, ref=f"site:{site.slug}")
        status = "queued"
        if charge is None:
            if body.pay != "wait":
                q = await billing.quota(s, user)
                await s.rollback()
                raise HTTPException(402, {"code": "paywall", "quota": q, "price": settings.video_price, "topups": settings.topups})
            charge, status = ("paid", settings.video_price), "awaiting_payment"
        kind, price = charge
        page = p_free if kind in ("free", "bonus") else p_paid
        job = RenderJob(owner_id=uid, site_id=site.id, design=body.design, lang=lang, charge=kind, price=price, status=status,
                        payload={"page": page, "music": music, "guest": guest}, hash=h_free if kind in ("free", "bonus") else h_paid)
        s.add(job)
        await s.flush()
        payment = None
        if status == "awaiting_payment":
            amount = body.topup if body.topup and body.topup >= settings.video_price else settings.video_price
            payment = Payment(user_id=uid, amount=amount, job_id=job.id)
            s.add(payment)
        await s.commit()
        q = await billing.quota(s, user)
    if payment:
        await videobot.send_payment_prompt(payment.id)
        return {"status": "awaiting_payment", "job": job.id, "site": site.slug, "payment": payment.id, "quota": q}
    await notify_queued(job.id)
    need_sub = job.free and bool(settings.channel_username)
    subscribed = await videobot.is_subscribed(videobot.BOT, uid) if need_sub and videobot.BOT else True
    return {"status": "queued", "job": job.id, "site": site.slug, "charge": kind, "position": await videobot.queue_position(job.id),
            "need_sub": need_sub, "subscribed": subscribed, "channel": settings.channel_link, "quota": q}


def _job_out(job: RenderJob) -> dict:
    page = job.payload.get("page") or {}
    t = page.get("t") or {}
    return {"id": job.id, "status": job.status, "progress": job.progress, "delivered": job.delivered, "charge": job.charge,
            "design": job.design, "section": page.get("section"), "title": t.get("event"), "names": t.get("names_line"),
            "date": t.get("date"), "guest": job.payload.get("guest"), "site_id": job.site_id,
            "created": job.created_at.isoformat() if job.created_at else None, "free": job.free}


async def _own_job(s, job_id: int, uid: int) -> RenderJob:
    job = await s.get(RenderJob, job_id)
    if not job or job.owner_id != uid:
        raise HTTPException(404)
    return job


@router.get("/api/video/{job_id}")
async def video_status(job_id: int, x_init_data: str = Header("")):
    uid, _ = _uid(x_init_data)
    async with Session() as s:
        job = await _own_job(s, job_id, uid)
        site = await s.get(Site, job.site_id) if job.site_id else None
    out = _job_out(job)
    out["site"] = site.slug if site else None
    out["position"] = await videobot.queue_position(job.id) if job.status == "queued" else 0
    need_sub = job.free and not job.guest_id and bool(settings.channel_username)
    out["need_sub"] = need_sub
    out["subscribed"] = await videobot.is_subscribed(videobot.BOT, uid) if need_sub and videobot.BOT else True
    out["channel"] = settings.channel_link
    return out


@router.post("/api/video/{job_id}/claim")
async def video_claim(job_id: int, x_init_data: str = Header("")):
    """Obunadan keyin tayyor bepul videoni chatga yuborish."""
    uid, _ = _uid(x_init_data)
    async with Session() as s:
        job = await _own_job(s, job_id, uid)
    if job.status != "done":
        return {"delivered": False, "status": job.status}
    if job.free and videobot.BOT and not await videobot.is_subscribed(videobot.BOT, uid):
        return {"delivered": False, "need_sub": True, "channel": settings.channel_link}
    ok = await videobot.send_video(videobot.BOT, job) if videobot.BOT else False
    return {"delivered": ok}


@router.post("/api/video/{job_id}/resend")
async def video_resend(job_id: int, x_init_data: str = Header("")):
    uid, _ = _uid(x_init_data)
    async with Session() as s:
        job = await _own_job(s, job_id, uid)
    if job.status != "done" or not job.delivered:
        raise HTTPException(400, "not_ready")
    ok = await videobot.send_video(videobot.BOT, job) if videobot.BOT else False
    return {"ok": ok}


@router.post("/api/video/{job_id}/share")
async def video_share(job_id: int, x_init_data: str = Header("")):
    """Mini App ichidagi «Ulashish»: Telegram shareMessage uchun tayyor xabar."""
    uid, _ = _uid(x_init_data)
    async with Session() as s:
        job = await _own_job(s, job_id, uid)
    if not job.tg_file_id or not videobot.BOT:
        raise HTTPException(400, "not_ready")
    page = job.payload.get("page") or {}
    result = InlineQueryResultCachedVideo(
        id=f"v{job.id}-{uuid.uuid4().hex[:6]}", video_file_id=job.tg_file_id, title=(page.get("t") or {}).get("event") or "Tayyorla",
        caption=video.caption(page, paid=not job.free, guest=job.payload.get("guest")), parse_mode="HTML")
    prepared = await videobot.BOT.save_prepared_inline_message(
        user_id=uid, result=result, allow_user_chats=True, allow_group_chats=True, allow_channel_chats=True)
    return {"id": prepared.id}


@router.get("/api/videos")
async def my_videos(x_init_data: str = Header("")):
    uid, _ = _uid(x_init_data)
    async with Session() as s:
        jobs = (await s.execute(select(RenderJob).where(RenderJob.owner_id == uid, RenderJob.guest_id.is_(None))
                                .order_by(RenderJob.id.desc()).limit(50))).scalars().all()
        slugs = dict((await s.execute(select(Site.id, Site.slug).where(Site.id.in_({j.site_id for j in jobs if j.site_id})))).all())
    out = []
    for j in jobs:
        row = _job_out(j)
        row["site"] = slugs.get(j.site_id)
        out.append(row)
    return {"videos": out}


# ---------------------------------------------------------------- AI: matn va tarjima

class VideoWriteIn(BaseModel):
    section: str
    data: dict = Field(default_factory=dict)
    lang: str = "uz"
    brief: str = Field(default="", max_length=500)
    previous: str | None = Field(default=None, max_length=400)


@router.post("/api/video/ai/write")
async def video_ai_write(body: VideoWriteIn, x_init_data: str = Header("")):
    user = check_init_data(x_init_data)
    _rate_limit(user)
    data = video.clean_data(body.section, body.data, strict=False)
    try:
        text = await ai.write_video_message(body.section, data, i18n.norm_lang(body.lang), body.brief, body.previous)
    except Exception:
        log.exception("Video matnini yozib bo'lmadi")
        raise HTTPException(502, "ai_failed")
    return {"text": text}


TRANSLATABLE = ("kuyov", "kelin", "ism", "joy", "manzil", "matn", "imzo", "sababi", "guruh", "navbat", "nomi_matn",
                "marosim_nomi", "karta_egasi", "kimga")


class TranslateIn(BaseModel):
    section: str
    data: dict = Field(default_factory=dict)
    lang: str


@router.post("/api/video/translate")
async def video_translate(body: TranslateIn, x_init_data: str = Header("")):
    user = check_init_data(x_init_data)
    lang = i18n.norm_lang(body.lang)
    data = video.clean_data(body.section, body.data, strict=False)
    fields = {k: data[k] for k in TRANSLATABLE if isinstance(data.get(k), str) and data[k]}
    if lang == "cy":  # kirill — qoidaga ko'ra, AI shart emas
        return {"data": {**data, **{k: i18n.to_cyrillic(v) for k, v in fields.items()}}}
    _rate_limit(user)
    try:
        out = await ai.translate_fields(fields, lang)
    except Exception:
        log.exception("Tarjima qilib bo'lmadi")
        raise HTTPException(502, "ai_failed")
    return {"data": {**data, **out}}


# ---------------------------------------------------------------- QR (tadbir vositalari)

@router.get("/api/qr")
async def qr_image(text: str = Query(..., max_length=400)):
    from .qr import qr_svg
    return Response(qr_svg(text, size=320), media_type="image/svg+xml", headers={"Cache-Control": "public, max-age=86400"})


# ---------------------------------------------------------------- musiqa

def _track_out(t: MusicTrack) -> dict:
    return {"id": t.id, "title": t.title, "subtitle": t.subtitle, "theme": t.theme, "kind": t.kind, "url": t.file,
            "start": t.start, "active": t.active, "sort": t.sort, "author": t.author, "license": t.license}


@router.get("/api/music")
async def music_list():
    async with Session() as s:
        rows = (await s.execute(select(MusicTrack).where(MusicTrack.active.is_(True))
                                .order_by(MusicTrack.theme, MusicTrack.sort, MusicTrack.id))).scalars().all()
    return {"themes": MUSIC_THEMES, "tracks": [_track_out(t) for t in rows]}


# ---------------------------------------------------------------- ochiq hisoblagich

_PUBLIC = {"at": 0.0, "data": None}


@router.get("/api/stats/public")
async def public_stats():
    if _PUBLIC["data"] and time.time() - _PUBLIC["at"] < 600:
        return _PUBLIC["data"]
    async with Session() as s:
        videos = await s.scalar(select(func.count()).select_from(RenderJob).where(RenderJob.status == "done"))
        sites = await s.scalar(select(func.count()).select_from(Site).where(Site.kind == "site"))
    _PUBLIC.update(at=time.time(), data={"created": (videos or 0) + (sites or 0), "videos": videos or 0, "sites": sites or 0})
    return _PUBLIC["data"]


# ---------------------------------------------------------------- til va hamyon

class LangIn(BaseModel):
    lang: str


@router.post("/api/me/lang")
async def set_lang(body: LangIn, x_init_data: str = Header("")):
    uid, tg = _uid(x_init_data)
    if body.lang not in i18n.LANGS:
        raise HTTPException(400, "bad_lang")
    async with Session() as s:
        user, _ = await billing.touch_user(s, uid, tg.get("first_name", ""), tg.get("username", ""), tg.get("language_code", ""))
        user.lang = body.lang
        user.lang_set = True
        await s.commit()
    return {"ok": True}


@router.get("/api/wallet")
async def wallet(x_init_data: str = Header("")):
    uid, tg = _uid(x_init_data)
    async with Session() as s:
        user, _ = await billing.touch_user(s, uid, tg.get("first_name", ""), tg.get("username", ""), tg.get("language_code", ""))
        await s.commit()
        q = await billing.quota(s, user)
        tx = (await s.execute(select(BalanceTx).where(BalanceTx.user_id == uid).order_by(BalanceTx.id.desc()).limit(30))).scalars().all()
        pend = (await s.execute(select(Payment).where(Payment.user_id == uid, Payment.status.in_(("new", "pending")))
                                .order_by(Payment.id.desc()).limit(5))).scalars().all()
    return {**q, "history": [{"amount": t.amount, "kind": t.kind, "ref": t.ref, "at": t.created_at.isoformat()} for t in tx],
            "pending": [{"id": p.id, "amount": p.amount, "status": p.status} for p in pend],
            "topups": settings.topups, "ref_link": f"https://t.me/{settings.bot_username}?start=ref_{uid}"}


class TopupIn(BaseModel):
    amount: int = Field(ge=1000, le=10_000_000)


@router.post("/api/pay/topup")
async def topup(body: TopupIn, x_init_data: str = Header("")):
    uid, tg = _uid(x_init_data)
    if body.amount not in settings.topups and body.amount < settings.video_price:
        raise HTTPException(400, "bad_amount")
    async with Session() as s:
        await billing.touch_user(s, uid, tg.get("first_name", ""), tg.get("username", ""), tg.get("language_code", ""))
        p = Payment(user_id=uid, amount=body.amount)
        s.add(p)
        await s.commit()
    await videobot.send_payment_prompt(p.id)
    return {"ok": True, "payment": p.id}


@router.post("/api/sites/{slug}/pay")
async def pay_site_from_balance(slug: str, x_init_data: str = Header("")):
    """Saytni balansdan to'lash: yetsa darhol faollashadi."""
    uid, _ = _uid(x_init_data)
    from .catalog import site_price
    async with Session() as s:
        site = (await s.execute(select(Site).where(Site.slug == slug))).scalar_one_or_none()
        if not site or site.owner_id != uid or site.kind != "site":
            raise HTTPException(404)
        if site.paid:
            return {"ok": True, "paid": True}
        price = site_price(site.config)
        if not await billing.spend(s, uid, price, "site", f"site:{slug}"):
            user = await s.get(User, uid)
            raise HTTPException(402, {"code": "paywall", "need": price, "balance": user.balance if user else 0, "topups": settings.topups})
        site.status = "paid"
        await s.commit()
    await videobot.site_paid_notice(site.id)
    return {"ok": True, "paid": True}


# ---------------------------------------------------------------- admin paneli

@router.get("/api/admin/music")
async def admin_music(x_init_data: str = Header("")):
    _admin(x_init_data)
    async with Session() as s:
        rows = (await s.execute(select(MusicTrack).order_by(MusicTrack.theme, MusicTrack.sort, MusicTrack.id))).scalars().all()
    return {"themes": MUSIC_THEMES, "tracks": [_track_out(t) for t in rows]}


@router.post("/api/admin/music")
async def admin_music_add(file: UploadFile = File(...), title: str = Form(..., max_length=100), theme: str = Form(...),
                          kind: str = Form("instr"), subtitle: str = Form("", max_length=150), start: int = Form(0),
                          author: str = Form("", max_length=100), x_init_data: str = Header("")):
    _admin(x_init_data)
    if theme not in MUSIC_THEMES or kind not in ("vocal", "instr"):
        raise HTTPException(400, "bad_theme")
    data = await file.read()
    if len(data) > MAX_MUSIC:
        raise HTTPException(413, "too_big")
    ext = AUDIO_EXT.get(file.content_type or "") or (file.filename or "").rsplit(".", 1)[-1].lower()
    if ext not in ("mp3", "m4a", "aac", "ogg", "wav"):
        raise HTTPException(400, "not_audio")
    name = f"{uuid.uuid4().hex}.{ext}"
    (MUSIC_DIR / name).write_bytes(data)
    async with Session() as s:
        t = MusicTrack(title=title.strip(), subtitle=subtitle.strip(), theme=theme, kind=kind, file=f"/media/music/{name}",
                       start=max(0, start), author=author.strip())
        s.add(t)
        await s.commit()
    return _track_out(t)


class TrackPatch(BaseModel):
    title: str | None = Field(default=None, max_length=100)
    subtitle: str | None = Field(default=None, max_length=150)
    theme: str | None = None
    kind: str | None = None
    start: int | None = Field(default=None, ge=0, le=1800)
    active: bool | None = None
    sort: int | None = None


@router.patch("/api/admin/music/{track_id}")
async def admin_music_edit(track_id: int, body: TrackPatch, x_init_data: str = Header("")):
    _admin(x_init_data)
    async with Session() as s:
        t = await s.get(MusicTrack, track_id)
        if not t:
            raise HTTPException(404)
        for k, v in body.model_dump(exclude_none=True).items():
            if k == "theme" and v not in MUSIC_THEMES or k == "kind" and v not in ("vocal", "instr"):
                raise HTTPException(400, "bad_theme")
            setattr(t, k, v)
        await s.commit()
    return _track_out(t)


@router.delete("/api/admin/music/{track_id}")
async def admin_music_delete(track_id: int, x_init_data: str = Header("")):
    _admin(x_init_data)
    async with Session() as s:
        t = await s.get(MusicTrack, track_id)
        if not t:
            raise HTTPException(404)
        path = MEDIA_DIR / t.file.removeprefix("/media/")
        await s.delete(t)
        await s.commit()
    if path.resolve().parent == MUSIC_DIR.resolve():
        path.unlink(missing_ok=True)
    return {"ok": True}


@router.get("/api/admin/stats")
async def admin_stats(x_init_data: str = Header("")):
    _admin(x_init_data)
    from .stats import summary
    return await summary()
