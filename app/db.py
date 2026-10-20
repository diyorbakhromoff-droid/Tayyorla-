import secrets
from datetime import datetime

from sqlalchemy import JSON, BigInteger, DateTime, ForeignKey, Integer, String, Text, func, select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column

from .config import settings

engine = create_async_engine(settings.database_url)
Session = async_sessionmaker(engine, expire_on_commit=False)


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
    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())


class ReminderLog(Base):
    """Bir eslatma ikki marta yuborilmasligi uchun."""
    __tablename__ = "reminder_log"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    person_id: Mapped[int] = mapped_column(ForeignKey("people.id", ondelete="CASCADE"), index=True)
    occurs_on: Mapped[str] = mapped_column(String(10))  # YYYY-MM-DD
    days_before: Mapped[int] = mapped_column(Integer)


async def init_db() -> None:
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)


def new_slug() -> str:
    return secrets.token_urlsafe(6).replace("-", "a").replace("_", "b").lower()


async def get_site(session: AsyncSession, slug: str) -> Site | None:
    return (await session.execute(select(Site).where(Site.slug == slug))).scalar_one_or_none()
