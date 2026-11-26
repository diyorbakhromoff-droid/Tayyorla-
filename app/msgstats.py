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

from datetime import datetime, timedelta, timezone

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


# ---------------------------------------------------------------- bloklar hisoboti (statistika TZ, 5-band)

def _key_label(key: str | None, ncfg: dict) -> str:
    if not key:
        return "Progrev yoki chegirma xabari olmagan"
    for m in labels(ncfg, 9):
        if m["key"] == key:
            return m["label"]
    seq, _, step = key.partition(".")
    return f"{nudges.SEQ_NAMES.get(seq, seq)} — {int(step) + 1 if step.isdigit() else step}-xabar"


async def blocks(a: datetime | None, b: datetime, src: str = "") -> dict:
    """Bloklar: kunlar bo'yicha (blok vaqti yozilganlar), manba bo'yicha blok foizi (shu davrda kelganlar, hozirgi holat),
    blokdan oldin oxirgi olingan xabar va Start bosgandan blokgacha vaqt. users.blocked da vaqt yo'q — vaqtga bog'liq
    ko'rsatkichlar hisob boshlangan sanadan (since) beri. «Oxirgi xabar» butun davr uchun eski bloklarni ham qamraydi:
    bloklagan odamga shundan keyin hech narsa yetmagan, demak jurnaldagi oxirgi yetgan xabar — blokdan oldingi oxirgisi."""
    from .adstats import source_key
    excl = sorted(await track.excluded_ids())
    ncfg = await nudges.config()
    ucond = src_cond(src) + ([User.tg_id.notin_(excl)] if excl else [])
    ev_when = [Event.kind == track.BLOCK, Event.created_at < b] + ([Event.created_at >= a] if a is not None else [])
    key_expr = NudgeLog.seq + literal(".") + cast(NudgeLog.step, String)
    last_key = (select(key_expr).where(NudgeLog.user_id == User.tg_id, NudgeLog.status == "sent", NudgeLog.created_at <= Event.created_at)
                .order_by(NudgeLog.created_at.desc(), NudgeLog.id.desc()).limit(1).scalar_subquery())
    last_key_now = (select(key_expr).where(NudgeLog.user_id == User.tg_id, NudgeLog.status == "sent")
                    .order_by(NudgeLog.created_at.desc(), NudgeLog.id.desc()).limit(1).scalar_subquery())
    async with Session() as s:
        # davrdagi blok hodisalari: odam, vaqt, kelgan vaqti, blokdan oldingi oxirgi xabar — bitta so'rov
        evs = (await s.execute(select(Event.user_id, Event.created_at, User.created_at, last_key)
                               .join(User, User.tg_id == Event.user_id).where(*ev_when, *ucond))).all()
        now_blocked = await s.scalar(select(func.count()).select_from(User).where(User.blocked.is_(True), *ucond)) or 0
        users_all = await s.scalar(select(func.count()).select_from(User).where(*ucond)) or 0
        timed = exists().where(Event.user_id == User.tg_id, Event.kind == track.BLOCK)
        unknown = await s.scalar(select(func.count()).select_from(User).where(User.blocked.is_(True), ~timed, *ucond)) or 0
        # manba bo'yicha: shu davrda kelgan odamlar va ulardan hozir bloklab turganlar
        coh = [User.created_at < b] + ([User.created_at >= a] if a is not None else [])
        k = source_key()
        by_src = (await s.execute(select(k, func.count(), func.sum(case((User.blocked.is_(True), 1), else_=0)))
                                  .where(*coh, *ucond).group_by(k))).all()
        last_all = None
        if a is None:  # butun davr: hozir bloklab turgan hamma odamning oxirgi olgan xabari (eski bloklar ham)
            sub = select(User.tg_id, last_key_now.label("k")).where(User.blocked.is_(True), *ucond).subquery()
            last_all = (await s.execute(select(sub.c.k, func.count()).group_by(sub.c.k))).all()
    days: dict[str, set] = {}
    first: dict[int, tuple] = {}
    for uid, at, created, key in evs:
        days.setdefault(at.replace(tzinfo=timezone.utc).astimezone(nudges.TZ).date().isoformat(), set()).add(uid)
        if uid not in first or at < first[uid][0]:
            first[uid] = (at, created, key)
    spans = {"h1": 0, "d1": 0, "later": 0}
    for at, created, _ in first.values():
        if created is None:
            continue
        gone = at - created
        spans["h1" if gone <= timedelta(hours=1) else "d1" if gone <= timedelta(days=1) else "later"] += 1
    if last_all is not None:
        counts, base = {key: n for key, n in last_all}, now_blocked
    else:
        counts, base = {}, len(first)
        for _, _, key in first.values():
            counts[key] = counts.get(key, 0) + 1
    last = [{"key": key or "", "label": _key_label(key, ncfg), "n": n, "pct": _pct(n, base)}
            for key, n in sorted(counts.items(), key=lambda x: -x[1])]
    timed_n = sum(spans.values())
    return {
        "since": (await config())["since"], "blocked_now": now_blocked, "users": users_all, "blocked_pct": _pct(now_blocked, users_all),
        "unknown": unknown, "in_period": len(first),
        "by_day": [{"day": d, "n": len(v)} for d, v in sorted(days.items())],
        "by_source": [{"key": key, "users": int(u or 0), "blocked": int(bl or 0), "pct": _pct(int(bl or 0), int(u or 0))}
                      for key, u, bl in sorted(by_src, key=lambda x: -(x[1] or 0))],
        "last_msg": last, "last_base": base, "last_scope": "now" if last_all is not None else "period",
        "start_to_block": {**spans, "n": timed_n, **{f"{x}_pct": _pct(v, timed_n) for x, v in spans.items()}},
    }


# ---------------------------------------------------------------- mijoz kartasi: hodisalar tarixi

EVENT_LABELS = {
    "start": "Botda Start bosdi", "app": "Ilovani ochdi (kuniga bir marta yoziladi)", "click": "Reklama havolasini bosdi",
    "song_open": "Qo'shiq bo'limiga kirdi", "song_form_done": "Qo'shiq so'rovnomasini to'ldirdi", "lyrics_ready": "She'r tayyor bo'ldi",
    "lyrics_failed": "She'r yozilmadi", "sample_requested": "«Namunani tinglash»ni bosdi", "sample_ready": "Namuna tayyor bo'ldi",
    "sample_failed": "Namuna xato bilan tugadi", "sample_limit": "Limit sabab namuna berilmadi", "sample_played": "Namunani eshitdi",
    "sample_away": "Namuna tayyor bo'lganda ilovada emas edi", "sample_retry": "Namuna qayta navbatga qo'yildi",
    "buy_click": "«Sotib olish»ni bosdi", "song_delivered": "To'liq qo'shiq berildi", "song_shared": "Qo'shiqni yuklab oldi yoki ulashdi",
    "song_failed": "To'liq qo'shiq xato bilan tugadi", "song_retry": "To'liq qo'shiq qayta so'raldi", "song_pv": "Bepul namuna hisoblandi",
    "pay_sheet": "Summa tanlash oynasini ko'rdi", "pay_open": "To'lov oynasini ochdi", "pay_click": "Click sahifasiga o'tdi",
    "pay_prepare": "Click'da to'lovni boshladi", "pay_return": "Click sahifasidan qaytdi", "pay_cancel": "Click to'lovni bekor qildi",
    "pay_card": "Karta raqami ko'rsatildi", "pay_badrcpt": "Chek qabul qilinmadi", "pay_receipt": "Chek yubordi",
    "pay_success": "Pul tushdi", "pay_reject": "Chek rad etildi", "pay_ask": "«Nega to'lamadingiz» savoli yuborildi",
    "pay_why": "«Nega to'lamadingiz»ga javob berdi", "promo_buy": "Chegirmada sotib oldi", track.CLICK: "Xabardagi tugmani bosdi",
    track.BLOCK: "Botni blokladi", track.UNBLOCK: "Blokdan chiqardi",
}
STATUS_LABELS = {"sent": "yetdi", "failed": "yetmadi", "skipped": "o'tkazib yuborildi"}
VIA = {"update": "Telegram xabar berdi", "nudge": "progrev xabari yetmadi", "promo": "chegirma xabari yetmadi", "survey": "so'rov yetmadi",
       "song": "qo'shiq xabari yetmadi", "broadcast": "tarqatma yetmadi", "touch": "yana botga yozdi yoki ilovani ochdi"}


def _money(n) -> str:
    return f"{int(n):,}".replace(",", " ") + " so'm"


def event_detail(kind: str, ref: str, num, meta: dict | None, ncfg: dict) -> str:
    """Hodisaning qisqa izohi: summa, sabab, qaysi xabar..."""
    from . import payflow, paysurvey, songflow
    meta = meta if isinstance(meta, dict) else {}
    parts = []
    if ref.startswith("song:"):
        parts.append(f"qo'shiq #{ref[5:]}")
    elif ref.startswith("pay:"):
        parts.append(f"to'lov #{ref[4:]}")
    if kind.startswith("pay_") and num and kind not in ("pay_ask", "pay_why"):
        parts.append(_money(num))
    if kind == "pay_open":
        parts += [payflow.PURPOSES.get(meta.get("p"), ""), payflow.METHODS.get(meta.get("m"), "")]
    if kind == "buy_click":
        parts += [_money(num) if num else "", {"single": "1 ta", "pack": "paket", "credit": "paketdan"}.get(meta.get("kind"), ""),
                  "chegirmada" if meta.get("disc") else ""]
    if kind in ("sample_ready", "song_delivered") and num:
        parts.append(f"kutish {num} s")
    if kind == "sample_played" and num:
        parts.append(f"{num} s eshitdi" + (", oxirigacha" if meta.get("end") else ""))
    if kind in ("sample_failed", "song_failed") and meta.get("r"):
        parts.append(songflow.REASONS.get(meta["r"], str(meta["r"])))
    if kind == "sample_limit" and meta.get("l"):
        parts.append(songflow.LIMITS.get(meta["l"], str(meta["l"])))
    if kind == "lyrics_failed" and meta.get("r"):
        parts.append(songflow.LYRICS_WHY.get(meta["r"], str(meta["r"])))
    if kind == "song_form_done":
        parts += [str(meta.get("rel") or ""), str(meta.get("occ") or "")]
    if kind == "pay_why" and num and 1 <= num <= len(paysurvey.ANSWERS):
        parts.append(f"«{paysurvey.ANSWERS[num - 1][1]}»")
    if kind == track.CLICK and ref.startswith("n:"):
        parts = [_key_label(ref[2:], ncfg)]
    if kind in (track.BLOCK, track.UNBLOCK) and meta.get("via"):
        parts.append(VIA.get(meta["via"], str(meta["via"])))
    if kind == "song_shared" and meta.get("how"):
        parts.append({"download": "yuklab oldi", "share": "ulashdi"}.get(meta["how"], str(meta["how"])))
    return " · ".join(p for p in parts if p)


async def history(uid: int, limit: int = 300) -> list[dict]:
    """Odamning hodisalari va olgan progrev/chegirma xabarlari, yangisi tepada (vaqt UTC — panel Toshkentda ko'rsatadi)."""
    ncfg = await nudges.config()
    async with Session() as s:
        evs = (await s.execute(select(Event.kind, Event.ref, Event.num, Event.meta, Event.src, Event.created_at)
                               .where(Event.user_id == uid).order_by(Event.created_at.desc(), Event.id.desc()).limit(limit))).all()
        msgs = (await s.execute(select(NudgeLog.seq, NudgeLog.step, NudgeLog.status, NudgeLog.reason, NudgeLog.ref, NudgeLog.created_at)
                                .where(NudgeLog.user_id == uid).order_by(NudgeLog.created_at.desc()).limit(limit))).all()
    out = []
    for kind, ref, num, meta, src, at in evs:
        if kind in ("promo_offer", "promo_bf", "promo_rem") and msgs:  # bu xabarlar jurnaldan (pastda) to'liqroq chiqadi
            continue
        detail = f"parametr: {src}" if kind == "start" and src else event_detail(kind, ref or "", num, meta, ncfg)
        out.append({"at": at.isoformat(), "kind": kind, "label": EVENT_LABELS.get(kind, {"promo_offer": "Chegirma taklif qilindi",
                    "promo_bf": "Eski namunaga chegirma yuborildi", "promo_rem": "Chegirma eslatmasi yuborildi"}.get(kind, kind)), "detail": detail})
    for seq, step, status, reason, ref, at in msgs:
        why = SKIP_REASONS.get(reason or "old", "") if status == "skipped" else FAIL_REASONS.get(reason, "") if status == "failed" else ""
        out.append({"at": at.isoformat(), "kind": f"msg_{status}",
                    "label": f"{'Chegirma' if seq in DISCOUNT else 'Progrev'}: {_key_label(f'{seq}.{step}', ncfg)} — {STATUS_LABELS.get(status, status)}",
                    "detail": " · ".join(x for x in (why, f"qo'shiq #{ref[5:]}" if ref.startswith("song:") else "") if x)})
    out.sort(key=lambda x: x["at"], reverse=True)
    return out[:limit]


# ---------------------------------------------------------------- nazorat guruhi bilan taqqoslash (statistika TZ, 5-band)

async def control_compare(spend_kinds: tuple = ()) -> dict:
    """Guruh yoqilgandan (o'chirilgan bo'lsa — o'chirilgunga qadar) keyin kelgan yangi odamlar ikki guruhda: progrev va chegirma
    oladiganlar va nazorat guruhi (hech narsa olmaydi). Sotib oldi — tasdiqlangan to'lov yoki balansdan xarid (hozirgacha),
    blokladi — hozir botni bloklab turibdi. Bitta so'rov, GROUP BY guruh."""
    from . import control
    from .db import Payment
    cfg = await control.config()
    since = cfg["since_dt"]
    out = {"on": cfg["on"], "pct": cfg["pct"], "since": cfg["since"], "until": cfg["until"], "groups": []}
    if not since:
        return out
    excl = sorted(await track.excluded_ids())
    conds = [User.created_at >= since] + ([User.created_at < cfg["until_dt"]] if cfg["until_dt"] else [])
    if excl:
        conds.append(User.tg_id.notin_(excl))
    uid = User.tg_id
    bought = or_(exists().where(Payment.user_id == uid, Payment.status == "approved"),
                 exists().where(BalanceTx.user_id == uid, BalanceTx.kind.in_(spend_kinds or ("song",))))
    got = exists().where(NudgeLog.user_id == uid, NudgeLog.status == "sent")
    paid = select(func.coalesce(func.sum(Payment.amount), 0)).where(Payment.user_id == uid, Payment.status == "approved").scalar_subquery()
    grp = control.bucket_sql(uid) < cfg["pct"]

    def n(cond):
        return func.sum(case((cond, 1), else_=0))

    async with Session() as s:
        sub = select(grp.label("ctl"), bought.label("bought"), User.blocked.label("blocked"), got.label("got"), paid.label("paid")) \
            .where(*conds).subquery()
        rows = (await s.execute(select(sub.c.ctl, func.count(), n(sub.c.bought), n(sub.c.blocked), n(sub.c.got), func.sum(sub.c.paid))
                                .group_by(sub.c.ctl))).all()
    by = {bool(c): (int(t), int(b or 0), int(bl or 0), int(g or 0), int(p or 0)) for c, t, b, bl, g, p in rows}
    for key, label in ((False, "Progrev va chegirma oladiganlar"), (True, "Nazorat guruhi (hech narsa olmaydi)")):
        t, b, bl, g, p = by.get(key, (0, 0, 0, 0, 0))
        out["groups"].append({"key": "control" if key else "main", "label": label, "users": t, "bought": b, "bought_pct": _pct(b, t),
                              "blocked": bl, "blocked_pct": _pct(bl, t), "got": g, "revenue": p, "arpu": round(p / t) if t else 0})
    return out


# ---------------------------------------------------------------- chegirma voronkasi va A/B (statistika TZ, 5-band)

DISCOUNT_STEPS = [("offered", "Taklif yuborildi"), ("opened", "Ochdi (tugma yoki ilova)"), ("buy_click", "«Sotib olish»ni bosdi"),
                  ("pay_open", "To'lov oynasini ochdi"), ("paid", "To'ladi yoki sotib oldi")]
ARMS = {"": "Bitta narx (A/B o'chiq)", "a": "A — asosiy chegirma narxi", "b": "B — ikkinchi narx"}
OFFER_H = 48  # taklifdan keyin shuncha soat ichidagi harakatlar hisoblanadi


async def discount_funnel(a: datetime | None, b: datetime) -> dict:
    """Chegirma voronkasi har A/B guruhi bo'yicha, ODAMLAR soni: taklif (offer yoki bf) yuborildi → 48 soat ichida ochdi
    (chegirma tugmasi yoki ilovada bo'ldi) → «sotib olish» → to'lov oynasi → to'ladi (pul tushdi yoki chegirmada sotib oldi).
    Bitta so'rov: GROUP BY guruh, qadamlar EXISTS bilan."""
    from .db import Song
    excl = sorted(await track.excluded_ids())
    scope = [NudgeLog.seq.in_(("offer", "bf")), NudgeLog.status == "sent", NudgeLog.created_at < b]
    if a is not None:
        scope.append(NudgeLog.created_at >= a)
    if excl:
        scope.append(NudgeLog.user_id.notin_(excl))
    opened = or_(exists().where(Event.user_id == NudgeLog.user_id, Event.kind == track.CLICK,
                                or_(Event.ref.in_(("n:offer.0", "n:bf.0")), Event.ref.startswith("n:rem.", autoescape=True)),
                                Event.created_at >= NudgeLog.created_at, Event.created_at <= plus_hours(NudgeLog.created_at, OFFER_H)),
                 _after(APP_KINDS, OFFER_H))
    raw = [("opened", opened), ("buy_click", _after("buy_click", OFFER_H)), ("pay_open", _after("pay_open", OFFER_H)),
           ("paid", or_(_after("pay_success", OFFER_H), _after("promo_buy", OFFER_H)))]
    # keyingi qadamga yetgan odam oldingilaridan ham o'tgan hisoblanadi (balansidagi puldan to'lagan — to'lov oynasisiz):
    # sonlar faqat kamayadi, «Voronka» bo'limidagi kabi
    steps = {k: or_(*(c for _, c in raw[i:])) for i, (k, _) in enumerate(raw)}

    def people(cond):
        return func.count(func.distinct(case((cond, NudgeLog.user_id))))

    song_ref = literal("song:") + cast(Song.id, String)
    async with Session() as s:
        rows = (await s.execute(select(NudgeLog.arm, func.count(func.distinct(NudgeLog.user_id)), *(people(c) for c in steps.values()),
                                       people(_after("promo_buy", OFFER_H)))
                                .where(*scope).group_by(NudgeLog.arm))).all()
        prices = dict((await s.execute(select(NudgeLog.arm, func.max(Song.promo_price)).join(Song, NudgeLog.ref == song_ref)
                                       .where(*scope).group_by(NudgeLog.arm))).all())
    arms = []
    for arm, offered, *vals in sorted(rows, key=lambda r: r[0] or ""):
        counts = dict(zip(["offered", *steps], [offered, *vals[:len(steps)]]))
        prev = offered
        out_steps = []
        for key, label in DISCOUNT_STEPS:
            n = int(counts[key] or 0)
            out_steps.append({"key": key, "label": label, "n": n, "pct": _pct(n, prev) if key != "offered" else 100.0,
                              "of_first": _pct(n, offered)})
            prev = n
        arms.append({"arm": arm or "", "label": ARMS.get(arm or "", arm), "price": int(prices.get(arm) or 0), "offered": int(offered),
                     "steps": out_steps, "promo_buy": int(vals[-1] or 0), "conv": _pct(int(counts["paid"] or 0), int(offered))})
    return {"arms": arms, "window_h": OFFER_H, "since": (await config())["since"]}
