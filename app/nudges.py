"""Progrev: ishni boshlab, oxiriga yetkazmagan foydalanuvchilarga eslatma xabarlari ketma-ketligi.

Uchta ketma-ketlik (ustuvorlik shu tartibda):
  site — sayt yasagan, lekin to'lamagan (langar: sayt tayyorlangan vaqt);
  song — qo'shiq boshlagan, lekin sotib olmagan (langar: namuna so'ralgan yoki she'r yozilgan vaqt);
  new  — yangi qo'shilgan va hali hech narsa yasamagan (langar: ro'yxatdan o'tgan vaqt).

Har bir qadam: langardan necha soat keyin, matn va tugma. Sozlamalar admin panelidan o'zgaradi (store: "nudges").
Qoidalar: bitta qadam bitta obyekt uchun bir marta; bitta odamga xabarlar orasida kamida gap_hours soat;
faqat kunduzi (Toshkent vaqti); sotib olgan yoki botni bloklagan odamga yuborilmaydi; muddati o'tib ketgan
qadam (GRACE_H soatdan ko'p kechikkan) tashlab ketiladi — tizim yoqilganda eski foydalanuvchilarga to'satdan xabar ketmaydi.
Nazorat guruhidagilarga (app/control.py, standart o'chiq) hech narsa yuborilmaydi va jurnalga ham yozilmaydi.

O'tkazib yuborilgan qadam jurnalga sababi bilan yoziladi (nudge_log.reason, statistika TZ 5-band):
  bought  — allaqachon sotib olgan (shu yoki keyingi sayt/qo'shiq);  made — «new»: shu narsani allaqachon yasagan;
  blocked — botni bloklagan (qadam muddati tugaguncha kutiladi: shu orada blokdan chiqsa, xabar baribir boradi);
  gap     — qadam vaqtidan 36 soat o'tguncha tanaffus (gap_hours) tugamadi;
  night   — tanaffus tugagan paytlar faqat tunga to'g'ri keldi (yuborish soatlaridan tashqarida);
  late    — vaqti kelganda yuborilmadi, boshqa sabab: progrev o'chiq edi, bot ishlamadi yoki navbat to'lgan edi.
Yetmagan xabar (failed): blocked — botni bloklagan (bot_block hodisasi ham yoziladi), error — boshqa Telegram xatosi.

Tuzatish (statistika TZ: «qo'shiq ketma-ketligining 3-xabari 45 kishiga ketgan, 5 442 tasi o'tkazib yuborilgan»):
avval botni bloklagan odamning navbati har aylanishda «yuboriladigan» ro'yxatga tushar, faqat oxirida (MAX_PER_PASS dan
keyin) olib tashlanar va hech qachon jurnalga yozilmas edi. Ro'yxat eng yangi qo'shiqdan boshlab tuzilgani uchun bunday
odamlar 300 talik o'rinni doimiy egallab, eng eski qadamlar (3-xabar, 72 soat) navbatga yetmay 36 soatdan kechikib qolardi.
Endi bloklaganlar navbatga kirmaydi, cheklov ulardan keyin qo'llanadi va navbat muddati eng yaqin tugaydigan qadamdan boshlanadi.
"""

import asyncio
import copy
import logging
from collections import defaultdict
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone

from sqlalchemy import func, or_, select

from . import control, store, track
from .config import settings
from .db import Event, NudgeLog, RenderJob, Session, Site, Song, User, utcnow
from .reminders import TZ

log = logging.getLogger(__name__)

KEY = "nudges"
SEQS = ("site", "song", "new")
SEQ_NAMES = {"site": "Sayt yasab, to'lamaganlar", "song": "Qo'shiq boshlab, sotib olmaganlar", "new": "Yangi qo'shilganlar"}
GRACE_H = 36          # qadam shuncha soatdan ko'p kechiksa — yuborilmaydi
MAX_PER_PASS = 300    # bir aylanishda eng ko'pi bilan nechta xabar
MAX_STEPS = 6
# «new» ketma-ketligida tugma qayerni ochadi (va qaysi mahsulot yasalgan bo'lsa qadam tashlab ketiladi)
TARGETS = {"videos": "Bepul video", "sites": "Sayt", "song": "Qo'shiq", "app": "Bosh sahifa"}
PLACEHOLDERS = {
    "{name}": "foydalanuvchi ismi",
    "{title}": "sayt dizayni yoki qo'shiq nomi",
    "{price}": "shu sayt yoki qo'shiq narxi",
    "{free_videos}": "kuniga bepul videolar soni",
    "{free_songs}": "kuniga bepul qo'shiq namunalari soni",
}

DEFAULTS: dict = {
    "on": True,
    "from_hour": 9, "to_hour": 21,
    "gap_hours": 20,
    "seqs": {
        "site": {"on": True, "steps": [
            {"after": 2, "button": "Saytni yakunlash",
             "text": "{name}, saytingiz tayyor turibdi 🎁\n\n«{title}» dizaynidagi sayt hozircha namuna holatida. To‘lovdan keyin «Namuna» yozuvi "
                     "olinadi va havolani yaqiningizga yuborishingiz mumkin bo‘ladi. Narxi {price}."},
            {"after": 24, "button": "Saytimni ochish",
             "text": "Kecha boshlagan saytingiz hali sizni kutyapti.\n\nKiritgan matn va suratlaringiz saqlangan — qaytadan to‘ldirish shart emas. "
                     "Bir necha daqiqada yakunlab, yaqiningizga yuborishingiz mumkin."},
            {"after": 72, "button": "Dizaynlarni ko‘rish",
             "text": "Saytingizni yakunlamadingiz. Balki dizayn yoki narx to‘g‘ri kelmagandir?\n\nBoshqa dizayn yoki arzonroq tarifni tanlab ko‘ring — "
                     "kiritgan ma’lumotlaringiz saqlanadi. Savol bo‘lsa, shu yerga yozing, yordam beramiz."},
        ]},
        "song": {"on": True, "steps": [
            {"after": 2, "button": "Qo‘shiqni ochish",
             "text": "{name}, «{title}» qo‘shig‘ingiz sizni kutyapti 🎵\n\nShe’r tayyor. Namunani eshitib ko‘ring, yoqsa to‘liq qo‘shiqni olasiz: "
                     "{price}."},
            {"after": 24, "button": "Matnni o‘zgartirish",
             "text": "«{title}» qo‘shig‘i hali tugallanmagan.\n\nMatn yoqmagan bo‘lsa, bir bosishda o‘zgartirish mumkin: quvnoqroq, ta’sirliroq yoki "
                     "ismi ko‘proq aytiladigan qilib."},
            {"after": 72, "button": "Qo‘shiqni olish",
             "text": "Shaxsiy qo‘shiq — yaqiningiz uzoq eslab yuradigan sovg‘a.\n\n«{title}» qo‘shig‘ingiz saqlangan. Tayyor bo‘lsangiz, to‘liq "
                     "qo‘shiqni oling va videoga yoki saytga fon musiqa qilib qo‘ying."},
        ]},
        "new": {"on": True, "steps": [
            {"after": 1, "button": "Bepul video yasash", "target": "videos",
             "text": "{name}, Tayyorla’ga xush kelibsiz!\n\nBirinchi ishni bepul sinab ko‘ring: kuniga {free_videos} ta video taklifnoma yoki tabrik "
                     "bepul. Dizaynni tanlaysiz, ism va sanani yozasiz — video shu chatga keladi."},
            {"after": 24, "button": "Sayt dizaynlarini ko‘rish", "target": "sites",
             "text": "Yaqiningizni tabriklashning boshqacha yo‘li bor: unga atalgan kichik sayt.\n\nSuratlar, musiqa va sizning so‘zlaringiz bitta "
                     "havolada. Namunasini bepul ko‘rasiz, yoqsa keyin to‘laysiz."},
            {"after": 72, "button": "Qo‘shiq tayyorlash", "target": "song",
             "text": "Yaqiningizning ismi aytiladigan qo‘shiq tayyorlab ko‘ring 🎵\n\nU haqida bir necha savolga javob berasiz, she’rni biz yozamiz. "
                     "Kuniga {free_songs} ta 20 soniyalik namuna bepul."},
        ]},
    },
}

STATE: dict = {"last_run": None, "last_sent": 0}


class ConfigError(ValueError):
    pass


def clean(raw: dict) -> dict:
    """Admin paneldan kelgan sozlamani tekshiradi va tartibga keltiradi."""
    out = {"on": bool(raw.get("on", True))}
    try:
        out["from_hour"] = int(raw.get("from_hour", DEFAULTS["from_hour"]))
        out["to_hour"] = int(raw.get("to_hour", DEFAULTS["to_hour"]))
        out["gap_hours"] = int(raw.get("gap_hours", DEFAULTS["gap_hours"]))
    except (TypeError, ValueError):
        raise ConfigError("Soatlar butun son bo'lishi kerak")
    if not (0 <= out["from_hour"] < out["to_hour"] <= 24):
        raise ConfigError("Yuborish vaqti noto'g'ri: boshlanish tugashdan oldin bo'lsin (0–24)")
    if not (1 <= out["gap_hours"] <= 168):
        raise ConfigError("Xabarlar orasidagi tanaffus 1–168 soat bo'lsin")
    out["seqs"] = {}
    for k in SEQS:
        sq = (raw.get("seqs") or {}).get(k) or {}
        steps = []
        for i, st in enumerate(sq.get("steps") or []):
            try:
                after = int(st.get("after"))
            except (TypeError, ValueError):
                raise ConfigError(f"{SEQ_NAMES[k]}: {i + 1}-xabar vaqti noto'g'ri")
            text = str(st.get("text") or "").strip()
            button = str(st.get("button") or "").strip()[:40]
            if not (1 <= after <= 720):
                raise ConfigError(f"{SEQ_NAMES[k]}: {i + 1}-xabar vaqti 1–720 soat oralig'ida bo'lsin")
            if steps and after <= steps[-1]["after"]:
                raise ConfigError(f"{SEQ_NAMES[k]}: {i + 1}-xabar oldingisidan keyinroq bo'lishi kerak")
            if not text or len(text) > 3500:
                raise ConfigError(f"{SEQ_NAMES[k]}: {i + 1}-xabar matni bo'sh yoki juda uzun")
            step = {"after": after, "text": text, "button": button}
            if k == "new":
                step["target"] = st.get("target") if st.get("target") in TARGETS else "app"
            steps.append(step)
        if len(steps) > MAX_STEPS:
            raise ConfigError(f"{SEQ_NAMES[k]}: ko'pi bilan {MAX_STEPS} ta xabar")
        out["seqs"][k] = {"on": bool(sq.get("on", True)) and bool(steps), "steps": steps}
    return out


async def config() -> dict:
    cfg = await store.get(KEY)
    if not cfg:
        return copy.deepcopy(DEFAULTS)
    try:
        return clean(cfg)
    except ConfigError:
        log.exception("Progrev sozlamasi buzilgan — standart qiymatlar ishlatiladi")
        return copy.deepcopy(DEFAULTS)


async def save(raw: dict) -> dict:
    cfg = clean(raw)
    await store.put(KEY, cfg)
    return cfg


# ---------------------------------------------------------------- kimga nima yuboriladi

@dataclass
class Job:
    user_id: int
    seq: str
    step: int
    ref: str
    text: str
    button: str
    url: str
    ctx: dict = field(default_factory=dict)


def money(n: int) -> str:
    return f"{n:,}".replace(",", " ") + " so‘m"


def fill(text: str, ctx: dict) -> str:
    """O'rinlarni to'ldiradi. Ism bo'lmasa «{name}, » olib tashlanadi va gap bosh harf bilan boshlanadi."""
    name = (ctx.get("name") or "").strip()
    if not name:
        for lead in ("{name}, ", "{name}! ", "{name} — ", "{name} "):
            if text.startswith(lead):
                text = text[len(lead):]
                text = text[:1].upper() + text[1:]
                break
    for k in PLACEHOLDERS:
        text = text.replace(k, str(ctx.get(k[1:-1], "") or ""))
    return text.strip()


def app_url(query: str = "") -> str:
    return f"{settings.base_url}/app" + (f"?{query}" if query else "")


def next_step(steps: list[dict], done: set[int], anchor: datetime, now: datetime, skip=lambda i: False):
    """Navbatdagi qadam: (indeks, "send" | "skip") yoki None (hali vaqti kelmagan yoki hammasi tugagan)."""
    for i, st in enumerate(steps):
        if i in done:
            continue
        at = anchor + timedelta(hours=st["after"])
        if now < at:
            return None
        if now >= at + timedelta(hours=GRACE_H) or skip(i):
            return i, "skip"
        return i, "send"
    return None


def _cut(free: list[tuple[datetime, datetime]], a: datetime, b: datetime) -> list[tuple[datetime, datetime]]:
    """Bo'sh oraliqlardan [a, b) ni olib tashlaydi."""
    out = []
    for x, y in free:
        if b <= x or a >= y:
            out.append((x, y))
            continue
        if x < a:
            out.append((x, a))
        if b < y:
            out.append((b, y))
    return out


def _daytime(a: datetime, b: datetime, cfg: dict) -> timedelta:
    """[a, b) oralig'ining yuborish soatlariga (Toshkent) to'g'ri keladigan qismi."""
    la, lb = (x.replace(tzinfo=timezone.utc).astimezone(TZ) for x in (a, b))
    total, d = timedelta(0), la.date()
    while d <= lb.date():
        start = datetime(d.year, d.month, d.day, tzinfo=TZ) + timedelta(hours=cfg["from_hour"])
        end = datetime(d.year, d.month, d.day, tzinfo=TZ) + timedelta(hours=cfg["to_hour"])
        if max(start, la) < min(end, lb):
            total += min(end, lb) - max(start, la)
        d += timedelta(days=1)
    return total


MIN_SLOT = timedelta(minutes=30)  # undan qisqa kunduzgi bo'shliq hisobga olinmaydi (progrev 10 daqiqada bir tekshiradi)
HOLD: dict[tuple, str] = {}       # (odam, ketma-ketlik, obyekt, qadam) -> oxirgi marta nega kutib turildi: gap | cap


def late_reason(sent: list[datetime], ready: datetime, end: datetime, gap: timedelta, cfg: dict, held: str = "") -> str:
    """Qadam [ready, end) oralig'ida nega yuborilmadi: tanaffus hech tugamagan bo'lsa — gap; tugagan paytlar faqat
    tunga to'g'ri kelsa — night; kunduz bo'sh payt bo'lgan, lekin oxirgi marta tanaffus (yoki shu odamga boshqa progrev
    xabari navbatda) sabab kutilgan bo'lsa — gap; aks holda late (progrev o'chiq, bot ishlamagan yoki navbat to'lgan)."""
    free = [(ready, end)] if ready < end else []
    for t in sent:
        free = _cut(free, t, t + gap)
    if not free:
        return "gap"
    if sum((_daytime(a, b, cfg) for a, b in free), timedelta(0)) < MIN_SLOT:
        return "night"
    return "gap" if held == "gap" else "late"


async def collect(s, cfg: dict, now: datetime) -> list[Job]:
    """Hozir yuborilishi kerak bo'lgan xabarlar (bir odamga bittadan). Tashlab ketilgan qadamlar sababi bilan jurnalga yoziladi.
    Navbat muddati eng yaqin tugaydigan qadamdan boshlanadi; botni bloklaganlar navbatga kirmaydi (pastdagi izohga qarang)."""
    seqs = cfg["seqs"]
    max_after = max([st["after"] for k in SEQS for st in seqs[k]["steps"]] or [0])
    window = timedelta(hours=max_after + GRACE_H + 1)
    grace = timedelta(hours=GRACE_H)
    gap = timedelta(hours=cfg["gap_hours"])
    logs = (await s.execute(select(NudgeLog.user_id, NudgeLog.seq, NudgeLog.ref, NudgeLog.step, NudgeLog.status, NudgeLog.created_at)
                            .where(NudgeLog.created_at >= now - window - timedelta(days=2), NudgeLog.seq.in_(SEQS)))).all()
    done: dict[tuple, dict[int, datetime]] = {}   # (odam, ketma-ketlik, obyekt) -> {qadam: hal bo'lgan vaqt}
    sent: dict[int, list[datetime]] = defaultdict(list)  # odamga yetgan progrev xabarlari vaqti (tanaffus shundan)
    for uid, seq, ref, step, status, at in logs:
        mine = done.setdefault((uid, seq, ref), {})
        mine[step] = min(mine.get(step, at), at)
        if status == "sent":
            sent[uid].append(at)
    ctl = await control.config()
    jobs: dict[int, tuple[datetime, Job]] = {}  # odam -> (qadam muddati tugaydigan vaqt, xabar)

    def plan(uid: int, seq: str, ref: str, anchor: datetime, make, blocked: bool = False, why=lambda i: "") -> None:
        steps = seqs[seq]["steps"]
        mine = done.setdefault((uid, seq, ref), {})
        prev = anchor  # oldingi qadam hal bo'lgan vaqt: undan oldin keyingisi yuborilmaydi
        for i, st in enumerate(steps):
            if i in mine:
                prev = max(prev, mine[i])
                continue
            at = anchor + timedelta(hours=st["after"])
            if now < at:
                return
            key = (uid, seq, ref, i)
            reason = why(i)
            if not reason and now >= at + grace:
                reason = "blocked" if blocked else late_reason(sorted(sent.get(uid, ())), max(at, prev), at + grace, gap, cfg,
                                                               HOLD.get(key, ""))
            if reason:
                s.add(NudgeLog(user_id=uid, seq=seq, step=i, ref=ref, status="skipped", reason=reason, created_at=now))
                HOLD.pop(key, None)
                mine[i] = prev = min(now, at + grace)  # kechikkan qadam muddati tugagan paytda hal bo'lgan hisoblanadi
                continue
            # Botni bloklagan odam navbatga kirmaydi: muddat tugaguncha kutiladi (blokdan chiqsa — xabar boradi), keyin
            # «blocked» sababi bilan o'tkazib yuboriladi. Avval bunday navbat har aylanishda 300 talik o'rinni egallab turardi.
            if blocked:
                return
            if uid in jobs or (sent.get(uid) and now - max(sent[uid]) < gap):
                HOLD[key] = "gap"  # bu odamga yaqinda xabar ketgan yoki hozir boshqa progrev xabari navbatda
                return
            jobs[uid] = (at + grace, make(i, st))
            return

    def outside(uid: int, created: datetime | None) -> bool:
        return control.is_member(ctl, uid, created)  # nazorat guruhi: progrev umuman yo'q

    # --- 1. to'lanmagan sayt (har egasining eng oxirgi sayti; sotib olingani — «bought»)
    if seqs["site"]["on"]:
        from .catalog import TEMPLATES, site_price
        rows = (await s.execute(select(Site, User.blocked, User.created_at).outerjoin(User, User.tg_id == Site.owner_id).where(
            Site.kind == "site", Site.status.in_(("draft", "paid")), Site.created_at >= now - window).order_by(Site.id.desc()))).all()
        latest: dict[int, tuple] = {}
        for x, blk, created in rows:
            latest.setdefault(x.owner_id, (x, blk, created))
        bought = dict((await s.execute(select(Site.owner_id, func.max(Site.id)).where(
            Site.kind == "site", Site.status == "paid", Site.owner_id.in_(list(latest) or [0])).group_by(Site.owner_id))).all())
        for uid, (site, blk, created) in latest.items():
            if outside(uid, created):
                continue
            paid = site.status == "paid" or bought.get(uid, 0) > site.id  # shu yoki keyingi saytni sotib olgan
            cfg_s = site.config or {}
            tpl = TEMPLATES.get(cfg_s.get("template")) or {}
            try:
                price = site_price(cfg_s)
            except Exception:
                price = 0
            ctx = {"title": tpl.get("name") or "Sayt", "price": money(price) if price else ""}
            plan(uid, "site", f"site:{site.id}", site.created_at,
                 lambda i, st, ctx=ctx, uid=uid, site=site: Job(uid, "site", i, f"site:{site.id}", st["text"], st["button"],
                                                               app_url("tab=sites&mine=1"), ctx),
                 blocked=blk, why=lambda i, paid=paid: "bought" if paid else "")

    # --- 2. sotib olinmagan qo'shiq (har egasining eng oxirgisi; sotib olingani — «bought»)
    songs_due: dict[int, Song] = {}
    if seqs["song"]["on"]:
        rows = (await s.execute(select(Song, User.blocked, User.created_at).outerjoin(User, User.tg_id == Song.owner_id).where(
            or_(Song.paid.is_(True), Song.status.in_(("lyrics", "preview_ready"))),
            Song.created_at >= now - window - timedelta(days=1)).order_by(Song.id.desc()))).all()
        latest_song: dict[int, tuple] = {}
        for x, blk, created in rows:
            latest_song.setdefault(x.owner_id, (x, blk, created))
        bought = dict((await s.execute(select(Song.owner_id, func.max(Song.id)).where(
            Song.paid.is_(True), Song.owner_id.in_(list(latest_song) or [0])).group_by(Song.owner_id))).all())
        for uid, (song, blk, created) in latest_song.items():
            anchor = song.preview_at or song.created_at
            if anchor < now - window or outside(uid, created):
                continue
            paid = song.paid or bought.get(uid, 0) > song.id
            songs_due[uid] = song
            ctx = {"title": song.title or (f"{song.recipient} uchun qo‘shiq" if song.recipient else "Qo‘shiq")}
            plan(uid, "song", f"song:{song.id}", anchor,
                 lambda i, st, ctx=ctx, uid=uid, song=song: Job(uid, "song", i, f"song:{song.id}", st["text"], st["button"],
                                                               app_url(f"song={song.id}"), ctx),
                 blocked=blk, why=lambda i, paid=paid: "bought" if paid else "")

    # --- 3. yangi qo'shilganlar: hali yasamagan mahsulotini taklif qilamiz
    if seqs["new"]["on"]:
        fresh = (await s.execute(select(User.tg_id, User.created_at, User.blocked).where(User.created_at >= now - window))).all()
        ids = [u for u, _, _ in fresh] or [0]
        made = {
            "videos": set((await s.execute(select(RenderJob.owner_id).where(RenderJob.owner_id.in_(ids)).distinct())).scalars().all()),
            "sites": set((await s.execute(select(Site.owner_id).where(Site.owner_id.in_(ids), Site.kind == "site").distinct())).scalars().all()),
            "song": set((await s.execute(select(Song.owner_id).where(Song.owner_id.in_(ids)).distinct())).scalars().all()),
        }
        made["app"] = made["videos"] | made["sites"] | made["song"]
        steps = seqs["new"]["steps"]
        query = {"videos": "tab=videos", "sites": "tab=sites", "song": "song=new", "app": ""}
        for uid, created, blk in fresh:
            if outside(uid, created):
                continue
            plan(uid, "new", "", created,
                 lambda i, st, uid=uid: Job(uid, "new", i, "", st["text"], st["button"], app_url(query[st.get("target", "app")]), {}),
                 blocked=blk, why=lambda i, uid=uid: "made" if uid in made[steps[i].get("target", "app")] else "")

    # --- navbat: muddati eng yaqin tugaydiganlar birinchi (cheklov eng eski qadamlarni och qoldirmasin)
    queue = [j for _, j in sorted(jobs.values(), key=lambda x: x[0])]
    if len(HOLD) > 200_000:
        HOLD.clear()
    for j in queue[MAX_PER_PASS:]:
        HOLD[(j.user_id, j.seq, j.ref, j.step)] = "cap"  # bu aylanishga sig'madi
    for j in queue[:MAX_PER_PASS]:
        HOLD.pop((j.user_id, j.seq, j.ref, j.step), None)
    out = queue[:MAX_PER_PASS]
    if out:
        from . import songs as song_mod
        from .pricing import EV_SALE, config as pcfg, promo_of, sale_of
        users = {u.tg_id: u for u in (await s.execute(select(User).where(User.tg_id.in_([j.user_id for j in out])))).scalars().all()}
        per_user, _ = await song_mod.limits()
        song_uids = [j.user_id for j in out if j.seq == "song"]
        site_buyers = set()
        if song_uids and settings.song_site_price > 0:  # songs.price_for bilan bir xil, lekin hammasi bitta so'rovda
            site_buyers = set((await s.execute(select(Site.owner_id).where(
                Site.owner_id.in_(song_uids), Site.status == "paid", Site.kind == "site").distinct())).scalars().all())
        sale = sale_of(await pcfg(), now) if song_uids else None
        sale_used = set()
        if sale:  # aksiya: xabardagi narx ilovadagi bilan bir xil bo'lsin (aksiyada qo'shiq olganlarga — oddiy narx)
            sale_used = set((await s.execute(select(Event.user_id).where(
                Event.user_id.in_(song_uids), Event.kind == EV_SALE, Event.ref == f"sale:{sale['id']}"))).scalars().all())
        keep = []
        for j in out:
            u = users.get(j.user_id)
            if u and u.blocked:
                continue
            if j.seq == "song":
                song = songs_due[j.user_id]
                price = settings.song_site_price if j.user_id in site_buyers else settings.song_price
                promo = promo_of(song, now)
                price = min(price, promo["price"]) if promo else price
                if sale and j.user_id not in sale_used:
                    price = min(price, sale["price"])
                j.ctx["price"] = money(price)
            j.ctx.update(name=(u.first_name if u else "") or "", lang=(u.lang if u else "") or "uz",
                         free_videos=settings.free_videos_per_day, free_songs=per_user)
            keep.append(j)
        out = keep
    return out


# ---------------------------------------------------------------- yuborish

def render(job: Job) -> str:
    text = fill(job.text, job.ctx)
    if job.ctx.get("lang") == "cy":
        from .i18n import to_cyrillic
        text = to_cyrillic(text)
    return text


def keyboard(job: Job, tracked: bool = True):
    """Tugma Mini App'ni ochadi. tracked — havolaga imzolangan belgi qo'shiladi: bosilgani «msg_click» bo'lib yoziladi
    (app/track.py). Tugma yozuvi va ochiladigan sahifa o'zgarmaydi."""
    from aiogram.types import InlineKeyboardButton, InlineKeyboardMarkup, WebAppInfo
    if not job.button or not settings.base_url.startswith("https://"):
        return None
    label = job.button
    if job.ctx.get("lang") == "cy":
        from .i18n import to_cyrillic
        label = to_cyrillic(label)
    url = track.click_url(job.url, f"{job.seq}.{job.step}", job.user_id) if tracked else job.url
    return InlineKeyboardMarkup(inline_keyboard=[[InlineKeyboardButton(text=label, web_app=WebAppInfo(url=url))]])


async def deliver(bot, job: Job) -> str:
    """sent | failed | blocked"""
    from aiogram.exceptions import TelegramForbiddenError, TelegramRetryAfter
    for attempt in range(2):
        try:
            await bot.send_message(job.user_id, render(job), parse_mode=None, reply_markup=keyboard(job))
            return "sent"
        except TelegramRetryAfter as e:
            if attempt:
                return "failed"
            await asyncio.sleep(e.retry_after + 1)
        except TelegramForbiddenError:
            return "blocked"
        except Exception:
            log.exception("Progrev xabari yuborilmadi: %s %s/%s", job.user_id, job.seq, job.step)
            return "failed"
    return "failed"


def in_hours(cfg: dict, now_local: datetime) -> bool:
    return cfg["from_hour"] <= now_local.hour < cfg["to_hour"]


async def run_once(bot, now: datetime | None = None, force: bool = False) -> dict:
    """Bir aylanish: yuborilishi kerak bo'lganlarni topadi va yuboradi. now — bazadagi (UTC, zonasiz) vaqt."""
    cfg = await config()
    now = now or utcnow()
    res = {"sent": 0, "failed": 0, "blocked": 0}
    if not cfg["on"] and not force:
        return res
    local = now.replace(tzinfo=timezone.utc).astimezone(TZ)
    if not in_hours(cfg, local) and not force:
        return res
    async with Session() as s:
        jobs = await collect(s, cfg, now)
        await s.commit()  # tashlab ketilgan qadamlar
    for job in jobs:
        status = await deliver(bot, job)
        async with Session() as s:
            s.add(NudgeLog(user_id=job.user_id, seq=job.seq, step=job.step, ref=job.ref, status="sent" if status == "sent" else "failed",
                           reason="" if status == "sent" else "blocked" if status == "blocked" else "error", created_at=now))
            await s.commit()
        if status == "blocked":
            await track.mark_blocked(job.user_id, "nudge")  # bayroq va blok vaqti (bot_block hodisasi)
        res[status] += 1
        await asyncio.sleep(1 / 20)
    STATE.update(last_run=utcnow().isoformat(), last_sent=res["sent"])
    return res


async def loop(bot, interval: int = 600) -> None:
    await asyncio.sleep(60)  # ishga tushgach biroz kutamiz
    while True:
        try:
            res = await run_once(bot)
            if res["sent"] or res["failed"] or res["blocked"]:
                log.info("Progrev: %s yuborildi, %s yetmadi, %s bloklagan", res["sent"], res["failed"], res["blocked"])
        except Exception:
            log.exception("Progrev tsiklida xato")
        await asyncio.sleep(interval)


# ---------------------------------------------------------------- admin paneli uchun

async def stats() -> dict:
    """Har ketma-ketlik va qadam bo'yicha (butun davr): yuborildi / yetmadi / tashlab ketildi va natija (sotib oldi yoki yasadi).
    Davr bo'yicha batafsil ko'rsatkichlar (tugma, qaytish, xarid, blok, sabablar) — app/msgstats.py."""
    async with Session() as s:
        rows = (await s.execute(select(NudgeLog.seq, NudgeLog.step, NudgeLog.status, func.count()).where(NudgeLog.seq.in_(SEQS))
                                .group_by(NudgeLog.seq, NudgeLog.step, NudgeLog.status))).all()
        steps: dict[str, dict[int, dict]] = {k: {} for k in SEQS}
        for seq, step, status, n in rows:
            if seq in steps:
                steps[seq].setdefault(step, {"sent": 0, "failed": 0, "skipped": 0})[status if status in ("sent", "failed", "skipped") else "failed"] = n
        reached = {}
        for seq in SEQS:
            reached[seq] = await s.scalar(select(func.count(func.distinct(NudgeLog.user_id))).where(
                NudgeLog.seq == seq, NudgeLog.status == "sent")) or 0
        refs = (await s.execute(select(NudgeLog.ref).where(NudgeLog.status == "sent", NudgeLog.seq.in_(("site", "song"))).distinct())).scalars().all()
        site_ids = [int(r[5:]) for r in refs if r.startswith("site:")]
        song_ids = [int(r[5:]) for r in refs if r.startswith("song:")]
        won = {
            "site": await s.scalar(select(func.count()).select_from(Site).where(Site.id.in_(site_ids or [0]), Site.status == "paid")) or 0,
            "song": await s.scalar(select(func.count()).select_from(Song).where(Song.id.in_(song_ids or [0]), Song.paid.is_(True))) or 0,
        }
        new_ids = (await s.execute(select(NudgeLog.user_id).where(NudgeLog.seq == "new", NudgeLog.status == "sent").distinct())).scalars().all()
        ids = list(new_ids) or [0]
        makers = set((await s.execute(select(RenderJob.owner_id).where(RenderJob.owner_id.in_(ids)).distinct())).scalars().all())
        makers |= set((await s.execute(select(Site.owner_id).where(Site.owner_id.in_(ids), Site.kind == "site").distinct())).scalars().all())
        makers |= set((await s.execute(select(Song.owner_id).where(Song.owner_id.in_(ids)).distinct())).scalars().all())
        won["new"] = len(makers)
        day = await s.scalar(select(func.count()).select_from(NudgeLog).where(
            NudgeLog.seq.in_(SEQS), NudgeLog.status == "sent", NudgeLog.created_at >= utcnow() - timedelta(hours=24))) or 0
    return {"steps": {k: {str(i): v for i, v in d.items()} for k, d in steps.items()}, "reached": reached, "won": won,
            "sent_24h": day, "last_run": STATE["last_run"], "last_sent": STATE["last_sent"]}


async def send_test(bot, uid: int, seq: str, step: int, raw_step: dict | None = None) -> None:
    """Adminning o'ziga namuna xabar (saqlanmagan matnni ham sinab ko'rish mumkin)."""
    cfg = await config()
    st = raw_step or cfg["seqs"][seq]["steps"][step]
    from . import songs as song_mod
    async with Session() as s:
        u = await s.get(User, uid)
    per_user, _ = await song_mod.limits()
    ctx = {"name": (u.first_name if u else "") or "Admin", "lang": "uz", "free_videos": settings.free_videos_per_day, "free_songs": per_user,
           "title": "Shohizinda" if seq == "site" else "Opajonim", "price": money(settings.price_premium if seq == "site" else settings.song_price)}
    query = {"site": "tab=sites&mine=1", "song": "tab=songs",
             "new": {"videos": "tab=videos", "sites": "tab=sites", "song": "song=new", "app": ""}.get(st.get("target", "app"), "")}[seq]
    job = Job(uid, seq, step, "", str(st.get("text") or ""), str(st.get("button") or "")[:40], app_url(query), ctx)
    await bot.send_message(uid, render(job), parse_mode=None, reply_markup=keyboard(job, tracked=False))


# ---------------------------------------------------------------- sozlama tashxisi (panelda ogohlantirish)

def diagnose(cfg: dict) -> list[dict]:
    """Sozlamaning o'zidan kelib chiqadigan muammolar: tanaffus va 36 soat qoidasi bilan qadam hech qachon (yoki ko'pincha)
    yuborilmay qoladimi. Har biri: {"seq", "step", "level": bad|warn|info, "text"}."""
    out = []
    night = 24 - (cfg["to_hour"] - cfg["from_hour"])
    gap = cfg["gap_hours"]
    for k in SEQS:
        sq = cfg["seqs"][k]
        if not sq["on"]:
            continue
        steps = sq["steps"]
        for i in range(1, len(steps)):
            spacing = steps[i]["after"] - steps[i - 1]["after"]
            room = GRACE_H - max(0, gap - spacing)  # oldingisi o'z vaqtida ketsa, shu qadam uchun qolgan soatlar
            where = f"«{SEQ_NAMES[k]}», {i + 1}-xabar"
            if room <= 0:
                out.append({"seq": k, "step": i, "level": "bad", "text": (
                    f"{where}: oldingi xabardan {spacing} soat keyin turibdi, tanaffus esa {gap} soat — tanaffus tugaguncha "
                    f"{GRACE_H} soatlik muddat o'tib ketadi, oldingi xabarni olgan odamga bu xabar hech qachon yuborilmaydi. "
                    f"Tanaffusni {spacing + GRACE_H - 1} soatdan kam qiling yoki xabarni kechroqqa suring.")})
            elif room <= night:
                out.append({"seq": k, "step": i, "level": "warn", "text": (
                    f"{where}: tanaffus ({gap} soat) tugagach yuborish uchun {room} soat qoladi, tun esa {night} soat — "
                    f"oldingi xabar kechqurun ketgan bo'lsa, bu xabar ko'pincha «tungi vaqt» sababi bilan o'tkazib yuboriladi.")})
    # bir odamga bir vaqtda ikki ketma-ketlik: «new» va «song» (yoki «site») birinchi xabarlari tanaffus uchun bir-birini kutadi
    new = cfg["seqs"]["new"]
    for k in ("song", "site"):
        sq = cfg["seqs"][k]
        if new["on"] and sq["on"] and new["steps"] and sq["steps"] and abs(sq["steps"][0]["after"] - new["steps"][0]["after"]) < gap:
            out.append({"seq": k, "step": 0, "level": "info", "text": (
                f"Yangi kelib darhol {'qo‘shiq boshlagan' if k == 'song' else 'sayt yasagan'} odam «{SEQ_NAMES['new']}» 1-xabarini "
                f"({new['steps'][0]['after']} soatda) oladi, «{SEQ_NAMES[k]}» 1-xabari esa tanaffus tufayli taxminan "
                f"{new['steps'][0]['after'] + gap} soatgacha kutadi (bitta odamga {gap} soatda bitta xabar).")})
    return out
