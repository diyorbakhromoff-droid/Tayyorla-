"""Progrev: ishni boshlab, oxiriga yetkazmagan foydalanuvchilarga eslatma xabarlari ketma-ketligi.

Uchta ketma-ketlik (ustuvorlik shu tartibda):
  site — sayt yasagan, lekin to'lamagan (langar: sayt yaratilgan vaqt);
  song — qo'shiq boshlagan, lekin sotib olmagan (langar: namuna so'ralgan yoki she'r yozilgan vaqt);
  new  — yangi qo'shilgan va hali hech narsa yasamagan (langar: ro'yxatdan o'tgan vaqt).

Har bir qadam: langardan necha soat keyin, matn va tugma. Sozlamalar admin panelidan o'zgaradi (store: "nudges").
Qoidalar: bitta qadam bitta obyekt uchun bir marta; bitta odamga xabarlar orasida kamida gap_hours soat;
faqat kunduzi (Toshkent vaqti); sotib olgan yoki botni bloklagan odamga yuborilmaydi; muddati o'tib ketgan
qadam (GRACE_H soatdan ko'p kechikkan) tashlab ketiladi — tizim yoqilganda eski foydalanuvchilarga to'satdan xabar ketmaydi.
"""

import asyncio
import copy
import logging
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone

from sqlalchemy import func, select

from . import store
from .config import settings
from .db import NudgeLog, RenderJob, Session, Site, Song, User, utcnow
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
                     "ikki xil variant, {price}."},
            {"after": 24, "button": "Matnni o‘zgartirish",
             "text": "«{title}» qo‘shig‘i hali tugallanmagan.\n\nMatn yoqmagan bo‘lsa, bir bosishda o‘zgartirish mumkin: quvnoqroq, ta’sirliroq yoki "
                     "ismi ko‘proq aytiladigan qilib."},
            {"after": 72, "button": "Qo‘shiqni olish",
             "text": "Shaxsiy qo‘shiq — yaqiningiz uzoq eslab yuradigan sovg‘a.\n\n«{title}» qo‘shig‘ingiz saqlangan. Tayyor bo‘lsangiz, to‘liq "
                     "variantni oling va videoga yoki saytga fon musiqa qilib qo‘ying."},
        ]},
        "new": {"on": True, "steps": [
            {"after": 1, "button": "Bepul video yasash", "target": "videos",
             "text": "{name}, Tayyorla’ga xush kelibsiz!\n\nBirinchi ishni bepul sinab ko‘ring: kuniga {free_videos} ta video taklifnoma yoki tabrik "
                     "bepul. Dizaynni tanlaysiz, ism va sanani yozasiz — video shu chatga keladi."},
            {"after": 24, "button": "Sayt dizaynlarini ko‘rish", "target": "sites",
             "text": "Yaqiningizni tabriklashning boshqacha yo‘li bor: unga atalgan kichik sayt.\n\nSuratlar, musiqa va sizning so‘zlaringiz bitta "
                     "havolada. Namunasini bepul ko‘rasiz, yoqsa keyin to‘laysiz."},
            {"after": 72, "button": "Qo‘shiq yaratish", "target": "song",
             "text": "Yaqiningizning ismi aytiladigan qo‘shiq yaratib ko‘ring 🎵\n\nU haqida bir necha savolga javob berasiz, she’rni biz yozamiz. "
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


async def collect(s, cfg: dict, now: datetime) -> list[Job]:
    """Hozir yuborilishi kerak bo'lgan xabarlar (bir odamga bittadan). Tashlab ketilgan qadamlar jurnalga yoziladi."""
    seqs = cfg["seqs"]
    max_after = max([st["after"] for k in SEQS for st in seqs[k]["steps"]] or [0])
    window = timedelta(hours=max_after + GRACE_H + 1)
    logs = (await s.execute(select(NudgeLog).where(NudgeLog.created_at >= now - window - timedelta(days=2)))).scalars().all()
    done: dict[tuple, set[int]] = {}
    last_sent: dict[int, datetime] = {}
    for r in logs:
        done.setdefault((r.user_id, r.seq, r.ref), set()).add(r.step)
        if r.status == "sent" and (r.user_id not in last_sent or r.created_at > last_sent[r.user_id]):
            last_sent[r.user_id] = r.created_at
    gap = timedelta(hours=cfg["gap_hours"])
    jobs: dict[int, Job] = {}

    def plan(uid: int, seq: str, ref: str, anchor: datetime, make, skip=lambda i: False) -> None:
        if uid in jobs:
            return
        steps = seqs[seq]["steps"]
        mine = done.setdefault((uid, seq, ref), set())
        while True:
            nxt = next_step(steps, mine, anchor, now, skip)
            if not nxt:
                return
            i, what = nxt
            if what == "skip":
                s.add(NudgeLog(user_id=uid, seq=seq, step=i, ref=ref, status="skipped", created_at=now))
                mine.add(i)
                continue
            if uid in last_sent and now - last_sent[uid] < gap:
                return  # yaqinda xabar olgan — keyingi aylanishda
            jobs[uid] = make(i, steps[i])
            return

    # --- 1. to'lanmagan sayt (har egasining eng oxirgi qoralamasi)
    if seqs["site"]["on"]:
        from .catalog import TEMPLATES, site_price
        rows = (await s.execute(select(Site).where(Site.kind == "site", Site.status == "draft", Site.created_at >= now - window)
                                .order_by(Site.id.desc()))).scalars().all()
        latest: dict[int, Site] = {}
        for x in rows:
            latest.setdefault(x.owner_id, x)
        bought = dict((await s.execute(select(Site.owner_id, func.max(Site.id)).where(
            Site.kind == "site", Site.status == "paid", Site.owner_id.in_(list(latest) or [0])).group_by(Site.owner_id))).all())
        for uid, site in latest.items():
            if bought.get(uid, 0) > site.id:
                continue  # shundan keyin boshqa sayt sotib olgan
            cfg_s = site.config or {}
            tpl = TEMPLATES.get(cfg_s.get("template")) or {}
            try:
                price = site_price(cfg_s)
            except Exception:
                price = 0
            ctx = {"title": tpl.get("name") or "Sayt", "price": money(price) if price else ""}
            plan(uid, "site", f"site:{site.id}", site.created_at,
                 lambda i, st, ctx=ctx, uid=uid, site=site: Job(uid, "site", i, f"site:{site.id}", st["text"], st["button"],
                                                               app_url("tab=sites&mine=1"), ctx))

    # --- 2. sotib olinmagan qo'shiq (har egasining eng oxirgisi)
    if seqs["song"]["on"]:
        from . import songs as song_mod
        rows = (await s.execute(select(Song).where(Song.paid.is_(False), Song.status.in_(("lyrics", "preview_ready")),
                                                   Song.created_at >= now - window - timedelta(days=1)).order_by(Song.id.desc()))).scalars().all()
        latest_song: dict[int, Song] = {}
        for x in rows:
            latest_song.setdefault(x.owner_id, x)
        bought = dict((await s.execute(select(Song.owner_id, func.max(Song.id)).where(
            Song.paid.is_(True), Song.owner_id.in_(list(latest_song) or [0])).group_by(Song.owner_id))).all())
        for uid, song in latest_song.items():
            if bought.get(uid, 0) > song.id:
                continue
            anchor = song.preview_at or song.created_at
            if anchor < now - window:
                continue
            price = await song_mod.price_for(s, uid)
            ctx = {"title": song.title or (f"{song.recipient} uchun qo‘shiq" if song.recipient else "Qo‘shiq"), "price": money(price)}
            plan(uid, "song", f"song:{song.id}", anchor,
                 lambda i, st, ctx=ctx, uid=uid, song=song: Job(uid, "song", i, f"song:{song.id}", st["text"], st["button"],
                                                               app_url(f"song={song.id}"), ctx))

    # --- 3. yangi qo'shilganlar: hali yasamagan mahsulotini taklif qilamiz
    if seqs["new"]["on"]:
        fresh = (await s.execute(select(User.tg_id, User.created_at).where(User.created_at >= now - window, User.blocked.is_(False)))).all()
        ids = [u for u, _ in fresh] or [0]
        made = {
            "videos": set((await s.execute(select(RenderJob.owner_id).where(RenderJob.owner_id.in_(ids)).distinct())).scalars().all()),
            "sites": set((await s.execute(select(Site.owner_id).where(Site.owner_id.in_(ids), Site.kind == "site").distinct())).scalars().all()),
            "song": set((await s.execute(select(Song.owner_id).where(Song.owner_id.in_(ids)).distinct())).scalars().all()),
        }
        made["app"] = made["videos"] | made["sites"] | made["song"]
        steps = seqs["new"]["steps"]
        query = {"videos": "tab=videos", "sites": "tab=sites", "song": "song=new", "app": ""}
        for uid, created in fresh:
            plan(uid, "new", "", created,
                 lambda i, st, uid=uid: Job(uid, "new", i, "", st["text"], st["button"], app_url(query[st.get("target", "app")]), {}),
                 skip=lambda i, uid=uid: uid in made[steps[i].get("target", "app")])

    # --- ism, til, blok
    out = list(jobs.values())[:MAX_PER_PASS]
    if out:
        from . import songs as song_mod
        users = {u.tg_id: u for u in (await s.execute(select(User).where(User.tg_id.in_([j.user_id for j in out])))).scalars().all()}
        per_user, _ = await song_mod.limits()
        keep = []
        for j in out:
            u = users.get(j.user_id)
            if u and u.blocked:
                continue
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


def keyboard(job: Job):
    from aiogram.types import InlineKeyboardButton, InlineKeyboardMarkup, WebAppInfo
    if not job.button or not settings.base_url.startswith("https://"):
        return None
    label = job.button
    if job.ctx.get("lang") == "cy":
        from .i18n import to_cyrillic
        label = to_cyrillic(label)
    return InlineKeyboardMarkup(inline_keyboard=[[InlineKeyboardButton(text=label, web_app=WebAppInfo(url=job.url))]])


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
            s.add(NudgeLog(user_id=job.user_id, seq=job.seq, step=job.step, ref=job.ref,
                           status="sent" if status == "sent" else "failed", created_at=now))
            if status == "blocked":
                u = await s.get(User, job.user_id)
                if u:
                    u.blocked = True
            await s.commit()
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
    """Har ketma-ketlik va qadam bo'yicha: yuborildi / yetmadi / tashlab ketildi va natija (sotib oldi yoki yasadi)."""
    async with Session() as s:
        rows = (await s.execute(select(NudgeLog.seq, NudgeLog.step, NudgeLog.status, func.count())
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
            NudgeLog.status == "sent", NudgeLog.created_at >= utcnow() - timedelta(hours=24))) or 0
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
    await bot.send_message(uid, render(job), parse_mode=None, reply_markup=keyboard(job))
