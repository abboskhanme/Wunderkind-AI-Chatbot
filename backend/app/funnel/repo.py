"""Funnel DB helpers shared by the Instagram and Telegram sides.

Sessions are kept short on purpose: network calls (Instagram is throttled to
~1 request/second) must never hold a pooled DB connection, or a viral post
would exhaust the pool. Callers load → mutate → commit, then talk to the APIs.
"""
from __future__ import annotations

import secrets
import uuid
from datetime import datetime, timezone
from typing import Optional

from loguru import logger
from sqlalchemy import delete, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import settings
from app.funnel import texts
from app.leads import client as leads_client
from app.models.funnel import (
    COLLECTION_STEPS, START_TOKEN_LENGTH, FunnelDelivery, FunnelEntry, InterviewBooking,
)
from app.models.lead import CLOSED_STATUSES, STATUS_LABELS, Lead, LeadMessage

LEAD_SCORE_PDF = 60
LEAD_SCORE_BOOKED = 90


def now() -> datetime:
    return datetime.now(timezone.utc)


def new_token() -> str:
    """12 url-safe characters for t.me/<bot>?start=<token>."""
    return secrets.token_urlsafe(9)[:START_TOKEN_LENGTH]


def touch(entry: FunnelEntry) -> None:
    """Mark changed: bumps updated_at (the Sheets outbox compares it) and queues a sync."""
    entry.sheet_dirty = True
    entry.updated_at = now()


# --- Telegram person -> entries (one per funnel, SPEC §11.1) ---------------------
async def entry_by_tg(db: AsyncSession, tg_user_id: str,
                      funnel_id: Optional[uuid.UUID] = None) -> Optional[FunnelEntry]:
    """With `funnel_id`: the person's entry in that funnel. Without: the person's
    most recently touched entry in any funnel."""
    q = select(FunnelEntry).where(FunnelEntry.tg_user_id == str(tg_user_id))
    if funnel_id is not None:
        q = q.where(FunnelEntry.funnel_id == funnel_id)
    return (await db.execute(q.order_by(FunnelEntry.updated_at.desc()).limit(1))
            ).scalar_one_or_none()


async def entries_by_tg(db: AsyncSession, tg_user_id: str) -> list[FunnelEntry]:
    return list((await db.execute(
        select(FunnelEntry).where(FunnelEntry.tg_user_id == str(tg_user_id))
        .order_by(FunnelEntry.updated_at.desc())
    )).scalars().all())


async def current_entry(db: AsyncSession, tg_user_id: str) -> Optional[FunnelEntry]:
    """The entry whose questions the person is answering: the most recently
    touched one in a collection step (§11.2)."""
    return (await db.execute(
        select(FunnelEntry).where(FunnelEntry.tg_user_id == str(tg_user_id),
                                  FunnelEntry.step.in_(COLLECTION_STEPS))
        .order_by(FunnelEntry.updated_at.desc()).limit(1)
    )).scalar_one_or_none()


async def person_booking(db: AsyncSession,
                         tg_user_id: str) -> Optional[InterviewBooking]:
    """The person's one `scheduled` interview, whichever funnel booked it."""
    return (await db.execute(
        select(InterviewBooking).join(FunnelEntry, FunnelEntry.id == InterviewBooking.entry_id)
        .where(FunnelEntry.tg_user_id == str(tg_user_id),
               InterviewBooking.status == "scheduled")
        .order_by(InterviewBooking.created_at.desc()).limit(1)
    )).scalar_one_or_none()


async def booking_entry(db: AsyncSession, tg_user_id: str) -> Optional[FunnelEntry]:
    """The entry booking buttons act on (callbacks carry no funnel): the one with
    the scheduled interview, else the latest to receive a PDF, else the latest."""
    booking = await person_booking(db, tg_user_id)
    if booking is not None:
        return await db.get(FunnelEntry, booking.entry_id)
    got_pdf = (await db.execute(
        select(FunnelEntry).where(FunnelEntry.tg_user_id == str(tg_user_id),
                                  FunnelEntry.pdf_sent_at.is_not(None))
        .order_by(FunnelEntry.pdf_sent_at.desc()).limit(1)
    )).scalar_one_or_none()
    return got_pdf or await entry_by_tg(db, tg_user_id)


async def prefill_contact(db: AsyncSession, entry: FunnelEntry) -> None:
    """A person entering another funnel is not asked their name/phone again."""
    if entry.full_name and entry.phone or not entry.tg_user_id:
        return
    for other in await entries_by_tg(db, entry.tg_user_id):
        if other.id == entry.id:
            continue
        entry.full_name = entry.full_name or other.full_name
        entry.phone = entry.phone or other.phone
        if entry.full_name and entry.phone:
            return


async def entry_by_token(db: AsyncSession, token: str) -> Optional[FunnelEntry]:
    return (await db.execute(
        select(FunnelEntry).where(FunnelEntry.start_token == token)
    )).scalar_one_or_none()


# --- Instagram person -> entries ----------------------------------------------------
async def entry_by_ig(db: AsyncSession, ig_user_id: str,
                      funnel_id: Optional[uuid.UUID] = None) -> Optional[FunnelEntry]:
    """The person's entry (in `funnel_id`, or the newest in any funnel)."""
    q = select(FunnelEntry).where(FunnelEntry.ig_user_id == str(ig_user_id))
    if funnel_id is not None:
        q = q.where(FunnelEntry.funnel_id == funnel_id)
    return (await db.execute(q.order_by(FunnelEntry.updated_at.desc()).limit(1))
            ).scalar_one_or_none()


async def active_booking(db: AsyncSession, entry_id: uuid.UUID) -> Optional[InterviewBooking]:
    return (await db.execute(
        select(InterviewBooking).where(InterviewBooking.entry_id == entry_id,
                                       InterviewBooking.status == "scheduled")
    )).scalar_one_or_none()


async def latest_bookings(db: AsyncSession,
                          entry_ids: list[uuid.UUID]) -> dict[uuid.UUID, InterviewBooking]:
    """Newest booking per entry (reschedules create new rows) — one query for a page."""
    if not entry_ids:
        return {}
    rows = (await db.execute(
        select(InterviewBooking).where(InterviewBooking.entry_id.in_(entry_ids))
        .order_by(InterviewBooking.created_at)
    )).scalars().all()
    return {b.entry_id: b for b in rows}


async def merge_into(db: AsyncSession, ig_entry: FunnelEntry, tg_entry: FunnelEntry) -> None:
    """A Telegram user who already has an entry opened an Instagram link:
    copy the Instagram data onto the Telegram entry and drop the IG-only entry."""
    for field in ("ig_user_id", "ig_username", "ig_comment_id", "followed_at",
                  "link_sent_at"):
        if getattr(ig_entry, field) and not getattr(tg_entry, field):
            setattr(tg_entry, field, getattr(ig_entry, field))
    tg_entry.follow_checks = max(tg_entry.follow_checks or 0, ig_entry.follow_checks or 0)
    # A bare /start is the weakest attribution; the Instagram campaign wins over it
    if tg_entry.source == "telegram_direct":
        tg_entry.source = "instagram"
    # Its sheet row is taken over (or marked "Birlashtirildi") on the next sync
    tg_entry.sheet_merged_id = ig_entry.id
    # Explicit child cleanup: SQLite (tests) does not enforce ON DELETE CASCADE
    await db.execute(delete(FunnelDelivery).where(FunnelDelivery.entry_id == ig_entry.id))
    await db.execute(delete(InterviewBooking).where(InterviewBooking.entry_id == ig_entry.id))
    await db.delete(ig_entry)
    await db.flush()
    touch(tg_entry)
    logger.info("Funnel entry merged: IG {} -> TG {}", ig_entry.ig_user_id, tg_entry.tg_user_id)


def lead_source(entry: FunnelEntry) -> str:
    return "lead_magnet_instagram" if entry.source == "instagram" else "lead_magnet_telegram"


async def ensure_lead(db: AsyncSession, entry: FunnelEntry) -> Lead:
    """The open Telegram lead of this entry, filled with the funnel facts."""
    lead = await db.get(Lead, entry.lead_id) if entry.lead_id else None
    if lead is None or lead.status in CLOSED_STATUSES:
        lead = await leads_client.open_lead(
            db, channel="telegram", user_id=str(entry.tg_user_id), username=entry.tg_username,
            source=lead_source(entry))
        assert lead is not None
    lead.source = lead_source(entry)
    if entry.full_name:
        lead.name = entry.full_name
    if entry.phone:
        lead.contact = entry.phone
    if entry.grade:
        lead.student_age = texts.grade_display(entry.grade)[:64]
    if entry.tg_username and not lead.username:
        lead.username = entry.tg_username
    entry.lead_id = lead.id
    return lead


def log_system(db: AsyncSession, lead: Lead, text: str, **meta: object) -> None:
    """Funnel step line in the lead's thread. kind "status": shown in the panel,
    but not part of the conversation — the AI history and the first-message
    disclosure check (fetch_context: dm/comment only) never see it."""
    at = now()
    db.add(LeadMessage(lead_id=lead.id, kind="status", role="system", text=text,
                       meta={"funnel": True, **meta}, created_at=at))
    lead.last_message_at = at


def log_status(db: AsyncSession, lead: Lead, new_status: str) -> None:
    """Status change line, same shape as the panel writes (app.api.leads)."""
    old = lead.status
    if old == new_status:
        return
    db.add(LeadMessage(
        lead_id=lead.id, kind="status", role="system", created_at=now(),
        text=f"Holat: {STATUS_LABELS.get(old, old)} → {STATUS_LABELS.get(new_status, new_status)}",
        meta={"by_name": "Voronka", "from": old, "to": new_status, "funnel": True},
    ))
    lead.status = new_status


async def bot_link(payload: str) -> Optional[str]:
    """https://t.me/<bot>?start=<payload>, or None while the bot is not configured."""
    from app.services.agent_status import telegram_bot_username

    username = await telegram_bot_username()
    return f"https://t.me/{username}?start={payload}" if username else None


async def ig_link(payload: str) -> Optional[str]:
    """Link for Instagram DMs: our `/go/<payload>` page (Instagram's in-app
    browser blocks t.me → Telegram app), or plain t.me without a public URL."""
    direct = await bot_link(payload)
    if direct and settings.PUBLIC_URL:
        return f"{settings.PUBLIC_URL.rstrip('/')}/go/{payload}"
    return direct


def is_blocked(result: dict) -> bool:
    """Telegram refused because the person blocked the bot / deleted the account."""
    error = str(result.get("error") or "").lower()
    return "forbidden" in error or "blocked" in error or "deactivated" in error


async def set_opted_out(entry_id: uuid.UUID) -> None:
    from app.db import session as db_session

    async with db_session.SessionLocal() as db:
        entry = await db.get(FunnelEntry, entry_id)
        if entry and not entry.opted_out:
            entry.opted_out = True
            await db.commit()
            logger.info("Funnel entry {} opted out (bot blocked)", entry_id)
