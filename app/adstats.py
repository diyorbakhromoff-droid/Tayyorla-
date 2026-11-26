"""Reklama manbasi bo'yicha kesim (statistika TZ, 4-band): havola nomlash qoidasi, kunlik reklama xarajati,
«Trafik manbalari» jadvalining yangi ustunlari va kogorta (kelgandan 1, 3, 7 kun ichida xarid).

Havola nomlash qoidasi: kampaniya_video_lending — qoshiq_v3_l1, qoshiq_v3_l2, tabrik_v1_l1. Video «v», lending «l»
bilan boshlanadi; reklama lendingsiz, to'g'ridan-to'g'ri botga olib borsa — qoshiq_v3. Jadval kampaniya bo'yicha
guruhlanadi; qoidaga mos kelmagan eski havolalar (insta_noyabr) alohida guruhda qoladi.

Lending kodni botga Start parametri orqali uzatadi: lendingdagi tugmaga kuzatuv havolasi (/go/<kod>) qo'yiladi — u bosishni
sanaydi va t.me/<bot>?start=src_<kod> ga yo'naltiradi (bot users.ref ga yozadi). To'g'ridan-to'g'ri t.me havolasi bosishni
sanamaydi — «Bosish» 0 bo'lib qolgani shundan; Start va keyingi ustunlar esa baribir to'g'ri sanaladi.

Hisob ODAM bo'yicha, odamning birinchi manbasi (users.ref) bo'yicha: tanlangan davrda shu manbadan birinchi marta kelganlar
va ularning keyingi (hozirgacha) harakatlari — «Trafik manbalari»dagi kogorta. Hammasi bazaning o'zida, GROUP BY manba:
har bir odam uchun belgilar EXISTS bilan bitta so'rovda olinadi, qator boshiga alohida so'rov yo'q.
  Xarajat        — tanlangan davrdagi kunlik yozuvlar yig'indisi; havolada kunlik yozuv umuman bo'lmasa — eski «Reklama narxi»
  Start narxi    — xarajat / shu davrda shu havola orqali Start bosgan odamlar
  Xaridor narxi  — xarajat / sotib olganlar
  ROI            — (tushum − xarajat − AI xarajati) / xarajat; AI va musiqa xarajati — cost_log dan, shu odamlar bo'yicha
  Blok foizi     — shu manbadan kelganlardan hozir botni bloklab turganlar ulushi
  Kogorta        — birinchi xarid (tasdiqlangan to'lov yoki balansdan xizmat sotib olish) kelgandan 1, 3, 7 kun (24, 72, 168 soat) ichida
Admin va sinov akkauntlari (track.excluded_ids) sanalmaydi. Vaqtlar bazada UTC, kunlar Toshkent bo'yicha.
"""

import re
from datetime import date, datetime, timedelta

from sqlalchemy import case, delete, exists, func, or_, select

from . import costs, payflow, songflow
from .db import AdSpend, BalanceTx, CostLog, Event, Payment, RenderJob, Session, Site, Song, TrafficLink, User, engine, utcnow

# ---------------------------------------------------------------- havola nomlash qoidasi

NAME_RE = re.compile(r"^([a-z0-9]+(?:_[a-z0-9]+)*?)_(v\d{1,4}[a-z]?)(?:_(l\d{1,4}[a-z]?))?$")
_PART = {"campaign": re.compile(r"^[a-z0-9]+(?:_[a-z0-9]+)*$"), "video": re.compile(r"^v?(\d{1,4}[a-z]?)$"),
         "landing": re.compile(r"^l?(\d{1,4}[a-z]?)$")}
NO_CAMPAIGN = "Nomlash qoidasidan oldingi havolalar"


def parse_code(code: str) -> dict:
    """«qoshiq_v3_l1» → kampaniya, video, lending. Qoidaga mos kelmasa — hammasi bo'sh."""
    m = NAME_RE.match(code or "")
    if not m:
        return {"campaign": "", "video": "", "landing": ""}
    return {"campaign": m.group(1), "video": m.group(2), "landing": m.group(3) or ""}


def compose_code(campaign: str, video: str, landing: str = "") -> str:
    """Formadagi uch maydondan kod: («qoshiq», «3», «1») → qoshiq_v3_l1. Xato bo'lsa ValueError (o'zbekcha matn bilan)."""
    c = re.sub(r"[\s\-]+", "_", (campaign or "").strip().lower()).strip("_")
    if not _PART["campaign"].match(c):
        raise ValueError("Kampaniya nomi faqat lotin harflari, raqam va _ dan iborat bo'lsin (masalan: qoshiq)")
    m = _PART["video"].match((video or "").strip().lower())
    if not m:
        raise ValueError("Video raqami: 3 yoki v3 ko'rinishida")
    code = f"{c}_v{m.group(1)}"
    if (landing or "").strip():
        m = _PART["landing"].match(landing.strip().lower())
        if not m:
            raise ValueError("Lending raqami: 1 yoki l1 ko'rinishida (lendingsiz bo'lsa bo'sh qoldiring)")
        code += f"_l{m.group(1)}"
    if len(code) > 24:
        raise ValueError(f"Kod 24 belgidan uzun bo'lib ketdi ({code}) — kampaniya nomini qisqartiring")
    return code


# ---------------------------------------------------------------- kunlik reklama xarajati

CURRENCIES = {"som": "so'm", "usd": "$"}
MAX_SOM = 10**11


async def usd_rate() -> int:
    """Dollar kursi — admin paneldagi umumiy sozlama («Xarajatlar» bilan bitta: costs.usd_som)."""
    return round((await costs.rates())["usd_som"])


def amount_of(v) -> int | float:
    """Kiritilgan summa: butun bo'lsa butun son (300000, $20), aks holda 2 xonagacha ($12.5)."""
    v = round(float(v or 0), 2)
    return int(v) if v.is_integer() else v


def _row(x: AdSpend) -> dict:
    return {"id": x.id, "day": x.day, "amount": amount_of(x.amount), "currency": x.currency, "rate": x.rate or None, "som": int(x.som)}


async def spend_list(link_id: int) -> list[dict]:
    async with Session() as s:
        rows = (await s.execute(select(AdSpend).where(AdSpend.link_id == link_id).order_by(AdSpend.day.desc()))).scalars().all()
    return [_row(x) for x in rows]


async def spend_put(link_id: int, day: date, amount: float, currency: str, uid: int | None = None) -> dict:
    """Bir kunlik xarajat: shu kun uchun yozuv bo'lsa — yangilanadi (bir havola, bir kun — bitta yozuv)."""
    if currency not in CURRENCIES:
        raise ValueError("Valyuta: so'm yoki dollar")
    if not amount or amount <= 0:
        raise ValueError("Summa 0 dan katta bo'lsin")
    rate = await usd_rate() if currency == "usd" else 0
    som = round(amount * rate) if currency == "usd" else round(amount)
    if som > MAX_SOM:
        raise ValueError("Summa juda katta")
    async with Session() as s:
        x = (await s.execute(select(AdSpend).where(AdSpend.link_id == link_id, AdSpend.day == day.isoformat()))).scalar_one_or_none()
        new = x is None
        if new:
            x = AdSpend(link_id=link_id, day=day.isoformat(), created_by=uid)
            s.add(x)
        x.amount, x.currency, x.rate, x.som = round(float(amount), 2), currency, rate, som
        await s.commit()
    return {**_row(x), "updated": not new}


async def spend_drop(link_id: int, spend_id: int) -> bool:
    async with Session() as s:
        n = (await s.execute(delete(AdSpend).where(AdSpend.id == spend_id, AdSpend.link_id == link_id))).rowcount
        await s.commit()
    return bool(n)


async def spend_totals(s, d1: date | None, d2: date) -> tuple[dict[int, int], dict[int, int], set[int]]:
    """(havola → davrdagi xarajat so'mda, havola → davrdagi kunlar soni, kunlik yozuvi umuman bor havolalar)."""
    cond = [AdSpend.day <= d2.isoformat()] + ([AdSpend.day >= d1.isoformat()] if d1 else [])
    rows = (await s.execute(select(AdSpend.link_id, func.sum(AdSpend.som), func.count()).where(*cond).group_by(AdSpend.link_id))).all()
    have = set((await s.execute(select(AdSpend.link_id).distinct())).scalars().all())
    return {i: int(v or 0) for i, v, _ in rows}, {i: n for i, _, n in rows}, have


async def spend_export(d1: date | None, d2: date) -> list[tuple]:
    """CSV uchun: davrdagi barcha kunlik yozuvlar (sana, havola kodi, nomi, summa, valyuta, kurs, so'mda)."""
    cond = [AdSpend.day <= d2.isoformat()] + ([AdSpend.day >= d1.isoformat()] if d1 else [])
    async with Session() as s:
        return (await s.execute(select(AdSpend.day, TrafficLink.code, TrafficLink.name, AdSpend.amount, AdSpend.currency, AdSpend.rate, AdSpend.som)
                                .join(TrafficLink, TrafficLink.id == AdSpend.link_id).where(*cond)
                                .order_by(AdSpend.day, TrafficLink.code))).all()


# ---------------------------------------------------------------- manba bo'yicha ko'rsatkichlar (bitta so'rov, GROUP BY manba)

COUNTS = ("users", "app", "created", "songs", "song_bought", "bought", "played", "buy_click", "pay_open", "blocked",
          "d1", "d3", "d7", "young")
SUMS = ("revenue", "spent")


def source_key():
    """users.ref → manba kaliti: src_<kod> (kichik harfda), ref_ (do'st taklifi), r_ (tabrik sahifasi), '' (organik), other."""
    r = User.ref
    return case((r.startswith("src_", autoescape=True), func.lower(r)), (r.startswith("ref_", autoescape=True), "ref_"),
                (r.startswith("r_", autoescape=True), "r_"), (r == "", ""), else_="other")


def _plus_days(col, n: int):
    """Vaqtga n kun qo'shish: PostgreSQL da interval, SQLite da datetime(…, '+n days')."""
    if engine.dialect.name == "sqlite":
        return func.datetime(col, f"+{n} days")
    return col + timedelta(days=n)


def _cohort(a: datetime | None, b: datetime, excl) -> list:
    conds = [User.created_at < b]
    if a is not None:
        conds.append(User.created_at >= a)
    if excl:
        conds.append(User.tg_id.notin_(sorted(excl)))
    return conds


def _ev(kind: str):
    return exists().where(Event.user_id == User.tg_id, Event.kind == kind)


def _per_user(a, b, excl, spend_kinds):
    """Kogortadagi har bir odam: manba kaliti va belgilar (EXISTS / bog'langan qisqa so'rovlar — indeks bo'yicha)."""
    uid = User.tg_id
    pay = (Payment.user_id == uid, Payment.status == "approved")
    tx = (BalanceTx.user_id == uid, BalanceTx.kind.in_(spend_kinds))
    return select(
        source_key().label("k"), User.created_at.label("at"), User.blocked.label("blocked"),
        _ev("app").label("app"), _ev("sample_played").label("played"), _ev("buy_click").label("buyc"), _ev("pay_open").label("popen"),
        or_(exists().where(Site.owner_id == uid, Site.kind == "site"),
            exists().where(RenderJob.owner_id == uid, RenderJob.guest_id.is_(None))).label("created"),
        exists().where(Song.owner_id == uid).label("songs"),
        exists().where(Song.owner_id == uid, Song.paid.is_(True)).label("song_bought"),
        exists().where(Site.owner_id == uid, Site.status == "paid").label("site_paid"),
        select(func.coalesce(func.sum(Payment.amount), 0)).where(*pay).scalar_subquery().label("paid_sum"),
        select(func.coalesce(func.sum(-BalanceTx.amount), 0)).where(*tx).scalar_subquery().label("spent_sum"),
        select(func.min(Payment.decided_at)).where(*pay).scalar_subquery().label("pay_first"),
        select(func.min(BalanceTx.created_at)).where(*tx).scalar_subquery().label("tx_first"),
    ).where(*_cohort(a, b, excl)).subquery("uf")


async def by_source(s, a: datetime | None, b: datetime, excl, spend_kinds) -> dict[str, dict]:
    """Manba kaliti → kogorta ko'rsatkichlari (odamlar soni, tushum, sarflangan, kogorta 1/3/7 kun).
    Sotib oldi — «Trafik manbalari»dagi kabi: tasdiqlangan to'lov, balansdan xizmat (spend_kinds) yoki to'langan sayt."""
    u = _per_user(a, b, excl, spend_kinds)
    first = case((u.c.pay_first.is_(None), u.c.tx_first), (u.c.tx_first.is_(None), u.c.pay_first),
                 (u.c.pay_first < u.c.tx_first, u.c.pay_first), else_=u.c.tx_first)

    def n(cond):
        return func.sum(case((cond, 1), else_=0))

    bought = or_(u.c.pay_first.is_not(None), u.c.tx_first.is_not(None), u.c.site_paid)
    q = select(u.c.k, func.count(), n(u.c.app), n(u.c.created), n(u.c.songs), n(u.c.song_bought), n(bought),
               n(u.c.played), n(u.c.buyc), n(u.c.popen), n(u.c.blocked),
               n(first < _plus_days(u.c.at, 1)), n(first < _plus_days(u.c.at, 3)), n(first < _plus_days(u.c.at, 7)),
               n(u.c.at > utcnow() - timedelta(days=7)),
               func.sum(u.c.paid_sum), func.sum(u.c.spent_sum)).group_by(u.c.k)
    out = {}
    for k, *vals in (await s.execute(q)).all():
        out[k] = {**dict(zip(COUNTS, (int(v or 0) for v in vals[:len(COUNTS)]))),
                  **dict(zip(SUMS, (int(v or 0) for v in vals[len(COUNTS):])))}
    return out


async def ai_by_source(s, a: datetime | None, b: datetime, excl) -> dict[str, float]:
    """AI va musiqa xarajati (so'm) kogortadagi odamlar bo'yicha — butun tarixi (tushum ham shunday hisoblanadi)."""
    us = select(User.tg_id.label("uid"), source_key().label("k")).where(*_cohort(a, b, excl)).subquery("us")
    rows = (await s.execute(select(us.c.k, CostLog.kind, CostLog.model, func.sum(CostLog.units_in), func.sum(CostLog.units_out))
                            .join(us, us.c.uid == CostLog.user_id).group_by(us.c.k, CostLog.kind, CostLog.model))).all()
    r = await costs.rates()
    out: dict[str, float] = {}
    for k, kind, model, uin, uout in rows:
        out[k] = out.get(k, 0.0) + costs.som_of(kind, uin or 0, uout or 0, r, model or "")
    return out


async def starts_clicks(s, a: datetime | None, b: datetime, excl) -> tuple[dict[str, int], dict[str, int]]:
    """Shu davrda: Start bosgan odamlar (havola kodi → odamlar) va kuzatuv havolasi orqali bosishlar (kod → soni)."""
    when = [Event.created_at < b] + ([Event.created_at >= a] if a is not None else [])
    src = func.lower(Event.src)
    sq = select(src, func.count(func.distinct(Event.user_id))).where(
        Event.kind == "start", Event.src.startswith("src_", autoescape=True), Event.user_id.is_not(None), *when)
    if excl:
        sq = sq.where(Event.user_id.notin_(sorted(excl)))
    starts = {k[4:]: int(v) for k, v in (await s.execute(sq.group_by(src))).all()}
    clicks = {k: int(v) for k, v in (await s.execute(select(Event.src, func.count()).where(Event.kind == "click", *when)
                                                     .group_by(Event.src))).all()}
    return starts, clicks


# ---------------------------------------------------------------- hosila ko'rsatkichlar

def _pct(a: float, b: float) -> float:
    return round(100 * a / b, 1) if b else 0.0


def empty() -> dict:
    return {**{k: 0 for k in COUNTS + SUMS}, "starts": 0, "clicks": 0, "ai_cost": 0.0}


def derive(m: dict, spend: int | None) -> dict:
    """Narx va ulushlar: Start narxi, bir kishi narxi, xaridor narxi, ROI, blok foizi, konversiya, kogorta foizlari."""
    users, bought, starts, ai = m["users"], m["bought"], m.get("starts", 0), m.get("ai_cost", 0) or 0
    m["ai_cost"] = round(ai)
    m["spend"] = spend or 0
    m["cps"] = round(spend / starts) if spend and starts else None
    m["cpu"] = round(spend / users) if spend and users else None
    m["cpb"] = round(spend / bought) if spend and bought else None
    m["roi"] = round(100 * (m["revenue"] - spend - ai) / spend, 1) if spend else None
    m["conv"] = _pct(bought, users)
    m["block_pct"] = _pct(m["blocked"], users)
    for k in ("d1", "d3", "d7", "bought"):
        m[f"{k}_pct"] = _pct(m[k], users)
    return m


def add_into(total: dict, m: dict) -> None:
    for k in COUNTS + SUMS + ("starts", "clicks", "ai_cost", "spend"):
        total[k] = (total.get(k) or 0) + (m.get(k) or 0)


async def since_notes() -> dict:
    """Hodisalarga asoslangan ustunlar qachondan beri sanaladi (TZ: tiklab bo'lmaydiganlari uchun sana ko'rsatiladi)."""
    sf = (await songflow.config())["since"]
    return {"played": sf, "buy_click": sf, "pay_open": None, "pay_since": (await payflow.config())["since"]}
