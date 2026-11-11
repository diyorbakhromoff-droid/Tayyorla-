"""Click SHOP API: to'lov havolasi va Prepare/Complete so'rovlari.

Oqim: foydalanuvchi balansni to'ldiradi -> Payment yoziladi -> my.click.uz havolasi (transaction_param = Payment.id).
Click avval /api/click/prepare, pul yechilgach /api/click/complete ga murojaat qiladi. Complete muvaffaqiyatli
bo'lsa balans to'ldiriladi, to'lov kutayotgan videolar navbatga qo'yiladi va sayt (bo'lsa) balansdan faollashadi.
Kalitlar faqat .env da: CLICK_SERVICE_ID, CLICK_MERCHANT_ID, CLICK_MERCHANT_USER_ID, CLICK_SECRET_KEY.
"""

import hashlib
import hmac
import logging
from urllib.parse import urlencode

from fastapi import APIRouter, Request
from fastapi.responses import JSONResponse

from . import billing
from .config import settings
from .db import Payment, Session, User, utcnow

log = logging.getLogger(__name__)
router = APIRouter()

PAY_URL = "https://my.click.uz/services/pay"

# Click xato kodlari
OK, SIGN, AMOUNT, ACTION, PAID, NOT_FOUND, NO_TRANS, UPDATE, REQUEST, CANCELLED = 0, -1, -2, -3, -4, -5, -6, -7, -8, -9
NOTES = {OK: "Success", SIGN: "SIGN CHECK FAILED!", AMOUNT: "Incorrect parameter amount", ACTION: "Action not found",
         PAID: "Already paid", NOT_FOUND: "User does not exist", NO_TRANS: "Transaction does not exist",
         UPDATE: "Failed to update user", REQUEST: "Error in request from click", CANCELLED: "Transaction cancelled"}


def pay_url(payment_id: int, amount: int) -> str:
    if not settings.click_on:
        return ""
    q = {"service_id": settings.click_service_id, "merchant_id": settings.click_merchant_id, "amount": f"{amount}.00",
         "transaction_param": str(payment_id), "return_url": f"https://t.me/{settings.bot_username}"}
    return f"{PAY_URL}?{urlencode(q)}"


def sign(f: dict, complete: bool) -> str:
    parts = [f.get("click_trans_id", ""), f.get("service_id", ""), settings.click_secret_key, f.get("merchant_trans_id", "")]
    if complete:
        parts.append(f.get("merchant_prepare_id", ""))
    parts += [f.get("amount", ""), f.get("action", ""), f.get("sign_time", "")]
    return hashlib.md5("".join(str(x) for x in parts).encode()).hexdigest()


def _answer(f: dict, code: int, **extra) -> JSONResponse:
    body = {"click_trans_id": f.get("click_trans_id"), "merchant_trans_id": f.get("merchant_trans_id"),
            **extra, "error": code, "error_note": NOTES[code]}
    return JSONResponse(body)


def _same_amount(raw: str, amount: int) -> bool:
    try:
        return abs(float(raw) - amount) < 0.01
    except (TypeError, ValueError):
        return False


async def _check(request: Request, complete: bool):
    """Umumiy tekshiruvlar: (maydonlar, xato kodi yoki None)."""
    f = {k: str(v) for k, v in (await request.form()).items()}
    need = ["click_trans_id", "service_id", "merchant_trans_id", "amount", "action", "sign_time", "sign_string"]
    if complete:
        need.append("merchant_prepare_id")
    if not settings.click_on or any(k not in f for k in need):
        return f, REQUEST
    if not hmac.compare_digest(sign(f, complete).lower(), f["sign_string"].lower()) or f["service_id"] != settings.click_service_id:
        return f, SIGN
    if f["action"] != ("1" if complete else "0"):
        return f, ACTION
    return f, None


@router.post("/api/click/prepare")
async def prepare(request: Request):
    f, err = await _check(request, complete=False)
    if err is not None:
        log.warning("Click prepare rad etildi (%s): %s", err, f.get("merchant_trans_id"))
        return _answer(f, err)
    pid = int(f["merchant_trans_id"]) if f["merchant_trans_id"].isdigit() else 0
    async with Session() as s:
        p = await s.get(Payment, pid) if pid else None
        if not p:
            return _answer(f, NOT_FOUND)
        if p.status == "approved":
            return _answer(f, PAID)
        if p.status in ("rejected", "cancelled"):
            return _answer(f, CANCELLED)
        if not _same_amount(f["amount"], p.amount):
            return _answer(f, AMOUNT)
        p.provider, p.ext_id = "click", f["click_trans_id"][:40]
        await s.commit()
    return _answer(f, OK, merchant_prepare_id=p.id)


@router.post("/api/click/complete")
async def complete(request: Request):
    f, err = await _check(request, complete=True)
    if err is not None:
        log.warning("Click complete rad etildi (%s): %s", err, f.get("merchant_trans_id"))
        return _answer(f, err)
    pid = int(f["merchant_trans_id"]) if f["merchant_trans_id"].isdigit() else 0
    async with Session() as s:
        p = await s.get(Payment, pid) if pid else None
        if not p:
            return _answer(f, NOT_FOUND)
        if str(p.id) != f["merchant_prepare_id"] or p.provider != "click" or p.ext_id != f["click_trans_id"][:40]:
            return _answer(f, NO_TRANS)
        if p.status == "approved":
            return _answer(f, PAID)
        if p.status in ("rejected", "cancelled"):
            return _answer(f, CANCELLED)
        if not _same_amount(f["amount"], p.amount):
            return _answer(f, AMOUNT)
        try:
            click_error = int(f.get("error") or 0)
        except ValueError:
            click_error = 0
        if click_error < 0:  # Click tomonida to'lov amalga oshmadi
            p.status, p.decided_at = "cancelled", utcnow()
            await s.commit()
            return _answer(f, CANCELLED)
        p.status, p.decided_at = "approved", utcnow()
        await billing.credit(s, p.user_id, p.amount, "topup", f"pay:{p.id}")
        await s.commit()
        user = await s.get(User, p.user_id)
    log.info("Click to'lovi: #%s, %s so'm, foydalanuvchi %s", p.id, p.amount, p.user_id)
    try:
        from . import videobot
        from .bot.money import after_topup
        await after_topup(videobot.BOT, p, user)
    except Exception:
        log.exception("Click to'lovidan keyingi xabarlar yuborilmadi: #%s", p.id)
    return _answer(f, OK, merchant_confirm_id=p.id)
