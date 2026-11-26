"""Google Lyria 3.5 (Gemini API, Interactions): o'zbekcha she'r bilan to'liq qo'shiq.

Rasmiy hujjat: aistudio.google.com/docs/music-generation — POST /v1beta/interactions, model «lyria-3.5»,
javobda base64 audio (MP3, 44.1 kHz) va qo'shiq matni/tuzilishi. Narx: bir qo'shiq $0.08.
Kalit admin paneldan kiritiladi (bazada saqlanadi, hech qayerda ko'rsatilmaydi) yoki GEMINI_API_KEY orqali.
"""

import asyncio
import base64
import json
import logging
import re

import aiohttp

from .config import RUNTIME, settings

log = logging.getLogger(__name__)

URL = "https://generativelanguage.googleapis.com/v1beta/interactions"
API_REVISION = "2026-05-20"

SECTION_TAG = {"intro": "Intro", "verse": "Verse", "chorus": "Chorus", "bridge": "Bridge", "outro": "Outro"}
VOICE_UZ = {"male": "erkak xonanda", "female": "ayol xonanda"}
VOICE_EN = {"male": "warm male vocals", "female": "warm female vocals"}
# so'zlar aniq eshitilsin: cholg'u ovozni bosib ketmasin
MIX_UZ = ("Xonanda ovozi oldinda — musiqadan balandroq va juda aniq eshitilsin, cholg'u ovozni bosib ketmasin, "
          "faqat orqa fonda yumshoq jo'r bo'lsin. Har bir so'z tushunarli bo'lsin.")
MIX_EN = ("Lead vocals upfront and loud in the mix, clearly louder than the instruments; the backing track stays soft "
          "and supportive, never covering the voice. Every word must be clearly intelligible.")


class LyriaError(Exception):
    """Foydalanuvchiga ko'rsatsa bo'ladigan xato matni bilan."""

    def __init__(self, message: str, quota: bool = False, reason: str = "service", detail: str = ""):
        super().__init__(message)
        self.quota = quota
        self.reason = "quota" if quota else reason  # statistika uchun sabab kodi (app/songflow.py: REASONS)
        self.detail = detail  # Google'ning asl javobidan qisqa sabab (admin panel «Oxirgi xatolar» uchun)


def detail_of(status: int, body: str) -> str:
    """Google javobidan qisqa sabab: error.status / error.message, blockReason, finishReason, safety toifalari.
    Kalit yoki uzun belgilar ketma-ketligi kirmaydi."""
    parts: list[str] = [str(status)] if status and status != 200 else []
    try:
        data = json.loads(body)
    except ValueError:
        data = None
    if isinstance(data, dict):
        err = data.get("error") if isinstance(data.get("error"), dict) else {}
        for k in ("status", "message"):
            if err.get(k):
                parts.append(str(err[k]))
        seen: list[str] = []

        def walk(node):
            if isinstance(node, dict):
                for k, v in node.items():
                    if k in ("blockReason", "block_reason", "finishReason", "finish_reason", "category", "reason",
                             "status", "message", "error_message") and isinstance(v, str) and v and v not in seen:
                        seen.append(v)
                    elif isinstance(v, (dict, list)):
                        walk(v)
            elif isinstance(node, list):
                for v in node:
                    walk(v)
        walk({k: v for k, v in data.items() if k != "error"})
        parts.extend(seen[:6])
    elif body:
        parts.append(body[:160])
    text = " ".join(" · ".join(dict.fromkeys(p for p in parts if p)).split())
    return re.sub(r"[A-Za-z0-9_\-]{28,}", "…", text)[:220]


def key() -> str:
    return RUNTIME.get("gemini_key") or settings.gemini_api_key


def lyrics_block(sections: list[dict]) -> str:
    """Bizning bo'limlarni Lyria tushunadigan teglarga o'giradi: [Verse 1], [Chorus], [Bridge]..."""
    out, verse = [], 0
    for sec in sections:
        kind = sec["kind"]
        if not sec["lines"]:
            continue
        if kind == "verse":
            verse += 1
            tag = f"Verse {verse}"
        else:
            tag = SECTION_TAG.get(kind, "Verse")
        out.append(f"[{tag}]\n" + "\n".join(sec["lines"]))
    return "\n\n".join(out)


def prompt(sections: list[dict], style_name: str, style_tags: list[str], voice: str, occasion: str,
           extra: list[str], seconds: float, lang: str = "uz", clip: bool = False) -> str:
    """Ko'rsatma va so'zlar alohida (hujjat tavsiyasi). Til — talaffuzga ta'sir qiladi, shuning uchun asosan o'zbekcha."""
    words = lyrics_block(sections)
    if clip:  # namuna: faqat naqorat, 30 soniyalik bo'lak
        tags = ", ".join([*style_tags, *extra][:12])
        if lang == "en":
            return (f"Create a {style_name} song chorus sung in Uzbek language by a native Uzbek singer, "
                    f"{VOICE_EN.get(voice, VOICE_EN['female'])}, clear native Uzbek pronunciation. Style: {tags}. "
                    f"Start singing right away. {MIX_EN} Sing exactly these lyrics:\n\n{words}")
        return (f"O'zbek tilidagi qo'shiqning naqorati. Janr: {style_name} ({tags}). {VOICE_UZ.get(voice, VOICE_UZ['female']).capitalize()} "
                f"ona tili o'zbek bo'lgan xonandadek aniq o'zbekcha talaffuz bilan kuylaydi. Qo'shiq darhol boshlansin. {MIX_UZ} "
                f"Quyidagi so'zlarni aynan shunday kuylang:\n\n{words}")
    minutes = 1.5  # sovg'a qo'shig'i uchun yetarli va tezroq tayyorlanadi
    tags = ", ".join([*style_tags, *extra][:12])
    if lang == "en":
        return (f"Create a {style_name} song sung entirely in Uzbek language by a native Uzbek singer, "
                f"{VOICE_EN.get(voice, VOICE_EN['female'])}, clear native Uzbek pronunciation. Style: {tags}. "
                f"Occasion: {occasion}. Length about 90 seconds. {MIX_EN} Sing exactly these lyrics, do not change or add words.\n\n"
                f"Lyrics:\n{words}")
    return (f"O'zbek tilida qo'shiq yarating. Janr: {style_name} ({tags}). Qo'shiqni {VOICE_UZ.get(voice, VOICE_UZ['female'])} "
            f"kuylaydi — ona tili o'zbek bo'lgan xonandadek aniq va tabiiy o'zbekcha talaffuz bilan. Munosabat: {occasion}. "
            f"Davomiyligi taxminan 1,5 daqiqa (90 soniya). {MIX_UZ} Quyidagi so'zlarni aynan shunday kuylang, so'z qo'shmang va o'zgartirmang.\n\n"
            f"Qo'shiq so'zlari:\n{words}")


def _walk(node, audio: list, texts: list) -> None:
    if isinstance(node, dict):
        kind = node.get("type")
        if kind == "audio" and isinstance(node.get("data"), str):
            audio.append(node["data"])
        elif kind == "text" and isinstance(node.get("text"), str):
            texts.append(node["text"])
        for v in node.values():
            if isinstance(v, (dict, list)):
                _walk(v, audio, texts)
    elif isinstance(node, list):
        for v in node:
            _walk(v, audio, texts)


def parse(data: dict) -> tuple[bytes | None, str]:
    """Javobdan oxirgi audio blokini va matn bloklarini oladi (steps → model_output → content)."""
    audio, texts = [], []
    _walk(data.get("steps", data), audio, texts)
    if not audio:
        _walk(data, audio, texts)
    raw = base64.b64decode(audio[-1]) if audio else None
    seen, uniq = set(), []
    for t in texts:
        if t not in seen:
            seen.add(t)
            uniq.append(t)
    return raw, "\n".join(uniq)


def chorus_seconds(text: str) -> float | None:
    """Lyria qaytargan tuzilishdan naqorat boshlanish vaqti (topilmasa None)."""
    if not text:
        return None
    try:  # JSON tuzilma bo'lsa
        obj = json.loads(text)
        items = obj if isinstance(obj, list) else next((v for v in obj.values() if isinstance(v, list)), [])
        for it in items:
            if isinstance(it, dict) and "chorus" in json.dumps(it).lower():
                for k in ("start", "start_time", "startTime", "start_sec", "time"):
                    if k in it:
                        v = it[k]
                        return float(v) if not isinstance(v, str) else _mmss(v)
    except Exception:
        pass
    for line in text.splitlines():
        if re.search(r"chorus|naqorat", line, re.I):
            m = re.search(r"(\d{1,2}):(\d{2})", line)
            if m:
                return int(m.group(1)) * 60 + int(m.group(2))
    return None


def _mmss(v: str) -> float | None:
    m = re.match(r"\s*(\d{1,2}):(\d{2})", v)
    return int(m.group(1)) * 60 + int(m.group(2)) if m else None


async def compose(text: str, model: str | None = None) -> tuple[bytes, str]:
    """Bitta qo'shiq. Xatoda LyriaError. Hech qachon o'zi qayta urinmaydi (har urinish pullik)."""
    k = key()
    if not k:
        raise LyriaError("Qo'shiq xizmati hozircha sozlanmagan.", quota=True)
    headers = {"x-goog-api-key": k, "Api-Revision": API_REVISION, "Content-Type": "application/json"}
    timeout = aiohttp.ClientTimeout(total=900)
    async with aiohttp.ClientSession(timeout=timeout) as http:
        async with http.post(URL, headers=headers, json={"model": model or settings.lyria_model, "input": text}) as r:
            body = await r.text()
            status = r.status
        if status != 200:
            _raise(status, body)
        data = json.loads(body)
        # uzoq davom etsa — tayyor bo'lguncha holatini so'raymiz (bu qayta yaratish emas)
        for _ in range(96):
            audio, info = parse(data)
            if audio:
                if len(audio) < 5_000:
                    raise LyriaError("Qo'shiq tayyorlanmadi, qayta urinib ko'ring.", reason="empty")
                return audio, info
            st = str(data.get("status", "")).lower()
            if not data.get("id") or st in ("failed", "cancelled", "completed"):
                break
            await asyncio.sleep(5)
            async with http.get(f"{URL}/{data['id']}", headers=headers) as r:
                body = await r.text()
                if r.status != 200:
                    _raise(r.status, body)
                data = json.loads(body)
    log.warning("Lyria javobida audio yo'q: %s", body[:1500])
    raise LyriaError("Qo'shiq tayyorlanmadi, qayta urinib ko'ring.", reason="empty", detail=detail_of(200, body))


def _raise(status: int, body: str) -> None:
    low = body.lower()
    log.warning("Lyria %s: %s", status, body[:2000])
    d = detail_of(status, body)
    if status in (401, 403) or "api key" in low or "permission" in low:
        raise LyriaError("Qo'shiq xizmati vaqtincha band. Birozdan so'ng qayta urinib ko'ring — buyurtmangiz saqlanib qoladi.", quota=True, detail=d)
    if "billing" in low or "quota" in low or "exhausted" in low or status == 402:
        raise LyriaError("Qo'shiq xizmati vaqtincha band. Birozdan so'ng qayta urinib ko'ring — buyurtmangiz saqlanib qoladi.", quota=True, detail=d)
    if status == 429:
        raise LyriaError("Navbat band, bir necha daqiqadan so'ng qayta urinib ko'ring.", reason="busy", detail=d)
    if "safety" in low or "blocked" in low or "copyright" in low or "recitation" in low:
        raise LyriaError("Matnda mualliflik huquqi bilan himoyalangan so'z yoki taqiqlangan ibora bor. Matnni o'zgartirib ko'ring.",
                         reason="content", detail=d)
    raise LyriaError("Qo'shiq tayyorlashda xato bo'ldi, qayta urinib ko'ring.", detail=d)
