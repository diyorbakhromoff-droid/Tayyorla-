import secrets
from datetime import datetime, timezone

from sqlalchemy import (JSON, BigInteger, Boolean, DateTime, Float, ForeignKey, Index, Integer, String, Text, UniqueConstraint, func, inspect,
                        select, text)
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column

from .config import settings

engine = create_async_engine(settings.database_url)
Session = async_sessionmaker(engine, expire_on_commit=False)


def utcnow() -> datetime:
    """Bazada vaqt UTC da, vaqt zonasisiz saqlanadi."""
    return datetime.now(timezone.utc).replace(tzinfo=None)


class Base(DeclarativeBase):
    pass


class Site(Base):
    __tablename__ = "sites"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    slug: Mapped[str] = mapped_column(String(32), unique=True, index=True)
    owner_id: Mapped[int] = mapped_column(BigInteger, index=True)
    owner_name: Mapped[str] = mapped_column(String(128), default="")
    category: Mapped[str] = mapped_column(String(32))
    config: Mapped[dict] = mapped_column(JSON)
    # draft -> pending (to'lov tekshirilmoqda) -> paid
    status: Mapped[str] = mapped_column(String(16), default="draft")
    # site — interaktiv sayt, video — video taklifnoma tadbiri
    kind: Mapped[str] = mapped_column(String(8), default="site")
    edits_used: Mapped[int] = mapped_column(Integer, default=0)
    views: Mapped[int] = mapped_column(Integer, default=0)
    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())

    @property
    def paid(self) -> bool:
        return self.status == "paid"

    @property
    def url(self) -> str:
        return f"{settings.base_url}/s/{self.slug}"


class Rsvp(Base):
    __tablename__ = "rsvps"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    site_id: Mapped[int] = mapped_column(ForeignKey("sites.id"), index=True)
    name: Mapped[str] = mapped_column(String(128))
    attending: Mapped[bool]
    guests: Mapped[int] = mapped_column(Integer, default=1)
    note: Mapped[str] = mapped_column(Text, default="")
    guest_id: Mapped[int | None] = mapped_column(Integer, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())


class Person(Base):
    """«Yaqinlarim» kalendaridagi muhim sana."""
    __tablename__ = "people"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    owner_id: Mapped[int] = mapped_column(BigInteger, index=True)
    name: Mapped[str] = mapped_column(String(100))
    kind: Mapped[str] = mapped_column(String(16))  # birthday | anniversary | other
    title: Mapped[str] = mapped_column(String(100), default="")  # «boshqa» sana uchun nomi
    day: Mapped[int] = mapped_column(Integer)
    month: Mapped[int] = mapped_column(Integer)
    year: Mapped[int | None] = mapped_column(Integer, nullable=True)
    relation: Mapped[str] = mapped_column(String(16), default="")  # ona, sevgili, dost... (catalog.RELATIONS)
    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())


class ReminderLog(Base):
    """Bir eslatma ikki marta yuborilmasligi uchun."""
    __tablename__ = "reminder_log"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    person_id: Mapped[int] = mapped_column(ForeignKey("people.id", ondelete="CASCADE"), index=True)
    occurs_on: Mapped[str] = mapped_column(String(10))  # YYYY-MM-DD
    days_before: Mapped[int] = mapped_column(Integer)


class UserProfile(Base):
    """Mini App tanishuvi: foydalanuvchi kimlarni quvontiradi."""
    __tablename__ = "user_profiles"

    tg_id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    first_name: Mapped[str] = mapped_column(String(100), default="")
    relations: Mapped[list] = mapped_column(JSON, default=list)
    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())


class Reaction(Base):
    """Tabriklangan odamning javobi: yurak va qisqa xabar."""
    __tablename__ = "reactions"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    site_id: Mapped[int] = mapped_column(ForeignKey("sites.id"), index=True)
    emoji: Mapped[str] = mapped_column(String(8))
    message: Mapped[str] = mapped_column(Text, default="")
    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())


class User(Base):
    """Bot yoki Mini App dan foydalangan har bir odam: til, balans, referal."""
    __tablename__ = "users"

    tg_id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    first_name: Mapped[str] = mapped_column(String(100), default="")
    username: Mapped[str] = mapped_column(String(64), default="")
    language_code: Mapped[str] = mapped_column(String(16), default="")
    lang: Mapped[str] = mapped_column(String(8), default="uz")  # interfeys tili (boshida o'zbekcha)
    lang_set: Mapped[bool] = mapped_column(Boolean, default=False)  # foydalanuvchi tilni o'zi tanlagan
    ref: Mapped[str] = mapped_column(String(32), default="")  # kim taklif qilgan yoki qayerdan kelgan
    balance: Mapped[int] = mapped_column(Integer, default=0)  # so'm
    bonus_videos: Mapped[int] = mapped_column(Integer, default=0)  # do'st taklif qilgani uchun
    song_credits: Mapped[int] = mapped_column(Integer, default=0)  # sotib olingan paketdagi ishlatilmagan qo'shiqlar
    blocked: Mapped[bool] = mapped_column(Boolean, default=False)  # botni bloklagan (xabar yetmaydi)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)
    last_seen: Mapped[datetime] = mapped_column(DateTime, default=utcnow)


class RenderJob(Base):
    """Video navbati: renderer servisi shu jadvaldan ish oladi."""
    __tablename__ = "render_jobs"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    owner_id: Mapped[int] = mapped_column(BigInteger, index=True)
    site_id: Mapped[int | None] = mapped_column(Integer, nullable=True, index=True)
    guest_id: Mapped[int | None] = mapped_column(Integer, nullable=True, index=True)
    design: Mapped[str] = mapped_column(String(32))
    lang: Mapped[str] = mapped_column(String(8), default="uz")
    payload: Mapped[dict] = mapped_column(JSON)
    hash: Mapped[str] = mapped_column(String(40), index=True)
    # free | bonus | paid | package
    charge: Mapped[str] = mapped_column(String(8), default="free")
    price: Mapped[int] = mapped_column(Integer, default=0)
    # awaiting_payment -> queued -> rendering -> done | failed
    status: Mapped[str] = mapped_column(String(16), default="queued", index=True)
    delivered: Mapped[bool] = mapped_column(Boolean, default=False)
    progress: Mapped[int] = mapped_column(Integer, default=0)
    file_path: Mapped[str] = mapped_column(String(255), default="")
    tg_file_id: Mapped[str] = mapped_column(String(255), default="")
    status_msg_id: Mapped[int | None] = mapped_column(BigInteger, nullable=True)
    error: Mapped[str] = mapped_column(Text, default="")
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)
    started_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    finished_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)

    @property
    def free(self) -> bool:
        return self.charge in ("free", "bonus")


class Guest(Base):
    """Tadbir mehmoni: shaxsiy havola va shaxsiy video."""
    __tablename__ = "guests"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    site_id: Mapped[int] = mapped_column(ForeignKey("sites.id"), index=True)
    name: Mapped[str] = mapped_column(String(120))
    token: Mapped[str] = mapped_column(String(32), unique=True, index=True)
    opened_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    rsvp_id: Mapped[int | None] = mapped_column(Integer, nullable=True)
    job_id: Mapped[int | None] = mapped_column(Integer, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)


class MusicTrack(Base):
    """Kuylar kutubxonasi: admin paneldan qo'shiladi."""
    __tablename__ = "music_tracks"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    title: Mapped[str] = mapped_column(String(100))
    subtitle: Mapped[str] = mapped_column(String(150), default="")
    theme: Mapped[str] = mapped_column(String(16), index=True)  # toy, osh, gap, choy, tk, sevgi, farzand, umumiy
    kind: Mapped[str] = mapped_column(String(8), default="instr")  # vocal | instr
    file: Mapped[str] = mapped_column(String(255))  # /media/music/....mp3
    start: Mapped[int] = mapped_column(Integer, default=0)  # videoga qo'yiladigan qism boshlanishi (soniya)
    author: Mapped[str] = mapped_column(String(100), default="")
    license: Mapped[str] = mapped_column(String(100), default="")
    active: Mapped[bool] = mapped_column(Boolean, default=True)
    sort: Mapped[int] = mapped_column(Integer, default=0)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)


class Payment(Base):
    """Balansni to'ldirish: chek skrinshoti admin tomonidan tasdiqlanadi."""
    __tablename__ = "payments"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    user_id: Mapped[int] = mapped_column(BigInteger, index=True)
    amount: Mapped[int] = mapped_column(Integer)
    # new (chek kutilmoqda) -> pending (admin tekshiradi) -> approved | rejected
    status: Mapped[str] = mapped_column(String(12), default="new")
    job_id: Mapped[int | None] = mapped_column(Integer, nullable=True)  # to'lovdan keyin navbatga qo'yiladigan video
    admin_id: Mapped[int | None] = mapped_column(BigInteger, nullable=True)
    receipt: Mapped[str] = mapped_column(String(255), default="")  # chek fayli (Telegram file_id), admin paneli uchun
    site_id: Mapped[int | None] = mapped_column(Integer, nullable=True)  # to'lovdan keyin balansdan to'lanadigan sayt
    song_id: Mapped[int | None] = mapped_column(Integer, nullable=True)  # to'lovdan keyin balansdan to'lanadigan qo'shiq
    pack: Mapped[int] = mapped_column(Integer, default=0)  # to'lovdan keyin sotib olinadigan qo'shiq paketi (soni)
    provider: Mapped[str] = mapped_column(String(12), default="")  # "" — eski chek, "click", "card" — karta raqamiga o'tkazma
    ext_id: Mapped[str] = mapped_column(String(40), default="")  # to'lov tizimidagi tranzaksiya raqami
    receipt_hash: Mapped[str] = mapped_column(String(64), default="", index=True)  # chek faylining sha256 (takror chek)
    purpose: Mapped[str] = mapped_column(String(8), default="")  # nima uchun: song | pack | site | video | balance (app/payflow.py)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)
    decided_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)


class BalanceTx(Base):
    """Balans harakati: + to'ldirish, - video/sayt/paket."""
    __tablename__ = "balance_tx"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    user_id: Mapped[int] = mapped_column(BigInteger, index=True)
    amount: Mapped[int] = mapped_column(Integer)
    kind: Mapped[str] = mapped_column(String(16))  # topup | video | site | package | refund
    ref: Mapped[str] = mapped_column(String(64), default="")
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)


class Event(Base):
    """Faollik hodisasi: /start bosildi, ilovaga kirdi (kuniga bir marta), reklama havolasi bosildi,
    voronka qadamlari (pay_open, pay_success... — app/track.py: event())."""
    __tablename__ = "events"
    __table_args__ = (Index("ix_events_kind_created", "kind", "created_at"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    user_id: Mapped[int | None] = mapped_column(BigInteger, nullable=True, index=True)
    kind: Mapped[str] = mapped_column(String(24), index=True)  # start | app | click | pay_open | sample_requested ...
    src: Mapped[str] = mapped_column(String(32), default="", index=True)  # start parametri, havola kodi yoki foydalanuvchi manbasi
    ref: Mapped[str] = mapped_column(String(24), default="", index=True)  # qaysi obyekt: pay:<id> | song:<id> | site:<id>
    num: Mapped[int | None] = mapped_column(Integer, nullable=True)  # son qiymat: summa (so'm), soniya, javob raqami
    meta: Mapped[dict | None] = mapped_column(JSON, nullable=True)  # qisqa qo'shimcha ma'lumot (mahsulot, usul, sabab)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow, index=True)


class TrafficLink(Base):
    """Reklama uchun trafik manbasi havolasi: t.me/<bot>?start=src_<code> va /go/<code>."""
    __tablename__ = "traffic_links"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    code: Mapped[str] = mapped_column(String(24), unique=True, index=True)
    name: Mapped[str] = mapped_column(String(100))
    note: Mapped[str] = mapped_column(String(255), default="")
    cost: Mapped[int] = mapped_column(Integer, default=0)  # reklamaga to'langan summa (so'm)
    archived: Mapped[bool] = mapped_column(Boolean, default=False)
    share: Mapped[str] = mapped_column(String(32), default="", index=True)  # hamkor hisobotining maxfiy kaliti
    share_revenue: Mapped[bool] = mapped_column(Boolean, default=False)  # eski sozlama (endi tushum doim ko'rinadi)
    share_pct: Mapped[int] = mapped_column(Integer, default=0)  # hamkor ulushi, % (hisobotda «Sizning ulushingiz»)
    created_by: Mapped[int | None] = mapped_column(BigInteger, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)


class AdSpend(Base):
    """Reklama xarajati kunma-kun (statistika TZ, 4-band): bitta havola uchun bir kunda ketgan pul, admin qo'lda kiritadi.
    Bir havola uchun bir kunda bitta yozuv — qayta kiritilsa yangilanadi (app/adstats.py). Jadval create_all bilan yaratiladi."""
    __tablename__ = "ad_spend"
    __table_args__ = (UniqueConstraint("link_id", "day", name="uq_ad_spend_link_day"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    link_id: Mapped[int] = mapped_column(ForeignKey("traffic_links.id", ondelete="CASCADE"), index=True)
    day: Mapped[str] = mapped_column(String(10), index=True)  # YYYY-MM-DD (Toshkent)
    amount: Mapped[float] = mapped_column(Float)  # kiritilgan summa, o'z valyutasida
    currency: Mapped[str] = mapped_column(String(3), default="som")  # som | usd
    rate: Mapped[int] = mapped_column(Integer, default=0)  # usd bo'lsa: kiritilgan paytdagi dollar kursi (so'm)
    som: Mapped[int] = mapped_column(BigInteger)  # so'mdagi qiymati — hamma hisob shu bilan
    created_by: Mapped[int | None] = mapped_column(BigInteger, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)


class Snapshot(Base):
    """Kunlik ko'rsatkich (masalan, kanal obunachilari soni) — o'sishni ko'rish uchun."""
    __tablename__ = "snapshots"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    day: Mapped[str] = mapped_column(String(10), index=True)  # YYYY-MM-DD (Toshkent)
    key: Mapped[str] = mapped_column(String(24))
    value: Mapped[int] = mapped_column(Integer, default=0)


class Song(Base):
    """Shaxsiy qo'shiq buyurtmasi: she'r (Claude) -> 20 s namuna -> to'lov -> to'liq qo'shiq (ElevenLabs Music)."""
    __tablename__ = "songs"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    owner_id: Mapped[int] = mapped_column(BigInteger, index=True)
    # lyrics (she'r tayyor) -> preview_queued -> preview_ready -> paid_queued -> ready | failed
    status: Mapped[str] = mapped_column(String(16), default="lyrics", index=True)
    recipient: Mapped[str] = mapped_column(String(80), default="")      # kimga (ism)
    relation: Mapped[str] = mapped_column(String(24), default="")       # sevgilim, onam, dugonam...
    occasion: Mapped[str] = mapped_column(String(24), default="")       # tug'ilgan kun, sevgi izhori...
    style: Mapped[str] = mapped_column(String(24), default="")
    voice: Mapped[str] = mapped_column(String(8), default="male")       # male | female
    answers: Mapped[dict] = mapped_column(JSON, default=dict)           # savollarga javoblar, o'z janri
    title: Mapped[str] = mapped_column(String(120), default="")
    lyrics: Mapped[str] = mapped_column(Text, default="")
    tags: Mapped[list] = mapped_column(JSON, default=list)              # inglizcha uslub teglari (ElevenLabs uchun)
    plan: Mapped[dict] = mapped_column(JSON, default=dict)              # oxirgi yuborilgan kompozitsiya rejasi
    preview: Mapped[str] = mapped_column(String(255), default="")       # /media/... 20 s namuna
    previews: Mapped[int] = mapped_column(Integer, default=0)           # nechta namuna yaratildi (bepul namunalar hisobi)
    preview_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)  # oxirgi namuna so'ralgan vaqt (kunlik limit)
    variants: Mapped[list] = mapped_column(JSON, default=list)          # [{"file": "/media/...", "private": "..."}]
    chosen: Mapped[int] = mapped_column(Integer, default=-1)
    price: Mapped[int] = mapped_column(Integer, default=0)
    paid: Mapped[bool] = mapped_column(Boolean, default=False)
    promo_until: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)  # namunadan keyingi chegirma tugash vaqti
    promo_price: Mapped[int] = mapped_column(Integer, default=0)
    promo_sent: Mapped[int] = mapped_column(Integer, default=0)  # chegirma tugashi haqida nechanchi eslatma yuborilgan
    site_slug: Mapped[str] = mapped_column(String(32), default="")      # qaysi saytga qo'yilgan
    error: Mapped[str] = mapped_column(String(255), default="")
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)


class Setting(Base):
    """Admin paneldan o'zgartiriladigan sozlama: kalit -> JSON qiymat (app/store.py)."""
    __tablename__ = "settings"

    key: Mapped[str] = mapped_column(String(40), primary_key=True)
    value: Mapped[dict] = mapped_column(JSON)
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)


class CostLog(Base):
    """Bizning tashqi xarajatimiz jurnali (app/costs.py): ElevenLabs musiqasi soniyalarda, Claude tokenlarda.
    Pul shu yerda saqlanmaydi — hisobot paytida admin kiritgan joriy narxlar bilan hisoblanadi."""
    __tablename__ = "cost_log"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    user_id: Mapped[int | None] = mapped_column(BigInteger, nullable=True, index=True)
    kind: Mapped[str] = mapped_column(String(8), index=True)      # music | ai
    purpose: Mapped[str] = mapped_column(String(24), index=True)  # song_preview | song_full | lyrics | site_text ...
    units_in: Mapped[int] = mapped_column(Integer, default=0)     # music: soniya · ai: kirish tokenlari
    units_out: Mapped[int] = mapped_column(Integer, default=0)    # ai: chiqish tokenlari
    ref: Mapped[str] = mapped_column(String(40), default="")
    model: Mapped[str] = mapped_column(String(40), default="")    # ai: qaysi model (narxi shundan hisoblanadi)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow, index=True)


class NudgeLog(Base):
    """Progrev xabari jurnali: bir qadam bir obyekt uchun bir marta yuboriladi (app/nudges.py)."""
    __tablename__ = "nudge_log"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    user_id: Mapped[int] = mapped_column(BigInteger, index=True)
    seq: Mapped[str] = mapped_column(String(12), index=True)   # site | song | new
    step: Mapped[int] = mapped_column(Integer)                 # 0, 1, 2...
    ref: Mapped[str] = mapped_column(String(24), default="")   # site:<id> | song:<id> | ""
    status: Mapped[str] = mapped_column(String(8), default="sent")  # sent | failed | skipped
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow, index=True)


async def init_db() -> None:
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
        await conn.run_sync(_add_missing_columns)
        await conn.run_sync(_widen_columns)
        await conn.run_sync(_add_missing_indexes)


# Oddiy migratsiya: create_all mavjud jadvalga yangi ustun qo'shmaydi.
# To'rtinchi qism (bo'lsa) — ustun birinchi marta qo'shilganda bir marta bajariladigan SQL.
_NEW_COLUMNS = [
    ("people", "relation", "VARCHAR(16) DEFAULT '' NOT NULL"),
    ("sites", "kind", "VARCHAR(8) DEFAULT 'site' NOT NULL"),
    ("rsvps", "guest_id", "INTEGER"),
    # til endi Telegram'dan olinmaydi: avval avtomatik qo'yilgan tillar o'zbekchaga qaytariladi
    ("users", "lang_set", "BOOLEAN DEFAULT FALSE NOT NULL", "UPDATE users SET lang = 'uz'"),
    ("payments", "receipt", "VARCHAR(255) DEFAULT '' NOT NULL"),
    ("traffic_links", "share", "VARCHAR(32) DEFAULT '' NOT NULL"),
    ("traffic_links", "share_revenue", "BOOLEAN DEFAULT FALSE NOT NULL"),
    ("traffic_links", "share_pct", "INTEGER DEFAULT 0 NOT NULL"),
    ("payments", "site_id", "INTEGER"),
    ("payments", "provider", "VARCHAR(12) DEFAULT '' NOT NULL"),
    ("payments", "ext_id", "VARCHAR(40) DEFAULT '' NOT NULL"),
    ("payments", "song_id", "INTEGER"),
    ("songs", "preview_at", "TIMESTAMP"),
    ("cost_log", "model", "VARCHAR(40) DEFAULT '' NOT NULL"),
    ("users", "song_credits", "INTEGER DEFAULT 0 NOT NULL"),
    ("payments", "pack", "INTEGER DEFAULT 0 NOT NULL"),
    ("songs", "promo_until", "TIMESTAMP"),
    ("songs", "promo_price", "INTEGER DEFAULT 0 NOT NULL"),
    ("songs", "promo_sent", "INTEGER DEFAULT 0 NOT NULL"),
    ("payments", "receipt_hash", "VARCHAR(64) DEFAULT '' NOT NULL"),
    # statistika TZ: hodisaga obyekt (ref), son (num) va qo'shimcha ma'lumot (meta)
    ("events", "ref", "VARCHAR(24) DEFAULT '' NOT NULL"),
    ("events", "num", "INTEGER"),
    ("events", "meta", "JSON"),
    # to'lov nima uchun: eski yozuvlar mavjud ustunlardan tiklanadi (aniqlab bo'lmaganlari — balans)
    ("payments", "purpose", "VARCHAR(8) DEFAULT '' NOT NULL",
     "UPDATE payments SET purpose = CASE WHEN pack > 0 THEN 'pack' WHEN song_id IS NOT NULL THEN 'song' "
     "WHEN site_id IS NOT NULL THEN 'site' WHEN job_id IS NOT NULL THEN 'video' ELSE 'balance' END"),
]

# Ustunni kengaytirish: (jadval, ustun, yangi uzunlik). Faqat PostgreSQL da kerak — SQLite VARCHAR uzunligini tekshirmaydi.
_WIDER_COLUMNS = [
    ("events", "kind", 24),  # TZ hodisa nomlari 12 belgidan uzun: sample_requested, song_form_done...
]

# Mavjud jadvalga yangi indeks: (nomi, jadval, ustunlar). create_all yangi jadvalda o'zi yaratadi.
_NEW_INDEXES = [
    ("ix_events_ref", "events", "ref"),
    ("ix_events_kind_created", "events", "kind, created_at"),
]


def _add_missing_columns(conn) -> None:
    insp = inspect(conn)
    for table, col, ddl, *after in _NEW_COLUMNS:
        if col not in {c["name"] for c in insp.get_columns(table)}:
            conn.execute(text(f"ALTER TABLE {table} ADD COLUMN {col} {ddl}"))
            for sql in after:
                conn.execute(text(sql))


def _widen_columns(conn) -> None:
    """VARCHAR ustunini uzaytiradi (qisqartirmaydi). Uzunlik yetarli bo'lsa hech narsa qilmaydi — qayta ishga tushirish xavfsiz."""
    if conn.dialect.name != "postgresql":
        return
    insp = inspect(conn)
    for table, col, size in _WIDER_COLUMNS:
        cur = next((c for c in insp.get_columns(table) if c["name"] == col), None)
        length = getattr(cur["type"], "length", None) if cur else None
        if length is not None and length < size:
            conn.execute(text(f"ALTER TABLE {table} ALTER COLUMN {col} TYPE VARCHAR({size})"))


def _add_missing_indexes(conn) -> None:
    for name, table, cols in _NEW_INDEXES:
        conn.execute(text(f"CREATE INDEX IF NOT EXISTS {name} ON {table} ({cols})"))


def new_slug() -> str:
    return secrets.token_urlsafe(6).replace("-", "a").replace("_", "b").lower()


async def get_site(session: AsyncSession, slug: str) -> Site | None:
    return (await session.execute(select(Site).where(Site.slug == slug))).scalar_one_or_none()
