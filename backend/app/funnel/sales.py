"""Per-minute funnel job (SPEC §10.1 "PDF", "Sales sequence").

1. Entries stuck in `pdf_pending` get the PDF once one is uploaded.
2. Sales sequence: for every entry that got the PDF, the first undelivered
   active message of ITS funnel whose delay has passed — at most one per entry
   per run, only 09:00–21:00 local, never once the person has an interview
   (scheduled/attended, from any funnel) or sent /stop.
   A message's delay counts from (SPEC §14): the PDF (condition "none"), the
   first click on the named button ("clicked"), or the delivery of the source
   message when that button was not clicked ("not_clicked").
3. Instant follow-ups: a new click sends the "clicked" messages with delay 0 of
   that button right away (any hour — the person just acted), same stop rules.

A delivery row is inserted BEFORE sending (unique entry+message), so a crash
or a parallel run can never send the same message twice; a transient send
error removes the row again so the next run retries.
"""
from __future__ import annotations

import re
import uuid
from datetime import datetime, time, timedelta, timezone
from typing import Optional

from loguru import logger
from sqlalchemy import and_, delete, exists, func, or_, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import aliased

from app.config import settings
from app.db import session as db_session
from app.funnel import delivery, funnels, locks, repo, texts
from app.funnel.funnels import FunnelView
from app.models.funnel import (
    LEAD_MAGNET_KEY, FunnelButtonClick, FunnelDelivery, FunnelEntry, FunnelFile, FunnelMessage,
    FunnelMessageButton, InterviewBooking,
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


def _click_match(m: FunnelMessage):
    """Clicks that satisfy m's condition: its button, or any button of the source."""
    if m.condition_button_id is not None:
        return FunnelButtonClick.button_id == m.condition_button_id
    return FunnelButtonClick.message_id == m.condition_message_id


def _matches(m: FunnelMessage, message_id: uuid.UUID, button_id: uuid.UUID) -> bool:
    if m.condition_button_id is not None:
        return button_id == m.condition_button_id
    return message_id == m.condition_message_id


def _condition_ok(m: FunnelMessage, by_id: dict[uuid.UUID, FunnelMessage]) -> bool:
    """A conditional message whose source (or button) is gone never goes out:
    "not clicked" on a deleted button would otherwise reach everyone."""
    if m.condition == "none":
        return True
    if m.condition not in ("clicked", "not_clicked"):
        return False
    source = by_id.get(m.condition_message_id) if m.condition_message_id else None
    if source is None or source.funnel_id != m.funnel_id or not source.buttons:
        return False
    return (m.condition_button_id is None
            or any(b.id == m.condition_button_id for b in source.buttons))


def _anchor(entry: FunnelEntry, m: FunnelMessage,
            sent: dict[tuple[uuid.UUID, uuid.UUID], datetime],
            clicks: dict[uuid.UUID, list[tuple[uuid.UUID, uuid.UUID, datetime]]],
            ) -> Optional[datetime]:
    """When m's delay starts for this entry; None = the condition is not met."""
    if m.condition == "clicked":
        times = [_aware(at) for message_id, button_id, at in clicks.get(entry.id, ())
                 if _matches(m, message_id, button_id)]
        return min(times) if times else None
    if m.condition == "not_clicked":
        if any(_matches(m, message_id, button_id)
               for message_id, button_id, _ in clicks.get(entry.id, ())):
            return None
        source_sent = sent.get((entry.id, m.condition_message_id))
        return _aware(source_sent) if source_sent else None
    return _aware(entry.pdf_sent_at)


async def due_messages(now: datetime) -> list[tuple[FunnelEntry, FunnelMessage]]:
    """(entry, message) pairs to send now — the first due, undelivered one per entry."""
    async with db_session.SessionLocal() as db:
        every = list((await db.execute(
            select(FunnelMessage).order_by(FunnelMessage.sort_order, FunnelMessage.created_at)
        )).scalars().all())
        by_id = {m.id: m for m in every}
        messages = [m for m in every if m.is_active and not has_placeholders(m.text)
                    and _condition_ok(m, by_id)]
        if not messages:
            return []

        def window(anchor, m: FunnelMessage):
            send_at_latest = now - timedelta(minutes=m.delay_minutes)
            return and_(anchor <= send_at_latest, anchor > send_at_latest - STALE_AFTER)

        def undelivered(m: FunnelMessage):
            return ~exists().where(FunnelDelivery.entry_id == FunnelEntry.id,
                                   FunnelDelivery.message_id == m.id)

        def due(m: FunnelMessage):
            if m.condition == "clicked":
                # The delay starts at the FIRST matching click (same as _anchor)
                first_click = (select(func.min(FunnelButtonClick.clicked_at))
                               .where(FunnelButtonClick.entry_id == FunnelEntry.id,
                                      _click_match(m)).scalar_subquery())
                met = window(first_click, m)
            elif m.condition == "not_clicked":
                met = and_(
                    exists().where(FunnelDelivery.entry_id == FunnelEntry.id,
                                   FunnelDelivery.message_id == m.condition_message_id,
                                   window(FunnelDelivery.sent_at, m)),
                    ~exists().where(FunnelButtonClick.entry_id == FunnelEntry.id,
                                    _click_match(m)))
            else:
                met = window(FunnelEntry.pdf_sent_at, m)
            return and_(FunnelEntry.funnel_id == m.funnel_id, met, undelivered(m))

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
                or_(*[due(m) for m in messages]),
            ).order_by(FunnelEntry.pdf_sent_at).limit(BATCH)
        )).scalars().all())
        if not entries:
            return []
        entry_ids = [e.id for e in entries]
        sent = {(e, m): at for e, m, at in (await db.execute(
            select(FunnelDelivery.entry_id, FunnelDelivery.message_id, FunnelDelivery.sent_at)
            .where(FunnelDelivery.entry_id.in_(entry_ids))
        )).all()}
        clicks: dict[uuid.UUID, list[tuple[uuid.UUID, uuid.UUID, datetime]]] = {}
        for e, m, b, at in (await db.execute(
            select(FunnelButtonClick.entry_id, FunnelButtonClick.message_id,
                   FunnelButtonClick.button_id, FunnelButtonClick.clicked_at)
            .where(FunnelButtonClick.entry_id.in_(entry_ids))
        )).all():
            clicks.setdefault(e, []).append((m, b, at))

    out: list[tuple[FunnelEntry, FunnelMessage]] = []
    for entry in entries:
        for message in (m for m in messages if m.funnel_id == entry.funnel_id):
            if (entry.id, message.id) in sent:
                continue
            anchor = _anchor(entry, message, sent, clicks)
            if anchor is None:
                continue
            due_at = anchor + timedelta(minutes=message.delay_minutes)
            if due_at > now or now - due_at >= STALE_AFTER:
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
        if await _deliver(entry, message, by_id.get(entry.funnel_id), now):
            sent += 1
    if sent:
        logger.info("Funnel sales messages sent: {}", sent)
    return sent


async def _deliver(entry: FunnelEntry, message: FunnelMessage,
                   funnel: Optional[FunnelView], now: datetime) -> bool:
    """Claim, send, and on failure opt out (bot blocked) or release for a retry."""
    if not await _claim(entry, message, now):
        return False
    if message.condition == "not_clicked" and await _clicked_meanwhile(entry, message):
        await _release(entry, message)       # pressed after the batch was chosen
        return False
    result = await delivery.send_sales_message(str(entry.tg_chat_id), message, funnel,
                                               entry_id=entry.id)
    if result.get("sent"):
        return True
    if repo.is_blocked(result):
        await repo.set_opted_out(entry.id)   # the claim stays: never retried
    else:
        await _release(entry, message)
        logger.warning("Sales message {} not sent to {}: {}", message.id,
                       entry.tg_chat_id, result.get("error"))
    return False


async def _clicked_meanwhile(entry: FunnelEntry, message: FunnelMessage) -> bool:
    async with db_session.SessionLocal() as db:
        return (await db.execute(
            select(FunnelButtonClick.id).where(FunnelButtonClick.entry_id == entry.id,
                                               _click_match(message)).limit(1)
        )).first() is not None


async def send_click_followups(entry_id: uuid.UUID, button: FunnelMessageButton) -> int:
    """Right after a new click: the "clicked" messages of this button (or of any
    button of its message) with delay 0, in order. Same stop rules as the
    sequence; the hour window does not apply. Returns how many were sent."""
    if not settings.FUNNEL_ENABLED:
        return 0
    now = datetime.now(timezone.utc)
    async with db_session.SessionLocal() as db:
        entry = await db.get(FunnelEntry, entry_id)
        if (entry is None or entry.opted_out or not entry.tg_chat_id
                or entry.step != "pdf_sent"):
            return 0
        if entry.tg_user_id and await _has_interview(db, entry.tg_user_id):
            return 0
        every = list((await db.execute(
            select(FunnelMessage).where(FunnelMessage.funnel_id == entry.funnel_id)
            .order_by(FunnelMessage.sort_order, FunnelMessage.created_at)
        )).scalars().all())
        delivered = set((await db.execute(
            select(FunnelDelivery.message_id).where(FunnelDelivery.entry_id == entry.id)
        )).scalars().all())
        funnel = await funnels.get(db, entry.funnel_id)
    by_id = {m.id: m for m in every}
    followups = [m for m in every
                 if m.is_active and m.condition == "clicked" and m.delay_minutes == 0
                 and m.id not in delivered and not has_placeholders(m.text)
                 and _condition_ok(m, by_id) and _matches(m, button.message_id, button.id)]
    sent = 0
    for message in followups:
        if await _deliver(entry, message, funnel, now):
            sent += 1
    return sent


async def _has_interview(db, tg_user_id: str) -> bool:
    return (await db.execute(
        select(InterviewBooking.id).join(FunnelEntry, FunnelEntry.id == InterviewBooking.entry_id)
        .where(FunnelEntry.tg_user_id == str(tg_user_id),
               InterviewBooking.status.in_(_STOP_STATUSES)).limit(1)
    )).first() is not None


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
