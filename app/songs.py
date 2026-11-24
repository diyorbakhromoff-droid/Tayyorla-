"""Shaxsiy qo'shiq: she'r (Claude) -> 20 soniyalik namuna -> to'lov -> namunadagi qo'shiqning to'liq o'zi (ElevenLabs Music).

Oqim:
  1. Foydalanuvchi kimga, qaysi munosabat bilan, uslub va savollarga javob beradi -> Claude o'zbekcha qo'shiq matnini yozadi.
  2. Matnni ko'radi, o'zgartiradi yoki AI dan qayta yozdiradi.
  3. Namuna: 1-variant to'liq tayyorlanadi (yopiq papkada), foydalanuvchiga faqat naqoratdan 20 soniya beriladi.
  4. To'lov: namuna kesilgan to'liq qo'shiq /media ga chiqadi va bot orqali yuboriladi (qo'shimcha ElevenLabs xarajati yo'q).
     Namunasiz to'langan bo'lsa, bitta to'liq qo'shiq tayyorlanadi.
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

from . import billing, costs, lyria
from .config import MEDIA_DIR, ROOT, RUNTIME, settings
from .db import Event, Session, Site, Song, User, utcnow

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


class QuotaError(SongError):
    """ElevenLabs krediti tugagan yoki kalit ishlamayapti."""


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
    """Har uslub uchun tayyor namuna (bir marta tayyorlangan, hamma uchun bepul): {uslub: url}."""
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
    song._lyrics_usage = resp.usage  # chaqiruvchi xarajat jurnaliga yozadi (app/costs.py)
    out = json.loads(ai._text(resp))
    sections = [{"kind": s["kind"], "lines": [ln.strip()[:200] for ln in s["lines"] if ln.strip()]} for s in out["sections"]]
    tags = [re.sub(r"[^\w\s,&'-]", "", t)[:60] for t in out.get("tags", []) if t.strip()][:6]
    return out.get("title", "")[:120].strip() or "Qo'shiq", render_lyrics(sections), tags


# ---------------------------------------------------------------- ElevenLabs

async def compose(plan: dict, store: bool = False, info: dict | None = None) -> bytes:
    """Kompozitsiya rejasi bo'yicha mp3. Xatoda SongError (foydalanuvchiga tushunarli matn bilan).
    store=True — ElevenLabs qo'shiqni keyingi inpainting uchun saqlaydi, uning raqami info["song_id"] ga yoziladi."""
    if not settings.elevenlabs_api_key:
        raise SongError("Qo'shiq xizmati hozircha sozlanmagan.")
    body = {"composition_plan": plan, "model_id": settings.song_model}
    if store:
        body["store_for_inpainting"] = True
    timeout = aiohttp.ClientTimeout(total=600)
    async with aiohttp.ClientSession(timeout=timeout) as http:
        async with http.post(API_URL, params={"output_format": "mp3_48000_192"},
                             headers={"xi-api-key": settings.elevenlabs_api_key, "accept": "audio/mpeg"},
                             json=body) as r:
            if r.status == 200:
                data = await r.read()
                if len(data) < 5_000:
                    raise SongError("Qo'shiq tayyorlanmadi, qayta urinib ko'ring.")
                if info is not None:
                    info["song_id"] = r.headers.get("song-id", "")
                return data
            body = (await r.text())[:2000]
            log.warning("ElevenLabs music %s: %s", r.status, body)
            if "bad_prompt" in body or "bad_composition_plan" in body:
                raise SongError("Matnda mualliflik huquqi bilan himoyalangan so'z yoki nom bor. Matnni o'zgartirib ko'ring.")
            if r.status == 429:
                raise SongError("Navbat band, bir necha daqiqadan so'ng qayta urinib ko'ring.")
            if "quota" in body or "credit" in body or r.status in (401, 402):
                _CREDITS.update(at=0.0, data=None)  # keyingi tekshiruv yangidan o'qisin
                _ALERT["at"] = 0.0                  # adminga darhol ogohlantirish
                raise QuotaError("Qo'shiq xizmati vaqtincha band. Birozdan so'ng qayta urinib ko'ring — buyurtmangiz saqlanib qoladi.")
            raise SongError("Qo'shiq tayyorlashda xato bo'ldi, qayta urinib ko'ring.")


# Ovoz musiqadan past chiqsa so'zlar eshitilmaydi. Alohida yo'laklar (stem) yo'q, shuning uchun:
# o'rtadagi (markaz) kanal — ovoz — yon kanallarga nisbatan balandroq, ovoz chastotalari (2–5 kHz) ko'tariladi,
# bo'g'iq past-o'rta chastotalar (250 Hz) pasaytiriladi, keyin yumshoq kompressor va bir xil balandlik (-14 LUFS).
MIX = {
    "off": "",
    "soft": ("aformat=channel_layouts=stereo,highpass=f=50,equalizer=f=250:t=q:w=1:g=-2,equalizer=f=3000:t=q:w=1.2:g=3,"
             "equalizer=f=5500:t=q:w=1.5:g=1,stereotools=mlev=1:slev=0.8,"
             "acompressor=threshold=-20dB:ratio=2.5:attack=8:release=160,loudnorm=I=-14:TP=-1.2:LRA=11"),
    "strong": ("aformat=channel_layouts=stereo,highpass=f=60,equalizer=f=250:t=q:w=1:g=-3.5,equalizer=f=3000:t=q:w=1.2:g=5,"
               "equalizer=f=5500:t=q:w=1.5:g=2,stereotools=mlev=1:slev=0.65,"
               "acompressor=threshold=-22dB:ratio=3:attack=6:release=150,loudnorm=I=-14:TP=-1.2:LRA=10"),
}
MIX_DEFAULT = "soft"


async def mix_level() -> str:
    v = (await music_cfg()).get("mix", MIX_DEFAULT)
    return v if v in MIX else MIX_DEFAULT


def cut_preview(src: Path, dst: Path, start_ms: int, seconds: int, mix: str = "") -> None:
    """Naqoratdan seconds soniyalik bo'lak, boshida va oxirida yumshoq o'tish bilan (mix — ovozni oldinga chiqarish)."""
    dur = max(5, seconds)
    chain = (MIX.get(mix, "") + ",") if MIX.get(mix) else ""
    cmd = ["ffmpeg", "-nostdin", "-y", "-loglevel", "error", "-ss", f"{max(0, start_ms - 500) / 1000:.2f}", "-t", str(dur), "-i", str(src),
           "-af", f"{chain}afade=t=in:d=0.6,afade=t=out:st={dur - 1.8:.2f}:d=1.8", "-c:a", "libmp3lame", "-b:a", "128k", str(dst)]
    try:
        subprocess.run(cmd, check=True, timeout=180)
    except subprocess.CalledProcessError:
        if not chain:
            raise
        log.warning("Aralashtirish ishlamadi, namuna ishlovsiz kesiladi: %s", src)
        cut_preview(src, dst, start_ms, seconds, "")


def apply_mix(src: Path, dst: Path, mix: str) -> None:
    """To'liq qo'shiq: ovozni oldinga chiqarib dst ga yozadi (src o'zgarmaydi). Xatoda — oddiy nusxa."""
    chain = MIX.get(mix, "")
    if not chain:
        shutil.copyfile(src, dst)
        return
    tmp = dst.with_name(dst.stem + ".mixtmp.mp3")
    try:
        subprocess.run(["ffmpeg", "-nostdin", "-y", "-loglevel", "error", "-i", str(src), "-af", chain,
                        "-c:a", "libmp3lame", "-b:a", "192k", str(tmp)], check=True, timeout=600)
        tmp.replace(dst)
    except Exception:
        log.warning("Aralashtirish ishlamadi, qo'shiq ishlovsiz beriladi: %s", src)
        tmp.unlink(missing_ok=True)
        if src != dst:
            shutil.copyfile(src, dst)


def _public_name(prefix: str) -> str:
    return f"{prefix}{secrets.token_urlsafe(9).replace('-', 'a').replace('_', 'b')}.mp3"


# ---------------------------------------------------------------- narx va namunalar

async def price_for(s, uid: int, song: Song | None = None) -> int:
    """Sayt egasi uchun (song_site_price > 0 bo'lsa) arzonroq narx; qo'shiqda faol chegirma bo'lsa — chegirma narxi."""
    price = settings.song_price
    if settings.song_site_price > 0:
        has_site = await s.scalar(select(func.count()).select_from(Site).where(Site.owner_id == uid, Site.status == "paid", Site.kind == "site"))
        if has_site:
            price = settings.song_site_price
    if song is not None:
        from .pricing import promo_of
        promo = promo_of(song)
        if promo:
            price = min(price, promo["price"])
    return price


PV_EVENT = "song_pv"  # har bir bepul namuna so'rovi — kunlik limitlar shu hodisalar bo'yicha sanaladi


async def limits() -> tuple[int, int]:
    """(bir kishiga kuniga bepul namuna, hamma uchun kuniga jami; 0 — cheklovsiz). Admin paneldan o'zgaradi."""
    from . import store
    v = await store.get("song_limits") or {}
    return max(0, int(v.get("per_user", settings.song_free_previews))), max(0, int(v.get("per_day", settings.song_daily_previews)))


async def user_limits() -> dict:
    """Bir kishiga: bepul namuna (kuniga / jami) va she'r yozish (kuniga / jami). 0 — cheklovsiz (jami uchun)."""
    from . import store
    v = await store.get("song_limits") or {}
    g = lambda k, d: max(0, int(v.get(k, d)))  # noqa: E731
    return {"pv_day": g("per_user", settings.song_free_previews), "pv_total": g("pv_total", settings.song_previews_total),
            "ly_day": g("ly_day", settings.song_lyrics_per_day), "ly_total": g("ly_total", settings.song_lyrics_total)}


async def previews_used_total(s, uid: int) -> int:
    return await s.scalar(select(func.count()).select_from(Event).where(Event.user_id == uid, Event.kind == PV_EVENT)) or 0


async def free_previews_left(s, uid: int) -> int:
    """Foydalanuvchining bugungi (Toshkent vaqti) qolgan bepul namunalari (umumiy chegara ham hisobga olinadi)."""
    lim = await user_limits()
    used = await s.scalar(select(func.count()).select_from(Event).where(
        Event.user_id == uid, Event.kind == PV_EVENT, Event.created_at >= billing.day_start_utc()))
    left = max(0, lim["pv_day"] - (used or 0))
    if lim["pv_total"]:
        left = min(left, max(0, lim["pv_total"] - await previews_used_total(s, uid)))
    return left


# ---------------------------------------------------------------- namuna faqat ilova ichida

def _sig(song_id: int, name: str, day: int) -> str:
    import hashlib
    import hmac
    return hmac.new(settings.bot_token.encode(), f"pv:{song_id}:{name}:{day}".encode(), hashlib.sha256).hexdigest()[:24]


def preview_path(song: Song) -> Path | None:
    """Yopiq namuna fayli (song.preview = «pv:<nom>»). Eski namunalar /media da — None."""
    if song.preview and song.preview.startswith("pv:"):
        return PRIVATE_DIR / Path(song.preview[3:]).name
    return None


def preview_url(song: Song) -> str | None:
    """Ilova pleeri uchun imzolangan havola: kun davomida o'zgarmaydi, 2 kundan keyin ishlamaydi."""
    if not song.preview:
        return None
    path = preview_path(song)
    if path is None:
        return song.preview
    import time
    day = int(time.time() // 86400)
    return f"/api/songs/{song.id}/listen?d={day}&t={_sig(song.id, path.name, day)}"


def preview_ok(song: Song, d: int, t: str) -> bool:
    import hmac
    import time
    path = preview_path(song)
    today = int(time.time() // 86400)
    return bool(path) and d in (today, today - 1) and hmac.compare_digest(t, _sig(song.id, path.name, d))


def count_preview(s, song: Song) -> None:
    s.add(Event(user_id=song.owner_id, kind=PV_EVENT, src=str(song.id)))


async def refund_preview(s, song: Song) -> None:
    """Muvaffaqiyatsiz namuna bepul hisobdan qaytariladi."""
    ev = (await s.execute(select(Event).where(Event.user_id == song.owner_id, Event.kind == PV_EVENT, Event.src == str(song.id))
                          .order_by(Event.id.desc()).limit(1))).scalar_one_or_none()
    if ev:
        await s.delete(ev)


SONG_VARIANTS = 1  # to'lovdan keyin beriladigan to'liq qo'shiqlar soni (namunadagi qo'shiq qayta ishlatiladi)


# ---------------------------------------------------------------- musiqa xizmati (ElevenLabs yoki Google Lyria)

MUSIC_KEY = "music"


async def music_cfg() -> dict:
    """Admin paneldagi sozlama: {provider, gemini_key, lang}. Kalit xotiraga ham yuklanadi (settings.gemini_key)."""
    from . import store
    v = await store.get(MUSIC_KEY) or {}
    RUNTIME["gemini_key"] = v.get("gemini_key", "")
    return v


async def provider() -> str:
    """Hozir ishlatiladigan xizmat. Tanlangan xizmatning kaliti bo'lmasa — kaliti bor boshqasi."""
    v = await music_cfg()
    want = v.get("provider", settings.song_provider)
    if want == "lyria" and settings.gemini_key:
        return "lyria"
    if settings.elevenlabs_api_key:
        return "elevenlabs"
    return "lyria" if settings.gemini_key else "elevenlabs"


def credits_needed(song: Song, variants: int) -> int:
    """Qo'shiq tayyorlash uchun taxminiy kredit: sinovda 100 s ≈ 1500 kredit."""
    plan, _, _ = build_plan(parse_lyrics(song.lyrics), song.style, song.voice, song.tags or [])
    seconds = sum(c["duration_ms"] for c in plan["chunks"]) / 1000
    return int(seconds * 15 * variants) + 100


def chorus_parts(plan: dict, chorus_at: int) -> list[int]:
    """Rejadagi naqorat bo'limlari (birinchi naqorat bilan bir xil matnli hamma bo'limlar)."""
    t, first = 0, None
    for i, c in enumerate(plan["chunks"]):
        if t == chorus_at and c["text"].startswith("[Chorus]"):
            first = i
            break
        t += c["duration_ms"]
    if first is None:
        return []
    text = plan["chunks"][first]["text"]
    return [i for i, c in enumerate(plan["chunks"]) if c["text"] == text]


def preview_credits(song: Song) -> int:
    """Namuna uchun taxminiy kredit (naqorat usulida faqat naqorat)."""
    if settings.song_preview_mode != "chorus":
        return credits_needed(song, 1)
    plan, chorus_at, chorus_len = build_plan(parse_lyrics(song.lyrics), song.style, song.voice, song.tags or [])
    return int(chorus_len / 1000 * 15) + 100 if chorus_parts(plan, chorus_at) else credits_needed(song, 1)


def full_credits(song: Song) -> int:
    """To'lovdan keyin kerak bo'ladigan kredit: tayyor qo'shiq bo'lsa 0, naqorat saqlangan bo'lsa — qolgan qismlar."""
    if song.variants:
        return 0
    demo = (song.plan or {}).get("_demo") or {}
    plan, chorus_at, _ = build_plan(parse_lyrics(song.lyrics), song.style, song.voice, song.tags or [])
    if demo.get("song_id"):
        parts = set(chorus_parts(plan, chorus_at))
        return int(sum(c["duration_ms"] for i, c in enumerate(plan["chunks"]) if i not in parts) / 1000 * 15) + 100
    return credits_needed(song, 1)


async def enough_credits(need: int) -> bool:
    """Kredit ma'lum bo'lsa va yetmasa False. O'qib bo'lmasa — ruxsat (xizmat to'xtab qolmasin)."""
    c = await credits()
    if not c or c.get("usage_based"):
        return True
    return c["remaining"] >= need


async def previews_today(s) -> int:
    """Bugun (Toshkent vaqti) hamma foydalanuvchilar so'ragan bepul namunalar soni."""
    return await s.scalar(select(func.count()).select_from(Event).where(
        Event.kind == PV_EVENT, Event.created_at >= billing.day_start_utc())) or 0


async def pay(s, song: Song, uid: int) -> bool:
    """Balansdan to'laydi va to'liq tayyorlashni navbatga qo'yadi. Yetmasa False."""
    if song.paid:
        return True
    from .pricing import use_credit
    if await use_credit(s, uid, song):  # paketdagi qo'shiq — pul yechilmaydi
        song.paid, song.price, song.status, song.error, song.updated_at = True, 0, "paid_queued", "", utcnow()
        return True
    price = await price_for(s, uid, song)
    if not await billing.spend(s, uid, price, "song", f"song:{song.id}"):
        return False
    from .pricing import EV_BUY, log_event, promo_of
    promo = promo_of(song)
    if promo and price == promo["price"]:
        await log_event(uid, EV_BUY, song.id, s=s)  # chegirmada sotib oldi (kunlik hisobot uchun)
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
    left = f"{c['remaining']:,}".replace(",", " ")
    text = (f"⚠️ ElevenLabs krediti kam qoldi: {left} (taxminan {c['songs_left']} ta qo'shiq).\n"
            f"Tarif: {c['tier']}. Avtomatik to'ldirish yoqilmagan bo'lsa, qo'shiq xizmati to'xtab qolishi mumkin.")
    for admin in settings.admins:
        try:
            await bot.send_message(admin, text)
        except Exception:
            log.exception("Adminga kredit ogohlantirishini yuborib bo'lmadi")


# ---------------------------------------------------------------- navbat

_wake = asyncio.Event()


def wake() -> None:
    _wake.set()


async def _generate_variant(s, song: Song, purpose: str) -> Path:
    sections = parse_lyrics(song.lyrics)
    plan, chorus_at, chorus_len = build_plan(sections, song.style, song.voice, song.tags or [])
    data = await compose(plan)
    # ElevenLabs har bir tayyorlash uchun to'liq qo'shiq narxini oladi (namuna ham to'liq qo'shiqdan kesiladi)
    s.add(costs.music_row(sum(c["duration_ms"] for c in plan["chunks"]) / 1000, purpose, song.owner_id, f"song:{song.id}"))
    PRIVATE_DIR.mkdir(parents=True, exist_ok=True)
    path = PRIVATE_DIR / f"{song.id}-{len(song.variants or [])}-{secrets.token_hex(4)}.mp3"
    path.write_bytes(data)
    song.plan = {**plan, "_chorus_at": chorus_at, "_chorus_len": chorus_len}
    song.variants = [*(song.variants or []), {"private": str(path), "file": ""}]
    return path


def _audio_ms(path: Path) -> int:
    try:
        out = subprocess.run(["ffprobe", "-v", "error", "-show_entries", "format=duration", "-of", "csv=p=0", str(path)],
                             capture_output=True, text=True, timeout=30).stdout.strip()
        return int(float(out) * 1000)
    except Exception:
        return 0


def audible_range(path: Path, total_ms: int = 0) -> tuple[int, int]:
    """Yozuvning ovozli qismi (boshidagi va oxiridagi jimlik/so'nish tashlanadi).
    Alohida tayyorlangan naqorat oxirida «qo'shiq yakuni» jimligi bo'ladi — uni qo'shiq ichiga qo'ysak, kupletlar orasida pauza qoladi."""
    total_ms = total_ms or _audio_ms(path)
    try:
        err = subprocess.run(["ffmpeg", "-nostdin", "-hide_banner", "-i", str(path), "-af", "silencedetect=noise=-35dB:d=0.25", "-f", "null", "-"],
                             capture_output=True, text=True, timeout=60).stderr
    except Exception:
        return 0, total_ms
    starts = [float(x) for x in re.findall(r"silence_start: (-?[\d.]+)", err)]
    ends = [float(x) for x in re.findall(r"silence_end: ([\d.]+)", err)]
    begin, end = 0, total_ms
    if starts and starts[0] <= 0.05 and ends:
        begin = int(ends[0] * 1000)
    if starts and starts[-1] > 0.05 and (len(ends) < len(starts) or ends[-1] * 1000 >= total_ms - 150):
        end = int(starts[-1] * 1000)
    begin, end = max(0, begin - 60), min(total_ms, end + 120)  # yumshoq kirish va chiqish uchun ozgina zaxira
    return (begin, end) if end - begin >= 3000 else (0, total_ms)


async def _generate_chorus_demo(s, song: Song) -> Path | None:
    """Namuna: faqat naqorat tayyorlanadi va ElevenLabs'da saqlanadi. Naqorat topilmasa None (eski usul ishlaydi)."""
    plan, chorus_at, chorus_len = build_plan(parse_lyrics(song.lyrics), song.style, song.voice, song.tags or [])
    parts = chorus_parts(plan, chorus_at)
    if not parts:
        return None
    info: dict = {}
    # naqorat keyin qo'shiq o'rtasiga qo'yiladi — alohida qo'shiqdek tugamasin (so'nish va oxiridagi jimliksiz)
    chunk = dict(plan["chunks"][parts[0]])
    chunk["negative_styles"] = [*chunk.get("negative_styles", []), "fade out", "song ending", "silence at the end"][:50]
    data = await compose({"chunks": [chunk]}, store=True, info=info)
    s.add(costs.music_row(chorus_len / 1000, "song_preview", song.owner_id, f"song:{song.id}"))
    PRIVATE_DIR.mkdir(parents=True, exist_ok=True)
    path = PRIVATE_DIR / f"{song.id}-demo-{secrets.token_hex(4)}.mp3"
    path.write_bytes(data)
    ms = await asyncio.to_thread(_audio_ms, path) or chorus_len
    if not info.get("song_id"):
        log.warning("ElevenLabs naqorat uchun song-id qaytarmadi (song %s) — to'liq qo'shiq oddiy usulda tayyorlanadi", song.id)
    song.plan = {"_demo": {"song_id": info.get("song_id", ""), "private": str(path), "ms": ms}, "_chorus_at": 0, "_chorus_len": ms}
    return path


async def _generate_from_demo(s, song: Song) -> Path | None:
    """To'liq qo'shiq: har bir naqorat — namunadagi yozuvning o'zi, qolgan qismlar shu naqoratga tayanib tayyorlanadi.
    Saqlangan naqorat bo'lmasa yoki ElevenLabs rad etsa None (oddiy to'liq qo'shiq tayyorlanadi)."""
    demo = (song.plan or {}).get("_demo") or {}
    if not demo.get("song_id"):
        return None
    plan, chorus_at, _ = build_plan(parse_lyrics(song.lyrics), song.style, song.voice, song.tags or [])
    parts = set(chorus_parts(plan, chorus_at))
    if not parts:
        return None
    ms = int(demo.get("ms") or 0)
    begin, end = 0, ms
    if demo.get("private") and Path(demo["private"]).exists():  # naqorat oxiridagi «yakun» jimligisiz
        begin, end = await asyncio.to_thread(audible_range, Path(demo["private"]), ms)
    ms = end - begin
    ref = {"song_id": demo["song_id"], "range": {"start_ms": begin, "end_ms": end}}
    chunks, conditioned, t, first_chorus, gen_ms = [], False, 0, None, 0
    for i, c in enumerate(plan["chunks"]):
        if i in parts:
            if first_chorus is None:
                first_chorus = t
            chunks.append({**ref, "range": dict(ref["range"])})
            t += ms
            continue
        c = dict(c)
        if not conditioned:  # birinchi bo'lim butun qo'shiqni naqorat ovozi va kuyiga bog'laydi
            c["conditioning_ref"] = {"song_id": demo["song_id"], "range": {"start_ms": begin, "end_ms": begin + min(ms, 30000)}}
            c["condition_strength"] = "high"
            conditioned = True
        chunks.append(c)
        t += c["duration_ms"]
        gen_ms += c["duration_ms"]
    try:
        data = await compose({"chunks": chunks})
    except QuotaError:
        raise
    except SongError as e:
        log.warning("Naqoratdan to'liq qo'shiq yasab bo'lmadi (song %s): %s — oddiy usulga o'tiladi", song.id, e)
        return None
    s.add(costs.music_row(gen_ms / 1000, "song_full", song.owner_id, f"song:{song.id}"))
    PRIVATE_DIR.mkdir(parents=True, exist_ok=True)
    path = PRIVATE_DIR / f"{song.id}-0-{secrets.token_hex(4)}.mp3"
    path.write_bytes(data)
    song.plan = {**song.plan, "_chorus_at": first_chorus or 0, "_chorus_len": ms}
    song.variants = [{"private": str(path), "file": ""}]
    return path


async def _generate_lyria(s, song: Song, purpose: str) -> Path:
    """Lyria: bitta to'liq qo'shiq. Namuna shu qo'shiqning naqoratidan kesiladi, sotilsa aynan shu qo'shiq beriladi."""
    sections = parse_lyrics(song.lyrics)
    plan, chorus_at, _ = build_plan(sections, song.style, song.voice, song.tags or [])
    total = sum(c["duration_ms"] for c in plan["chunks"])
    name, base, _ = STYLES.get(song.style, STYLES["pop"])
    lang = (await music_cfg()).get("lang", "uz")
    text = lyria.prompt(sections, name, base, song.voice, OCCASIONS.get(song.occasion, song.occasion or ""),
                        list(song.tags or []), total / 1000, lang)
    try:
        data, info = await lyria.compose(text)
    except lyria.LyriaError as e:
        if e.quota:
            _ALERT["at"] = 0.0
            raise QuotaError(str(e))
        raise SongError(str(e))
    s.add(costs.lyria_row(purpose, song.owner_id, f"song:{song.id}", settings.lyria_model))
    PRIVATE_DIR.mkdir(parents=True, exist_ok=True)
    path = PRIVATE_DIR / f"{song.id}-l-{secrets.token_hex(4)}.mp3"
    path.write_bytes(data)
    ms = await asyncio.to_thread(_audio_ms, path) or total
    at = lyria.chorus_seconds(info)
    at_ms = int(at * 1000) if at is not None and 0 <= at * 1000 < ms - 8000 else int(ms * chorus_at / max(1, total))
    song.plan = {"_provider": "lyria", "_chorus_at": at_ms, "_chorus_len": 20000, "_lyria_text": (info or "")[:3000]}
    song.variants = [{"private": str(path), "file": ""}]
    return path


async def _generate_lyria_clip(s, song: Song) -> Path:
    """Namuna: Lyria Clip faqat naqoratni kuylaydi (30 s). To'liq qo'shiq sotilganda alohida tayyorlanadi —
    kuy biroz farq qilishi mumkin (egasi shunga rozi: namuna tez va arzon bo'lsin)."""
    sections = parse_lyrics(song.lyrics)
    chorus = [x for x in sections if x["kind"] == "chorus" and x["lines"]][:1] or [x for x in sections if x["lines"]][:1]
    name, base, _ = STYLES.get(song.style, STYLES["pop"])
    lang = (await music_cfg()).get("lang", "uz")
    text = lyria.prompt(chorus, name, base, song.voice, OCCASIONS.get(song.occasion, song.occasion or ""),
                        list(song.tags or []), 30, lang, clip=True)
    try:
        data, info = await lyria.compose(text, settings.lyria_clip_model)
    except lyria.LyriaError as e:
        if e.quota:
            _ALERT["at"] = 0.0
            raise QuotaError(str(e))
        raise SongError(str(e))
    s.add(costs.lyria_row("song_preview", song.owner_id, f"song:{song.id}", settings.lyria_clip_model))
    PRIVATE_DIR.mkdir(parents=True, exist_ok=True)
    path = PRIVATE_DIR / f"{song.id}-clip-{secrets.token_hex(4)}.mp3"
    path.write_bytes(data)
    ms = await asyncio.to_thread(_audio_ms, path) or 30000
    begin, _ = await asyncio.to_thread(audible_range, path, ms)  # boshidagi jimlikni o'tkazib yuboramiz
    song.plan = {"_provider": "lyria", "_demo": {"private": str(path), "ms": ms, "clip": True},
                 "_chorus_at": begin, "_chorus_len": ms}
    return path


async def process(song_id: int, bot=None) -> None:
    async with Session() as s:
        song = await s.get(Song, song_id)
        if not song or song.status not in ("preview_gen", "paid_gen"):
            return
        mode = song.status
        try:
            if mode == "preview_gen":
                if song.variants:
                    path = Path(song.variants[0]["private"])
                elif (song.plan or {}).get("_demo", {}).get("private") and Path(song.plan["_demo"]["private"]).exists():
                    path = Path(song.plan["_demo"]["private"])
                elif await provider() == "lyria":
                    path = await _generate_lyria_clip(s, song)
                else:
                    path = None
                    if settings.song_preview_mode == "chorus":
                        path = await _generate_chorus_demo(s, song)
                    if path is None:
                        path = await _generate_variant(s, song, "song_preview")
                # namuna ochiq /media da emas: faqat ilova ichida imzolangan havola orqali eshitiladi
                PRIVATE_DIR.mkdir(parents=True, exist_ok=True)
                dst = PRIVATE_DIR / f"{song.id}-pv-{secrets.token_hex(6)}.mp3"
                mix = await mix_level()
                await asyncio.to_thread(cut_preview, path, dst, song.plan.get("_chorus_at", 0), settings.song_preview_seconds, mix)
                song.preview, song.status = f"pv:{dst.name}", "preview_ready"
                song.plan = {**(song.plan or {}), "_mix_pv": mix}
            else:
                if not song.variants:
                    await _generate_from_demo(s, song)  # namunadagi naqoratdan (o'sha kuy va ovoz)
                if not song.variants and await provider() == "lyria":
                    await _generate_lyria(s, song, "song_full")
                while len(song.variants or []) < SONG_VARIANTS:
                    await _generate_variant(s, song, "song_full")
                variants = []
                mix = await mix_level()
                for v in song.variants:
                    if not v.get("file"):
                        dst = MEDIA_DIR / _public_name("song")
                        await asyncio.to_thread(apply_mix, Path(v["private"]), dst, mix)
                        v = {**v, "file": f"/media/{dst.name}"}
                    variants.append(v)
                song.variants, song.status = variants, "ready"
                song.plan = {**(song.plan or {}), "_mix_full": mix}
                if song.chosen < 0:
                    song.chosen = 0
            song.error = ""
        except Exception as e:
            if isinstance(e, SongError):
                song.error = str(e)[:255]
            else:
                log.exception("Qo'shiq tayyorlashda kutilmagan xato: %s", song_id)
                song.error = "Qo'shiq tayyorlashda xato bo'ldi, qayta urinib ko'ring."
            if mode == "preview_gen":
                song.previews = max(0, (song.previews or 0) - 1)  # muvaffaqiyatsiz namuna bepul hisobdan qaytariladi
                await refund_preview(s, song)
            song.status = "failed" if song.paid else "lyrics"
        song.updated_at = utcnow()
        await s.commit()
        await s.refresh(song)
    if bot:
        try:
            await notify(bot, song)
        except Exception:
            log.exception("Qo'shiq xabarini yuborib bo'lmadi: %s", song_id)
        if song.error and "vaqtincha band" in song.error:
            try:
                await check_credits(bot)
            except Exception:
                log.exception("Kredit ogohlantirishida xato")


async def worker(bot=None) -> None:
    """Navbatdagi qo'shiqlarni tayyorlaydi. Qayta ishga tushganda yarim qolganlarini davom ettiradi."""
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
        # namuna faylini yubormaymiz — faqat ilova ichida tinglanadi (yuklab olib bo'lmasin)
        tk = InlineKeyboardBuilder()
        tk.button(text="🎧 Ilovada tinglash", web_app=WebAppInfo(url=app_url(song=song.id)))
        await bot.send_message(song.owner_id, f"🎧 «{title}» — {settings.song_preview_seconds} soniyalik namuna tayyor!\n"
                                              f"Ilovada tinglang. Yoqsa, to'liq qo'shiqni shu yerda olasiz.", reply_markup=tk.as_markup())
    elif song.status == "ready":
        many = len(song.variants) > 1  # eski buyurtmalarda 2 ta variant bo'lishi mumkin
        for i, v in enumerate(song.variants):
            last = i == len(song.variants) - 1
            name = f"{title} — {i + 1}-variant" if many else title
            await bot.send_audio(song.owner_id, FSInputFile(MEDIA_DIR / Path(v["file"]).name, filename=f"{name}.mp3"),
                                 title=f"{title} ({i + 1}-variant)" if many else title, performer="Tayyorla",
                                 caption=(f"🎶 «{title}» tayyor! Uni ilovadan saytingizga yoki videongizga qo'yishingiz mumkin.")
                                 if last else None,
                                 reply_markup=kb.as_markup() if last else None)
    elif song.status in ("failed", "lyrics") and song.error:
        await bot.send_message(song.owner_id, f"⚠️ «{title}»: {song.error}", reply_markup=kb.as_markup())

# ---------------------------------------------------------------- Lyria sinovi (admin paneldagi tugma)

LYRIA_TEST_LYRICS = """[1-kuplet]
Onajonim, quyoshim, mehribonim
Sen borsan-u yorug'dir har tongim
Qo'llaring iliq, so'zlaring shirin
Sen bilan to'kis bu hayotim

[Naqorat]
Xush kelibsan, quvonchim, qo'shig'im o'zingsan
G'olib yurak bilan seni qishda ham kutganman
Onajon, onajon, jonim onajon
Sen menga eng aziz, eng mehribon

[2-kuplet]
Bolaligim o'tdi bag'ringda
Ertaklaring qoldi yodimda
Har bir yutug'imning ortida
Sening mehring bor, onajonim

[Naqorat]
Xush kelibsan, quvonchim, qo'shig'im o'zingsan
G'olib yurak bilan seni qishda ham kutganman
Onajon, onajon, jonim onajon
Sen menga eng aziz, eng mehribon"""


async def lyria_test(admin_id: int) -> None:
    """Bir xil she'r bilan ikki qo'shiq (o'zbekcha va inglizcha ko'rsatma) — qaysi biri yaxshi talaffuz qilishini solishtirish uchun.
    Har biri ≈ $0.08. Xato bo'lsa qayta urinilmaydi, natija adminga botda yuboriladi."""
    from aiogram.types import FSInputFile
    from . import videobot
    bot = videobot.BOT
    sections = parse_lyrics(LYRIA_TEST_LYRICS)
    plan, _, _ = build_plan(sections, "pop", "female", [])
    total = sum(c["duration_ms"] for c in plan["chunks"]) / 1000
    name, base, _ = STYLES["pop"]
    PRIVATE_DIR.mkdir(parents=True, exist_ok=True)
    results = []
    for lang, label in (("uz", "o'zbekcha ko'rsatma"), ("en", "inglizcha ko'rsatma")):
        text = lyria.prompt(sections, name, base, "female", "Onaga minnatdorchilik", [], total, lang)
        try:
            data, info = await lyria.compose(text)
        except lyria.LyriaError as e:
            results.append((label, None, str(e)))
            continue
        await costs._add(costs.lyria_row("song_test", admin_id, "lyria-test"))
        path = PRIVATE_DIR / f"lyria-test-{lang}-{secrets.token_hex(3)}.mp3"
        path.write_bytes(data)
        sec = (await asyncio.to_thread(_audio_ms, path)) / 1000
        results.append((label, path, f"{sec:.0f} s" + (f", naqorat {lyria.chorus_seconds(info):.0f}-soniyada" if lyria.chorus_seconds(info) is not None else "")))
    lines = [f"{'✅' if p else '❌'} {lab}: {info}" for lab, p, info in results]
    msg = "🎧 Lyria sinovi (bitta she'r, ikki xil ko'rsatma)\n\n" + "\n".join(lines) + \
          "\n\nTinglang va qaysi biri o'zbekchaga yaqinroq ekanini admin panelda «Ko'rsatma tili»da tanlang."
    if not bot:
        log.info(msg)
        return
    try:
        await bot.send_message(admin_id, msg)
        for lab, p, _ in results:
            if p:
                await bot.send_audio(admin_id, FSInputFile(p, filename=p.name), title=f"Lyria — {lab}", performer="Tayyorla sinov")
    except Exception:
        log.exception("Lyria sinov natijasini yuborib bo'lmadi")


# ---------------------------------------------------------------- mavjud qo'shiqlar: ovozni oldinga chiqarish (bir martalik)
REMIX_KEY = "song_remix"
REMIX_TASK: dict = {"t": None}  # fondagi qayta ishlash vazifasi (bitta)


async def remix_state() -> dict:
    from . import store
    return {"running": False, "done": 0, "total": 0, "failed": 0, "level": "", "finished": None, **(await store.get(REMIX_KEY) or {})}


def _remix_one(song: Song, mix: str) -> dict:
    """Bitta qo'shiq: namuna va to'liq fayl(lar) asl (ishlovsiz) manbadan qayta yoziladi — URL o'zgarmaydi.
    Manba yo'q bo'lsa, fayl o'zi bir marta ishlanadi (belgi qo'yiladi, ikki marta ishlanmaydi)."""
    plan = dict(song.plan or {})
    pv = preview_path(song)
    if pv and pv.exists() and plan.get("_mix_pv") != mix:
        demo = (plan.get("_demo") or {}).get("private")
        full = (song.variants or [{}])[0].get("private") if song.variants else None
        src = next((Path(x) for x in (demo, full) if x and Path(x).exists()), None)
        if src is not None:
            cut_preview(src, pv, plan.get("_chorus_at", 0), settings.song_preview_seconds, mix)
            plan["_mix_pv"] = mix
        elif not plan.get("_mix_pv") and MIX.get(mix):
            apply_mix(pv, pv, mix)
            plan["_mix_pv"] = mix
    if song.paid and plan.get("_mix_full") != mix:
        for v in song.variants or []:
            f = v.get("file") or ""
            if not f.startswith("/media/"):
                continue
            pub = MEDIA_DIR / Path(f).name
            src = Path(v["private"]) if v.get("private") and Path(v["private"]).exists() else None
            if src is not None:
                apply_mix(src, pub, mix)
            elif pub.exists() and not plan.get("_mix_full") and MIX.get(mix):
                apply_mix(pub, pub, mix)
        plan["_mix_full"] = mix
    return plan


async def remix_all() -> None:
    """Fonda: barcha namunalar va sotilgan qo'shiqlar. Bittadan, server sekinlashmasin."""
    from . import store
    mix = await mix_level()
    async with Session() as s:
        ids = (await s.execute(select(Song.id).where(
            (Song.status == "preview_ready") | ((Song.paid.is_(True)) & (Song.status == "ready"))).order_by(Song.id.desc()))).scalars().all()
    st = {"running": True, "done": 0, "total": len(ids), "failed": 0, "level": mix, "finished": None}
    await store.put(REMIX_KEY, st)
    for i, sid in enumerate(ids, 1):
        try:
            async with Session() as s:
                song = await s.get(Song, sid)
                if song:
                    song.plan = await asyncio.to_thread(_remix_one, song, mix)
                    await s.commit()
        except Exception:
            st["failed"] += 1
            log.exception("Qo'shiqni qayta ishlab bo'lmadi: %s", sid)
        st["done"] = i
        if i % 20 == 0 or i == len(ids):
            cur = await remix_state()
            if not cur.get("running"):
                log.info("Qayta ishlash to'xtatildi: %s/%s", i, len(ids))
                return
            await store.put(REMIX_KEY, st)
        await asyncio.sleep(0.2)
    st.update(running=False, finished=utcnow().isoformat())
    await store.put(REMIX_KEY, st)
