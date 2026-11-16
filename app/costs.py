"""Bizning tashqi xarajatlarimiz: musiqa (ElevenLabs yoki Google Lyria) va Claude (matn, she'r) chaqiruvlari.

Har bir chaqiruv haqiqiy hajmi bilan yoziladi (musiqa — soniya, Claude — kirish/chiqish tokenlari).
So'mdagi qiymat hisobot paytida admin paneldagi narxlar bilan hisoblanadi, shuning uchun narx o'zgarsa
eski yozuvlar ham yangi narx bilan qayta hisoblanadi.
"""

import logging

from sqlalchemy import func, select

from . import store
from .db import CostLog, Session, Song

log = logging.getLogger(__name__)

KEY = "costs"
DEFAULTS = {
    "usd_som": 12800,          # 1 AQSH dollari necha so'm
    "credits_per_sec": 15,     # ElevenLabs: 1 soniya musiqa ≈ 15 kredit (sinovda 100 s ≈ 1500 kredit)
    "usd_per_1k_credits": 0.22,  # tarifingizdagi 1000 kredit narxi (Creator: $22 / 100 000 kredit)
    "ai_in_per_m": 4.0,        # Claude: 1 mln kirish tokeni, $
    "ai_out_per_m": 20.0,      # Claude: 1 mln chiqish tokeni, $
    "lyria_usd_per_song": 0.08,  # Google Lyria 3.5: bitta qo'shiq, $
}
LIMITS = {"usd_som": (1000, 100000), "credits_per_sec": (1, 200), "usd_per_1k_credits": (0.01, 10),
          "ai_in_per_m": (0, 200), "ai_out_per_m": (0, 500), "lyria_usd_per_song": (0, 5)}

PURPOSES = {
    "song_preview": "Qo'shiq namunasi (demo)", "song_full": "Sotilgan qo'shiq",
    "song_est": "Qo'shiq (hisob yuritilishidan oldingi, taxmin)",
    "lyrics": "Qo'shiq she'ri", "lyrics_edit": "She'rni qayta yozish", "lyrics_est": "Qo'shiq she'ri (taxmin)",
    "song_test": "Musiqa xizmati sinovi",
    "site_text": "Taklifnoma matni", "site_edit": "Sayt tahriri (AI)", "video_text": "Video matni", "translate": "Tarjima",
}
SONG_PURPOSES = ("song_preview", "song_full", "song_est", "lyrics", "lyrics_edit", "lyrics_est")
# hisob yuritilishidan oldingi qo'shiqlar uchun she'r yozishning o'rtacha hajmi
EST_LYRICS_TOKENS = (3000, 5000)


async def rates() -> dict:
    saved = await store.get(KEY, {}) or {}
    return {k: float(saved.get(k, v)) for k, v in DEFAULTS.items()}


async def save_rates(values: dict) -> dict:
    cur = await rates()
    for k, (lo, hi) in LIMITS.items():
        if k in values and values[k] is not None:
            cur[k] = min(hi, max(lo, float(values[k])))
    await store.put(KEY, cur)
    return cur


def som_of(row_kind: str, units_in: int, units_out: int, r: dict) -> float:
    if row_kind == "music":
        return units_in * r["credits_per_sec"] / 1000 * r["usd_per_1k_credits"] * r["usd_som"]
    if row_kind == "lyria":  # units_in — qo'shiqlar soni
        return units_in * r["lyria_usd_per_song"] * r["usd_som"]
    return (units_in * r["ai_in_per_m"] + units_out * r["ai_out_per_m"]) / 1e6 * r["usd_som"]


async def _add(row: CostLog) -> None:
    """Xarajatni yozadi. Hech qachon asosiy jarayonni to'xtatmaydi."""
    try:
        async with Session() as s:
            s.add(row)
            await s.commit()
    except Exception:
        log.exception("Xarajatni yozib bo'lmadi: %s", row.purpose)


def music_row(seconds: float, purpose: str, user_id: int | None = None, ref: str = "") -> CostLog:
    return CostLog(kind="music", purpose=purpose, units_in=max(0, round(seconds)), user_id=user_id, ref=ref[:40])


def lyria_row(purpose: str, user_id: int | None = None, ref: str = "") -> CostLog:
    return CostLog(kind="lyria", purpose=purpose, units_in=1, user_id=user_id, ref=ref[:40])


def ai_row(usage, purpose: str, user_id: int | None = None, ref: str = "") -> CostLog | None:
    """usage — Claude javobining .usage maydoni (yoki javobning o'zi)."""
    u = getattr(usage, "usage", usage)
    if u is None:
        return None
    tin = (getattr(u, "input_tokens", 0) or 0) + (getattr(u, "cache_creation_input_tokens", 0) or 0) + (getattr(u, "cache_read_input_tokens", 0) or 0)
    return CostLog(kind="ai", purpose=purpose, units_in=int(tin), units_out=int(getattr(u, "output_tokens", 0) or 0),
                   user_id=user_id, ref=ref[:40])


async def log_ai(usage, purpose: str, user_id: int | None = None, ref: str = "") -> None:
    """Sessiyasi yo'q joylar uchun (matn yozish, tarjima): alohida sessiyada yozadi."""
    row = ai_row(usage, purpose, user_id, ref)
    if row is not None:
        await _add(row)


def _plan_seconds(plan: dict | None) -> float:
    return sum((c.get("duration_ms") or 0) for c in (plan or {}).get("chunks", [])) / 1000


async def summary(s, a, b, r: dict | None = None) -> dict:
    """[a, b) oralig'idagi xarajatlar so'mda va maqsadlar bo'yicha. Jurnal yuritilishidan oldin yaratilgan
    qo'shiqlar uchun xarajat Song yozuvidan taxmin qilinadi (nechta variant × reja uzunligi)."""
    r = r or await rates()
    rows = (await s.execute(select(CostLog.kind, CostLog.purpose, func.count(), func.sum(CostLog.units_in), func.sum(CostLog.units_out))
                            .where(CostLog.created_at >= a, CostLog.created_at < b).group_by(CostLog.kind, CostLog.purpose))).all()
    by = {}
    for kind, purpose, n, uin, uout in rows:
        by[purpose] = {"purpose": purpose, "label": PURPOSES.get(purpose, purpose), "kind": kind, "n": n,
                       "units_in": int(uin or 0), "units_out": int(uout or 0), "som": som_of(kind, uin or 0, uout or 0, r)}
    # jurnaldan oldingi qo'shiqlar (bu davrda yaratilgan, lekin xarajat yozuvi yo'q)
    logged = set((await s.execute(select(CostLog.ref).where(CostLog.ref.like("song:%")).distinct())).scalars().all())
    old = (await s.execute(select(Song.id, Song.variants, Song.plan, Song.lyrics).where(Song.created_at >= a, Song.created_at < b))).all()
    est_sec, est_n, est_lyr = 0.0, 0, 0
    for sid, variants, plan, lyrics in old:
        if f"song:{sid}" in logged:
            continue
        if variants:
            est_sec += len(variants) * _plan_seconds(plan)
            est_n += len(variants)
        if lyrics:
            est_lyr += 1
    if est_n:
        by["song_est"] = {"purpose": "song_est", "label": PURPOSES["song_est"], "kind": "music", "n": est_n,
                          "units_in": round(est_sec), "units_out": 0, "som": som_of("music", est_sec, 0, r)}
    if est_lyr:
        tin, tout = EST_LYRICS_TOKENS[0] * est_lyr, EST_LYRICS_TOKENS[1] * est_lyr
        by["lyrics_est"] = {"purpose": "lyrics_est", "label": PURPOSES["lyrics_est"], "kind": "ai", "n": est_lyr,
                            "units_in": tin, "units_out": tout, "som": som_of("ai", tin, tout, r)}
    items = sorted(by.values(), key=lambda x: -x["som"])
    for it in items:
        it["som"] = round(it["som"])
        it["credits"] = round(it["units_in"] * r["credits_per_sec"]) if it["kind"] == "music" else 0
    total = sum(it["som"] for it in items)
    song = sum(it["som"] for it in items if it["purpose"] in SONG_PURPOSES)
    demo = by.get("song_preview", {})
    return {"total": total, "song": song, "other": total - song, "items": items,
            "music_seconds": sum(it["units_in"] for it in items if it["kind"] == "music"),
            "demo_n": demo.get("n", 0), "demo_som": round(demo.get("som", 0)),
            "demo_avg": round(demo["som"] / demo["n"]) if demo.get("n") else 0}
