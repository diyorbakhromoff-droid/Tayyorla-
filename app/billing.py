"""Foydalanuvchilar, kunlik bepul videolar, balans va mehmon paketlari."""

from datetime import datetime, time, timezone

from sqlalchemy import func, select, update
from sqlalchemy.ext.asyncio import AsyncSession

from .config import settings
from .db import BalanceTx, RenderJob, User, utcnow
from .reminders import TZ


def day_start_utc(now: datetime | None = None) -> datetime:
    """Toshkent vaqti bo'yicha bugungi kun boshi (bazadagi UTC ko'rinishida)."""
    local = (now or datetime.now(TZ)).astimezone(TZ)
    start = datetime.combine(local.date(), time(0), TZ)
    return start.astimezone(timezone.utc).replace(tzinfo=None)


async def touch_user(s: AsyncSession, uid: int, first_name: str = "", username: str = "",
                     language_code: str = "", ref: str = "") -> tuple[User, bool]:
    """Foydalanuvchini yozadi yoki yangilaydi. (user, yangimi) qaytaradi."""
    user = await s.get(User, uid)
    if user is None:
        user = User(tg_id=uid, first_name=(first_name or "")[:100], username=(username or "")[:64],
                    language_code=(language_code or "")[:16], ref=(ref or "")[:32])
        s.add(user)
        await s.flush()
        return user, True
    if first_name:
        user.first_name = first_name[:100]
    if username:
        user.username = username[:64]
    if language_code:
        user.language_code = language_code[:16]
    user.last_seen = utcnow()
    user.blocked = False
    return user, False


async def apply_referral(s: AsyncSession, user: User, code: str) -> int | None:
    """Yangi foydalanuvchi «ref_<id>» havolasi bilan kelsa, taklif qilganga +1 bepul video beriladi."""
    if not code or not code.startswith("ref_") or not code[4:].isdigit():
        return None
    inviter_id = int(code[4:])
    if inviter_id == user.tg_id:
        return None
    inviter = await s.get(User, inviter_id)
    if not inviter:
        return None
    user.ref = code[:32]
    inviter.bonus_videos += 1
    return inviter_id


async def free_used_today(s: AsyncSession, uid: int) -> int:
    return await s.scalar(
        select(func.count()).select_from(RenderJob).where(
            RenderJob.owner_id == uid, RenderJob.charge == "free", RenderJob.created_at >= day_start_utc()))


async def quota(s: AsyncSession, user: User) -> dict:
    used = await free_used_today(s, user.tg_id)
    return {
        "free_left": max(0, settings.free_videos_per_day - used),
        "free_per_day": settings.free_videos_per_day,
        "bonus": user.bonus_videos,
        "balance": user.balance,
        "price": settings.video_price,
    }


async def spend(s: AsyncSession, uid: int, amount: int, kind: str, ref: str = "") -> bool:
    """Balansdan yechadi. Yetmasa False (bir vaqtdagi ikki so'rovda ham manfiyga tushmaydi)."""
    if amount <= 0:
        return True
    res = await s.execute(
        update(User).where(User.tg_id == uid, User.balance >= amount)
        .values(balance=User.balance - amount).execution_options(synchronize_session="fetch"))
    if res.rowcount != 1:
        return False
    s.add(BalanceTx(user_id=uid, amount=-amount, kind=kind, ref=ref[:64]))
    return True


async def credit(s: AsyncSession, uid: int, amount: int, kind: str, ref: str = "") -> None:
    await s.execute(
        update(User).where(User.tg_id == uid)
        .values(balance=User.balance + amount).execution_options(synchronize_session="fetch"))
    s.add(BalanceTx(user_id=uid, amount=amount, kind=kind, ref=ref[:64]))


async def take_video_charge(s: AsyncSession, user: User, ref: str = "") -> tuple[str, int] | None:
    """Video uchun to'lov turini tanlaydi: bugungi bepul, bonus, keyin balans. Hech biri bo'lmasa None."""
    q = await quota(s, user)
    if q["free_left"] > 0:
        return "free", 0
    if user.bonus_videos > 0:
        user.bonus_videos -= 1
        return "bonus", 0
    if await spend(s, user.tg_id, settings.video_price, "video", ref):
        return "paid", settings.video_price
    return None


async def refund_job(s: AsyncSession, job: RenderJob) -> None:
    """Video tayyorlanmasa to'lovni qaytaradi (bepul videolar kvotadan ham chiqariladi)."""
    if job.charge == "paid" and job.price:
        await credit(s, job.owner_id, job.price, "refund", f"job:{job.id}")
    elif job.charge == "bonus":
        await s.execute(update(User).where(User.tg_id == job.owner_id).values(bonus_videos=User.bonus_videos + 1))
    job.charge = "refunded"


def package_for(n: int) -> tuple[int, int] | None:
    """n ta mehmonga yetadigan eng kichik paket: (mehmonlar soni, narx)."""
    for size, price in settings.packages:
        if n <= size:
            return size, price
    return None


def package_cost(n: int, paid_before: int = 0) -> tuple[int, int] | None:
    """Paket va to'lanadigan farq (oldin kichikroq paket olingan bo'lsa)."""
    pkg = package_for(n)
    if not pkg:
        return None
    return pkg[0], max(0, pkg[1] - paid_before)
