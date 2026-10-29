import secrets
from datetime import datetime, timezone

from sqlalchemy import JSON, BigInteger, Boolean, DateTime, ForeignKey, Integer, String, Text, func, inspect, select, text
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
    lang: Mapped[str] = mapped_column(String(8), default="")  # tanlangan interfeys tili
    ref: Mapped[str] = mapped_column(String(32), default="")  # kim taklif qilgan yoki qayerdan kelgan
    balance: Mapped[int] = mapped_column(Integer, default=0)  # so'm
    bonus_videos: Mapped[int] = mapped_column(Integer, default=0)  # do'st taklif qilgani uchun
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


async def init_db() -> None:
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
        await conn.run_sync(_add_missing_columns)


# Oddiy migratsiya: create_all mavjud jadvalga yangi ustun qo'shmaydi
_NEW_COLUMNS = [
    ("people", "relation", "VARCHAR(16) DEFAULT '' NOT NULL"),
    ("sites", "kind", "VARCHAR(8) DEFAULT 'site' NOT NULL"),
    ("rsvps", "guest_id", "INTEGER"),
]


def _add_missing_columns(conn) -> None:
    insp = inspect(conn)
    for table, col, ddl in _NEW_COLUMNS:
        if col not in {c["name"] for c in insp.get_columns(table)}:
            conn.execute(text(f"ALTER TABLE {table} ADD COLUMN {col} {ddl}"))


def new_slug() -> str:
    return secrets.token_urlsafe(6).replace("-", "a").replace("_", "b").lower()


async def get_site(session: AsyncSession, slug: str) -> Site | None:
    return (await session.execute(select(Site).where(Site.slug == slug))).scalar_one_or_none()
