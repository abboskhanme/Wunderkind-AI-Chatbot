"""Dashboard numbers (admin + operator)."""
from __future__ import annotations

from datetime import date, datetime, time, timedelta, timezone
from zoneinfo import ZoneInfo

from fastapi import APIRouter, Depends, Query
from sqlalchemy import func, select

from app.config import settings
from app.core.deps import DB, get_current_user
from app.models.lead import LEAD_STATUSES, Lead, LeadMessage
from app.services.agent_status import agent_status

router = APIRouter(prefix="/dashboard", tags=["Dashboard"],
                   dependencies=[Depends(get_current_user)])


def _tz() -> ZoneInfo:
    try:
        return ZoneInfo(settings.TIMEZONE or "Asia/Tashkent")
    except Exception:  # noqa: BLE001
        return ZoneInfo("Asia/Tashkent")


async def _count(db, stmt) -> int:
    return int((await db.execute(stmt)).scalar() or 0)


@router.get("")
async def dashboard(db: DB, days: int = Query(7, ge=1, le=365)):
    tz = _tz()
    today = datetime.now(tz).date()
    # Bounds in UTC: portable comparison across DB backends
    today_start = datetime.combine(today, time.min, tz).astimezone(timezone.utc)
    since_local = datetime.combine(today - timedelta(days=days - 1), time.min, tz)
    since = since_local.astimezone(timezone.utc)

    def msgs(role: str, start: datetime):
        return (select(func.count()).select_from(LeadMessage)
                .where(LeadMessage.role == role, LeadMessage.created_at >= start))

    def convs(start: datetime):
        return (select(func.count(func.distinct(LeadMessage.lead_id)))
                .where(LeadMessage.role == "user", LeadMessage.created_at >= start))

    active = select(Lead).where(Lead.last_message_at >= since).subquery()
    totals = {
        "conversations": await _count(db, convs(since)),
        "messages_in": await _count(db, msgs("user", since)),
        "ai_replies": await _count(db, msgs("assistant", since)),
        "leads_with_contact": await _count(db, select(func.count()).select_from(Lead).where(
            Lead.created_at >= since, Lead.contact.is_not(None))),
        "hot": await _count(db, select(func.count()).select_from(Lead).where(
            Lead.created_at >= since, Lead.lead_score >= 85)),
        "trial": await _count(db, select(func.count()).select_from(Lead).where(
            Lead.updated_at >= since, Lead.status == "trial")),
        "enrolled": await _count(db, select(func.count()).select_from(Lead).where(
            Lead.updated_at >= since, Lead.status == "enrolled")),
    }
    today_stats = {
        "conversations": await _count(db, convs(today_start)),
        "messages_in": await _count(db, msgs("user", today_start)),
        "new_leads": await _count(db, select(func.count()).select_from(Lead).where(
            Lead.created_at >= today_start)),
        "hot": await _count(db, select(func.count()).select_from(Lead).where(
            Lead.last_message_at >= today_start, Lead.lead_score >= 85)),
    }
    by_channel = [
        {"channel": ch, "conversations": n} for ch, n in (await db.execute(
            select(active.c.channel, func.count()).group_by(active.c.channel)
        )).all()
    ]
    status_counts = dict((await db.execute(
        select(Lead.status, func.count()).where(Lead.created_at >= since).group_by(Lead.status)
    )).all())
    by_status = [{"status": s, "count": int(status_counts.get(s, 0))} for s in LEAD_STATUSES]

    # Per-day series, bucketed in Python (portable across DBs, small volumes)
    day_convs: dict[date, set] = {}
    for lead_id, at in (await db.execute(
        select(LeadMessage.lead_id, LeadMessage.created_at)
        .where(LeadMessage.role == "user", LeadMessage.created_at >= since)
    )).all():
        day_convs.setdefault(_local_day(at, tz), set()).add(lead_id)
    day_leads: dict[date, int] = {}
    for (at,) in (await db.execute(
        select(Lead.created_at).where(Lead.created_at >= since)
    )).all():
        d = _local_day(at, tz)
        day_leads[d] = day_leads.get(d, 0) + 1
    by_day = []
    for i in range(days):
        d = since_local.date() + timedelta(days=i)
        by_day.append({"date": d.isoformat(), "conversations": len(day_convs.get(d, ())),
                       "leads": day_leads.get(d, 0)})

    top = (await db.execute(
        select(Lead.course_interest, func.count().label("n"))
        .where(Lead.created_at >= since, Lead.course_interest.is_not(None))
        .group_by(Lead.course_interest).order_by(func.count().desc()).limit(8)
    )).all()

    return {
        "totals": totals,
        "today": today_stats,
        "by_channel": by_channel,
        "by_status": by_status,
        "by_day": by_day,
        "top_courses": [{"course": c, "count": n} for c, n in top],
        "status": await agent_status(),
    }


def _local_day(at: datetime, tz: ZoneInfo) -> date:
    if at.tzinfo is None:
        at = at.replace(tzinfo=ZoneInfo("UTC"))
    return at.astimezone(tz).date()
