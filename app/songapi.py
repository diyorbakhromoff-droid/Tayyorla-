"""Mini App: shaxsiy qo'shiq buyurtmasi (she'r, namuna, to'lov, variant tanlash, saytga qo'yish)."""

import logging

from fastapi import APIRouter, Header, HTTPException
from pydantic import BaseModel, Field
from sqlalchemy import select

from . import songs
from .config import settings
from .db import Session, Site, Song, User, utcnow
from .webapp import _rate_limit, check_init_data

log = logging.getLogger(__name__)
router = APIRouter()


def _uid(x_init_data: str) -> tuple[int, dict]:
    user = check_init_data(x_init_data)
    return int(user["id"]), user


def song_out(song: Song) -> dict:
    paid_files = [v.get("file") for v in (song.variants or []) if v.get("file")] if song.paid else []
    return {
        "id": song.id, "status": song.status, "recipient": song.recipient, "relation": song.relation, "occasion": song.occasion,
        "style": song.style, "voice": song.voice, "answers": {k: v for k, v in (song.answers or {}).items() if not k.startswith("_")},
        "title": song.title, "lyrics": song.lyrics, "preview": song.preview or None, "variants": paid_files,
        "chosen": song.chosen if paid_files else -1, "file": paid_files[song.chosen] if paid_files and 0 <= song.chosen < len(paid_files) else None,
        "paid": song.paid, "price": song.price, "site": song.site_slug or None, "error": song.error or None,
        "busy": song.status in ("preview_queued", "preview_gen", "paid_queued", "paid_gen"),
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
    return {**songs.meta(), "on": settings.songs_on, "price": price, "free_previews": left, "balance": user.balance if user else 0}


@router.get("/api/songs")
async def songs_list(x_init_data: str = Header("")):
    uid, _ = _uid(x_init_data)
    async with Session() as s:
        rows = (await s.execute(select(Song).where(Song.owner_id == uid).order_by(Song.id.desc()).limit(50))).scalars().all()
    return {"songs": [song_out(x) for x in rows]}


@router.get("/api/songs/{song_id}")
async def song_get(song_id: int, x_init_data: str = Header("")):
    uid, _ = _uid(x_init_data)
    async with Session() as s:
        return song_out(await _own(s, song_id, uid))


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
    _rate_limit(user)
    song = Song(owner_id=uid, recipient=body.recipient.strip(), relation=body.relation, occasion=body.occasion, style=body.style,
                voice=body.voice, answers=answers)
    try:
        song.title, song.lyrics, song.tags = await songs.write_lyrics(song)
    except Exception:
        log.exception("Qo'shiq matnini yozib bo'lmadi")
        raise HTTPException(502, "Hozir she'r yozib bo'lmadi, qayta urinib ko'ring")
    async with Session() as s:
        s.add(song)
        await s.commit()
        await s.refresh(song)
    return song_out(song)


class LyricsIn(BaseModel):
    text: str | None = Field(default=None, max_length=4000)        # qo'lda tahrirlangan matn
    instruction: str | None = Field(default=None, max_length=500)  # yoki AI ga istak: «quvnoqroq qil»
    title: str | None = Field(default=None, max_length=120)


@router.post("/api/songs/{song_id}/lyrics")
async def song_lyrics(song_id: int, body: LyricsIn, x_init_data: str = Header("")):
    uid, user = _uid(x_init_data)
    async with Session() as s:
        song = await _own(s, song_id, uid)
        if song.paid or song.status in ("preview_queued", "preview_gen"):
            raise HTTPException(409, "Qo'shiq yaratilgandan keyin matnni o'zgartirib bo'lmaydi")
        if body.instruction:
            _rate_limit(user)
            try:
                title, text, tags = await songs.write_lyrics(song, body.instruction)
            except Exception:
                log.exception("Qo'shiq matnini qayta yozib bo'lmadi")
                raise HTTPException(502, "Hozir she'r yozib bo'lmadi, qayta urinib ko'ring")
            song.title, song.lyrics, song.tags = title, text, tags or song.tags
        elif body.text is not None:
            sections = songs.parse_lyrics(body.text)
            try:
                songs.validate_lyrics(sections)
            except songs.SongError as e:
                raise HTTPException(400, str(e))
            song.lyrics = songs.render_lyrics(sections)
        if body.title:
            song.title = body.title.strip()
        # matn o'zgardi — eski namuna va yaratilgan variant endi mos emas
        song.preview, song.variants, song.plan, song.status, song.error, song.updated_at = "", [], {}, "lyrics", "", utcnow()
        await s.commit()
        return song_out(song)


@router.post("/api/songs/{song_id}/preview")
async def song_preview(song_id: int, x_init_data: str = Header("")):
    uid, _ = _uid(x_init_data)
    async with Session() as s:
        song = await _own(s, song_id, uid)
        if song.paid or song.preview or song.status != "lyrics":
            return song_out(song)
        try:
            songs.validate_lyrics(songs.parse_lyrics(song.lyrics))
        except songs.SongError as e:
            raise HTTPException(400, str(e))
        if await songs.free_previews_left(s, uid) <= 0:
            raise HTTPException(402, {"code": "preview_limit", "price": await songs.price_for(s, uid)})
        song.previews = (song.previews or 0) + 1
        song.status, song.error, song.updated_at = "preview_queued", "", utcnow()
        await s.commit()
        out = song_out(song)
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
            if not await songs.pay(s, song, uid):
                user = await s.get(User, uid)
                price = await songs.price_for(s, uid)
                raise HTTPException(402, {"code": "paywall", "need": price, "balance": user.balance if user else 0, "topups": settings.topups})
            await s.commit()
        out = song_out(song)
    songs.wake()
    return out


@router.post("/api/songs/{song_id}/retry")
async def song_retry(song_id: int, x_init_data: str = Header("")):
    """To'langan, lekin xato bilan tugagan qo'shiqni qayta yaratish."""
    uid, _ = _uid(x_init_data)
    async with Session() as s:
        song = await _own(s, song_id, uid)
        if song.paid and song.status == "failed":
            song.status, song.error, song.updated_at = "paid_queued", "", utcnow()
            await s.commit()
        out = song_out(song)
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
