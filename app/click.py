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
from sqlalchemy import update
from fastapi.responses import JSONResponse, RedirectResponse

from . import billing, payflow
from .config import settings
from .db import Payment, Session, User, utcnow
from .track import BOT_UA

log = logging.getLogger(__name__)
router = APIRouter()

PAY_URL = "https://my.click.uz/services/pay"

# Click xato kodlari
OK, SIGN, AMOUNT, ACTION, PAID, NOT_FOUND, NO_TRANS, UPDATE, REQUEST, CANCELLED = 0, -1, -2, -3, -4, -5, -6, -7, -8, -9
NOTES = {OK: "Success", SIGN: "SIGN CHECK FAILED!", AMOUNT: "Incorrect parameter amount", ACTION: "Action not found",
         PAID: "Already paid", NOT_FOUND: "User does not exist", NO_TRANS: "Transaction does not exist",
         UPDATE: "Failed to update user", REQUEST: "Error in request from click", CANCELLED: "Transaction cancelled"}


def pay_url(payment_id: int, amount: int, back: str = "") -> str:
    """Click to'lov sahifasi. back — to'lovdan keyin qaytish manzili (berilmasa — bot)."""
    if not settings.click_on:
        return ""
    q = {"service_id": settings.click_service_id, "merchant_id": settings.click_merchant_id, "amount": f"{amount}.00",
         "transaction_param": str(payment_id), "return_url": back or f"https://t.me/{settings.bot_username}"}
    return f"{PAY_URL}?{urlencode(q)}"


# ---------------------------------------------------------------- kuzatuv havolasi (statistika: Click sahifasiga o'tdi / qaytdi)

def _key(payment_id: int, amount: int) -> str:
    """Kuzatuv havolasining imzosi: begona odam to'lov raqamlarini terib, statistikani buza olmasin."""
    return hmac.new(settings.bot_token.encode(), f"pay:{payment_id}:{amount}".encode(), hashlib.sha256).hexdigest()[:12]


async def link(payment_id: int, amount: int) -> str:
    """Mijozga beriladigan Click havolasi (bot tugmasi va Mini App).

    Kuzatuv yoqilgan bo'lsa havola bizning /pay/c/… orqali o'tadi: bosilgani («Click sahifasiga o'tdi») yoziladi va
    mijoz darhol Click sahifasiga yo'naltiriladi. Sayt HTTPS da bo'lmasa yoki admin kuzatuvni o'chirgan bo'lsa —
    avvalgidek to'g'ridan-to'g'ri Click havolasi."""
    if not settings.click_on:
        return ""
    base = settings.base_url.rstrip("/")
    try:
        on = base.startswith("https://") and (await payflow.config())["click_track"]
    except Exception:
        on = False
    return f"{base}/pay/c/{payment_id}/{amount}/{_key(payment_id, amount)}" if on else pay_url(payment_id, amount)


async def _visit(kind: str, pid: int, request: Request, only_open: bool) -> None:
    """Kuzatuv havolasidan o'tishni yozadi. Xato bo'lsa jim — mijozni yo'naltirish to'xtamasligi kerak."""
    try:
        if BOT_UA.search(request.headers.get("user-agent", "")):
            return  # havola ko'rinishini (preview) olayotgan robotlar sanalmaydi
        async with Session() as s:
            p = await s.get(Payment, pid)
        if p and (p.status in ("new", "pending") or not only_open):
            await payflow.step(kind, p)
    except Exception:
        log.exception("To'lov qadamini yozib bo'lmadi: %s #%s", kind, pid)


@router.get("/pay/c/{pid}/{amount}/{key}")
async def to_click(pid: int, amount: int, key: str, request: Request):
    """Kuzatuv havolasi: «Click sahifasiga o'tdi» qadamini yozadi va Click to'lov sahifasiga yo'naltiradi."""
    if not settings.click_on or not hmac.compare_digest(key, _key(pid, amount)):
        return RedirectResponse(f"https://t.me/{settings.bot_username}", status_code=302)
    await _visit("pay_click", pid, request, only_open=True)
    back = f"{settings.base_url.rstrip('/')}/pay/r/{pid}/{amount}/{key}"
    return RedirectResponse(pay_url(pid, amount, back), status_code=302)


@router.get("/pay/r/{pid}/{amount}/{key}")
async def from_click(pid: int, amount: int, key: str, request: Request):
    """Click sahifasidan qaytish: «qaytdi» qadamini yozadi va botga yo'naltiradi."""
    if hmac.compare_digest(key, _key(pid, amount)):
        await _visit("pay_return", pid, request, only_open=False)
    return RedirectResponse(f"https://t.me/{settings.bot_username}", status_code=302)


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
    await payflow.step("pay_prepare", p)
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
            await payflow.step("pay_cancel", p, err=click_error)
            return _answer(f, CANCELLED)
        # Click so'rovni qayta yuborsa ham (bir vaqtda ikki complete) pul faqat bir marta tushadi
        res = await s.execute(update(Payment).where(Payment.id == p.id, Payment.status.in_(("new", "pending")))
                              .values(status="approved", decided_at=utcnow()).execution_options(synchronize_session=False))
        if res.rowcount != 1:
            await s.rollback()
            return _answer(f, PAID)
        await billing.credit(s, p.user_id, p.amount, "topup", f"pay:{p.id}")
        await s.commit()
        await s.refresh(p)
        user = await s.get(User, p.user_id)
    log.info("Click to'lovi: #%s, %s so'm, foydalanuvchi %s", p.id, p.amount, p.user_id)
    await payflow.paid(p)
    try:
        from . import videobot
        from .bot.money import after_topup
        await after_topup(videobot.BOT, p, user)
    except Exception:
        log.exception("Click to'lovidan keyingi xabarlar yuborilmadi: #%s", p.id)
    return _answer(f, OK, merchant_confirm_id=p.id)
