"""«Nega to'lamadingiz» so'rovi (statistika TZ, 3-band).

To'lov oynasini ochib, 15 daqiqa ichida to'lamagan odamga bot BITTA savol yuboradi; javob bir bosishda tanlanadi.
Qoidalar: bir odamga umrida bir marta; botni bloklaganlarga, admin va sinov akkauntlariga yuborilmaydi; tunda
(progrev sozlamasidagi soatlardan tashqari, app/nudges.py) yuborilmaydi — ertalab yuboriladi; shu orada to'lagan,
cheki tekshiruvda turgan yoki hozirgina yana urinayotgan odamga yuborilmaydi. Admin panelda yoqib-o'chiriladi.

Hodisalar: pay_ask — savol yuborildi (num = 1; yetib bormasa 0), pay_why — javob (num = javob raqami 1..5).
"""

import asyncio
import logging
from datetime import datetime, timedelta, timezone

from sqlalchemy import func, or_, select, update

from . import nudges, payflow, track
from .db import Event, Payment, Session, User, utcnow
from .i18n import tr
from .reminders import TZ

log = logging.getLogger(__name__)

DELAY_MIN = 15       # oyna ochilgandan keyin shuncha daqiqa to'lamasa — so'raymiz
MAX_AGE_H = 24       # bundan eski urinish haqida so'ralmaydi (tun o'tib, ertalab yuborishga yetadi)
PENDING_H = 48       # cheki tekshiruvda turgan odam shuncha vaqt bezovta qilinmaydi
MAX_PER_PASS = 100
# javob kodi va paneldagi nomi (botdagi tugma yozuvi — i18n: bot.why_a1..a5)
ANSWERS = [("nocard", "Kartam yo'q yoki Click ishlamadi"), ("price", "Qimmat ekan"), ("later", "Keyinroq olaman"),
           ("how", "Qanday to'lashni tushunmadim"), ("look", "Shunchaki ko'rayotgan edim")]
STATE: dict = {"last_run": None, "last_sent": 0}


def question(lang: str) -> str:
    return tr(lang, "bot.why_q")


def label(n: int, lang: str) -> str:
    return tr(lang, f"bot.why_a{n}")


def keyboard(pid: int, lang: str):
    from aiogram.types import InlineKeyboardButton, InlineKeyboardMarkup
    return InlineKeyboardMarkup(inline_keyboard=[[InlineKeyboardButton(text=label(i, lang), callback_data=f"pw:{pid}:{i}")]
                                                 for i in range(1, len(ANSWERS) + 1)])


async def due(s, now: datetime, lo: datetime, excl: set[int]) -> list[tuple[int, int, str]]:
    """Hozir so'ralishi kerak bo'lganlar: (foydalanuvchi, to'lov id, til). Bir odamga bitta — eng oxirgi urinishi."""
    hi = now - timedelta(minutes=DELAY_MIN)
    rows = (await s.execute(select(Payment.id, Payment.user_id, Payment.created_at).where(
        Payment.status.in_(("new", "cancelled")), Payment.created_at >= lo, Payment.created_at <= hi)
        .order_by(Payment.id.desc()))).all()
    cand: dict[int, tuple[int, datetime]] = {}
    for pid, uid, at in rows:
        if uid not in excl:
            cand.setdefault(uid, (pid, at))
    if not cand:
        return []
    ids = list(cand)
    # hozir yana urinayotgan (yangi urinishi bor) yoki cheki tekshiruvda turganlar — kutamiz
    busy = set((await s.execute(select(Payment.user_id).where(Payment.user_id.in_(ids), or_(
        Payment.created_at > hi,
        (Payment.status == "pending") & (Payment.created_at >= now - timedelta(hours=PENDING_H)))))).scalars().all())
    last_ok = dict((await s.execute(select(Payment.user_id, func.max(Payment.decided_at)).where(
        Payment.user_id.in_(ids), Payment.status == "approved").group_by(Payment.user_id))).all())
    asked = set((await s.execute(select(Event.user_id).where(Event.kind == "pay_ask", Event.user_id.in_(ids)))).scalars().all())
    users = {u[0]: u for u in (await s.execute(select(User.tg_id, User.blocked, User.lang).where(User.tg_id.in_(ids)))).all()}
    out = []
    for uid, (pid, at) in cand.items():
        u = users.get(uid)
        if uid in busy or uid in asked or not u or u[1]:
            continue
        if last_ok.get(uid) and last_ok[uid] >= at:
            continue  # shu urinishdan keyin to'lab bo'lgan
        out.append((uid, pid, u[2] or "uz"))
    return out


async def deliver(bot, uid: int, pid: int, lang: str) -> str:
    """sent | failed | blocked"""
    from aiogram.exceptions import TelegramForbiddenError, TelegramRetryAfter
    for attempt in range(2):
        try:
            await bot.send_message(uid, question(lang), reply_markup=keyboard(pid, lang))
            return "sent"
        except TelegramRetryAfter as e:
            if attempt:
                return "failed"
            await asyncio.sleep(e.retry_after + 1)
        except TelegramForbiddenError:
            return "blocked"
        except Exception:
            log.exception("To'lov so'rovi yuborilmadi: %s", uid)
            return "failed"
    return "failed"


async def run_once(bot, now: datetime | None = None) -> dict:
    """Bir aylanish. now — bazadagi (UTC, zonasiz) vaqt."""
    res = {"sent": 0, "failed": 0, "blocked": 0}
    cfg = await payflow.config()
    start = await payflow.survey_since()
    if not bot or not cfg["survey_on"] or not start:
        return res
    now = now or utcnow()
    if not nudges.in_hours(await nudges.config(), now.replace(tzinfo=timezone.utc).astimezone(TZ)):
        return res  # tunda yubormaymiz — ertalab davom etadi
    lo = max(start, now - timedelta(hours=MAX_AGE_H))  # tizim yoqilishidan oldingi urinishlar haqida so'ralmaydi
    excl = await track.excluded_ids()
    async with Session() as s:
        jobs = await due(s, now, lo, excl)
    for uid, pid, lang in jobs[:MAX_PER_PASS]:
        # avval yozamiz, keyin yuboramiz: uzilish bo'lsa ham bir odamga ikki marta ketmaydi
        if not await track.event("pay_ask", uid, payflow.ref_of(pid), 1, at=now):
            continue
        status = await deliver(bot, uid, pid, lang)
        if status != "sent":
            async with Session() as s:
                await s.execute(update(Event).where(Event.kind == "pay_ask", Event.user_id == uid).values(num=0))
                if status == "blocked":
                    await s.execute(update(User).where(User.tg_id == uid).values(blocked=True))
                await s.commit()
        res[status] += 1
        await asyncio.sleep(1 / 20)
    STATE.update(last_run=utcnow().isoformat(), last_sent=res["sent"])
    return res


async def loop(bot, interval: int = 60) -> None:
    await asyncio.sleep(75)  # ishga tushgach biroz kutamiz
    while True:
        try:
            res = await run_once(bot)
            if res["sent"] or res["failed"] or res["blocked"]:
                log.info("To'lov so'rovi: %s yuborildi, %s yetmadi, %s bloklagan", res["sent"], res["failed"], res["blocked"])
        except Exception:
            log.exception("To'lov so'rovi tsiklida xato")
        await asyncio.sleep(interval)


async def answer(uid: int, pid: int, n: int) -> str:
    """Javobni yozadi: ok | dup (allaqachon javob bergan) | test (so'ralmagan odam — yozilmaydi) | bad."""
    if not 1 <= n <= len(ANSWERS):
        return "bad"
    async with Session() as s:
        kinds = set((await s.execute(select(Event.kind).where(Event.user_id == uid, Event.kind.in_(("pay_ask", "pay_why")))
                                     .distinct())).scalars().all())
    if "pay_ask" not in kinds:
        return "test"  # admin o'ziga yuborgan sinov savoli
    if "pay_why" in kinds:
        return "dup"
    await track.event("pay_why", uid, payflow.ref_of(pid), n, {"a": ANSWERS[n - 1][0]})
    return "ok"


async def send_test(bot, uid: int) -> None:
    """Adminning o'ziga namuna savol (javobi statistikaga yozilmaydi)."""
    async with Session() as s:
        u = await s.get(User, uid)
    lang = (u.lang if u else "") or "uz"
    await bot.send_message(uid, question(lang), reply_markup=keyboard(0, lang))


async def stats(s, a: datetime | None, b: datetime, excl: set[int]) -> dict:
    """Davr ichida: nechta odamga yuborildi, nechtasi javob berdi va javoblar soni/foizi (odamlar bo'yicha)."""
    cond = [Event.kind.in_(("pay_ask", "pay_why")), Event.created_at < b]
    if a:
        cond.append(Event.created_at >= a)
    if excl:
        cond.append(Event.user_id.notin_(list(excl)))
    rows = (await s.execute(select(Event.kind, Event.num, func.count(func.distinct(Event.user_id)))
                            .where(*cond).group_by(Event.kind, Event.num))).all()
    sent = sum(n for k, num, n in rows if k == "pay_ask" and num == 1)
    failed = sum(n for k, num, n in rows if k == "pay_ask" and num != 1)
    ans = {num: n for k, num, n in rows if k == "pay_why"}
    answered = sum(ans.values())
    pct = lambda x, y: round(100 * x / y, 1) if y else 0.0  # noqa: E731
    return {"sent": sent, "failed": failed, "answered": answered, "answer_rate": pct(answered, sent),
            "answers": [{"key": code, "label": name, "n": ans.get(i, 0), "pct": pct(ans.get(i, 0), answered)}
                        for i, (code, name) in enumerate(ANSWERS, 1)],
            "delay_min": DELAY_MIN, "last_run": STATE["last_run"], "last_sent": STATE["last_sent"]}


async def answers_list(a: datetime | None, b: datetime, limit: int = 5000) -> list[dict]:
    """CSV uchun: har bir javob (kim, qachon, qaysi to'lov haqida)."""
    excl = await track.excluded_ids()
    cond = [Event.kind == "pay_why", Event.created_at < b]
    if a:
        cond.append(Event.created_at >= a)
    if excl:
        cond.append(Event.user_id.notin_(list(excl)))
    async with Session() as s:
        rows = (await s.execute(select(Event.user_id, Event.num, Event.ref, Event.created_at, User.first_name, User.username)
                                .outerjoin(User, User.tg_id == Event.user_id).where(*cond)
                                .order_by(Event.id.desc()).limit(limit))).all()
    names = dict(enumerate((x[1] for x in ANSWERS), 1))
    return [{"user_id": uid, "name": name or "", "username": username or "", "answer": names.get(num, str(num)),
             "payment": ref[4:] if (ref or "").startswith("pay:") else "", "at": at} for uid, num, ref, at, name, username in rows]
