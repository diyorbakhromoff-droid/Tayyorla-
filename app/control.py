"""Nazorat guruhi va chegirma A/B (statistika TZ, 5-band).

Nazorat guruhi: yoqilgandan keyin qo'shilgan YANGI foydalanuvchilarning `pct` foizi hech qanday progrev (app/nudges.py) va
chegirma xabarini (app/pricing.py: taklif, eski namunalarga tarqatma, eslatmalar) olmaydi — chegirmaning o'zi ham berilmaydi.
Panelda ikki guruhning sotuv va blok foizi yonma-yon chiqadi: progrev haqiqatan sotuv qo'shyaptimi, faqat shu bilan bilinadi.
Standart holatda O'CHIQ — egasi o'zi yoqadi.

Kim qaysi guruhda — saqlanmaydi, foydalanuvchi id sidan hisoblanadi (doim bir xil natija): bucket(id) = ((id mod 1000003) · 7919 + 13)
mod 100 — 0..99. Shu formula SQL da ham bor (bucket_sql) — so'rovlar nazorat guruhini bazaning o'zida ajratadi. Guruhga
bucket < pct va users.created_at >= since bo'lganlar kiradi (since — oxirgi marta yoqilgan vaqt; o'chirilsa hamma odatdagidek
xabar oladi). Foizni o'zgartirish guruhni kengaytiradi yoki toraytiradi: 10 → 20 — avvalgilar qoladi, yangilari qo'shiladi.

Chegirma A/B (app/pricing.py, «ab» sozlamasi, standart O'CHIQ): chegirma taklif qilinadigan odamlarning teng yarmi ikkinchi narxni
oladi. Guruh ham id dan: arm(id) = «b», agar ((id mod 999983) · 6007 + 7) mod 2 = 1, aks holda «a». Yuborilgan har bir chegirma
xabari jurnalga guruhi bilan yoziladi (nudge_log.arm) — «Narxlar»dagi chegirma voronkasi shu bo'yicha bo'linadi.
"""

from datetime import datetime

from sqlalchemy import and_

from . import store
from .db import utcnow

KEY = "control"
DEFAULTS = {"on": False, "pct": 10, "since": None}


def bucket(uid: int) -> int:
    return ((int(uid) % 1000003) * 7919 + 13) % 100


def bucket_sql(col):
    return ((col % 1000003) * 7919 + 13) % 100


def arm(uid: int) -> str:
    return "b" if ((int(uid) % 999983) * 6007 + 7) % 2 else "a"


def _dt(v) -> datetime | None:
    try:
        return datetime.fromisoformat(v or "")
    except (TypeError, ValueError):
        return None


async def config() -> dict:
    v = await store.get(KEY) or {}
    out = {k: v.get(k, d) for k, d in DEFAULTS.items()}
    out["since_dt"] = _dt(out["since"])
    return out


async def save(on: bool | None = None, pct: int | None = None) -> dict:
    cfg = {k: v for k, v in (await config()).items() if k in DEFAULTS}
    if pct is not None:
        pct = int(pct)
        if not 1 <= pct <= 50:
            raise ValueError("Nazorat guruhi 1–50 foiz bo'lsin")
        cfg["pct"] = pct
    if on is not None:
        if on and not cfg["on"]:
            cfg["since"] = utcnow().isoformat(timespec="seconds")  # taqqoslash shu paytdan keyin kelganlar bo'yicha
        cfg["on"] = bool(on)
    await store.put(KEY, cfg)
    return await config()


def is_member(cfg: dict, uid: int, created_at: datetime | None) -> bool:
    """Shu odam nazorat guruhidami (progrev va chegirma olmaydi)."""
    since = cfg.get("since_dt")
    return bool(cfg.get("on") and since and created_at and created_at >= since and bucket(uid) < cfg["pct"])


def member_sql(cfg: dict, uid_col, created_col):
    """SQL sharti: nazorat guruhida. Guruh o'chiq bo'lsa None."""
    since = cfg.get("since_dt")
    if not (cfg.get("on") and since):
        return None
    return and_(created_col >= since, bucket_sql(uid_col) < cfg["pct"])


def group_sql(cfg: dict, uid_col, created_col):
    """Taqqoslash uchun (guruh yoqilgan yoki yoqilmaganidan qat'i nazar): since dan keyin kelganlar orasida — nazoratdami."""
    return bucket_sql(uid_col) < cfg["pct"]
