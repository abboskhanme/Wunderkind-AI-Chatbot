"""Booking-day reminder (SPEC §10.1 "Reminder").

Cron at FUNNEL_REMINDER_TIME (TIMEZONE): today's `scheduled` bookings that have
no reminder yet and were created before the reminder time get
FUNNEL_REMINDER_TEXT + location. A booking made after 07:00 for the same day
just got its confirmation, so it is not reminded again.
"""
from __future__ import annotations

from datetime import datetime, time, timedelta, timezone

from loguru import logger
from sqlalchemy import select, update

from app.config import settings
from app.db import session as db_session
from app.funnel import booking, repo, slots, texts
from app.models.funnel import FunnelEntry, InterviewBooking


async def due_reminders(now: datetime) -> list[tuple[InterviewBooking, FunnelEntry]]:
    tz = texts.tz()
    today = now.astimezone(tz).date()
    day_start = datetime.combine(today, time.min, tz).astimezone(timezone.utc)
    day_end = day_start + timedelta(days=1)
    remind_at = datetime.combine(
        today, slots.parse_hhmm(settings.FUNNEL_REMINDER_TIME, time(7, 0)), tz,
    ).astimezone(timezone.utc)
    async with db_session.SessionLocal() as db:
        rows = (await db.execute(
            select(InterviewBooking, FunnelEntry)
            .join(FunnelEntry, FunnelEntry.id == InterviewBooking.entry_id)
            .where(InterviewBooking.status == "scheduled",
                   InterviewBooking.reminder_sent_at.is_(None),
                   InterviewBooking.starts_at >= day_start,
                   InterviewBooking.starts_at < day_end,
                   InterviewBooking.created_at < remind_at,
                   FunnelEntry.tg_chat_id.is_not(None))
            .order_by(InterviewBooking.starts_at)
        )).all()
    return [(b, e) for b, e in rows]


CATCH_UP_UNTIL = time(12, 0)


async def catch_up(now: datetime | None = None) -> int:
    """At startup: if the server was down at the reminder time, send today's
    reminders late — but only in the morning (a 15:00 "see you today" is noise)."""
    now = now or datetime.now(timezone.utc)
    local = now.astimezone(texts.tz()).time()
    start = slots.parse_hhmm(settings.FUNNEL_REMINDER_TIME, time(7, 0))
    if not start <= local < CATCH_UP_UNTIL:
        return 0
    try:
        return await run_reminders(now)
    except Exception as exc:  # noqa: BLE001 — a startup task must never crash
        logger.exception("Reminder catch-up failed: {}", exc)
        return 0


async def run_reminders(now: datetime | None = None) -> int:
    """Scheduler entry point. Returns the number of reminders delivered."""
    now = now or datetime.now(timezone.utc)
    sent = 0
    try:
        due = await due_reminders(now)
    except Exception as exc:  # noqa: BLE001
        logger.exception("Reminder query failed: {}", exc)
        return 0
    for item, entry in due:
        # Claim first: a second run (restart, manual trigger) never reminds twice
        async with db_session.SessionLocal() as db:
            claimed = await db.execute(
                update(InterviewBooking)
                .where(InterviewBooking.id == item.id, InterviewBooking.reminder_sent_at.is_(None))
                .values(reminder_sent_at=now))
            await db.commit()
        if claimed.rowcount != 1:
            continue
        result = await booking.send_booking_message(
            str(entry.tg_chat_id), settings.FUNNEL_REMINDER_TEXT, entry.full_name, item.starts_at)
        if result.get("sent"):
            sent += 1
        elif repo.is_blocked(result):
            await repo.set_opted_out(entry.id)
        else:
            logger.warning("Reminder not delivered to {}: {}", entry.tg_chat_id, result.get("error"))
    if sent:
        logger.info("Interview reminders sent: {}", sent)
    return sent
