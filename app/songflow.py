"""Qo'shiq voronkasi (statistika TZ, 1 va 2-bandlar): qadamlarni yozish, eski ma'lumotdan tiklash,
«Tizim» bo'limi uchun namuna vaqti va xatolar, adminlarga ogohlantirish.

Hodisalar events jadvaliga yoziladi (ref = song:<id>, manba — users.ref), nomlari TZ dagidek:
  song_open        — qo'shiq bo'limiga kirdi (ilova yuboradi; meta.from — qayerdan)
  song_form_done   — kimga, ism va sababni to'ldirib, so'rovnomani yubordi (meta: rel — kimga, occ — sabab,
                     date — bayram sanasi OY-KUN, agar shu ism «Yaqinlarim» kalendarida bo'lsa)
  lyrics_ready     — she'r tayyor bo'ldi (num = shu qo'shiqda nechanchi qayta yozish; 0 — birinchi matn)
  sample_requested — «Namunani tinglash» bosildi
  sample_ready     — namuna tayyor bo'ldi (num = kutish vaqti, soniya)
  sample_failed    — namuna xato bilan tugadi (meta: r — sabab kodi, e — xato matni)
  sample_limit     — limit sabab namuna berilmadi (meta: l — qaysi limit)
  sample_played    — namunani eshitdi (ilova yuboradi; num = necha soniya, meta.end — oxirigacha eshitdimi)
  buy_click        — «Sotib olish» bosildi (ilova yuboradi; num = ko'rsatilgan narx, meta: kind — 1 ta / paket, disc — chegirma)
  song_delivered   — to'liq qo'shiq berildi (num = to'lovdan keyin kutish, soniya)
  song_shared      — yuklab oldi yoki ulashdi (ilova yuboradi; meta.how)
bot_start = «start», app_open = «app», pay_open / pay_success — app/payflow.py (nomlari o'zgarmagan).

TZ jadvalida yo'q, lekin sabablarni ko'rsatish uchun kerak bo'lgan yordamchi hodisalar:
  lyrics_failed — she'r yozilmadi (meta.r: limit_day | limit_total | rate | ai)
  sample_away   — namuna tayyor bo'lganda odam ilovada emas edi (num = 1 — botdagi «namuna tayyor» xabari yetdi)
  song_failed   — to'liq qo'shiq xato bilan tugadi (meta: r, e)
  sample_retry  — yarim qolgan namuna avtomatik qayta navbatga qo'yildi;  song_retry — mijoz to'langan qo'shiqni qayta so'radi

Yozish bot va ilovani sekinlashtirmaydi: har biri bitta INSERT (track.event), xato chaqiruvchiga chiqmaydi.
"""

import asyncio
import functools
import logging
import re
import subprocess
import time
from collections import Counter, defaultdict
from datetime import datetime, timedelta, timezone

import aiohttp
from sqlalchemy import exists, func, insert, select
from sqlalchemy.orm import aliased

from . import store, track
from .config import settings
from .db import CostLog, Event, Person, Session, Song, User, utcnow
from .reminders import TZ

log = logging.getLogger(__name__)

KEY = "songflow"
DEFAULTS = {
    "since": None,      # yangi hodisalar qachondan beri yoziladi (birinchi ishga tushgan vaqt, UTC)
    "alert_on": True,   # adminlarga Telegram ogohlantirish
    "alert_pct": 5,     # bir soatdagi xatolar ulushi shundan oshsa (%)
    "alert_min": 4,     # ...va shu soatda kamida shuncha urinish bo'lgan bo'lsa (1 ta urinish 1 ta xato = 100% bo'lmasin)
    "alerted": {},      # sabab -> oxirgi ogohlantirish vaqti (bir sabab bo'yicha soatiga ko'pi bilan bitta)
}

CLIENT_KINDS = track.SONG_CLIENT_KINDS  # ilova (/api/track) yuboradigan qo'shiq hodisalari
# eski ma'lumotdan tiklab bo'lmaydigan hodisalar: hisob `since` dan boshlanadi (panel shu sanani ko'rsatadi)
NEW_KINDS = ("song_open", "song_form_done", "sample_played", "buy_click", "song_shared", "sample_limit", "sample_away", "lyrics_failed")

REASONS = {
    "timeout": "Musiqa xizmati javob bermadi (vaqt tugadi)",
    "network": "Musiqa xizmatiga ulanib bo'lmadi",
    "service": "Musiqa xizmati xato qaytardi",
    "quota": "Musiqa xizmati so'rovni rad etdi (kredit yoki kalit)",
    "no_credits": "Kredit yetmadi — so'rov navbatga qo'yilmadi",
    "config": "Qo'shiq xizmati sozlanmagan",
    "busy": "Musiqa xizmati band (so'rovlar juda ko'p)",
    "empty": "Musiqa xizmati bo'sh javob qaytardi",
    "content": "Matn rad etildi (mualliflik huquqi yoki taqiqlangan so'z)",
    "text": "Matn yaroqsiz (juda qisqa, juda uzun yoki naqoratsiz)",
    "audio": "Faylni kesish yoki qayta ishlashda xato",
    "internal": "Ichki xato",
    "ai": "She'r yozib bo'lmadi (AI xizmati xatosi)",
    "unknown": "Sababi yozilmagan (eski xato)",
}
DOWN = ("timeout", "network", "service", "quota", "no_credits", "config")  # «musiqa xizmati javob bermayapti»
USER_SIDE = ("text",)  # generatsiya boshlanmagan, mijoz o'zi tuzatadi — xatolar ulushiga kirmaydi
LIMITS = {
    "user_day": "Bir kishiga kunlik bepul namuna tugagan",
    "user_total": "Bir kishiga jami bepul namuna tugagan",
    "all_day": "Hamma uchun kunlik chegara to'lgan",
    "sub": "Kanalga obuna sharti bajarilmagan",
}
LYRICS_WHY = {"limit_day": "Kunlik she'r limiti", "limit_total": "Jami she'r limiti", "rate": "Juda ko'p so'rov", "ai": REASONS["ai"]}
KIND_LABELS = {"sample_failed": "Qo'shiq namunasi", "song_failed": "To'liq qo'shiq", "lyrics_failed": "She'r"}
STUCK_MIN = 20  # navbatdagi qo'shiq shuncha daqiqada tayyor bo'lmasa — xizmat javob bermayapti deb hisoblanadi


def ref_of(song_id: int) -> str:
    return f"song:{song_id}"


def song_id_of(ref: str) -> int | None:
    return int(ref[5:]) if ref and ref.startswith("song:") and ref[5:].isdigit() else None


# ---------------------------------------------------------------- sozlama

async def config() -> dict:
    v = await store.get(KEY) or {}
    return {k: v.get(k, d) for k, d in DEFAULTS.items()}


async def save(data: dict) -> dict:
    cfg = await config()
    if data.get("alert_on") is not None:
        cfg["alert_on"] = bool(data["alert_on"])
    for k, lo, hi in (("alert_pct", 1, 100), ("alert_min", 1, 1000)):
        if data.get(k) is not None:
            cfg[k] = min(hi, max(lo, int(data[k])))
    await store.put(KEY, cfg)
    return cfg


def _dt(v) -> datetime | None:
    try:
        return datetime.fromisoformat(v or "")
    except (TypeError, ValueError):
        return None


async def since() -> datetime | None:
    """Yangi hodisalar yozila boshlagan vaqt (UTC, zonasiz) yoki None — hali boshlanmagan."""
    return _dt((await config())["since"])


# ---------------------------------------------------------------- xato sababi

def reason_of(e: BaseException) -> str:
    """Xatodan sabab kodi: xizmat javob bermadimi, rad etdimi yoki o'zimizdagi xatomi."""
    r = getattr(e, "reason", "")
    if isinstance(r, str) and r in REASONS:
        return r
    if isinstance(e, aiohttp.ServerTimeoutError) or isinstance(e, (asyncio.TimeoutError, TimeoutError)):
        return "timeout"
    if isinstance(e, (aiohttp.ClientError, ConnectionError)):
        return "network"
    if isinstance(e, (subprocess.SubprocessError, OSError)):
        return "audio"
    return "internal"


def error_text(e: BaseException) -> str:
    """Panelda ko'rsatiladigan qisqa xato matni (kalit yoki uzun belgilar ketma-ketligi tushib qolmasin)."""
    text = str(e) if getattr(e, "reason", "") else f"{type(e).__name__}: {e}"
    return re.sub(r"[A-Za-z0-9_\-]{28,}", "…", " ".join(text.split()))[:200]


def guess_reason(text: str) -> str:
    """Eski yozuvlarda faqat mijozga ko'rsatilgan matn saqlangan — sabab shundan taxmin qilinadi."""
    low = (text or "").lower()
    for word, code in (("mualliflik", "content"), ("navbat band", "busy"), ("vaqtincha band", "quota"),
                       ("sozlanmagan", "config"), ("tayyorlanmadi", "empty")):
        if word in low:
            return code
    return "unknown"


# ---------------------------------------------------------------- odam hozir ilovadami

_SEEN: dict[int, float] = {}
PRESENT_S = 20  # ilova namuna kutayotganda holatni har 4 soniyada so'raydi


def seen(song_id: int) -> None:
    """Ilova shu qo'shiq holatini so'radi — egasi hozir qo'shiq sahifasida."""
    if len(_SEEN) > 20_000:
        _SEEN.clear()
    _SEEN[song_id] = time.monotonic()


def present(song_id: int) -> bool:
    t = _SEEN.get(song_id)
    return t is not None and time.monotonic() - t <= PRESENT_S


# ---------------------------------------------------------------- hodisalarni yozish (server tomoni)

def _quiet(fn):
    """Statistika qo'shiq oqimini hech qachon to'xtatmaydi: xato faqat jurnalga yoziladi."""
    @functools.wraps(fn)
    async def run(*a, **kw):
        try:
            return await fn(*a, **kw)
        except Exception:
            log.exception("Voronka hodisasini yozib bo'lmadi: %s", fn.__name__)
            return None
    return run


async def _person_date(uid: int, name: str) -> str:
    """Bayram sanasi: shu ism «Yaqinlarim» kalendarida bo'lsa, o'sha sana (OY-KUN)."""
    want = (name or "").strip().casefold()
    if not want:
        return ""
    async with Session() as s:
        rows = (await s.execute(select(Person.name, Person.month, Person.day).where(Person.owner_id == uid).limit(100))).all()
    for pname, month, day in rows:
        if (pname or "").strip().casefold() == want:
            return f"{month:02d}-{day:02d}"
    return ""


@_quiet
async def form_done(uid: int, relation: str, occasion: str, name: str = "", song_id: int | None = None, at: datetime | None = None) -> None:
    meta = {"rel": relation, "occ": occasion}
    date = await _person_date(uid, name)
    if date:
        meta["date"] = date
    await track.event("song_form_done", uid, ref_of(song_id) if song_id else "", meta=meta, at=at)


@_quiet
async def lyrics_ready(song: Song, how: str = "new") -> None:
    """how: new — birinchi matn, ai — AI qayta yozdi, manual — mijoz o'zi tahrirladi."""
    n = 0
    if how != "new":
        async with Session() as s:
            cnt, top = (await s.execute(select(func.count(), func.max(Event.num)).where(
                Event.kind == "lyrics_ready", Event.ref == ref_of(song.id)))).one()
        n = max(cnt or 0, (top or 0) + 1 if cnt else 0)
    await track.event("lyrics_ready", song.owner_id, ref_of(song.id), n, {"how": how})


@_quiet
async def lyrics_failed(uid: int, why: str, status: int, song_id: int | None = None) -> None:
    await track.event("lyrics_failed", uid, ref_of(song_id) if song_id else "", status, {"r": why})


@_quiet
async def preview_asked(uid: int, flow: dict) -> None:
    """«Namunani tinglash» bosildi: flow — so'rov davomida yig'ilgan natija (song, at, limit yoki fail)."""
    if not flow.get("song"):
        return
    ref = ref_of(flow["song"])
    await track.event("sample_requested", uid, ref, at=flow.get("at"))
    if flow.get("limit"):
        await track.event("sample_limit", uid, ref, meta={"l": flow["limit"]})
    elif flow.get("fail"):
        await track.event("sample_failed", uid, ref, meta={"r": flow["fail"], "e": (flow.get("error") or REASONS[flow["fail"]])[:200]})


@_quiet
async def processed(song: Song, flow: dict, sent: bool) -> None:
    """Navbatdagi ish tugadi (songs.process): namuna yoki to'liq qo'shiq tayyor bo'ldi yoki xato bilan tugadi."""
    if not flow.get("mode"):
        return
    ref, uid, at, wait = ref_of(song.id), song.owner_id, flow.get("at"), flow.get("wait")
    sample = flow["mode"] == "preview_gen"
    if flow.get("reason"):
        await track.event("sample_failed" if sample else "song_failed", uid, ref, wait, {"r": flow["reason"], "e": flow.get("error") or ""}, at=at)
    elif sample:
        away = bool(flow.get("away"))
        await track.event("sample_ready", uid, ref, wait, {"away": 1} if away else None, at=at)
        if away:
            await track.event("sample_away", uid, ref, 1 if sent else 0, at=at)
    else:
        await track.event("song_delivered", uid, ref, wait, at=at)


@_quiet
async def requeued(rows: list[tuple[int, int, str]]) -> None:
    """Server qayta ishga tushdi: yarim qolgan ishlar avtomatik qayta navbatga qo'yildi — [(qo'shiq, egasi, holat)]."""
    for sid, uid, status in rows:
        await track.event("sample_retry" if status.startswith("preview") else "song_retry", uid, ref_of(sid), meta={"by": "restart"})


@_quiet
async def retried(song: Song) -> None:
    await track.event("song_retry", song.owner_id, ref_of(song.id), meta={"by": "user"})


# ---------------------------------------------------------------- ilovadan kelgan hodisalar (/api/track)

_FROM = ("tab", "new", "song")  # «Musiqalar» bo'limi, yangi qo'shiq so'rovnomasi, qo'shiq sahifasi (havola orqali)
_BUY_KIND = ("single", "pack", "credit")
_BUY_AT = ("lyrics", "sample", "limit", "packs")
_HOW = ("download", "share")


async def client_event(uid: int, kind: str, ref: str, num: int | None, meta: dict | None) -> bool:
    """Ilova yuborgan qo'shiq hodisasini tekshirib yozadi: qo'shiq o'ziniki bo'lishi, qiymatlar ruxsat etilgan
    ro'yxatdan bo'lishi kerak. Noto'g'ri so'rov jim tashlab yuboriladi (False)."""
    meta = meta if isinstance(meta, dict) else {}
    sid = song_id_of(ref)
    if ref and sid is None:
        return False
    song = None
    try:
        if sid is not None:
            async with Session() as s:
                song = (await s.execute(select(Song.owner_id, Song.paid, Song.status).where(Song.id == sid))).one_or_none()
            if not song or song[0] != uid:
                return False
        if kind == "song_open":
            src = meta.get("from")
            return await track.event(kind, uid, ref, meta={"from": src} if src in _FROM else None)
        if kind == "buy_click":
            k = meta.get("kind")
            if k not in _BUY_KIND or (k != "pack" and song is None):
                return False
            out = {"kind": k, "disc": bool(meta.get("disc"))}
            if k == "pack" and isinstance(meta.get("n"), int) and not isinstance(meta.get("n"), bool) and 2 <= meta["n"] <= 50:
                out["n"] = meta["n"]
            if meta.get("at") in _BUY_AT:
                out["at"] = meta["at"]
            return await track.event(kind, uid, ref, min(max(num or 0, 0), 10_000_000), out)
        if song is None:  # qolgan hodisalar faqat aniq qo'shiq bo'yicha
            return False
        if kind == "sample_played":
            if not num or num < 1:
                return False
            out = {"end": bool(meta.get("end"))}
            total = meta.get("of")
            if isinstance(total, int) and not isinstance(total, bool) and 0 < total <= 3600:
                out["of"] = total
            return await track.event(kind, uid, ref, min(max(num or 0, 0), 3600), out)
        if kind == "song_shared":
            if not song[1] or song[2] != "ready" or meta.get("how") not in _HOW:
                return False
            return await track.event(kind, uid, ref, meta={"how": meta["how"]})
        if kind == "sample_limit":
            # ilovada «bepul namuna tugadi» ko'rsatildi (tugma chiqmaydi) — qaysi limit ekanini server o'zi aniqlaydi
            if song[1]:
                return False
            from . import songs
            async with Session() as s:
                if await songs.free_previews_left(s, uid) > 0:
                    return False
                lim = await songs.user_limits()
                total = lim["pv_total"] and await songs.previews_used_total(s, uid) >= lim["pv_total"]
            return await track.event(kind, uid, ref, meta={"l": "user_total" if total else "user_day", "ui": 1})
    except Exception:
        log.exception("Ilova hodisasini yozib bo'lmadi: %s", kind)
    return False


# ---------------------------------------------------------------- eski ma'lumotdan tiklash

BF_KINDS = ("lyrics_ready", "sample_requested", "sample_ready", "sample_failed", "song_failed", "song_delivered")


async def start() -> None:
    """Birinchi ishga tushishda: mavjud qo'shiqlardan hodisalarni tiklaydi va hisob boshlangan sanani belgilaydi."""
    cfg = await config()
    if cfg["since"]:
        return
    n = await backfill()
    cfg["since"] = utcnow().isoformat(timespec="seconds")
    await store.put(KEY, cfg)
    log.info("Qo'shiq voronkasi boshlandi: %s ta eski hodisa tiklandi", n)


async def backfill() -> int:
    """Mavjud Qo'shiqlar va Hodisalar jadvalidan halol tiklanadigan qadamlar (meta.bf = 1):
      lyrics_ready     — har bir qo'shiq yaratilgan vaqt (num — AI bilan qayta yozishlar soni, xarajat jurnalidan);
      sample_requested — har bir hisobga olingan namuna so'rovi (song_pv hodisalari);
      sample_ready     — namunasi tayyor bo'lgan qo'shiq: namuna hozir ham turgan bo'lsa tayyor bo'lgan vaqt va kutish soniyasi,
                         keyin sotilgan yoki she'ri tahrirlangan bo'lsa — so'ralgan vaqt (kutish noma'lum);
      sample_failed / song_failed — xatosi hali saqlanib turgan qo'shiqlar (keyin qayta urinilganlari o'chib ketgan);
      song_delivered   — to'langan va tayyor qo'shiq (tayyor bo'lgan vaqt).
    Qayta chaqirilsa takror yozmaydi: shu turdagi hodisasi bor qo'shiq o'tkazib yuboriladi."""
    from .songs import PV_EVENT
    async with Session() as s:
        have = set((await s.execute(select(Event.kind, Event.ref).where(Event.kind.in_(BF_KINDS), Event.ref.like("song:%")).distinct())).all())
        rows = (await s.execute(
            select(Song.id, Song.owner_id, Song.status, Song.paid, Song.preview, Song.preview_at, Song.error,
                   Song.created_at, Song.updated_at, User.ref)
            .outerjoin(User, User.tg_id == Song.owner_id).order_by(Song.id))).all()
        edits = dict((await s.execute(select(CostLog.ref, func.count()).where(CostLog.purpose == "lyrics_edit", CostLog.ref.like("song:%"))
                                      .group_by(CostLog.ref))).all())
        asked = (await s.execute(select(Event.user_id, Event.src, Event.created_at).where(Event.kind == PV_EVENT).order_by(Event.id))).all()
        new: list[dict] = []
        srcs: dict[int, str] = {}
        # hisobdan qaytarilmagan so'rov — namuna tayyor bo'lgan (xatoda so'rov yozuvi o'chiriladi): qo'shiq -> oxirgi so'rov vaqti
        pv_last = {int(src): at for _, src, at in asked if src and src.isdigit()}

        def add(kind, sid, uid, at, num=None, **meta):
            if (kind, ref_of(sid)) not in have:
                new.append({"user_id": uid, "kind": kind, "src": srcs.get(sid, ""), "ref": ref_of(sid), "num": num,
                            "meta": {**meta, "bf": 1}, "created_at": at or utcnow()})

        for r in rows:
            srcs[r.id] = (r[-1] or "")[:32]
            created, updated = r.created_at or utcnow(), r.updated_at or r.created_at or utcnow()
            add("lyrics_ready", r.id, r.owner_id, created, edits.get(ref_of(r.id), 0), how="new")
            if r.preview and r.status == "preview_ready":
                wait = int((updated - r.preview_at).total_seconds()) if r.preview_at else None
                add("sample_ready", r.id, r.owner_id, updated, wait if wait is not None and 0 <= wait <= 3600 else None)
            elif r.preview or (r.id in pv_last and r.status not in ("preview_queued", "preview_gen")):
                # keyin sotilgan yoki she'ri tahrirlanib namunasi olib tashlangan: tayyor bo'lgan aniq vaqt saqlanmagan
                add("sample_ready", r.id, r.owner_id, r.preview_at or pv_last.get(r.id) or created)
            if r.error and r.status == "lyrics" and not r.paid:
                add("sample_failed", r.id, r.owner_id, updated, r=guess_reason(r.error), e=r.error[:200])
            if r.status == "failed":
                add("song_failed", r.id, r.owner_id, updated, r=guess_reason(r.error), e=(r.error or "")[:200])
            if r.paid and r.status == "ready":
                add("song_delivered", r.id, r.owner_id, updated)
        for uid, src, at in asked:
            if src and src.isdigit() and int(src) in srcs and uid:
                add("sample_requested", int(src), uid, at)
        for i in range(0, len(new), 500):
            await s.execute(insert(Event), new[i:i + 500])
        await s.commit()
    return len(new)


# ---------------------------------------------------------------- «Tizim»: namuna vaqti, xatolar, qayta urinishlar

def local_day(dt: datetime):
    return dt.replace(tzinfo=timezone.utc).astimezone(TZ).date()


def _pct(a: float, b: float) -> float:
    return round(100 * a / b, 1) if b else 0.0


async def failed_counts(s, a: datetime, b: datetime, excl) -> dict:
    """[a, b) oralig'idagi qo'shiq xatolari: namuna va to'liq qo'shiq (hodisalar soni) va nechta odamda."""
    cond = [Event.kind.in_(("sample_failed", "song_failed")), Event.created_at >= a, Event.created_at < b]
    if excl:
        cond.append(Event.user_id.notin_(list(excl)))
    rows = (await s.execute(select(Event.kind, func.count(), func.count(func.distinct(Event.user_id))).where(*cond).group_by(Event.kind))).all()
    by = {k: n for k, n, _ in rows}
    people = await s.scalar(select(func.count(func.distinct(Event.user_id))).where(*cond)) if rows else 0
    return {"failed": sum(by.values()), "failed_sample": by.get("sample_failed", 0), "failed_full": by.get("song_failed", 0),
            "failed_people": people or 0}


async def system(days: int = 14, now: datetime | None = None) -> dict:
    """«Tizim» bo'limi uchun: namuna tayyorlash vaqti kunlar bo'yicha (o'rtacha, eng uzun), xatolar sababi bilan,
    qayta urinishlar, oxirgi soatdagi xatolar ulushi va ogohlantirish sozlamasi. Vaqtlar Toshkent bo'yicha."""
    now = now or utcnow()
    cfg = await config()
    excl = await track.excluded_ids()
    first = local_day(now) - timedelta(days=days - 1)
    start = datetime(first.year, first.month, first.day, tzinfo=TZ).astimezone(timezone.utc).replace(tzinfo=None)
    kinds = ("sample_requested", "sample_ready", "sample_failed", "sample_retry", "song_failed", "song_retry", "song_delivered")
    cond = [Event.kind.in_(kinds), Event.created_at >= start]
    if excl:
        cond.append(Event.user_id.notin_(list(excl)))
    async with Session() as s:
        rows = (await s.execute(select(Event.kind, Event.created_at, Event.num, Event.meta).where(*cond))).all()
        prev = aliased(Event)
        again = await s.scalar(select(func.count()).select_from(Event).where(
            Event.kind == "sample_requested", Event.created_at >= start, *cond[2:],
            exists().where(prev.kind == "sample_failed", prev.ref == Event.ref, prev.created_at < Event.created_at))) or 0
        errs = (await s.execute(select(Event.id, Event.kind, Event.user_id, Event.ref, Event.meta, Event.created_at)
                                .where(Event.kind.in_(tuple(KIND_LABELS))).order_by(Event.id.desc()).limit(80))).all()
        errs = [e for e in errs if e.kind != "lyrics_failed" or (e.meta or {}).get("r") == "ai"][:20]
        sids = {song_id_of(e.ref) for e in errs} - {None}
        titles = dict((await s.execute(select(Song.id, Song.title).where(Song.id.in_(sids or {0})))).all())
        names = {u[0]: u for u in (await s.execute(select(User.tg_id, User.first_name, User.username)
                                                   .where(User.tg_id.in_({e.user_id for e in errs if e.user_id} or {0})))).all()}
    by_day: dict = defaultdict(lambda: {"asked": 0, "ready": 0, "failed": 0, "waits": []})
    reasons: Counter = Counter()
    auto = full_failed = full_retry = delivered = 0
    for kind, at, num, meta in rows:
        d = by_day[local_day(at)]
        if kind == "sample_requested":
            d["asked"] += 1
        elif kind == "sample_ready":
            d["ready"] += 1
            if num is not None:
                d["waits"].append(num)
        elif kind == "sample_failed":
            d["failed"] += 1
            reasons[(meta or {}).get("r") or "unknown"] += 1
        elif kind == "sample_retry":
            auto += 1
        elif kind == "song_failed":
            full_failed += 1
            reasons[(meta or {}).get("r") or "unknown"] += 1
        elif kind == "song_retry":
            full_retry += 1
        elif kind == "song_delivered":
            delivered += 1
    out_days, waits_all = [], []
    for i in range(days):
        day = first + timedelta(days=days - 1 - i)  # yangisi tepada
        d = by_day.get(day)
        if not d:
            continue
        w = d["waits"]
        waits_all += w
        out_days.append({"day": day.isoformat(), "asked": d["asked"], "ready": d["ready"], "failed": d["failed"],
                         "fail_pct": _pct(d["failed"], d["ready"] + d["failed"]),
                         "avg_s": round(sum(w) / len(w)) if w else None, "max_s": max(w) if w else None, "timed": len(w)})
    ready = sum(d["ready"] for d in by_day.values())
    failed = sum(d["failed"] for d in by_day.values())
    return {
        "days": days, "since": cfg["since"], "by_day": out_days,
        "wait": {"n": len(waits_all), "avg_s": round(sum(waits_all) / len(waits_all)) if waits_all else None,
                 "max_s": max(waits_all) if waits_all else None},
        "samples": {"ready": ready, "failed": failed, "fail_pct": _pct(failed, ready + failed)},
        "full": {"delivered": delivered, "failed": full_failed, "retried": full_retry},
        "retries": {"auto": auto, "manual": again},
        "reasons": [{"key": k, "label": REASONS.get(k, k), "n": n} for k, n in reasons.most_common()],
        "errors": [{"id": e.id, "kind": e.kind, "kind_label": KIND_LABELS[e.kind], "song_id": song_id_of(e.ref),
                    "title": titles.get(song_id_of(e.ref)) or "", "user_id": e.user_id,
                    "name": names[e.user_id][1] if e.user_id in names else "", "username": names[e.user_id][2] if e.user_id in names else "",
                    "reason": (e.meta or {}).get("r") or "unknown", "reason_label": REASONS.get((e.meta or {}).get("r"), REASONS["unknown"]),
                    "error": (e.meta or {}).get("e") or "", "old": bool((e.meta or {}).get("bf")), "test": e.user_id in excl,
                    "at": e.created_at.isoformat() if e.created_at else None} for e in errs],
        "hour": await last_hour(now),
        "alert": {"on": cfg["alert_on"], "pct": cfg["alert_pct"], "min": cfg["alert_min"], "last": cfg["alerted"] or {},
                  "stuck_min": STUCK_MIN, "admins": len(settings.admins)},
    }


# ---------------------------------------------------------------- adminlarga ogohlantirish

async def last_hour(now: datetime | None = None) -> dict:
    """Oxirgi 60 daqiqa: urinishlar (tayyor + xato), xatolar va sabablari; shuncha vaqtdan beri navbatda turganlar."""
    now = now or utcnow()
    lo = now - timedelta(hours=1)
    async with Session() as s:
        rows = (await s.execute(select(Event.kind, Event.meta).where(
            Event.kind.in_(("sample_ready", "song_delivered", "sample_failed", "song_failed")), Event.created_at >= lo, Event.created_at <= now))).all()
        old = now - timedelta(minutes=STUCK_MIN)
        stuck = await s.scalar(select(func.count()).select_from(Song).where(
            (Song.status.in_(("preview_queued", "preview_gen")) & (func.coalesce(Song.preview_at, Song.updated_at) < old))
            | (Song.status.in_(("paid_queued", "paid_gen")) & (Song.updated_at < old)))) or 0
    reasons = Counter((m or {}).get("r") or "unknown" for k, m in rows if k in ("sample_failed", "song_failed"))
    for r in USER_SIDE:
        reasons.pop(r, None)
    errors = sum(reasons.values())
    ok = sum(1 for k, _ in rows if k in ("sample_ready", "song_delivered"))
    return {"attempts": ok + errors, "errors": errors, "pct": _pct(errors, ok + errors), "stuck": stuck,
            "down": sum(n for r, n in reasons.items() if r in DOWN),
            "reasons": [{"key": k, "label": REASONS.get(k, k), "n": n} for k, n in reasons.most_common()]}


def alert_texts(h: dict, cfg: dict) -> dict[str, str]:
    """Hozir ogohlantirishga arziydigan sabablar: {sabab: xabar matni}."""
    out = {}
    why = "; ".join(f"{x['label']} — {x['n']}" for x in h["reasons"])
    if h["down"] or h["stuck"]:
        parts = []
        if h["down"]:
            parts.append(f"oxirgi 1 soatda {h['down']} ta so'rov javobsiz qoldi yoki rad etildi")
        if h["stuck"]:
            parts.append(f"{h['stuck']} ta qo'shiq {STUCK_MIN} daqiqadan beri tayyor bo'lmayapti")
        out["down"] = ("🚨 Musiqa xizmati javob bermayapti: " + ", ".join(parts) + "."
                       + (f"\nSabablar: {why}." if why else "") + "\nBatafsil: admin panel → Tizim → Oxirgi xatolar.")
    if h["attempts"] >= cfg["alert_min"] and h["pct"] > cfg["alert_pct"]:
        out["rate"] = (f"⚠️ Qo'shiq xizmatida xatolar ko'paydi: oxirgi 1 soatda {h['attempts']} ta urinishdan {h['errors']} tasi xato "
                       f"({str(h['pct']).replace('.', ',')}%, chegara {cfg['alert_pct']}%)."
                       + (f"\nSabablar: {why}." if why else "") + "\nBatafsil: admin panel → Tizim → Oxirgi xatolar.")
    return out


_ALERT_LOCK = asyncio.Lock()  # bir vaqtda tugagan ikki xato bitta ogohlantirishni ikki marta yubormasin


async def alert_check(bot, now: datetime | None = None) -> list[str]:
    """Bir soatda xatolar chegaradan oshsa yoki musiqa xizmati javob bermasa adminlarga xabar yuboradi.
    Bir sabab bo'yicha soatiga ko'pi bilan bitta xabar; admin panelda o'chirsa bo'ladi. Yuborilgan sabablar qaytadi."""
    try:
        async with _ALERT_LOCK:
            cfg = await config()
            if not bot or not cfg["alert_on"] or not settings.admins:
                return []
            now = now or utcnow()
            texts = alert_texts(await last_hour(now), cfg)
            last = dict(cfg["alerted"] or {})
            due = [c for c in texts if not _dt(last.get(c)) or now - _dt(last[c]) >= timedelta(hours=1)]
            if not due:
                return []
            for c in due:  # avval belgilaymiz, keyin yuboramiz: uzilish bo'lsa ham takror ketmaydi
                last[c] = now.isoformat(timespec="seconds")
            cfg["alerted"] = last
            await store.put(KEY, cfg)
        for c in due:
            for admin in settings.admins:
                try:
                    await bot.send_message(admin, texts[c], parse_mode=None)
                except Exception:
                    log.warning("Adminga qo'shiq ogohlantirishini yuborib bo'lmadi: %s", admin)
        return due
    except Exception:
        log.exception("Qo'shiq ogohlantirishini tekshirib bo'lmadi")
        return []


async def alert_test(bot, admin_id: int) -> None:
    """Adminning o'ziga namuna ogohlantirish (hisobga yozilmaydi)."""
    h = await last_hour()
    await bot.send_message(admin_id, "🔔 Sinov: qo'shiq xatolari bo'yicha ogohlantirish shu ko'rinishda keladi.\n"
                                     f"Hozir oxirgi 1 soatda {h['attempts']} ta urinish, {h['errors']} tasi xato "
                                     f"({str(h['pct']).replace('.', ',')}%).", parse_mode=None)
