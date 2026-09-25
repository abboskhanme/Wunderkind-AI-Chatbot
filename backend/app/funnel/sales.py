"""Per-minute funnel job (SPEC §10.1 "PDF", "Sales sequence").

1. Entries stuck in `pdf_pending` get the PDF once one is uploaded.
2. Sales sequence: for every entry that got the PDF, the first undelivered
   active message of ITS funnel whose delay has passed — at most one per entry
   per run, only 09:00–21:00 local, never once the person has an interview
   (scheduled/attended, from any funnel) or sent /stop.

A delivery row is inserted BEFORE sending (unique entry+message), so a crash
or a parallel run can never send the same message twice; a transient send
error removes the row again so the next run retries.
"""
from __future__ import annotations

import re
from datetime import datetime, time, timedelta, timezone

from loguru import logger
from sqlalchemy import and_, delete, exists, or_, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import aliased

from app.config import settings
from app.db import session as db_session
from app.funnel import delivery, funnels, locks, repo, texts
from app.models.funnel import (
    LEAD_MAGNET_KEY, FunnelDelivery, FunnelEntry, FunnelFile, FunnelMessage, InterviewBooking,
)
from app.telegram_business.client import telegram

SEND_FROM = time(9, 0)
SEND_UNTIL = time(21, 0)
# A message overdue by more than this is skipped: a message added today must not
# blast everyone who got the PDF months ago.
STALE_AFTER = timedelta(days=3)
BATCH = 100
_STOP_STATUSES = ("scheduled", "attended")
# Seeded texts contain "[raqam]" / "[imtiyoz …]" for the client to fill in —
# never send them to a customer, even if someone switches the message on.
_UNFILLED = re.compile(r"\[(raqam|imtiyoz)[^\]]*\]", re.IGNORECASE)


def has_placeholders(text: str) -> bool:
    return bool(_UNFILLED.search(text or ""))


async def run_minutely() -> None:
    """Scheduler entry point (every minute)."""
    if not telegram.enabled:
        return
    try:
        await deliver_pending_pdfs()
    except Exception as exc:  # noqa: BLE001
        logger.exception("Pending PDF delivery failed: {}", exc)
    try:
        await run_sales()
    except Exception as exc:  # noqa: BLE001
        logger.exception("Sales sequence run failed: {}", exc)


async def deliver_pending_pdfs(limit: int = 50, now: datetime | None = None) -> int:
    """PDF for everyone waiting: after an upload, or a failed send whose backoff
    (`pdf_retry_at`) has passed."""
    now = now or datetime.now(timezone.utc)
    has_pdf = exists().where(FunnelFile.funnel_id == FunnelEntry.funnel_id,
                             FunnelFile.key == LEAD_MAGNET_KEY)
    async with db_session.SessionLocal() as db:
        rows = (await db.execute(
            select(FunnelEntry.id, FunnelEntry.tg_user_id)
            .where(FunnelEntry.step == "pdf_pending", FunnelEntry.opted_out.is_(False),
                   FunnelEntry.tg_chat_id.is_not(None), has_pdf,
                   or_(FunnelEntry.pdf_retry_at.is_(None), FunnelEntry.pdf_retry_at <= now))
            .order_by(FunnelEntry.updated_at).limit(limit)
        )).all()
    sent = 0
    for entry_id, tg_user_id in rows:
        async with locks.lock(f"tg:{tg_user_id}"):
            async with db_session.SessionLocal() as db:
                entry = await db.get(FunnelEntry, entry_id)
                still_pending = entry is not None and entry.step == "pdf_pending"
            if still_pending and await delivery.deliver_pdf(entry_id, notify=False) == "sent":
                sent += 1
    if sent:
        logger.info("Pending lead-magnet PDFs delivered: {}", sent)
    return sent


def in_send_window(now: datetime) -> bool:
    local = now.astimezone(texts.tz()).time()
    return SEND_FROM <= local < SEND_UNTIL


async def due_messages(now: datetime) -> list[tuple[FunnelEntry, FunnelMessage]]:
    """(entry, message) pairs to send now — the first due, undelivered one per entry."""
    async with db_session.SessionLocal() as db:
        messages = [m for m in (await db.execute(
            select(FunnelMessage).where(FunnelMessage.is_active.is_(True))
            .order_by(FunnelMessage.sort_order, FunnelMessage.created_at)
        )).scalars().all() if not has_placeholders(m.text)]
        if not messages:
            return []

        def due_window(m: FunnelMessage):
            send_at_latest = now - timedelta(minutes=m.delay_minutes)
            return and_(FunnelEntry.pdf_sent_at <= send_at_latest,
                        FunnelEntry.pdf_sent_at > send_at_latest - STALE_AFTER)

        def undelivered(m: FunnelMessage):
            return ~exists().where(FunnelDelivery.entry_id == FunnelEntry.id,
                                   FunnelDelivery.message_id == m.id)

        # The person has an interview through any of their funnel entries
        sibling = aliased(FunnelEntry)
        stopped = exists().where(InterviewBooking.entry_id == sibling.id,
                                 sibling.tg_user_id == FunnelEntry.tg_user_id,
                                 InterviewBooking.status.in_(_STOP_STATUSES))
        entries = list((await db.execute(
            select(FunnelEntry).where(
                FunnelEntry.step == "pdf_sent",
                FunnelEntry.pdf_sent_at.is_not(None),
                FunnelEntry.opted_out.is_(False),
                FunnelEntry.tg_chat_id.is_not(None),
                ~stopped,
                or_(*[and_(FunnelEntry.funnel_id == m.funnel_id, due_window(m), undelivered(m))
                      for m in messages]),
            ).order_by(FunnelEntry.pdf_sent_at).limit(BATCH)
        )).scalars().all())
        if not entries:
            return []
        delivered = {(e, m) for e, m in (await db.execute(
            select(FunnelDelivery.entry_id, FunnelDelivery.message_id)
            .where(FunnelDelivery.entry_id.in_([e.id for e in entries]))
        )).all()}

    out: list[tuple[FunnelEntry, FunnelMessage]] = []
    for entry in entries:
        sent_at = _aware(entry.pdf_sent_at)
        for message in (m for m in messages if m.funnel_id == entry.funnel_id):
            due_at = sent_at + timedelta(minutes=message.delay_minutes)
            if (entry.id, message.id) in delivered or due_at > now or now - due_at >= STALE_AFTER:
                continue
            out.append((entry, message))
            break
    return out


async def run_sales(now: datetime | None = None) -> int:
    """Send due sales messages. Returns how many were delivered."""
    now = now or datetime.now(timezone.utc)
    if not settings.FUNNEL_ENABLED or not in_send_window(now):
        return 0
    sent = 0
    by_id = {f.id: f for f in await funnels.load_all()}
    for entry, message in await due_messages(now):
        if not await _claim(entry, message, now):
            continue
        result = await delivery.send_sales_message(str(entry.tg_chat_id), message,
                                                   by_id.get(entry.funnel_id))
        if result.get("sent"):
            sent += 1
            continue
        if repo.is_blocked(result):
            await repo.set_opted_out(entry.id)   # the claim stays: never retried
        else:
            await _release(entry, message)
            logger.warning("Sales message {} not sent to {}: {}", message.id,
                           entry.tg_chat_id, result.get("error"))
    if sent:
        logger.info("Funnel sales messages sent: {}", sent)
    return sent


async def _claim(entry: FunnelEntry, message: FunnelMessage, now: datetime) -> bool:
    try:
        async with db_session.SessionLocal() as db:
            db.add(FunnelDelivery(entry_id=entry.id, message_id=message.id, sent_at=now))
            await db.commit()
        return True
    except IntegrityError:
        return False      # delivered by a parallel run


async def _release(entry: FunnelEntry, message: FunnelMessage) -> None:
    async with db_session.SessionLocal() as db:
        await db.execute(delete(FunnelDelivery).where(
            FunnelDelivery.entry_id == entry.id, FunnelDelivery.message_id == message.id))
        await db.commit()


def _aware(dt: datetime) -> datetime:
    return dt if dt.tzinfo else dt.replace(tzinfo=timezone.utc)
