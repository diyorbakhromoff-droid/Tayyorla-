"""Karta raqamiga o'tkazma: sozlamalar, chekni AI bilan o'qish va avtomatik tasdiqlash qoidalari.

AI faqat chekdagi maydonlarni o'qiydi (summa, vaqt, qabul qiluvchi karta, tranzaksiya raqami).
Tasdiqlash qarori shu yerda, kod bilan: summa aynan to'g'ri, karta bizniki, vaqt to'lov ochilgandan keyin,
chek va tranzaksiya raqami takrorlanmagan, summa chegaradan oshmagan, kunlik avtomatik limit.
Biror shart bajarilmasa — chek adminga qo'lda tekshirish uchun yuboriladi.
Mijozning karta raqami hech qayerga yozilmaydi.
"""

import base64
import hashlib
import json
import logging
import re
from datetime import datetime, timedelta, timezone

from sqlalchemy import func, select

from . import llm, store
from .db import Payment, Session, utcnow

log = logging.getLogger(__name__)

KEY = "cardpay"
TZ = timezone(timedelta(hours=5))  # cheklardagi vaqt — Toshkent vaqti
DEFAULTS = {
    "on": True,                     # admin paneldan o'chirsa bo'ladi
    "card": "9860 0201 0280 3622",  # mijozlarga ko'rsatiladigan karta (admin paneldan o'zgartiriladi)
    "owner": "Bakhromov Diyor",
    "auto": True,          # shartlar bajarilsa admin kutmasdan tasdiqlansin
    "auto_max": 300_000,   # bundan katta summalar doim qo'lda tekshiriladi
    "window_min": 180,     # chekdagi vaqt to'lov ochilganidan keyin shuncha daqiqa ichida bo'lishi kerak
    "daily_auto": 3,       # bir kishiga kuniga nechta avtomatik tasdiq
}
OPEN_HOURS = 48            # shuncha soatdan eski to'lovga chek qabul qilinmaydi


async def config() -> dict:
    v = await store.get(KEY) or {}
    return {k: v.get(k, d) for k, d in DEFAULTS.items()}


async def save(data: dict) -> dict:
    cfg = await config()
    for k, d in DEFAULTS.items():
        if k not in data or data[k] is None:
            continue
        val = data[k]
        if isinstance(d, bool):
            cfg[k] = bool(val)
        elif isinstance(d, int):
            cfg[k] = max(0, int(val))
        else:
            cfg[k] = str(val).strip()[:60]
    if cfg["card"]:
        digits = re.sub(r"\D", "", cfg["card"])
        cfg["card"] = " ".join(digits[i:i + 4] for i in range(0, len(digits), 4))
    await store.put(KEY, cfg)
    return cfg


def enabled(cfg: dict) -> bool:
    return bool(cfg.get("on") and len(re.sub(r"\D", "", cfg.get("card", ""))) >= 16)


def last4(card: str) -> str:
    return re.sub(r"\D", "", card or "")[-4:]


# ---------------------------------------------------------------- AI: chekni o'qish

SCHEMA = {
    "type": "object",
    "properties": {
        "is_receipt": {"type": "boolean"},
        "success": {"type": "boolean"},
        "amount": {"type": "integer"},
        "datetime": {"type": "string"},
        "recipient_last4": {"type": "string"},
        "recipient_name": {"type": "string"},
        "transaction_id": {"type": "string"},
        "app": {"type": "string"},
        "edited_signs": {"type": "boolean"},
    },
    "required": ["is_receipt", "success", "amount", "datetime", "recipient_last4", "recipient_name",
                 "transaction_id", "app", "edited_signs"],
    "additionalProperties": False,
}

SYSTEM = """You read screenshots of payment receipts from Uzbek banking and payment apps (Click, Payme, Uzum, Paynet, bank apps: Kapitalbank, Agrobank, Hamkorbank, TBC, Anorbank, Ipak Yo'li, Xalq banki, Asaka and others). The text may be in Uzbek (Latin or Cyrillic), Russian or English.
Extract the fields exactly as shown. Never guess: if a field is not visible, return an empty string (or 0 for amount).
- is_receipt: true only if this is a receipt/confirmation of a card-to-card transfer or payment.
- success: true only if the receipt clearly shows the operation succeeded (e.g. "Muvaffaqiyatli", "Успешно", "Success", "O'tkazildi", "Bajarildi", a green check). false for pending, processing, failed or cancelled.
- amount: the transferred amount in so'm as an integer, WITHOUT the commission/fee. "50 000,00 so'm" -> 50000.
- datetime: date and time of the operation as "YYYY-MM-DD HH:MM" (as printed, local time). Empty if not visible.
- recipient_last4: last 4 digits of the RECIPIENT card (not the sender card). Empty if not visible.
- recipient_name: recipient name as printed, transliterated to Latin letters. Empty if not visible.
- transaction_id: the operation/transaction/check/receipt number or ID, digits and letters only. Empty if not visible.
- app: name of the app or bank that issued the receipt.
- edited_signs: true if the image shows signs of editing (mismatched fonts, misaligned or overlapping digits, pasted text, inconsistent backgrounds)."""


def _parse_dt(v: str) -> datetime | None:
    v = (v or "").strip().replace("T", " ")
    for fmt in ("%Y-%m-%d %H:%M:%S", "%Y-%m-%d %H:%M", "%d.%m.%Y %H:%M:%S", "%d.%m.%Y %H:%M", "%d/%m/%Y %H:%M"):
        try:
            return datetime.strptime(v, fmt).replace(tzinfo=TZ).astimezone(timezone.utc).replace(tzinfo=None)
        except ValueError:
            continue
    return None


async def read(data: bytes, mime: str, uid: int | None = None) -> dict | None:
    """Chekdagi maydonlar yoki None (AI ishlamasa)."""
    try:
        text, usage = await llm.generate("main", SYSTEM, "Read this payment receipt.", 600, effort="low",
                                         schema=SCHEMA, image=(data, mime))
    except Exception:
        log.exception("Chekni AI o'qiy olmadi")
        return None
    try:
        from .costs import log_ai
        await log_ai(usage, "receipt", uid)
    except Exception:
        log.warning("Chek xarajatini yozib bo'lmadi")
    try:
        out = json.loads(text)
    except ValueError:
        log.warning("Chek javobi JSON emas: %s", text[:300])
        return None
    out["transaction_id"] = re.sub(r"[^0-9A-Za-z]", "", str(out.get("transaction_id") or ""))[:36]
    out["recipient_last4"] = re.sub(r"\D", "", str(out.get("recipient_last4") or ""))[-4:]
    return out


def _name_ok(owner: str, seen: str) -> bool:
    """Egasining ismi va familiyasi chekda bormi (katta-kichik harf, tutuq belgilarisiz)."""
    norm = lambda x: re.sub(r"[^a-z ]", "", (x or "").lower().replace("kh", "x").replace("h", "x"))
    want = [w for w in norm(owner).split() if len(w) >= 3]
    got = norm(seen)
    return bool(want) and all(w[:4] in got for w in want)


async def verify(p: Payment, r: dict | None, cfg: dict, now: datetime | None = None) -> tuple[bool, list[str]]:
    """(avtomatik tasdiqlash mumkinmi, sabablar). Sabablar adminga ko'rsatiladi."""
    now = now or utcnow()
    why: list[str] = []
    if r is None:
        return False, ["AI chekni o'qiy olmadi"]
    if not r.get("is_receipt"):
        return False, ["rasmda to'lov cheki topilmadi"]
    if not r.get("success"):
        why.append("chekda «muvaffaqiyatli» belgisi yo'q")
    if r.get("edited_signs"):
        why.append("AI tahrir belgilarini ko'rdi")
    amount = int(r.get("amount") or 0)
    if amount != p.amount:
        why.append(f"summa mos emas: chekda {amount:,} so'm, kerak {p.amount:,}".replace(",", " "))
    l4 = r.get("recipient_last4") or ""
    if l4:
        if l4 != last4(cfg["card"]):
            why.append(f"qabul qiluvchi karta boshqa: *{l4}")
    elif not _name_ok(cfg["owner"], r.get("recipient_name", "")):
        why.append("qabul qiluvchi karta/ism chekda ko'rinmadi")
    at = _parse_dt(r.get("datetime", ""))
    if not at:
        why.append("chekda vaqt topilmadi")
    else:
        opened = p.created_at or now
        if at < opened - timedelta(minutes=5):
            why.append("chek to'lov ochilishidan oldingi vaqtda")
        elif at > now + timedelta(minutes=5):
            why.append("chekdagi vaqt kelajakda")
        elif now - at > timedelta(minutes=cfg["window_min"]):
            why.append(f"chek eski: {int((now - at).total_seconds() // 60)} daqiqa oldin")
    tid = r.get("transaction_id") or ""
    async with Session() as s:
        if not tid:
            why.append("tranzaksiya raqami ko'rinmadi")
        elif await s.scalar(select(func.count()).select_from(Payment).where(
                Payment.provider == "card", Payment.ext_id == tid, Payment.id != p.id)):
            why.append("bu tranzaksiya raqami oldin ishlatilgan")
        day = now - timedelta(hours=24)
        autos = await s.scalar(select(func.count()).select_from(Payment).where(
            Payment.user_id == p.user_id, Payment.provider == "card", Payment.status == "approved",
            Payment.admin_id == 0, Payment.decided_at >= day))
    if not cfg["auto"]:
        why.append("avtomatik tasdiqlash o'chirilgan")
    if p.amount > cfg["auto_max"]:
        why.append(f"summa avtomatik chegaradan katta ({cfg['auto_max']:,})".replace(",", " "))
    if autos >= cfg["daily_auto"]:
        why.append("bugungi avtomatik tasdiqlar limiti tugagan")
    return not why, why


def digest(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def b64(data: bytes) -> str:
    return base64.standard_b64encode(data).decode()


def summary(r: dict | None) -> str:
    """Admin uchun qisqa satr (mijoz kartasi raqamisiz)."""
    if not r:
        return "AI o'qiy olmadi"
    parts = [f"{int(r.get('amount') or 0):,} so'm".replace(",", " "), r.get("datetime") or "vaqt yo'q",
             f"→ *{r['recipient_last4']}" if r.get("recipient_last4") else (r.get("recipient_name") or ""),
             f"ID {r['transaction_id']}" if r.get("transaction_id") else "", r.get("app") or ""]
    return " · ".join(x for x in parts if x)
