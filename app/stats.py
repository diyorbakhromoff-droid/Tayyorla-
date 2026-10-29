"""Admin statistikasi: bot /stats va Mini App admin paneli uchun."""

from collections import Counter
from datetime import timedelta

from sqlalchemy import func, select

from .billing import day_start_utc
from .catalog import TEMPLATES, site_price
from .db import Payment, RenderJob, Session, Site, User


async def summary() -> dict:
    today = day_start_utc()
    week = today - timedelta(days=6)
    async with Session() as s:
        count = lambda model, *where: s.scalar(select(func.count()).select_from(model).where(*where))  # noqa: E731
        users = {"total": await count(User), "today": await count(User, User.created_at >= today),
                 "week": await count(User, User.created_at >= week)}
        jobs = (await s.execute(select(RenderJob.charge, RenderJob.status, RenderJob.created_at, RenderJob.payload["page"]["section"].as_string(),
                                       RenderJob.owner_id, RenderJob.guest_id)
                                .where(RenderJob.created_at >= today - timedelta(days=30)))).all()
        sites = (await s.execute(select(Site.config, Site.status, Site.created_at, Site.kind))).all()
        approved = (await s.execute(select(Payment.amount, Payment.decided_at).where(Payment.status == "approved"))).all()
        payers = set((await s.execute(select(Payment.user_id).where(Payment.status == "approved"))).scalars().all())
        video_users = set((await s.execute(select(RenderJob.owner_id).where(RenderJob.status == "done"))).scalars().all())
        queue = {"queued": await count(RenderJob, RenderJob.status == "queued"),
                 "rendering": await count(RenderJob, RenderJob.status == "rendering"),
                 "failed_today": await count(RenderJob, RenderJob.status == "failed", RenderJob.created_at >= today)}
    done = [j for j in jobs if j[1] == "done"]
    videos = {
        "today": sum(1 for j in done if j[2] >= today and j[5] is None),
        "week": sum(1 for j in done if j[2] >= week and j[5] is None),
        "guest_today": sum(1 for j in done if j[2] >= today and j[5] is not None),
        "by_charge": dict(Counter(j[0] for j in done if j[5] is None)),
        "by_section": dict(Counter(j[3] or "?" for j in done if j[5] is None)),
    }
    real_sites = [x for x in sites if x[3] == "site"]
    site_sections = Counter(TEMPLATES.get(c.get("template"), {}).get("section", c.get("category", "?")) for c, *_ in real_sites)
    paid_sites = [c for c, st, *_ in real_sites if st == "paid"]
    sites_out = {"total": len(real_sites), "today": sum(1 for x in real_sites if x[2] and x[2] >= today),
                 "paid": len(paid_sites), "by_section": dict(site_sections)}
    revenue = {"topups_total": sum(a for a, _ in approved), "topups_today": sum(a for a, d in approved if d and d >= today),
               "sites_total": sum(site_price(c) for c in paid_sites)}
    conv = round(100 * len(payers & video_users) / len(video_users), 1) if video_users else 0.0
    return {"users": users, "videos": videos, "sites": sites_out, "revenue": revenue, "queue": queue,
            "video_to_paid_pct": conv}
