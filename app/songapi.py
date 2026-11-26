"""Mini App: shaxsiy qo'shiq buyurtmasi (she'r, namuna, to'lov, variant tanlash, saytga qo'yish)."""

import logging

from fastapi import APIRouter, Header, HTTPException
from fastapi.responses import FileResponse
from pydantic import BaseModel, Field
from sqlalchemy import select

from . import pricing
from . import billing, costs, songflow, songs
from .config import settings
from .db import CostLog, Session, Site, Song, User, utcnow
from .webapp import _rate_limit, check_init_data

log = logging.getLogger(__name__)
router = APIRouter()


async def _lyrics_quota(uid: int) -> None:
    """She'r yozish (AI) xarajatini cheklash: bir kishiga kuniga va jami (yangi she'r + AI bilan qayta yozish).
    Sanoq xarajat jurnalidan (qayta ishga tushganda ham saqlanadi). Balansida qo'shiq puli bo'lsa — cheklanmaydi."""
    from sqlalchemy import func as _f
    lim = await songs.user_limits()
    async with Session() as s:
        user = await s.get(User, uid)
        if user and user.balance >= await songs.price_for(s, uid):
            return
        q = select(_f.count()).select_from(CostLog).where(CostLog.user_id == uid, CostLog.purpose.in_(("lyrics", "lyrics_edit")))
        total = await s.scalar(q) or 0
        today = await s.scalar(q.where(CostLog.created_at >= billing.day_start_utc())) or 0
    if lim["ly_total"] and total >= lim["ly_total"]:
        raise _limit("limit_total", "Bepul she'r yozish imkoniyatingiz tugadi. Balansni to'ldirsangiz, yangi qo'shiq tayyorlashingiz mumkin.")
    if lim["ly_day"] and today >= lim["ly_day"]:
        raise _limit("limit_day", "Bugungi she'r yozish imkoniyati tugadi — ertaga yana urinib ko'ring yoki matnni o'zingiz tahrirlang.")


def _limit(why: str, text: str) -> HTTPException:
    e = HTTPException(429, text)
    e.why = why  # statistika uchun: qaysi limit (lyrics_failed hodisasi)
    return e


def _why(e: HTTPException) -> str:
    """She'r yozilmaganining sababi: limit (qaysi biri), juda ko'p so'rov yoki AI xizmati xatosi."""
    return getattr(e, "why", "rate") if e.status_code == 429 else "ai"


def _uid(x_init_data: str) -> tuple[int, dict]:
    user = check_init_data(x_init_data)
    return int(user["id"]), user


def song_out(song: Song) -> dict:
    paid_files = [v.get("file") for v in (song.variants or []) if v.get("file")] if song.paid else []
    return {
        "id": song.id, "status": song.status, "recipient": song.recipient, "relation": song.relation, "occasion": song.occasion,
        "style": song.style, "voice": song.voice, "answers": {k: v for k, v in (song.answers or {}).items() if not k.startswith("_")},
        "title": song.title, "lyrics": song.lyrics, "preview": songs.preview_url(song), "variants": paid_files,
        "chosen": song.chosen if paid_files else -1, "file": paid_files[song.chosen] if paid_files and 0 <= song.chosen < len(paid_files) else None,
        "paid": song.paid, "price": song.price, "site": song.site_slug or None, "error": song.error or None,
        "busy": song.status in ("preview_queued", "preview_gen", "paid_queued", "paid_gen"),
        "promo": pricing.promo_of(song),
        "regular": settings.song_price,
        # naqorat boshlanishi (soniya) — videoga qo'yilganda 20 soniyalik bo'lak shu yerdan olinadi
        "chorus_at": round((song.plan or {}).get("_chorus_at", 0) / 1000) if paid_files else 0,
        "created_at": song.created_at.isoformat() if song.created_at else None,
    }


async def _own(s, song_id: int, uid: int) -> Song:
    song = await s.get(Song, song_id)
    if not song or song.owner_id != uid:
        raise HTTPException(404)
    return song


@router.get("/api/songs/meta")
async def songs_meta(x_init_data: str = Header("")):
    uid, _ = _uid(x_init_data)
    async with Session() as s:
        price = await songs.price_for(s, uid)
        left = await songs.free_previews_left(s, uid)
        user = await s.get(User, uid)
    cfg = await pricing.config()
    sub = bool(settings.song_preview_sub and settings.channel_username)
    per_user, _ = await songs.limits()
    return {**songs.meta(), "on": settings.songs_on, "price": price, "free_previews": left, "free_per_day": per_user,
            "balance": user.balance if user else 0, "credits": user.song_credits if user else 0,
            "packs": pricing.packs_public(cfg),
            "preview_sub": sub, "channel": settings.channel_link if sub else ""}


@router.get("/api/songs")
async def songs_list(x_init_data: str = Header("")):
    uid, _ = _uid(x_init_data)
    async with Session() as s:
        rows = (await s.execute(select(Song).where(Song.owner_id == uid).order_by(Song.id.desc()).limit(50))).scalars().all()
    return {"songs": [song_out(x) for x in rows]}


@router.get("/api/songs/{song_id}/listen")
async def song_listen(song_id: int, d: int = 0, t: str = ""):
    """Namunani faqat ilova pleeri uchun beradi (imzolangan havola, yuklab olish uchun emas)."""
    async with Session() as s:
        song = await s.get(Song, song_id)
    if not song or not songs.preview_ok(song, d, t):
        raise HTTPException(404)
    path = songs.preview_path(song)
    if not path.exists():
        raise HTTPException(404)
    return FileResponse(path, media_type="audio/mpeg", headers={
        "Cache-Control": "private, no-store", "Content-Disposition": "inline", "X-Content-Type-Options": "nosniff"})


@router.get("/api/songs/{song_id}")
async def song_get(song_id: int, x_init_data: str = Header("")):
    uid, _ = _uid(x_init_data)
    async with Session() as s:
        out = song_out(await _own(s, song_id, uid))
    songflow.seen(song_id)  # egasi hozir ilovada (namuna tayyor bo'lganda kutib turgan-turmagani shundan bilinadi)
    return out


class SongIn(BaseModel):
    recipient: str = Field(min_length=1, max_length=80)
    relation: str = Field(max_length=24)
    occasion: str = Field(max_length=24)
    style: str = Field(max_length=24)
    voice: str = Field(default="male", max_length=8)
    answers: dict[str, str] = Field(default_factory=dict)


def _clean_answers(a: dict) -> dict:
    keys = {k for k, _, _ in songs.QUESTIONS} | {"janr"}
    return {k: str(v).strip()[:400] for k, v in (a or {}).items() if k in keys and str(v).strip()}


@router.post("/api/songs")
async def song_create(body: SongIn, x_init_data: str = Header("")):
    uid, user = _uid(x_init_data)
    if not settings.songs_on:
        raise HTTPException(503, "Qo'shiq xizmati tez orada ishga tushadi")
    if body.relation not in songs.RELATIONS or body.occasion not in songs.OCCASIONS or body.style not in songs.STYLES or body.voice not in songs.VOICES:
        raise HTTPException(400, "bad_choice")
    answers = _clean_answers(body.answers)
    if body.style == "custom" and not answers.get("janr"):
        raise HTTPException(400, "O'z janringizni qisqacha yozing")
    sent_at = utcnow()  # so'rovnoma to'ldirib yuborilgan vaqt (she'r 10–30 soniyada yoziladi)
    try:
        _rate_limit(user)
        await _lyrics_quota(uid)
        song = Song(owner_id=uid, recipient=body.recipient.strip(), relation=body.relation, occasion=body.occasion, style=body.style,
                    voice=body.voice, answers=answers)
        try:
            song.title, song.lyrics, song.tags = await songs.write_lyrics(song)
        except Exception:
            log.exception("Qo'shiq matnini yozib bo'lmadi")
            raise HTTPException(502, "Hozir she'r yozib bo'lmadi, qayta urinib ko'ring")
    except HTTPException as e:
        await songflow.form_done(uid, body.relation, body.occasion, body.recipient, at=sent_at)
        await songflow.lyrics_failed(uid, _why(e), e.status_code)
        raise
    async with Session() as s:
        s.add(song)
        await s.flush()
        row = costs.ai_row(getattr(song, "_lyrics_usage", None), "lyrics", uid, f"song:{song.id}")
        if row is not None:
            s.add(row)
        await s.commit()
        await s.refresh(song)
    await songflow.form_done(uid, body.relation, body.occasion, body.recipient, song.id, at=sent_at)
    await songflow.lyrics_ready(song)
    return song_out(song)


class LyricsIn(BaseModel):
    text: str | None = Field(default=None, max_length=4000)        # qo'lda tahrirlangan matn
    instruction: str | None = Field(default=None, max_length=500)  # yoki AI ga istak: «quvnoqroq qil»
    title: str | None = Field(default=None, max_length=120)


@router.post("/api/songs/{song_id}/lyrics")
async def song_lyrics(song_id: int, body: LyricsIn, x_init_data: str = Header("")):
    uid, user = _uid(x_init_data)
    how = ""  # voronka: she'r qanday yangilandi (ai — qayta yozildi, manual — mijoz o'zi tahrirladi)
    try:
        async with Session() as s:
            song = await _own(s, song_id, uid)
            if song.paid or song.status in ("preview_queued", "preview_gen"):
                raise HTTPException(409, "Qo'shiq tayyorlangandan keyin matnni o'zgartirib bo'lmaydi")
            if body.instruction:
                how = "ai"
                _rate_limit(user)
                await _lyrics_quota(uid)
                try:
                    title, text, tags = await songs.write_lyrics(song, body.instruction)
                except Exception:
                    log.exception("Qo'shiq matnini qayta yozib bo'lmadi")
                    raise HTTPException(502, "Hozir she'r yozib bo'lmadi, qayta urinib ko'ring")
                song.title, song.lyrics, song.tags = title, text, tags or song.tags
                row = costs.ai_row(getattr(song, "_lyrics_usage", None), "lyrics_edit", uid, f"song:{song.id}")
                if row is not None:
                    s.add(row)
            elif body.text is not None:
                sections = songs.parse_lyrics(body.text)
                try:
                    songs.validate_lyrics(sections)
                except songs.SongError as e:
                    raise HTTPException(400, str(e))
                song.lyrics = songs.render_lyrics(sections)
                how = "manual"
            if body.title:
                song.title = body.title.strip()
            # matn o'zgardi — eski namuna va tayyorlangan variant endi mos emas
            song.preview, song.variants, song.plan, song.status, song.error, song.updated_at = "", [], {}, "lyrics", "", utcnow()
            await s.commit()
            out = song_out(song)
    except HTTPException as e:
        if how == "ai" and e.status_code in (429, 502):
            await songflow.lyrics_failed(uid, _why(e), e.status_code, song_id)
        raise
    if how:
        await songflow.lyrics_ready(song, how)
    return out


@router.post("/api/songs/{song_id}/preview")
async def song_preview(song_id: int, x_init_data: str = Header("")):
    uid, _ = _uid(x_init_data)
    flow: dict = {}  # voronka: tugma bosildi va nima bo'ldi (limit, xato) — tranzaksiya yopilgach yoziladi
    try:
        async with Session() as s:
            await billing.lock_user(s, uid)  # bir vaqtdagi so'rovlar bilan bepul namunani oshirib bo'lmasin
            song = await _own(s, song_id, uid)
            if song.paid or song.preview or song.status != "lyrics":
                return song_out(song)
            flow.update(song=song.id, at=utcnow())
            try:
                songs.validate_lyrics(songs.parse_lyrics(song.lyrics))
            except songs.SongError as e:
                flow.update(fail="text", error=str(e))
                raise HTTPException(400, str(e))
            if await songs.free_previews_left(s, uid) <= 0:
                lim = await songs.user_limits()
                total = lim["pv_total"] and await songs.previews_used_total(s, uid) >= lim["pv_total"]
                flow["limit"] = "user_total" if total else "user_day"
                raise HTTPException(402, {"code": "preview_limit", "reason": "total" if total else "used", "price": await songs.price_for(s, uid)})
            _, per_day = await songs.limits()
            if per_day and await songs.previews_today(s) >= per_day:
                flow["limit"] = "all_day"
                raise HTTPException(402, {"code": "preview_limit", "reason": "daily", "price": await songs.price_for(s, uid)})
            if settings.song_preview_sub and settings.channel_username:
                from . import videobot
                if videobot.BOT and not await videobot.is_subscribed(videobot.BOT, uid):
                    flow["limit"] = "sub"
                    raise HTTPException(403, {"code": "need_sub", "channel": settings.channel_link})
            if await songs.provider() == "elevenlabs" and not await songs.enough_credits(songs.preview_credits(song)):
                flow["fail"] = "no_credits"
                raise HTTPException(503, "Qo'shiq xizmati vaqtincha band. Birozdan so'ng qayta urinib ko'ring.")
            song.previews = (song.previews or 0) + 1
            song.preview_at = flow["at"]
            songs.count_preview(s, song)
            song.status, song.error, song.updated_at = "preview_queued", "", utcnow()
            await s.commit()
            out = song_out(song)
    finally:
        await songflow.preview_asked(uid, flow)
    songs.wake()
    return out


@router.post("/api/songs/{song_id}/pay")
async def song_pay(song_id: int, x_init_data: str = Header("")):
    uid, _ = _uid(x_init_data)
    async with Session() as s:
        song = await _own(s, song_id, uid)
        if not song.paid:
            try:
                songs.validate_lyrics(songs.parse_lyrics(song.lyrics))
            except songs.SongError as e:
                raise HTTPException(400, str(e))
            if song.status in ("preview_queued", "preview_gen"):
                raise HTTPException(409, "Namuna tayyorlanmoqda, bir oz kuting")
            # namuna tayyorlangan bo'lsa, to'liq qo'shiq allaqachon bor — ElevenLabs krediti kerak emas
            need = songs.full_credits(song) if await songs.provider() == "elevenlabs" else 0
            if need and not await songs.enough_credits(need):
                raise HTTPException(503, "Qo'shiq xizmati vaqtincha band — pul yechilmadi. Birozdan so'ng qayta urinib ko'ring.")
            if not await songs.pay(s, song, uid):
                user = await s.get(User, uid)
                price = await songs.price_for(s, uid, song)
                raise HTTPException(402, {"code": "paywall", "need": price, "balance": user.balance if user else 0, "topups": settings.topups})
            await s.commit()
        out = song_out(song)
    songs.wake()
    return out


@router.post("/api/songs/packs/{n}")
async def pack_buy(n: int, x_init_data: str = Header("")):
    """Qo'shiq paketini balansdan sotib olish. Yetmasa 402 (ilova balansni to'ldirish oynasini ochadi)."""
    uid, _ = _uid(x_init_data)
    async with Session() as s:
        ok = await pricing.buy_pack(s, uid, n)
        if ok is None:
            raise HTTPException(404, "Bunday paket yo'q")
        user = await s.get(User, uid)
        if not ok:
            raise HTTPException(402, {"code": "paywall", "need": await pricing.pack_price(n), "balance": user.balance if user else 0})
        await s.commit()
        await s.refresh(user)
    return {"ok": True, "credits": user.song_credits, "balance": user.balance}


@router.post("/api/songs/{song_id}/retry")
async def song_retry(song_id: int, x_init_data: str = Header("")):
    """To'langan, lekin xato bilan tugagan qo'shiqni qayta tayyorlash."""
    uid, _ = _uid(x_init_data)
    async with Session() as s:
        song = await _own(s, song_id, uid)
        again = song.paid and song.status == "failed"
        if again:
            song.status, song.error, song.updated_at = "paid_queued", "", utcnow()
            await s.commit()
        out = song_out(song)
    if again:
        await songflow.retried(song)
    songs.wake()
    return out


class ChooseIn(BaseModel):
    index: int = Field(ge=0, le=3)


@router.post("/api/songs/{song_id}/choose")
async def song_choose(song_id: int, body: ChooseIn, x_init_data: str = Header("")):
    uid, _ = _uid(x_init_data)
    async with Session() as s:
        song = await _own(s, song_id, uid)
        if not song.paid or song.status != "ready" or body.index >= len(song.variants or []):
            raise HTTPException(409, "Qo'shiq hali tayyor emas")
        song.chosen = body.index
        file = song.variants[body.index]["file"]
        if song.site_slug:  # saytga qo'yilgan bo'lsa — saytdagi musiqa ham almashadi
            site = (await s.execute(select(Site).where(Site.slug == song.site_slug))).scalar_one_or_none()
            if site and site.owner_id == uid:
                site.config = {**site.config, "music": file}
        await s.commit()
        return song_out(song)


class AttachIn(BaseModel):
    site: str = Field(max_length=40)


@router.post("/api/songs/{song_id}/attach")
async def song_attach(song_id: int, body: AttachIn, x_init_data: str = Header("")):
    """Tanlangan variantni sayt fon musiqasi qiladi."""
    uid, _ = _uid(x_init_data)
    async with Session() as s:
        song = await _own(s, song_id, uid)
        out = song_out(song)
        if not out["file"]:
            raise HTTPException(409, "Qo'shiq hali tayyor emas")
        site = (await s.execute(select(Site).where(Site.slug == body.site))).scalar_one_or_none()
        if not site or site.owner_id != uid or site.kind != "site":
            raise HTTPException(404)
        site.config = {**site.config, "music": out["file"]}
        song.site_slug = site.slug
        await s.commit()
        return song_out(song)
