"""Shaxsiy qo'shiq: she'r (Claude) -> 20 soniyalik namuna -> to'lov -> 2 ta variant (ElevenLabs Music).

Oqim:
  1. Foydalanuvchi kimga, qaysi munosabat bilan, uslub va savollarga javob beradi -> Claude o'zbekcha qo'shiq matnini yozadi.
  2. Matnni ko'radi, o'zgartiradi yoki AI dan qayta yozdiradi.
  3. Namuna: 1-variant to'liq yaratiladi (yopiq papkada), foydalanuvchiga faqat naqoratdan 20 soniya beriladi.
  4. To'lov: 2-variant yaratiladi, ikkala to'liq qo'shiq /media ga chiqadi, bot orqali yuboriladi, bittasini tanlaydi.
Qo'shiqlar /media/ ichida tekis nomda saqlanadi — sayt fon musiqasi va video uchun to'g'ridan-to'g'ri ishlatiladi.
"""

import asyncio
import json
import logging
import re
import secrets
import shutil
import subprocess
from pathlib import Path

import aiohttp
from sqlalchemy import func, select

from . import billing
from .config import MEDIA_DIR, ROOT, settings
from .db import Session, Site, Song, User, utcnow

log = logging.getLogger(__name__)

PRIVATE_DIR = ROOT / "data" / "songs"          # to'lanmagan to'liq qo'shiqlar — tashqariga berilmaydi
API_URL = "https://api.elevenlabs.io/v1/music"

# ---------------------------------------------------------------- katalog

# uslub: (nomi, inglizcha teglar, bitta qatorga ketadigan soniya — tempni bildiradi)
STYLES: dict[str, tuple[str, list[str], float]] = {
    "pop": ("Pop", ["modern pop", "catchy melodic hooks", "polished modern production", "mid-tempo groove"], 3.6),
    "rep": ("Rep", ["melodic hip hop", "rap verses with clear flow", "sung melodic chorus", "punchy drums", "deep 808 bass"], 3.0),
    "disko90": ("90-yillar disko", ["90s eurodisco", "retro analog synths", "four-on-the-floor beat", "upbeat and danceable"], 3.2),
    "rok": ("Rok", ["pop rock", "driving electric guitars", "live drums", "energetic anthemic chorus"], 3.4),
    "shanson": ("Shanson", ["chanson ballad", "accordion", "nylon-string guitar", "storytelling vocals", "nostalgic mood"], 3.8),
    "klassika": ("Klassika", ["orchestral pop ballad", "grand piano and string orchestra", "cinematic and elegant"], 4.2),
    "klub": ("Klub musiqasi", ["dance pop", "house beat", "bright synths", "festive club energy"], 3.0),
    "indi": ("Indi", ["indie pop", "dreamy chorus guitars", "warm lo-fi texture", "heartfelt and sincere"], 3.8),
    "xalqona": ("Xalqona", ["Uzbek folk song", "doira hand drum", "accordion and dutor", "festive celebration feel", "lively rhythm"], 3.4),
    "akustika": ("Akustika", ["acoustic ballad", "fingerpicked acoustic guitar", "soft piano", "intimate and warm"], 4.2),
    "milliy": ("O'zbek milliy", ["traditional Uzbek music", "dutor and rubab", "doira percussion", "Central Asian maqam-inspired melody",
                                "heartfelt and dignified"], 4.0),
    "custom": ("O'z janrim", [], 3.6),
}
VOICES = {"male": ("Erkak ovozi", "warm expressive male lead vocals"), "female": ("Ayol ovozi", "warm expressive female lead vocals")}
RELATIONS = {
    "sevgilim": "Sevgilim", "juftim": "Turmush o'rtog'im", "onam": "Onam", "otam": "Otam", "opa_singil": "Opam / singlim",
    "aka_uka": "Akam / ukam", "dostim": "Do'stim / dugonam", "farzandim": "Farzandim", "buvim_bobom": "Buvim / bobom", "boshqa": "Boshqa",
}
OCCASIONS = {
    "tugilgan_kun": "Tug'ilgan kun", "sevgi": "Sevgi izhori", "toy": "To'y / yubiley", "uzr": "Uzr so'rash",
    "rahmat": "Minnatdorchilik", "bayram": "Bayram tabrigi", "shunchaki": "Shunchaki, ko'nglini olish",
}
QUESTIONS = [
    ("xarakter", "U qanday inson? (bir necha so'z bilan)", "Masalan: mehribon, hazilkash, g'amxo'r"),
    ("xotira", "Birga esda qolgan bitta voqea yoki odati", "Masalan: har tong choy damlab kutadi"),
    ("erkalash", "Uni qanday erkalab chaqirasiz?", "Masalan: onajonim, quyoshim"),
    ("istak", "Qo'shiq orqali unga nima demoqchisiz?", "Masalan: rahmat, kechir, seni sevaman"),
    ("qoshimcha", "Qo'shimcha istak (ixtiyoriy)", "Masalan: quvnoq bo'lsin, ismi ko'p aytilsin"),
]
SECTION_LABEL = {"intro": "Kirish", "verse": "kuplet", "chorus": "Naqorat", "bridge": "Ko'prik", "outro": "Yakun"}
SECTION_EN = {"intro": "Intro", "verse": "Verse", "chorus": "Chorus", "bridge": "Bridge", "outro": "Outro"}


class SongError(Exception):
    """Foydalanuvchiga ko'rsatiladigan xato (o'zbekcha)."""


def meta() -> dict:
    return {
        "styles": [{"key": k, "name": v[0]} for k, v in STYLES.items()],
        "voices": [{"key": k, "name": v[0]} for k, v in VOICES.items()],
        "relations": [{"key": k, "name": v} for k, v in RELATIONS.items()],
        "occasions": [{"key": k, "name": v} for k, v in OCCASIONS.items()],
        "questions": [{"key": k, "label": a, "hint": b} for k, a, b in QUESTIONS],
        "preview_seconds": settings.song_preview_seconds,
        "demos": demos(),
    }


DEMO_DIR = ROOT / "static" / "songs" / "demo"


def demos() -> dict[str, str]:
    """Har uslub uchun tayyor namuna (bir marta yaratilgan, hamma uchun bepul): {uslub: url}."""
    return {k: f"/static/songs/demo/{k}.mp3" for k in STYLES if (DEMO_DIR / f"{k}.mp3").is_file()}


# ---------------------------------------------------------------- matn: bo'limlar <-> matn

def render_lyrics(sections: list[dict]) -> str:
    """[{kind, lines}] -> foydalanuvchiga ko'rinadigan matn: [1-kuplet], [Naqorat] ..."""
    out, n = [], 0
    for sec in sections:
        kind = sec.get("kind", "verse")
        if kind == "verse":
            n += 1
            head = f"[{n}-kuplet]"
        else:
            head = f"[{SECTION_LABEL.get(kind, 'kuplet')}]"
        lines = [ln.strip() for ln in sec.get("lines", []) if ln and ln.strip()]
        out.append("\n".join([head, *lines]))
    return "\n\n".join(out).strip()


def _kind_of(head: str) -> str:
    h = head.lower().replace("’", "'").replace("`", "'")
    for kind, keys in (("chorus", ("naqorat", "chorus", "qaytarma")), ("bridge", ("ko'prik", "kuprik", "bridge")),
                       ("outro", ("yakun", "xotima", "outro", "oxiri")), ("intro", ("kirish", "intro", "boshlanish")),
                       ("verse", ("kuplet", "verse", "band"))):
        if any(k in h for k in keys):
            return kind
    return "verse"


def parse_lyrics(text: str) -> list[dict]:
    """Foydalanuvchi tahrirlagan matnni bo'limlarga ajratadi. Sarlavhasiz qatorlar kupletga tushadi."""
    sections: list[dict] = []
    cur = None
    for raw in (text or "").replace("\r", "").split("\n"):
        line = raw.strip()
        m = re.fullmatch(r"\[(.{1,30})\]", line)
        if m:
            cur = {"kind": _kind_of(m.group(1)), "lines": []}
            sections.append(cur)
            continue
        if not line:
            continue
        if cur is None:
            cur = {"kind": "verse", "lines": []}
            sections.append(cur)
        cur["lines"].append(line[:200])
    # bo'sh kuplet/naqoratlarni tashlaymiz (kirish va yakun matnsiz ham bo'ladi)
    return [s for s in sections if s["lines"] or s["kind"] in ("intro", "outro")][:24]


def validate_lyrics(sections: list[dict]) -> None:
    sung = [s for s in sections if s["kind"] not in ("intro",) and s["lines"]]
    lines = sum(len(s["lines"]) for s in sung)
    if lines < 4:
        raise SongError("Qo'shiq matni juda qisqa: kamida 4 qator bo'lsin.")
    if lines > 44:
        raise SongError("Qo'shiq matni juda uzun: 44 qatordan oshmasin.")
    if not any(s["kind"] == "chorus" for s in sung):
        raise SongError("Matnda [Naqorat] bo'limi bo'lishi kerak.")


# ---------------------------------------------------------------- kompozitsiya rejasi

def build_plan(sections: list[dict], style: str, voice: str, tags: list[str]) -> tuple[dict, int, int]:
    """ElevenLabs uchun kompozitsiya rejasi. Natija: (reja, naqorat boshlanishi ms, naqorat uzunligi ms)."""
    name, base, per_line = STYLES.get(style, STYLES["pop"])
    common = ["sung in Uzbek language", "clear Uzbek pronunciation", VOICES.get(voice, VOICES["male"])[1], *base, *tags][:40]
    negative = ["English lyrics", "explicit content", "spoken word", "off-key vocals"]
    extra = {"intro": ["instrumental intro", "no vocals", "gentle build"], "verse": ["intimate verse", "lighter arrangement"],
             "chorus": ["emotional memorable chorus", "fuller arrangement", "strong melodic hook"],
             "bridge": ["contrasting bridge", "dynamic lift"], "outro": ["soft ending", "gradual fade out"]}
    chunks, t, chorus_at, chorus_len = [], 0, -1, 0
    has_intro = any(s["kind"] == "intro" for s in sections)
    secs = ([{"kind": "intro", "lines": []}] if not has_intro else []) + sections
    for sec in secs:
        kind, lines = sec["kind"], sec["lines"]
        if lines:
            dur = int(len(lines) * per_line * 1000 + 2500)
        else:
            dur = 7000 if kind == "intro" else 6000
        dur = max(3000, min(120000, dur))
        text = f"[{SECTION_EN.get(kind, 'Verse')}]" + ("\n" + "\n".join(lines) if lines else "")
        chunks.append({"text": text[:6000], "duration_ms": dur, "positive_styles": [*common, *extra.get(kind, [])][:50],
                       "negative_styles": negative if lines else [*negative, "vocals"], "context_adherence": "high"})
        if kind == "chorus" and chorus_at < 0:
            chorus_at, chorus_len = t, dur
        t += dur
    if not any(s["kind"] == "outro" for s in sections):
        chunks.append({"text": "[Outro]", "duration_ms": 6000, "positive_styles": [*common, *extra["outro"]][:50],
                       "negative_styles": [*negative, "vocals"], "context_adherence": "high"})
    return {"chunks": chunks[:30]}, max(0, chorus_at), chorus_len


# ---------------------------------------------------------------- she'r yozish (Claude)

LYRICS_SYSTEM = """Sen o'zbek tilida yozadigan iste'dodli shoir va qo'shiq matni muallifisan.
Vazifang: foydalanuvchi aytganlar asosida aynan o'sha insonga atalgan, samimiy va kuylash oson qo'shiq matni yozish.

Qoidalar:
- Faqat o'zbek tilida, lotin alifbosida yoz (o', g', sh, ch harflarini to'g'ri ishlat). Kuylanganda tabiiy eshitilsin.
- Tuzilish: 1-kuplet (4 qator), naqorat (4 qator, yaqin odamning ismi yoki erkalab chaqiriladigan ismi bilan), 2-kuplet (4 qator),
  naqorat (aynan takror), xohlasang 2 qatorli ko'prik, oxirida 1-2 qatorli yakun.
- Qatorlar qisqa va ritmik bo'lsin (6-11 bo'g'in), qofiyalansin. Har qator 60 belgidan oshmasin.
- Foydalanuvchi bergan tafsilotlarni (xarakter, xotira, erkalash, istak) tabiiy singdir — umumiy shablon gaplardan qoch.
- Uslubga moslash: rep — ritmik, so'z o'yini; xalqona va milliy — xalq qo'shiqlari ohangi, milliy obrazlar; klub va disko — quvnoq.
- Mashhur qo'shiqlardan qator olma, ijrochilar nomini tilga olma. Odob doirasida yoz: haqoratli, behayo yoki zararli mazmun yo'q.
- title — qo'shiq nomi (2-4 so'z, o'zbekcha).
- tags — ElevenLabs uchun 3-6 ta INGLIZCHA uslub tegi (janr, cholg'u, kayfiyat, temp). Ijrochi yoki qo'shiq nomlari YO'Q."""

LYRICS_SCHEMA = {
    "type": "object",
    "properties": {
        "title": {"type": "string"},
        "sections": {"type": "array", "items": {
            "type": "object",
            "properties": {"kind": {"type": "string", "enum": ["intro", "verse", "chorus", "bridge", "outro"]},
                           "lines": {"type": "array", "items": {"type": "string"}}},
            "required": ["kind", "lines"], "additionalProperties": False}},
        "tags": {"type": "array", "items": {"type": "string"}},
    },
    "required": ["title", "sections", "tags"],
    "additionalProperties": False,
}


def _brief(song: Song) -> str:
    a = song.answers or {}
    facts = {
        "kimga (ismi)": song.recipient, "kim bo'ladi": RELATIONS.get(song.relation, song.relation),
        "munosabat": OCCASIONS.get(song.occasion, song.occasion), "uslub": STYLES.get(song.style, STYLES["pop"])[0],
        "ovoz": VOICES.get(song.voice, VOICES["male"])[0],
        **{label: a.get(k, "") for k, label, _ in QUESTIONS if a.get(k)},
    }
    if song.style == "custom" and a.get("janr"):
        facts["o'z janri (tasvir)"] = a["janr"]
    return json.dumps(facts, ensure_ascii=False)


async def write_lyrics(song: Song, instruction: str = "") -> tuple[str, str, list[str]]:
    """(nomi, matn, teglar). instruction bo'lsa — joriy matnni shu istak bo'yicha qayta yozadi."""
    from . import ai
    prompt = f"Ma'lumotlar: {_brief(song)}"
    if instruction and song.lyrics:
        prompt += f"\n\nJoriy matn:\n{song.lyrics}\n\nFoydalanuvchi istagi bo'yicha qayta yoz: {instruction[:500]}"
    resp = await ai.client.beta.messages.create(
        **ai.COMMON_ARGS,
        max_tokens=6000,
        output_config={"effort": "high", "format": {"type": "json_schema", "schema": LYRICS_SCHEMA}},
        system=LYRICS_SYSTEM,
        messages=[{"role": "user", "content": prompt}],
    )
    out = json.loads(ai._text(resp))
    sections = [{"kind": s["kind"], "lines": [ln.strip()[:200] for ln in s["lines"] if ln.strip()]} for s in out["sections"]]
    tags = [re.sub(r"[^\w\s,&'-]", "", t)[:60] for t in out.get("tags", []) if t.strip()][:6]
    return out.get("title", "")[:120].strip() or "Qo'shiq", render_lyrics(sections), tags


# ---------------------------------------------------------------- ElevenLabs

async def compose(plan: dict) -> bytes:
    """Kompozitsiya rejasi bo'yicha mp3. Xatoda SongError (foydalanuvchiga tushunarli matn bilan)."""
    if not settings.elevenlabs_api_key:
        raise SongError("Qo'shiq xizmati hozircha sozlanmagan.")
    timeout = aiohttp.ClientTimeout(total=600)
    async with aiohttp.ClientSession(timeout=timeout) as http:
        async with http.post(API_URL, params={"output_format": "mp3_48000_192"},
                             headers={"xi-api-key": settings.elevenlabs_api_key, "accept": "audio/mpeg"},
                             json={"composition_plan": plan, "model_id": settings.song_model}) as r:
            if r.status == 200:
                data = await r.read()
                if len(data) < 10_000:
                    raise SongError("Qo'shiq yaratilmadi, qayta urinib ko'ring.")
                return data
            body = (await r.text())[:2000]
            log.warning("ElevenLabs music %s: %s", r.status, body)
            if "bad_prompt" in body or "bad_composition_plan" in body:
                raise SongError("Matnda mualliflik huquqi bilan himoyalangan so'z yoki nom bor. Matnni o'zgartirib ko'ring.")
            if r.status == 429:
                raise SongError("Navbat band, bir necha daqiqadan so'ng qayta urinib ko'ring.")
            raise SongError("Qo'shiq yaratishda xato bo'ldi, qayta urinib ko'ring.")


def cut_preview(src: Path, dst: Path, start_ms: int, seconds: int) -> None:
    """Naqoratdan seconds soniyalik bo'lak, boshida va oxirida yumshoq o'tish bilan."""
    dur = max(5, seconds)
    cmd = ["ffmpeg", "-nostdin", "-y", "-loglevel", "error", "-ss", f"{max(0, start_ms - 500) / 1000:.2f}", "-t", str(dur), "-i", str(src),
           "-af", f"afade=t=in:d=0.6,afade=t=out:st={dur - 1.8:.2f}:d=1.8", "-c:a", "libmp3lame", "-b:a", "128k", str(dst)]
    subprocess.run(cmd, check=True, timeout=120)


def _public_name(prefix: str) -> str:
    return f"{prefix}{secrets.token_urlsafe(9).replace('-', 'a').replace('_', 'b')}.mp3"


# ---------------------------------------------------------------- narx va namunalar

async def price_for(s, uid: int) -> int:
    """Sayt egasi uchun (song_site_price > 0 bo'lsa) arzonroq narx."""
    if settings.song_site_price > 0:
        has_site = await s.scalar(select(func.count()).select_from(Site).where(Site.owner_id == uid, Site.status == "paid", Site.kind == "site"))
        if has_site:
            return settings.song_site_price
    return settings.song_price


async def free_previews_left(s, uid: int) -> int:
    used = await s.scalar(select(func.coalesce(func.sum(Song.previews), 0)).where(Song.owner_id == uid, Song.paid.is_(False)))
    return max(0, settings.song_free_previews - (used or 0))


async def previews_today(s) -> int:
    """Bugun (Toshkent vaqti) so'ralgan bepul namunalar soni."""
    from .reminders import TZ
    from datetime import datetime, timezone
    start = datetime.now(TZ).replace(hour=0, minute=0, second=0, microsecond=0).astimezone(timezone.utc).replace(tzinfo=None)
    return await s.scalar(select(func.count()).select_from(Song).where(Song.preview_at >= start, Song.paid.is_(False))) or 0


async def pay(s, song: Song, uid: int) -> bool:
    """Balansdan to'laydi va to'liq yaratishni navbatga qo'yadi. Yetmasa False."""
    if song.paid:
        return True
    price = await price_for(s, uid)
    if not await billing.spend(s, uid, price, "song", f"song:{song.id}"):
        return False
    song.paid, song.price, song.status, song.error, song.updated_at = True, price, "paid_queued", "", utcnow()
    return True


# ---------------------------------------------------------------- kredit qoldig'i

_CREDITS: dict = {"at": 0.0, "data": None}
_ALERT = {"at": 0.0}


async def credits(force: bool = False) -> dict | None:
    """ElevenLabs obunasi: {tier, used, limit, remaining, reset}. 10 daqiqa keshlanadi. Kalit yoki ruxsat bo'lmasa None."""
    import time
    if not settings.elevenlabs_api_key:
        return None
    if not force and _CREDITS["data"] is not None and time.time() - _CREDITS["at"] < 600:
        return _CREDITS["data"]
    try:
        async with aiohttp.ClientSession(timeout=aiohttp.ClientTimeout(total=20)) as http:
            async with http.get("https://api.elevenlabs.io/v1/user/subscription", headers={"xi-api-key": settings.elevenlabs_api_key}) as r:
                if r.status != 200:
                    log.warning("ElevenLabs obunasini o'qib bo'lmadi: %s %s", r.status, (await r.text())[:300])
                    return None
                j = await r.json()
    except Exception:
        log.exception("ElevenLabs obunasini o'qib bo'lmadi")
        return None
    used, limit = int(j.get("character_count") or 0), int(j.get("character_limit") or 0)
    data = {"tier": j.get("tier", ""), "used": used, "limit": limit, "remaining": max(0, limit - used),
            "reset": j.get("next_character_count_reset_unix"), "songs_left": max(0, limit - used) // 1500,
            "usage_based": bool(j.get("can_extend_character_limit")) and bool(j.get("allowed_to_extend_character_limit"))}
    _CREDITS.update(at=time.time(), data=data)
    return data


async def check_credits(bot) -> None:
    """Kredit kam qolsa adminlarga ogohlantirish (12 soatda bir martadan ko'p emas)."""
    import time
    if not bot or not settings.song_credit_alert or time.time() - _ALERT["at"] < 12 * 3600:
        return
    c = await credits(force=True)
    if not c or c["remaining"] >= settings.song_credit_alert:
        return
    _ALERT["at"] = time.time()
    text = (f"⚠️ ElevenLabs krediti kam qoldi: {c['remaining']:,} (taxminan {c['songs_left']} ta qo'shiq).\n"
            f"Tarif: {c['tier']}. Avtomatik to'ldirish yoqilmagan bo'lsa, qo'shiq xizmati to'xtab qolishi mumkin.").replace(",", " ")
    for admin in settings.admins:
        try:
            await bot.send_message(admin, text)
        except Exception:
            log.exception("Adminga kredit ogohlantirishini yuborib bo'lmadi")


# ---------------------------------------------------------------- navbat

_wake = asyncio.Event()


def wake() -> None:
    _wake.set()


async def _generate_variant(song: Song) -> Path:
    sections = parse_lyrics(song.lyrics)
    plan, chorus_at, chorus_len = build_plan(sections, song.style, song.voice, song.tags or [])
    data = await compose(plan)
    PRIVATE_DIR.mkdir(parents=True, exist_ok=True)
    path = PRIVATE_DIR / f"{song.id}-{len(song.variants or [])}-{secrets.token_hex(4)}.mp3"
    path.write_bytes(data)
    song.plan = {**plan, "_chorus_at": chorus_at, "_chorus_len": chorus_len}
    song.variants = [*(song.variants or []), {"private": str(path), "file": ""}]
    return path


async def process(song_id: int, bot=None) -> None:
    async with Session() as s:
        song = await s.get(Song, song_id)
        if not song or song.status not in ("preview_gen", "paid_gen"):
            return
        mode = song.status
        try:
            if mode == "preview_gen":
                path = Path(song.variants[0]["private"]) if song.variants else await _generate_variant(song)
                dst = MEDIA_DIR / _public_name("songp")
                await asyncio.to_thread(cut_preview, path, dst, song.plan.get("_chorus_at", 0), settings.song_preview_seconds)
                song.preview, song.status = f"/media/{dst.name}", "preview_ready"
            else:
                while len(song.variants or []) < 2:
                    await _generate_variant(song)
                variants = []
                for v in song.variants:
                    if not v.get("file"):
                        dst = MEDIA_DIR / _public_name("song")
                        shutil.copyfile(v["private"], dst)
                        v = {**v, "file": f"/media/{dst.name}"}
                    variants.append(v)
                song.variants, song.status = variants, "ready"
                if song.chosen < 0:
                    song.chosen = 0
            song.error = ""
        except Exception as e:
            if isinstance(e, SongError):
                song.error = str(e)[:255]
            else:
                log.exception("Qo'shiq yaratishda kutilmagan xato: %s", song_id)
                song.error = "Qo'shiq yaratishda xato bo'ldi, qayta urinib ko'ring."
            if mode == "preview_gen":
                song.previews = max(0, (song.previews or 0) - 1)  # muvaffaqiyatsiz namuna bepul hisobdan qaytariladi
            song.status = "failed" if song.paid else "lyrics"
        song.updated_at = utcnow()
        await s.commit()
        await s.refresh(song)
    if bot:
        try:
            await notify(bot, song)
        except Exception:
            log.exception("Qo'shiq xabarini yuborib bo'lmadi: %s", song_id)


async def worker(bot=None) -> None:
    """Navbatdagi qo'shiqlarni yaratadi. Qayta ishga tushganda yarim qolganlarini davom ettiradi."""
    async with Session() as s:
        for song in (await s.execute(select(Song).where(Song.status.in_(("preview_gen", "paid_gen"))))).scalars().all():
            song.status = song.status.replace("_gen", "_queued")
        await s.commit()
    sem = asyncio.Semaphore(max(1, settings.song_workers))
    running: set[int] = set()
    import time
    last_check = 0.0

    async def run(sid: int) -> None:
        async with sem:
            try:
                await process(sid, bot)
            finally:
                running.discard(sid)

    while True:
        try:
            async with Session() as s:
                rows = (await s.execute(select(Song).where(Song.status.in_(("preview_queued", "paid_queued")))
                                        .order_by(Song.paid.desc(), Song.updated_at).limit(10))).scalars().all()
                todo = []
                for song in rows:
                    if song.id in running:
                        continue
                    song.status = song.status.replace("_queued", "_gen")
                    todo.append(song.id)
                await s.commit()
            for sid in todo:
                running.add(sid)
                asyncio.create_task(run(sid))
        except Exception:
            log.exception("Qo'shiq navbatida xato")
        if settings.songs_on and time.time() - last_check > 3600:
            last_check = time.time()
            try:
                await check_credits(bot)
            except Exception:
                log.exception("Kredit tekshiruvida xato")
        _wake.clear()
        try:
            await asyncio.wait_for(_wake.wait(), timeout=5)
        except asyncio.TimeoutError:
            pass


# ---------------------------------------------------------------- bot xabarlari

async def notify(bot, song: Song) -> None:
    from aiogram.types import FSInputFile, WebAppInfo
    from aiogram.utils.keyboard import InlineKeyboardBuilder

    from .videobot import app_url
    kb = InlineKeyboardBuilder()
    kb.button(text="🎵 Ilovada ochish", web_app=WebAppInfo(url=app_url(song=song.id)))
    title = song.title or "Qo'shiq"
    if song.status == "preview_ready" and song.preview:
        await bot.send_audio(song.owner_id, FSInputFile(MEDIA_DIR / Path(song.preview).name, filename=f"{title} — namuna.mp3"),
                             title=f"{title} (namuna)", performer="Tayyorla",
                             caption=f"🎧 «{title}» — {settings.song_preview_seconds} soniyalik namuna tayyor.\n"
                                     f"To'liq qo'shiq va ikkinchi variantni ilovada oling.", reply_markup=kb.as_markup())
    elif song.status == "ready":
        for i, v in enumerate(song.variants):
            await bot.send_audio(song.owner_id, FSInputFile(MEDIA_DIR / Path(v["file"]).name, filename=f"{title} — {i + 1}-variant.mp3"),
                                 title=f"{title} ({i + 1}-variant)", performer="Tayyorla",
                                 caption=(f"🎶 «{title}» tayyor! Ikkala variantni tinglab, ilovada bittasini tanlang — "
                                          f"uni saytingizga yoki videongizga qo'yish mumkin.") if i == len(song.variants) - 1 else None,
                                 reply_markup=kb.as_markup() if i == len(song.variants) - 1 else None)
    elif song.status in ("failed", "lyrics") and song.error:
        await bot.send_message(song.owner_id, f"⚠️ «{title}»: {song.error}", reply_markup=kb.as_markup())
