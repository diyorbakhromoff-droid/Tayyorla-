"""To'lov bosqichi statistikasi (statistika TZ, 3-band): urinish qadamlari va «To'lovlar» bo'limi xulosasi.

Urinish — payments jadvalidagi bitta yozuv: mijoz summani tanlab, to'lov oynasini ochgan.
Har bir urinishning qadamlari events jadvaliga vaqti bilan yoziladi (ref = pay:<id>, num = summa):
  pay_sheet    — ilovada summa tanlash oynasi ko'rsatildi (hali to'lov yozuvi yo'q, ref bo'sh)
  pay_open     — to'lov oynasi ochildi: summa tanlandi, to'lov yozuvi yaratildi
  pay_click    — Click sahifasiga o'tdi (kuzatuv havolasi /pay/c/… orqali)
  pay_prepare  — Click'da to'lovni boshladi (Click «prepare» so'rovi keldi)
  pay_return   — Click sahifasidan qaytdi (/pay/r/…)
  pay_cancel   — Click to'lovni bekor qildi (pul yechilmadi)
  pay_card     — karta raqami ko'rsatildi
  pay_badrcpt  — chek yubordi, qabul qilinmadi (chek emas, takror yoki juda katta fayl)
  pay_receipt  — chek yuborildi va tekshiruvga olindi
  pay_success  — pul tushdi (Click yoki chek tasdiqlandi)
  pay_reject   — chek rad etildi yoki avtomatik tasdiq bekor qilindi

«Qaysi qadamda to'xtadi» shu hodisalar va to'lov holatidan chiqariladi (step_of) — eski to'lovlar uchun ham ishlaydi:
usul provider dan, chek va natija status dan tiklanadi. Tiklab bo'lmaydigani («Click sahifasiga o'tdi», «qaytdi»,
qadamlar vaqti) faqat hisob boshlangan sanadan (since) beri bor — panel shu sanani ko'rsatadi.
Sanash odamlar bo'yicha; admin va sinov akkauntlari (track.excluded_ids) statistikaga kirmaydi.
"""

import logging
from collections import Counter, defaultdict
from datetime import datetime, timezone

from sqlalchemy import String, cast, delete, func, insert, literal, select

from . import store, track
from .config import settings
from .db import BalanceTx, Event, Payment, Session, User, utcnow
from .reminders import TZ

log = logging.getLogger(__name__)

KEY = "paystats"
DEFAULTS = {
    "survey_on": True,    # «Nega to'lamadingiz» so'rovi (app/paysurvey.py)
    "click_track": True,  # Click havolasi kuzatuv orqali ochiladi; o'chirilsa mijoz to'g'ridan-to'g'ri Click'ka o'tadi
    "since": None,        # qadamlar qachondan beri yoziladi (birinchi ishga tushgan vaqt, UTC)
    "survey_from": None,  # so'rov oxirgi marta yoqilgan vaqt: o'chiq turgan paytdagi urinishlar haqida so'ralmaydi
}

PURPOSES = {"song": "Qo'shiq", "pack": "Qo'shiq paketi", "site": "Sayt", "video": "Video", "balance": "Balans"}
METHODS = {"click": "Click", "card": "Karta", "none": "Usul tanlanmagan"}
# qadam: (jadvaldagi yozuv, usul ichidagi tartibi — kattasi uzoqroq borgan)
STEPS = {
    "open": ("Oynani ochdi, usul tanlamadi", 0),
    "click": ("Click sahifasiga o'tdi, to'lamadi", 1),
    "return": ("Click sahifasidan to'lamay qaytdi", 2),
    "prepare": ("Click'da to'lovni boshladi, yakunlamadi", 3),
    "cancel": ("Click to'lovni bekor qildi", 4),
    "card": ("Karta raqamini ko'rdi, chek yubormadi", 1),
    "badrcpt": ("Chek yubordi, qabul qilinmadi", 2),
    "receipt": ("Chek yubordi, tekshiruvda", 3),
    "reject": ("Chek rad etildi", 4),
    "paid": ("To'ladi", 9),
}
METHOD_STEPS = {"click": ("click", "return", "prepare", "cancel", "paid"), "card": ("card", "badrcpt", "receipt", "reject", "paid")}
EVENT_NAMES = {
    "pay_open": "oyna ochildi", "pay_click": "Click sahifasiga o'tdi", "pay_prepare": "Click'da to'lovni boshladi",
    "pay_return": "qaytdi", "pay_cancel": "Click bekor qildi", "pay_card": "karta raqami ko'rsatildi",
    "pay_badrcpt": "chek qabul qilinmadi", "pay_receipt": "chek yuborildi", "pay_success": "pul tushdi",
    "pay_reject": "rad etildi",
}
STEP_KINDS = tuple(EVENT_NAMES)
BUCKETS = [(10_000, "10 000 so'mgacha"), (30_000, "10 001 – 30 000"), (50_000, "30 001 – 50 000"),
           (70_000, "50 001 – 70 000"), (100_000, "70 001 – 100 000"), (None, "100 000 so'mdan ko'p")]


# ---------------------------------------------------------------- sozlama va boshlanish sanasi

async def config() -> dict:
    v = await store.get(KEY) or {}
    return {k: v.get(k, d) for k, d in DEFAULTS.items()}


async def save(data: dict) -> dict:
    cfg = await config()
    was_on = cfg["survey_on"]
    for k in ("survey_on", "click_track"):
        if data.get(k) is not None:
            cfg[k] = bool(data[k])
    if cfg["survey_on"] and not was_on:
        cfg["survey_from"] = utcnow().isoformat(timespec="seconds")
    await store.put(KEY, cfg)
    return cfg


def _dt(v) -> datetime | None:
    try:
        return datetime.fromisoformat(v or "")
    except (TypeError, ValueError):
        return None


async def since() -> datetime | None:
    """Qadamlar yozila boshlagan vaqt (UTC, zonasiz) yoki None — hali boshlanmagan."""
    return _dt((await config())["since"])


async def survey_since() -> datetime | None:
    """So'rov qaysi vaqtdan keyingi urinishlar haqida yuboriladi: hisob boshlangan yoki so'rov qayta yoqilgan vaqt."""
    cfg = await config()
    marks = [x for x in (_dt(cfg["since"]), _dt(cfg["survey_from"])) if x]
    return max(marks) if _dt(cfg["since"]) else None


async def start() -> None:
    """Birinchi ishga tushishda: eski to'lovlardan pay_open / pay_success hodisalarini tiklaydi va sanani belgilaydi."""
    cfg = await config()
    if cfg["since"]:
        return
    n = await backfill()
    cfg["since"] = utcnow().isoformat(timespec="seconds")
    await store.put(KEY, cfg)
    log.info("To'lov statistikasi boshlandi: %s ta eski to'lov hodisasi tiklandi", n)


async def backfill() -> int:
    """Eski to'lovlar uchun pay_open (yaratilgan vaqt) va pay_success (tasdiqlangan vaqt) hodisalari.
    Qayta chaqirilsa takror yozmaydi: faqat pay_open hodisasi yo'q to'lovlar olinadi."""
    async with Session() as s:
        have = set((await s.execute(select(Event.ref).where(Event.kind == "pay_open"))).scalars().all())
        rows = (await s.execute(
            select(Payment.id, Payment.user_id, Payment.amount, Payment.status, Payment.provider, Payment.purpose,
                   Payment.site_id, Payment.song_id, Payment.pack, Payment.job_id, Payment.admin_id,
                   Payment.created_at, Payment.decided_at, User.ref)
            .outerjoin(User, User.tg_id == Payment.user_id).order_by(Payment.id))).all()
        new = []
        for r in rows:
            if ref_of(r.id) in have:
                continue
            purpose = r.purpose or guess_purpose(r.site_id, r.song_id, r.pack, r.job_id)
            base = {"user_id": r.user_id, "src": (r[-1] or "")[:32], "ref": ref_of(r.id), "num": r.amount}
            meta = {"p": purpose, "bf": 1}
            if r.provider in ("click", "card"):
                meta["m"] = r.provider
            new.append({**base, "kind": "pay_open", "meta": meta, "created_at": r.created_at or utcnow()})
            if r.status == "approved" and r.decided_at:
                by = "click" if r.provider == "click" else ("auto" if r.admin_id == 0 else "admin")
                new.append({**base, "kind": "pay_success", "created_at": r.decided_at,
                            "meta": {"p": purpose, "m": "click" if r.provider == "click" else "card", "by": by, "bf": 1}})
        for i in range(0, len(new), 500):
            await s.execute(insert(Event), new[i:i + 500])
        await s.commit()
    return len(new)


# ---------------------------------------------------------------- qadamlarni yozish

def ref_of(pid: int) -> str:
    return f"pay:{pid}"


def guess_purpose(site_id=None, song_id=None, pack=0, job_id=None, hint: str = "") -> str:
    """To'lov nima uchun: mahsulot ustunlaridan; bo'lmasa ilova aytgan maqsad (video, sayt), aks holda balans."""
    if pack:
        return "pack"
    if song_id:
        return "song"
    if site_id:
        return "site"
    if job_id:
        return "video"
    return hint if hint in ("site", "video") else "balance"


def purpose_of(p) -> str:
    return p.purpose or guess_purpose(p.site_id, p.song_id, p.pack, p.job_id)


async def step(kind: str, pay: Payment, /, **meta) -> None:
    """Urinish qadamini yozadi; meta — qisqa qo'shimcha ma'lumot (p — mahsulot, m — usul...)."""
    await track.event(kind, pay.user_id, ref_of(pay.id), pay.amount, meta or None)


async def opened(p: Payment, via: str = "app") -> None:
    """To'lov oynasi ochildi. Usul faqat bittasi yoqilgan bo'lsa ma'lum; ikkalasi bo'lsa keyingi qadamdan bilinadi."""
    meta = {"p": purpose_of(p), "via": via}
    try:
        from . import receipt
        card = receipt.enabled(await receipt.config())
        if bool(settings.click_on) != card:
            meta["m"] = "click" if settings.click_on else "card"
    except Exception:
        log.warning("To'lov usullarini aniqlab bo'lmadi")
    await step("pay_open", p, **meta)


async def paid(p: Payment) -> None:
    by = "click" if p.provider == "click" else ("auto" if p.admin_id == 0 else "admin")
    await step("pay_success", p, p=purpose_of(p), m="click" if p.provider == "click" else "card", by=by)


async def reverted(p: Payment) -> None:
    """Avtomatik tasdiq bekor qilindi: pul aslida tushmagan, shuning uchun pay_success hodisasi o'chiriladi."""
    try:
        async with Session() as s:
            await s.execute(delete(Event).where(Event.kind == "pay_success", Event.ref == ref_of(p.id)))
            await s.commit()
    except Exception:
        log.exception("pay_success hodisasini o'chirib bo'lmadi: #%s", p.id)
    await step("pay_reject", p, rev=1)


# ---------------------------------------------------------------- qaysi qadamda to'xtadi

def method_of(provider: str, status: str, has_receipt: bool, ev: dict) -> str:
    if provider in ("click", "card"):
        return provider
    if has_receipt or status in ("pending", "approved", "rejected"):
        return "card"  # eski oqim: chek skrinshoti, admin tasdig'i
    if "pay_click" in ev or "pay_return" in ev:
        return "click"
    return "none"


def step_of(provider: str, status: str, has_receipt: bool, ev: dict) -> tuple[str, str]:
    """(usul, eng uzoq yetgan qadam). ev — shu urinish hodisalari: {hodisa nomi: birinchi vaqti}."""
    method = method_of(provider, status, has_receipt, ev)
    if status == "approved":
        return method, "paid"
    if method == "click":
        if status == "cancelled" or "pay_cancel" in ev:
            return method, "cancel"
        if provider == "click" or "pay_prepare" in ev:
            return method, "prepare"
        return method, "return" if "pay_return" in ev else "click"
    if method == "card":
        if status == "rejected":
            return method, "reject"
        if status == "pending":
            return method, "receipt"
        return method, "badrcpt" if "pay_badrcpt" in ev else "card"
    return method, "open"


async def load_steps(s, ids=None, cond=None) -> dict[int, dict[str, datetime]]:
    """To'lovlar bo'yicha hodisalar: {to'lov id: {hodisa: birinchi vaqti}}. Bitta (yoki bo'lib-bo'lib) so'rov.
    ids — aniq to'lovlar; cond — payments ustidagi shart (davr); ikkalasi ham yo'q — hammasi."""
    q = select(Event.ref, Event.kind, func.min(Event.created_at)).where(Event.kind.in_(STEP_KINDS)).group_by(Event.ref, Event.kind)
    rows = []
    if ids is not None:
        ids = list(ids)
        for i in range(0, len(ids), 500):
            rows += (await s.execute(q.where(Event.ref.in_([ref_of(x) for x in ids[i:i + 500]])))).all()
    elif cond is not None:
        rows = (await s.execute(q.where(Event.ref.in_(select(literal("pay:") + cast(Payment.id, String)).where(*cond))))).all()
    else:
        rows = (await s.execute(q.where(Event.ref.like("pay:%")))).all()
    out: dict[int, dict[str, datetime]] = defaultdict(dict)
    for ref, kind, at in rows:
        if ref[4:].isdigit():
            out[int(ref[4:])][kind] = at
    return out


def describe(p, ev: dict) -> dict:
    """Jadval qatori uchun: nima uchun, usul, qaysi qadamda to'xtadi va qadamlar vaqti bilan."""
    purpose = purpose_of(p)
    method, st = step_of(p.provider or "", p.status, bool(p.receipt), ev)
    detail = (f"{p.pack} ta" if p.pack else f"#{p.song_id}" if p.song_id else f"#{p.site_id}" if p.site_id
              else f"#{p.job_id}" if p.job_id else "")
    opened_at = min([t for t in (ev.get("pay_open"), p.created_at) if t], default=None)
    line = dict(ev)
    line.setdefault("pay_open", p.created_at)
    if p.status == "approved" and p.decided_at:
        line.setdefault("pay_success", p.decided_at)
    took = int((p.decided_at - opened_at).total_seconds()) if p.status == "approved" and p.decided_at and opened_at else None
    return {
        "purpose": purpose, "purpose_label": PURPOSES.get(purpose, purpose), "purpose_detail": detail,
        "method": method, "method_label": METHODS[method], "step": st, "step_label": STEPS[st][0],
        "took_s": took if took is not None and took >= 0 else None,
        "timeline": [{"k": k, "label": EVENT_NAMES[k], "at": t.isoformat()}
                     for k, t in sorted(line.items(), key=lambda x: x[1]) if t and k in EVENT_NAMES],
    }


# ---------------------------------------------------------------- xulosa («To'lovlar» bo'limi tepasi)

def _pct(a: float, b: float) -> float:
    return round(100 * a / b, 1) if b else 0.0


def local_day(dt: datetime):
    return dt.replace(tzinfo=timezone.utc).astimezone(TZ).date()


def bucket_of(amount: int) -> int:
    for i, (top, _) in enumerate(BUCKETS):
        if top is None or amount <= top:
            return i
    return len(BUCKETS) - 1


def _times(xs: list[float]) -> dict:
    xs = sorted(xs)
    if not xs:
        return {"n": 0, "avg_s": None, "median_s": None}
    mid = len(xs) // 2
    median = xs[mid] if len(xs) % 2 else (xs[mid - 1] + xs[mid]) / 2
    return {"n": len(xs), "avg_s": round(sum(xs) / len(xs)), "median_s": round(median)}


async def summary(a: datetime | None, b: datetime, spend_kinds: tuple = ()) -> dict:
    """[a, b) oralig'ida ochilgan to'lov urinishlari bo'yicha xulosa (a = None — butun davr). Hammasi ODAMLAR soni.
    Bir necha so'rov va bitta aylanish: qator boshiga so'rov yo'q."""
    excl = await track.excluded_ids()
    cond = [Payment.created_at < b]
    if a:
        cond.append(Payment.created_at >= a)
    if excl:
        cond.append(Payment.user_id.notin_(list(excl)))
    async with Session() as s:
        pays = (await s.execute(select(Payment.id, Payment.user_id, Payment.amount, Payment.status, Payment.provider, Payment.purpose,
                                       Payment.site_id, Payment.song_id, Payment.pack, Payment.job_id, Payment.receipt,
                                       Payment.created_at, Payment.decided_at).where(*cond))).all()
        evs = await load_steps(s, cond=cond)
        ev_cond = [Event.kind == "pay_sheet", Event.created_at < b, Event.user_id.is_not(None)]
        if a:
            ev_cond.append(Event.created_at >= a)
        if excl:
            ev_cond.append(Event.user_id.notin_(list(excl)))
        sheet_users = set((await s.execute(select(Event.user_id).where(*ev_cond).distinct())).scalars().all())
        idle_out = await idle(s, a, b, excl, spend_kinds)
        from . import paysurvey
        survey = await paysurvey.stats(s, a, b, excl)

    people, payers = set(), set()
    groups = {"product": defaultdict(lambda: [set(), set(), 0]), "method": defaultdict(lambda: [set(), set(), 0]),
              "amount": defaultdict(lambda: [set(), set(), 0]), "day": defaultdict(lambda: [set(), set(), 0])}
    best: dict[tuple, str] = {}                     # (odam, usul) -> eng uzoq yetgan qadami
    tries: dict[int, list] = defaultdict(list)      # odam -> [(ochilgan vaqt, to'ladimi)]
    took: dict[str, list] = {"click": [], "card": []}
    paid_sum = 0
    for r in pays:
        ev = evs.get(r.id, {})
        method, st = step_of(r.provider or "", r.status, bool(r.receipt), ev)
        ok = st == "paid"
        opened_at = min([t for t in (ev.get("pay_open"), r.created_at) if t])
        purpose = r.purpose or guess_purpose(r.site_id, r.song_id, r.pack, r.job_id)
        people.add(r.user_id)
        tries[r.user_id].append((opened_at, ok))
        if ok:
            payers.add(r.user_id)
            paid_sum += r.amount
            if r.decided_at and r.decided_at >= opened_at and method in took:
                took[method].append((r.decided_at - opened_at).total_seconds())
        for name, key in (("product", purpose), ("method", method), ("amount", bucket_of(r.amount)), ("day", local_day(r.created_at))):
            g = groups[name][key]
            g[0].add(r.user_id)
            g[2] += 1
            if ok:
                g[1].add(r.user_id)
        k = (r.user_id, method)
        if k not in best or STEPS[st][1] > STEPS[best[k]][1]:
            best[k] = st

    def rows(name: str, keys, label) -> list[dict]:
        out = []
        for key in keys:
            if key not in groups[name]:
                continue
            opened, ok, n = groups[name][key]
            out.append({"key": str(key), "label": label(key), "people": len(opened), "paid": len(ok),
                        "conv": _pct(len(ok), len(opened)), "attempts": n})
        return out

    stops = {}
    for m, order in METHOD_STEPS.items():
        c = Counter(st for (_, mm), st in best.items() if mm == m)
        stops[m] = {"people": sum(c.values()),
                    "steps": [{"key": k, "label": STEPS[k][0], "n": c.get(k, 0)} for k in order]}
    chose = {uid for (uid, m) in best if m != "none"}
    stops["none"] = len(people - chose)             # hech bir urinishida usul tanlamaganlar

    n_tries = Counter(min(len(v), 4) for v in tries.values())
    first_ok = []                                   # to'laganlar nechanchi urinishda to'lagan
    for uid in payers:
        seq = sorted(tries[uid], key=lambda x: x[0])
        first_ok.append(next(i for i, (_, ok) in enumerate(seq, 1) if ok))
    attempts = len(pays)
    return {
        "since": (await config())["since"], "excluded": len(excl),
        "total": {"people": len(people), "paid": len(payers), "conv": _pct(len(payers), len(people)), "attempts": attempts,
                  "paid_attempts": sum(1 for v in tries.values() for _, ok in v if ok), "paid_sum": paid_sum},
        "sheet": {"people": len(sheet_users), "chose": len(sheet_users & people)},
        "by_product": rows("product", PURPOSES, lambda k: PURPOSES[k]),
        "by_method": rows("method", METHODS, lambda k: METHODS[k]),
        "by_amount": rows("amount", range(len(BUCKETS)), lambda k: BUCKETS[k][1]),
        "by_day": rows("day", sorted(groups["day"]), lambda k: k.isoformat())[-92:],
        "stops": stops,
        "repeat": {"avg": round(attempts / len(people), 2) if people else 0, "max": max((len(v) for v in tries.values()), default=0),
                   "multi": sum(1 for v in tries.values() if len(v) > 1),
                   "multi_unpaid": sum(1 for u, v in tries.items() if len(v) > 1 and u not in payers),
                   "dist": [{"label": l, "n": n_tries.get(i, 0)} for i, l in ((1, "1 marta"), (2, "2 marta"), (3, "3 marta"), (4, "4 va undan ko'p"))],
                   "paid_first_try": sum(1 for x in first_ok if x == 1),
                   "paid_avg_try": round(sum(first_ok) / len(first_ok), 2) if first_ok else None},
        "time": {**_times(took["click"] + took["card"]), "click": _times(took["click"]), "card": _times(took["card"])},
        "idle": idle_out, "survey": survey,
    }


async def idle(s, a: datetime | None, b: datetime, excl: set, spend_kinds: tuple, limit: int | None = 100) -> dict:
    """Shu davrda balans to'ldirib, shundan keyin hech narsa sotib olmaganlar va ularning hozirgi qoldig'i."""
    cond = [Payment.status == "approved", Payment.decided_at < b]
    if a:
        cond.append(Payment.decided_at >= a)
    if excl:
        cond.append(Payment.user_id.notin_(list(excl)))
    topups = (await s.execute(select(Payment.user_id, func.min(Payment.decided_at), func.max(Payment.decided_at), func.sum(Payment.amount))
                              .where(*cond).group_by(Payment.user_id))).all()
    if not topups:
        return {"people": 0, "payers": 0, "balance": 0, "paid_sum": 0, "rows": []}
    scope = select(Payment.user_id).where(*cond)
    spent = dict((await s.execute(select(BalanceTx.user_id, func.max(BalanceTx.created_at))
                                  .where(BalanceTx.kind.in_(spend_kinds), BalanceTx.user_id.in_(scope)).group_by(BalanceTx.user_id))).all())
    lazy = [t for t in topups if not spent.get(t[0]) or spent[t[0]] < t[1]]
    users = {}
    ids = [t[0] for t in lazy]
    for i in range(0, len(ids), 500):
        for u in (await s.execute(select(User.tg_id, User.first_name, User.username, User.balance).where(User.tg_id.in_(ids[i:i + 500])))).all():
            users[u[0]] = u
    out = []
    for uid, _first, last, total in lazy:
        u = users.get(uid)
        out.append({"id": uid, "name": u[1] if u else "", "username": u[2] if u else "", "balance": u[3] if u else 0,
                    "paid_sum": int(total or 0), "last_paid_at": last.isoformat() if last else None})
    out.sort(key=lambda x: (-x["balance"], -x["paid_sum"]))
    return {"people": len(out), "payers": len(topups), "balance": sum(max(0, x["balance"]) for x in out),
            "paid_sum": sum(x["paid_sum"] for x in out), "rows": out[:limit] if limit else out}
