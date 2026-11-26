"""Progrev va chegirma xabarlari natijasi (statistika TZ, 5-band): har bir xabardan keyin odam nima qildi.

Xabarlar jurnali — nudge_log: progrev (seq = site | song | new, app/nudges.py) va chegirma (offer — namunadan keyingi taklif,
bf — eski namunalarga tarqatma, rem — tugashidan oldingi eslatma; app/pricing.py). Xabar kaliti «seq.step»: song.2, offer.0, rem.1.
Har bir xabar uchun, ODAMLAR soni bilan (bir odamga bir xabar ikki marta ketsa ham bitta):
  Yuborildi (yetdi)  — status = sent;   Yetmadi — failed (sababi: botni bloklagan / boshqa Telegram xatosi)
  Tugmani bosdi      — shu xabardagi tugma orqali Mini App ochilgan (msg_click hodisasi, ref = n:<kalit>, xabardan keyin)
  Ilovaga qaytdi     — xabardan keyin 24 soat ichida ilovada bo'lgan: app (kuniga bir marta yoziladi), tugma bosilishi yoki
                       ilovaning o'zi yuboradigan hodisalar (qo'shiq bo'limi, namuna, «sotib olish», to'lov oynasi)
  Sotib oldi         — xabardan keyin 48 soat ichida pul tushgan (pay_success) yoki balansdan xizmat sotib olgan
  Blokladi           — xabardan keyin 24 soat ichida botni bloklagan (bot_block hodisasi, app/track.py)
  O'tkazib yuborildi — status = skipped, sababi bilan (nudge_log.reason)
Hammasi bazaning o'zida: GROUP BY xabar, natijalar EXISTS bilan (events (user_id, kind, created_at) indeksi bo'yicha) — qator
boshiga so'rov yo'q. Admin va sinov akkauntlari (track.excluded_ids) sanalmaydi. Vaqtlar bazada UTC, panelda Toshkent.
Tugma bosilishi, blok vaqti va o'tkazib yuborish sababi hisob boshlangan sanadan (since) beri yoziladi — panel shuni ko'rsatadi.
"""

from datetime import datetime, timedelta

from sqlalchemy import String, case, cast, exists, func, literal, or_, select

from . import nudges, store, track
from .db import BalanceTx, Event, NudgeLog, Session, User, engine, utcnow
from .funnel import src_cond

KEY = "msgstats"
DISCOUNT = ("offer", "bf", "rem")
# «Ilovaga qaytdi»: ilovada bo'lganini bildiradigan hodisalar (app kuniga bir marta yoziladi — shuning uchun boshqalari ham)
APP_KINDS = ("app", track.CLICK, "song_open", "sample_requested", "sample_played", "buy_click", "pay_sheet", "pay_open")
RETURN_H, BUY_H, BLOCK_H = 24, 48, 24
SKIP_REASONS = {
    "late": "36 soatdan ko'p kechikdi",
    "gap": "Xabarlar orasidagi tanaffus",
    "night": "Tungi vaqt",
    "bought": "Allaqachon sotib olgan",
    "made": "Shu narsani allaqachon yasagan",
    "blocked": "Botni bloklagan",
    "pack": "Qo'shiq paketi bor",
    "old_blocked": "Sababi yozilmagan (eski yozuv), hozir botni bloklab turibdi",
    "old": "Sababi yozilmagan (eski yozuv)",
}
SKIP_ABOUT = {
    "late": "Vaqti kelganda yuborilmadi: progrev o'chiq edi, bot ishlamadi yoki navbat to'lgan edi",
    "gap": "Bitta odamga xabarlar orasida «tanaffus» soatidan tez xabar ketmaydi; shu orada boshqa progrev xabari ham olgan bo'lishi mumkin",
    "night": "Tanaffus tugagan paytlar faqat tunga (yuborish soatlaridan tashqariga) to'g'ri keldi",
    "bought": "Xabar vaqti kelguncha sotib olib bo'lgan",
    "made": "«Yangi qo'shilganlar»: tugma ochadigan narsani allaqachon yasagan",
    "blocked": "Botni bloklagan — xabar muddati tugaguncha kutildi",
    "pack": "Paketida ishlatilmagan qo'shiq bor — chegirma kerak emas",
    "old_blocked": "Sabab yozila boshlashidan oldin. Avvalgi xatoda bloklagan odamlar navbatni egallab, boshqalarning xabari ham kechikib ketardi",
    "old": "Sabab yozila boshlashidan oldin (asosan navbat to'lib qolgani — tuzatildi)",
}
FAIL_REASONS = {"blocked": "Botni bloklagan", "error": "Telegram xatosi", "": "Sababi yozilmagan (eski yozuv)"}


# ---------------------------------------------------------------- hisob boshlangan sana

async def config() -> dict:
    return {"since": None, **(await store.get(KEY) or {})}


async def start() -> None:
    """Birinchi ishga tushishda: tugma, blok vaqti va sabablar shu paytdan beri yozilishini belgilaydi."""
    cfg = await config()
    if not cfg["since"]:
        cfg["since"] = utcnow().isoformat(timespec="seconds")
        await store.put(KEY, cfg)


# ---------------------------------------------------------------- xabarlar ro'yxati

def labels(ncfg: dict, rem_n: int = 3) -> list[dict]:
    """Paneldagi tartib: progrev ketma-ketliklari qadamlari, keyin chegirma xabarlari."""
    out = []
    for k in nudges.SEQS:
        for i, st in enumerate(ncfg["seqs"][k]["steps"]):
            out.append({"key": f"{k}.{i}", "group": "progrev", "seq": k, "step": i, "label": f"{nudges.SEQ_NAMES[k]} — {i + 1}-xabar",
                        "about": f"{st['after']} soatdan keyin" + (f" · tugma: {st['button']}" if st.get("button") else "")})
    out.append({"key": "offer.0", "group": "discount", "seq": "offer", "step": 0, "label": "Chegirma taklifi (namunadan keyin)", "about": ""})
    out.append({"key": "bf.0", "group": "discount", "seq": "bf", "step": 0, "label": "Chegirma: eski namunalarga tarqatma", "about": ""})
    for j in range(1, rem_n + 1):
        out.append({"key": f"rem.{j}", "group": "discount", "seq": "rem", "step": j, "label": f"Chegirma eslatmasi — {j}", "about": ""})
    return out


def plus_hours(col, n: int):
    """Vaqtga n soat qo'shish: PostgreSQL da interval, SQLite da datetime(…, '+n hours')."""
    if engine.dialect.name == "sqlite":
        return func.datetime(col, f"+{n} hours")
    return col + timedelta(hours=n)


def _after(kinds, hours: int | None):
    """Shu xabardan keyin (hours soat ichida) shu odamda hodisa bormi — korrelyatsiyalangan EXISTS."""
    conds = [Event.user_id == NudgeLog.user_id, Event.kind.in_(kinds) if isinstance(kinds, tuple) else Event.kind == kinds,
             Event.created_at >= NudgeLog.created_at]
    if hours:
        conds.append(Event.created_at <= plus_hours(NudgeLog.created_at, hours))
    return exists().where(*conds)


def _scope(a: datetime | None, b: datetime, excl, src: str) -> list:
    conds = [NudgeLog.created_at < b]
    if a is not None:
        conds.append(NudgeLog.created_at >= a)
    if excl:
        conds.append(NudgeLog.user_id.notin_(sorted(excl)))
    if src:
        conds.append(NudgeLog.user_id.in_(select(User.tg_id).where(*src_cond(src))))
    return conds


def _pct(a: int, b: int) -> float:
    return round(100 * a / b, 1) if b else 0.0


async def report(a: datetime | None, b: datetime, src: str = "", spend_kinds: tuple = ()) -> dict:
    """Har bir xabar: yuborildi, yetmadi, tugma, ilovaga qaytdi (24 s), sotib oldi (48 s), blokladi (24 s) va o'tkazib
    yuborish sabablari — odamlar soni. Davr — xabar yuborilgan (yoki o'tkazib yuborilgan) vaqt bo'yicha."""
    excl = await track.excluded_ids()
    ncfg = await nudges.config()
    scope = _scope(a, b, excl, src)
    key_ref = literal("n:") + NudgeLog.seq + literal(".") + cast(NudgeLog.step, String)
    clicked = exists().where(Event.user_id == NudgeLog.user_id, Event.kind == track.CLICK, Event.ref == key_ref,
                             Event.created_at >= NudgeLog.created_at)
    bought = or_(_after("pay_success", BUY_H),
                 exists().where(BalanceTx.user_id == NudgeLog.user_id, BalanceTx.kind.in_(spend_kinds or ("song",)),
                                BalanceTx.created_at >= NudgeLog.created_at, BalanceTx.created_at <= plus_hours(NudgeLog.created_at, BUY_H)))

    def people(cond):
        return func.count(func.distinct(case((cond, NudgeLog.user_id))))

    async with Session() as s:
        status_rows = (await s.execute(select(NudgeLog.seq, NudgeLog.step, NudgeLog.status, func.count(func.distinct(NudgeLog.user_id)))
                                       .where(*scope).group_by(NudgeLog.seq, NudgeLog.step, NudgeLog.status))).all()
        blk = func.coalesce(User.blocked, False)
        reason_rows = (await s.execute(
            select(NudgeLog.seq, NudgeLog.step, NudgeLog.status, NudgeLog.reason, blk, func.count(func.distinct(NudgeLog.user_id)))
            .outerjoin(User, User.tg_id == NudgeLog.user_id).where(*scope, NudgeLog.status != "sent")
            .group_by(NudgeLog.seq, NudgeLog.step, NudgeLog.status, NudgeLog.reason, blk))).all()
        out_rows = (await s.execute(
            select(NudgeLog.seq, NudgeLog.step, people(clicked), people(_after(APP_KINDS, RETURN_H)), people(bought),
                   people(_after(track.BLOCK, BLOCK_H)))
            .where(*scope, NudgeLog.status == "sent").group_by(NudgeLog.seq, NudgeLog.step))).all()
    from . import pricing
    rem_n = max([len((await pricing.config())["promo"]["reminders"])] + [st for seq, st, *_ in status_rows if seq == "rem"])
    msgs = labels(ncfg, rem_n)
    by_key = {m["key"]: {**m, "sent": 0, "failed": 0, "skipped": 0, "fails": {}, "skips": {}, "clicked": 0, "returned": 0,
                         "bought": 0, "blocked": 0} for m in msgs}

    def row(seq: str, step: int) -> dict:
        k = f"{seq}.{step}"
        if k not in by_key:  # sozlamadan o'chirilgan qadam — jurnalda bor
            name = nudges.SEQ_NAMES.get(seq, seq)
            by_key[k] = {"key": k, "group": "discount" if seq in DISCOUNT else "progrev", "seq": seq, "step": step,
                         "label": f"{name} — {step + 1}-xabar (sozlamada yo'q)", "about": "", "sent": 0, "failed": 0, "skipped": 0,
                         "fails": {}, "skips": {}, "clicked": 0, "returned": 0, "bought": 0, "blocked": 0}
        return by_key[k]

    for seq, step, status, n in status_rows:
        if status in ("sent", "failed", "skipped"):
            row(seq, step)[status] = n
    for seq, step, status, reason, is_blocked, n in reason_rows:
        r = row(seq, step)
        if status == "failed":
            r["fails"][reason or ""] = r["fails"].get(reason or "", 0) + n
        elif status == "skipped":
            key = reason or ("old_blocked" if is_blocked else "old")
            r["skips"][key] = r["skips"].get(key, 0) + n
    for seq, step, c, ret, buy, blkd in out_rows:
        r = row(seq, step)
        r.update(clicked=c, returned=ret, bought=buy, blocked=blkd)
    rows = list(by_key.values())
    for r in rows:
        r["pct"] = {k: _pct(r[k], r["sent"]) for k in ("clicked", "returned", "bought", "blocked")}
        r["skips"] = [{"key": k, "label": SKIP_REASONS.get(k, k), "n": n} for k, n in sorted(r["skips"].items(), key=lambda x: -x[1])]
        r["fails"] = [{"key": k, "label": FAIL_REASONS.get(k, k), "n": n} for k, n in sorted(r["fails"].items(), key=lambda x: -x[1])]
    return {"rows": rows, "since": (await config())["since"], "excluded": len(excl),
            "skip_reasons": [{"key": k, "label": v, "about": SKIP_ABOUT[k]} for k, v in SKIP_REASONS.items()],
            "windows": {"return_h": RETURN_H, "buy_h": BUY_H, "block_h": BLOCK_H}}
