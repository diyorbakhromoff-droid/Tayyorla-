"""Voronka (statistika TZ, 1 va 2-bandlar): qo'shiq, sayt va video yo'lida odamlar qaysi qadamgacha yetgani
va «Namunasiz qolganlar» sabab bo'yicha.

Sanash ODAM bo'yicha: bir kishi 5 ta qo'shiq boshlasa ham bitta. Har bir odam uchun har qadamning birinchi vaqti
bazaning o'zida bitta so'rov bilan yig'iladi (GROUP BY foydalanuvchi) — qator boshiga so'rov yo'q.
  n («yetib kelgan»)   — shu qadam yoki undan keyingi istalgan qadam yozuvi bor odamlar. Shuning uchun sonlar faqat
                         kamayadi va har bir odam aynan bitta «to'xtagan qadam»ga tushadi (tushib qolganlar ro'yxati shu).
                         Qadamni o'tkazib yuborib keyingisiga yetgan odam (namunasiz sotib olgan, balansidagi puldan
                         to'lagan yoki hodisa yozila boshlashidan oldingi davr) oldingi qadamlardan ham o'tgan hisoblanadi.
  exact («hodisasi bor») — aynan shu hodisa yozilgan odamlar: bazadagi son bilan solishtirish uchun.
Ikki ko'rinish: cohort — tanlangan davrda kelgan yangi odamlar keyin (hozirgacha) nima qilgani («Umumiy»dagi kabi);
                period — kim qachon kelganidan qat'i nazar, shu davr ichidagi harakatlar.
Admin va sinov akkauntlari (track.excluded_ids) sanalmaydi. Vaqtlar bazada UTC, panelda Toshkent vaqti.
"""

from collections import Counter
from datetime import datetime

from sqlalchemy import String, and_, case, cast, func, literal, or_, select, union_all

from . import songflow, track
from .db import BalanceTx, Event, Payment, RenderJob, Session, Site, User
from .payflow import _times

# qadam: (kalit, paneldagi nomi, TZ dagi hodisa nomi)
START = [("start", "Botda Start bosdi", "bot_start"), ("app", "Ilovani ochdi", "app_open")]
PAY = [("pay_open", "To'lov oynasini ochdi", "pay_open"), ("pay_success", "Pul tushdi", "pay_success")]
SPECS = {
    "song": {
        "label": "Qo'shiq", "pay": ("song", "pack"),
        "steps": START + [
            ("song_open", "Qo'shiq bo'limiga kirdi", "song_open"),
            ("song_form_done", "Kimga, ism va sababni to'ldirdi", "song_form_done"),
            ("lyrics_ready", "She'r tayyor bo'ldi", "lyrics_ready"),
            ("sample_requested", "«Namunani tinglash»ni bosdi", "sample_requested"),
            ("sample_ready", "Namuna tayyor bo'ldi", "sample_ready"),
            ("sample_played", "Namunani eshitdi", "sample_played"),
            ("buy_click", "«Sotib olish»ni bosdi", "buy_click"),
        ] + PAY + [
            ("song_delivered", "To'liq qo'shiq berildi", "song_delivered"),
            ("song_shared", "Yuklab oldi yoki ulashdi", "song_shared"),
        ],
        # yon hodisalar (zanjirga kirmaydi): (kalit, nomi, qaysi qadamga yetmaganini tushuntiradi)
        "side": [("lyrics_failed", "She'r yozilmadi (limit yoki xato)", "lyrics_ready"),
                 ("sample_limit", "Limit sabab namuna berilmadi", "sample_ready"),
                 ("sample_failed", "Namuna xato bilan tugadi", "sample_ready")],
        "spans": [("sample_ready", "pay_success", "Namuna tayyor bo'lgandan pul tushguncha"),
                  ("buy_click", "pay_success", "«Sotib olish»dan pul tushguncha"),
                  ("start", "pay_success", "Start bosgandan pul tushguncha")],
    },
    "site": {
        "label": "Sayt", "pay": ("site",),
        "steps": START + [("site_made", "Sayt (taklifnoma) yaratdi", "")] + PAY + [("site_paid", "Saytni sotib oldi", "")],
        "side": [],
        "spans": [("site_made", "site_paid", "Sayt yaratgandan sotib olguncha"), ("start", "site_paid", "Start bosgandan sotib olguncha")],
    },
    "video": {
        "label": "Video", "pay": ("video",),
        "steps": START + [("video_made", "Video buyurtma berdi", ""), ("video_free", "Bepul videoni oldi", "")] + PAY
        + [("video_paid", "Pullik video sotib oldi", "")],
        "side": [],
        "spans": [("video_made", "video_paid", "Birinchi videodan pullik videogacha"), ("start", "video_paid", "Start bosgandan pullik videogacha")],
    },
}
MODES = ("cohort", "period")


def _tables(product: str) -> list[tuple]:
    """Hodisalar jadvalida bo'lmagan qadamlar mavjud jadvallardan olinadi: (foydalanuvchi, vaqt, qadam kaliti, shartlar)."""
    if product == "site":
        return [(Site.owner_id, Site.created_at, "site_made", [Site.kind == "site"]),
                (BalanceTx.user_id, BalanceTx.created_at, "site_paid", [BalanceTx.kind == "site"])]
    if product == "video":
        own = RenderJob.guest_id.is_(None)
        return [(RenderJob.owner_id, RenderJob.created_at, "video_made", [own]),
                (RenderJob.owner_id, func.coalesce(RenderJob.finished_at, RenderJob.created_at), "video_free",
                 [own, RenderJob.charge.in_(("free", "bonus")), RenderJob.status == "done"]),
                (BalanceTx.user_id, BalanceTx.created_at, "video_paid", [BalanceTx.kind.in_(("video", "package"))])]
    return []


def src_cond(src: str) -> list:
    """Manba filtri (users.ref — odamning birinchi manbasi): src_<kod>, organic, ref_, r_, other."""
    if not src:
        return []
    if src == "organic":
        return [User.ref == ""]
    if src in ("ref_", "r_"):
        return [User.ref.startswith(src, autoescape=True)]
    if src == "other":
        return [User.ref != ""] + [~User.ref.startswith(p, autoescape=True) for p in ("src_", "ref_", "r_")]
    if src.startswith("src_"):
        return [User.ref == src]
    return [User.tg_id == -1]  # noma'lum filtr — hech kim


def _user_conds(a: datetime | None, b: datetime, mode: str, src: str) -> list:
    conds = src_cond(src)
    if mode == "cohort":
        if a is not None:
            conds.append(User.created_at >= a)
        conds.append(User.created_at < b)
    return conds


def _scoped(q, uid, t, a, b, mode, excl, users_q):
    """Hamma manbaga bir xil filtr: davr (period ko'rinishida), sinov akkauntlari, kogorta yoki manba."""
    if mode == "period":
        if a is not None:
            q = q.where(t >= a)
        q = q.where(t < b)
    if excl:
        q = q.where(uid.notin_(excl))
    if users_q is not None:
        q = q.where(uid.in_(users_q))
    return q


def _pivot(product: str, keys: list[str], a, b, mode, excl, users_q):
    """Har bir odam uchun har qadamning birinchi vaqti: (uid, t0, t1, ...) — bitta so'rov."""
    idx = {k: i for i, k in enumerate(keys)}
    tables = _tables(product)
    kinds = [k for k in keys if k not in {x[2] for x in tables}]
    pay = [k for k in kinds if k in ("pay_open", "pay_success")]
    cond = Event.kind.in_([k for k in kinds if k not in pay])
    if pay:  # to'lov qadamlari faqat shu mahsulot uchun ochilgan to'lovlar bo'yicha
        refs = select(literal("pay:") + cast(Payment.id, String)).where(Payment.purpose.in_(SPECS[product]["pay"]))
        cond = or_(cond, and_(Event.kind.in_(pay), Event.ref.in_(refs)))
    parts = [(Event.user_id, Event.created_at, case(*[(Event.kind == k, idx[k]) for k in kinds]), [Event.user_id.is_not(None), cond])]
    parts += [(uid, t, literal(idx[key]), conds) for uid, t, key, conds in tables]
    selects = [_scoped(select(uid.label("uid"), step.label("step"), t.label("t")).where(*conds), uid, t, a, b, mode, excl, users_q)
               for uid, t, step, conds in parts]
    u = (union_all(*selects) if len(selects) > 1 else selects[0]).subquery("u")
    return select(u.c.uid, *[func.min(case((u.c.step == i, u.c.t))) for i in range(len(keys))]).group_by(u.c.uid)


def _pct(a: float, b: float) -> float:
    return round(100 * a / b, 1) if b else 0.0


async def _load(product: str, a, b, mode: str, src: str, s, with_cohort_ids: bool = False):
    spec = SPECS[product]
    keys = [k for k, *_ in spec["steps"]] + [k for k, *_ in spec["side"]]
    excl = sorted(await track.excluded_ids())
    conds = _user_conds(a, b, mode, src)
    users_q = select(User.tg_id).where(*conds) if conds else None
    rows = (await s.execute(_pivot(product, keys, a, b, mode, excl, users_q))).all()
    cohort = None
    if mode == "cohort":
        cq = select(User.tg_id, User.created_at) if with_cohort_ids else select(func.count()).select_from(User)
        cq = cq.where(*conds)
        if excl:
            cq = cq.where(User.tg_id.notin_(excl))
        cohort = dict((await s.execute(cq)).all()) if with_cohort_ids else (await s.scalar(cq) or 0)
    return spec, keys, rows, cohort, len(excl)


def _last(ts, n: int) -> int:
    """Odam eng uzoq yetgan qadam raqami (-1 — zanjirdagi birorta qadami yo'q)."""
    for i in range(n - 1, -1, -1):
        if ts[i] is not None:
            return i
    return -1


async def report(product: str, a: datetime | None, b: datetime, mode: str = "cohort", src: str = "") -> dict:
    """Voronka: qadamlar ketma-ket, har birida odamlar soni, oldingi qadamdan o'tganlar foizi, tushib qolganlar soni
    va oldingi qadamdan beri o'tgan vaqt (o'rtacha va mediana)."""
    async with Session() as s:
        spec, keys, rows, cohort, excluded = await _load(product, a, b, mode, src, s)
    steps, n = spec["steps"], len(spec["steps"])
    idx = {k: i for i, k in enumerate(keys)}
    stop, exact = [0] * n, [0] * len(keys)
    gaps = [[] for _ in range(n)]
    spans = [[] for _ in spec["spans"]]
    for r in rows:
        ts = r[1:]
        for i, t in enumerate(ts):
            if t is not None:
                exact[i] += 1
        last = _last(ts, n)
        if last < 0:
            continue
        stop[last] += 1
        for i in range(1, n):
            if ts[i] is not None and ts[i - 1] is not None and ts[i] >= ts[i - 1]:
                gaps[i].append((ts[i] - ts[i - 1]).total_seconds())
        for j, (k1, k2, _) in enumerate(spec["spans"]):
            t1, t2 = ts[idx[k1]], ts[idx[k2]]
            if t1 is not None and t2 is not None and t2 >= t1:
                spans[j].append((t2 - t1).total_seconds())
    reach, acc = [0] * n, 0
    for i in range(n - 1, -1, -1):
        acc += stop[i]
        reach[i] = acc
    if cohort is not None:
        reach[0] = cohort  # kogorta: davrda kelgan hamma yangi odam (hodisasi yozilmagan bo'lsa ham)
    since = (await songflow.config())["since"]
    out = []
    for i, (key, label, tz) in enumerate(steps):
        out.append({
            "key": key, "label": label, "event": tz, "n": reach[i], "exact": exact[i],
            "pct": _pct(reach[i], reach[i - 1]) if i else None, "of_first": _pct(reach[i], reach[0]),
            "lost": reach[i - 1] - reach[i] if i else None, "lost_at": steps[i - 1][0] if i else None,
            "time": _times(gaps[i]) if i else None,
            "since": since if product == "song" and key in songflow.NEW_KINDS else None,
        })
    return {
        "product": product, "label": spec["label"], "mode": mode, "src": src, "steps": out, "since": since, "excluded": excluded,
        "side": [{"key": k, "label": label, "under": under, "n": exact[idx[k]],
                  "since": since if k in songflow.NEW_KINDS else None} for k, label, under in spec["side"]],
        "spans": [{"label": label, **_times(spans[j])} for j, (_, _, label) in enumerate(spec["spans"])],
    }


async def _users(s, ids: list[int]) -> dict:
    out = {}
    for i in range(0, len(ids), 500):
        for u in (await s.execute(select(User.tg_id, User.first_name, User.username, User.ref, User.blocked, User.last_seen)
                                  .where(User.tg_id.in_(ids[i:i + 500])))).all():
            out[u[0]] = u
    return out


def _people_out(picked: list[tuple], users: dict, total: int) -> dict:
    rows = []
    for uid, at in picked:
        u = users.get(uid)
        rows.append({"id": uid, "name": u[1] if u else "", "username": u[2] if u else "", "ref": (u[3] if u else "") or "",
                     "blocked": bool(u[4]) if u else False, "last_seen": u[5].isoformat() if u and u[5] else None,
                     "at": at.isoformat() if at else None})
    return {"total": total, "rows": rows}


async def people(product: str, a: datetime | None, b: datetime, mode: str, src: str, step: str, limit: int | None = 200) -> dict:
    """Shu qadamda to'xtaganlar: eng uzoq yetgan qadami `step` bo'lgan (keyingisiga o'tmagan) odamlar, yangisi tepada.
    at — shu qadamga yetgan vaqti."""
    async with Session() as s:
        spec, keys, rows, cohort, _ = await _load(product, a, b, mode, src, s, with_cohort_ids=True)
        n = len(spec["steps"])
        want = next((i for i, x in enumerate(spec["steps"]) if x[0] == step), None)
        if want is None:
            return {"total": 0, "rows": [], "label": ""}
        found, seen = [], set()
        for r in rows:
            last = _last(r[1:], n)
            if last >= 0:
                seen.add(r[0])
            if last == want:
                found.append((r[0], r[1 + want]))
        if cohort is not None and want == 0:  # kelgan, lekin birorta qadami yozilmagan odamlar ham shu yerda to'xtagan
            found += [(uid, at) for uid, at in cohort.items() if uid not in seen]
        found.sort(key=lambda x: x[1] or datetime.min, reverse=True)
        picked = found[:limit] if limit else found
        out = _people_out(picked, await _users(s, [u for u, _ in picked]), len(found))
    return {**out, "label": spec["steps"][want][1]}


# ---------------------------------------------------------------- namunasiz qolganlar (TZ 2-band)

# guruh: (kalit, nomi, ta'rifi, nima qilinadi)
NOSAMPLE = [
    ("nopress", "Tugmani bosmagan", "She'r tayyor, «Namunani tinglash» bosilmagan", "Interfeys yoki matn muammosi"),
    ("limit", "Limitga yetgan", "Limit sabab namuna berilmagan", "Limit sozlamasini qayta ko'rish"),
    ("error", "Xato", "Namuna xato bilan tugagan va qayta olinmagan", "Texnik tuzatish, qayta urinish"),
    ("left", "Kutib o'tirmagan", "So'ragan, namuna tayyor bo'lguncha ilovadan chiqqan va qaytib eshitmagan",
     "Tayyor bo'lganda botga xabar (yuborilyapti)"),
    ("pending", "Hozir tayyorlanmoqda", "So'ralgan, hali tayyor ham, xato ham emas", "Kutish"),
    ("old", "Sababi yozilmagan (eski)", "Hisob boshlanishidan oldingi she'rlar: tugma bosilgani, limit va xato u paytda yozilmagan", "—"),
]
_NS_KINDS = ("lyrics_ready", "sample_requested", "sample_failed", "sample_limit", "sample_ready", "sample_away", "sample_played",
             "song_delivered")


def _why(row, since: datetime | None) -> str | None:
    """Bitta odam: ok — namunasi bor, bought — namunasiz sotib olgan, aks holda nega namunasiz qolgani.
    Bir necha to'siq bo'lsa, eng oxirgisi hisobga olinadi (odam aynan shu yerda to'xtagan)."""
    _, ly, req, fail, lim, n_ready, n_away, _, played, bought = row
    if ly is None:
        return None
    if n_ready and (played is not None or (n_away or 0) < n_ready):
        return "ok"  # eshitgan yoki namuna tayyor bo'lganda ilovada kutib turgan
    if bought is not None:
        return "bought"
    if n_ready:
        return "left"
    marks = [x for x in (req, fail, lim) if x is not None]
    if not marks:
        return "old" if since is None or ly < since else "nopress"
    last = max(marks)
    if lim == last:
        return "limit"
    return "error" if fail == last else "pending"


async def _ns_rows(s, a, b, mode: str, src: str):
    excl = sorted(await track.excluded_ids())
    conds = _user_conds(a, b, mode, src)
    users_q = select(User.tg_id).where(*conds) if conds else None
    E = Event

    def mx(kind):
        return func.max(case((E.kind == kind, E.created_at)))

    def cnt(kind, col=None):
        return func.sum(case((E.kind == kind, 1 if col is None else func.coalesce(col, 0)), else_=0))

    q = select(E.user_id, mx("lyrics_ready"), mx("sample_requested"), mx("sample_failed"), mx("sample_limit"), cnt("sample_ready"),
               cnt("sample_away"), cnt("sample_away", E.num), mx("sample_played"), mx("song_delivered")) \
        .where(E.kind.in_(_NS_KINDS), E.user_id.is_not(None)).group_by(E.user_id)
    rows = (await s.execute(_scoped(q, E.user_id, E.created_at, a, b, mode, excl, users_q))).all()
    detail = _scoped(select(E.user_id, E.kind, E.meta).where(E.kind.in_(("sample_failed", "sample_limit")), E.user_id.is_not(None))
                     .order_by(E.id), E.user_id, E.created_at, a, b, mode, excl, users_q)
    return rows, detail


async def nosample(a: datetime | None, b: datetime, mode: str = "cohort", src: str = "") -> dict:
    """She'ri tayyor odamlardan namunasiz qolganlari — sabab bo'yicha (har bir sababning yechimi boshqa)."""
    since = await songflow.since()
    async with Session() as s:
        rows, detail = await _ns_rows(s, a, b, mode, src)
        last_meta = {(uid, kind): meta or {} for uid, kind, meta in (await s.execute(detail)).all()}  # oxirgisi qoladi
    groups: Counter = Counter()
    sub = {"limit": Counter(), "error": Counter()}
    notified = 0
    for r in rows:
        why = _why(r, since)
        if why is None:
            continue
        groups[why] += 1
        if why == "limit":
            sub["limit"][last_meta.get((r[0], "sample_limit"), {}).get("l") or "?"] += 1
        elif why == "error":
            sub["error"][last_meta.get((r[0], "sample_failed"), {}).get("r") or "unknown"] += 1
        elif why == "left" and (r[7] or 0) > 0:
            notified += 1
    total = sum(groups.values())
    none = total - groups["ok"] - groups["bought"]
    labels = {"limit": songflow.LIMITS, "error": songflow.REASONS}
    return {
        "lyrics": total, "with_sample": groups["ok"], "bought": groups["bought"], "none": none, "notified": notified,
        "since": since.isoformat() if since else None,
        "groups": [{"key": k, "label": label, "about": about, "todo": todo, "n": groups[k], "pct": _pct(groups[k], none),
                    "sub": [{"key": x, "label": labels[k].get(x, x), "n": c} for x, c in sub[k].most_common()] if k in sub else []}
                   for k, label, about, todo in NOSAMPLE],
    }


async def nosample_people(a: datetime | None, b: datetime, mode: str, src: str, group: str, limit: int | None = 200) -> dict:
    """Namunasiz qolganlarning bitta guruhi: odamlar ro'yxati (at — oxirgi to'siq yoki she'r tayyor bo'lgan vaqt)."""
    since = await songflow.since()
    label = next((x[1] for x in NOSAMPLE if x[0] == group), "")
    async with Session() as s:
        rows, _ = await _ns_rows(s, a, b, mode, src)
        found = [(r[0], max(x for x in (r[1], r[2], r[3], r[4]) if x is not None)) for r in rows if label and _why(r, since) == group]
        found.sort(key=lambda x: x[1], reverse=True)
        picked = found[:limit] if limit else found
        out = _people_out(picked, await _users(s, [u for u, _ in picked]), len(found))
    return {**out, "label": label}
