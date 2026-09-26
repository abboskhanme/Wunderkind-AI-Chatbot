"""Conversation memory and lead storage — local database.

Same function names and signatures as NUR's ERP HTTP client, so the ported
pipeline / menu / importer code is unchanged:

  push()          — upsert lead facts from an AI turn
  log_message()   — append one message to the conversation log
  fetch_context() — conversation history + known facts for the next AI turn
"""
from __future__ import annotations

from datetime import datetime, timezone
from typing import Optional

from loguru import logger
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.db import session as db_session
from app.models.lead import CHANNELS, CLOSED_STATUSES, Lead, LeadMessage
from app.models.profile import CustomerProfile
from app.models_ai import LeadPayload
from app.services.phone import extract_phone

_FACT_FIELDS = (
    "name", "contact", "course_interest", "student_age", "preferred_time",
    "language", "intent", "stage", "summary",
)


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _channel(value: str | None) -> str:
    return value if value in CHANNELS else "instagram"


def _source(source: str | None, channel: str) -> str:
    if not source or (source == "instagram" and channel != "instagram"):
        return channel
    return source


async def open_lead(
    db: AsyncSession, *, channel: str, user_id: str, username: Optional[str] = None,
    source: Optional[str] = None, create: bool = True,
) -> Optional[Lead]:
    """The person's open lead on this channel (created on demand)."""
    lead = (await db.execute(
        select(Lead)
        .where(Lead.channel == channel, Lead.external_id == user_id,
               Lead.status.notin_(CLOSED_STATUSES))
        .order_by(Lead.created_at.desc())
        .limit(1)
    )).scalar_one_or_none()
    if lead is None:
        if not create:
            return None
        lead = Lead(channel=channel, external_id=user_id, username=username,
                    source=_source(source, channel), status="new", lead_score=0, extra={})
        await _from_profile(db, lead)
        try:
            # Savepoint: a concurrent webhook may have just created the same
            # open lead (unique index uq_leads_open_per_person) — reuse it.
            async with db.begin_nested():
                db.add(lead)
        except IntegrityError:
            return await open_lead(db, channel=channel, user_id=user_id, username=username,
                                   source=source, create=False)
    elif username and not lead.username:
        lead.username = username
    return lead


async def _from_profile(db: AsyncSession, lead: Lead) -> None:
    """A new lead starts with what the account profile already knows
    (Instagram DMs carry no username; a shared Telegram phone)."""
    profile = (await db.execute(select(CustomerProfile).where(
        CustomerProfile.channel == lead.channel,
        CustomerProfile.external_id == lead.external_id,
    ))).scalar_one_or_none()
    if profile is None:
        return
    lead.username = lead.username or profile.username
    lead.contact = lead.contact or profile.phone


async def push(payload: LeadPayload) -> bool:
    """Merge AI-collected facts into the person's open lead."""
    if not payload.user_id:
        return False
    channel = _channel(payload.channel)
    try:
        async with db_session.SessionLocal() as db:
            lead = await open_lead(db, channel=channel, user_id=payload.user_id,
                                   username=payload.username, source=payload.source)
            assert lead is not None
            for field in _FACT_FIELDS:
                value = getattr(payload, field, None)
                if value:
                    setattr(lead, field, _fit(field, str(value)))
            lead.lead_score = max(lead.lead_score or 0, payload.lead_score or 0)
            if payload.extra:
                lead.extra = {**(lead.extra or {}), **payload.extra}
            await db.commit()
        return True
    except Exception as exc:  # noqa: BLE001
        logger.exception("Lead save failed: {}", exc)
        from app.telegram.notifier import notify_ingest_failed

        await notify_ingest_failed(payload)
        return False


async def log_message(
    *,
    user_id: str,
    text: str,
    role: str = "user",
    username: str | None = None,
    channel: str = "instagram",
    kind: str = "dm",
    ig_message_id: str | None = None,
    comment_id: str | None = None,
    media_id: str | None = None,
    sent_at: str | datetime | None = None,
    source: str = "instagram",
    create_lead: bool = True,
    meta: dict | None = None,
) -> bool:
    """Append one message to the conversation log. Best effort — never raises."""
    if not text or not user_id:
        return False
    channel = _channel(channel)
    try:
        async with db_session.SessionLocal() as db:
            lead = await open_lead(db, channel=channel, user_id=user_id, username=username,
                                   source=source, create=create_lead)
            if lead is None:
                await db.commit()
                return False
            if ig_message_id:
                exists = (await db.execute(
                    select(LeadMessage.id).where(
                        LeadMessage.lead_id == lead.id,
                        LeadMessage.external_message_id == ig_message_id,
                    ).limit(1)
                )).scalar_one_or_none()
                if exists:
                    await db.commit()
                    return False

            at = _parse_time(sent_at) or _now()
            db.add(LeadMessage(
                lead_id=lead.id,
                kind="comment" if kind == "comment" else "dm",
                role=role,
                text=text,
                external_message_id=ig_message_id,
                comment_id=comment_id,
                media_id=media_id,
                meta=meta or {},
                created_at=at,
            ))
            if not lead.last_message_at or at >= _aware(lead.last_message_at):
                lead.last_message_at = at
            # Reply windows (Instagram 24h/7d) are opened by DMs only, not comments
            if role == "user" and kind != "comment":
                if not lead.last_customer_at or at >= _aware(lead.last_customer_at):
                    lead.last_customer_at = at
                    # A new customer message re-arms the follow-up
                    lead.last_followup_at = None
            if role == "user" and not lead.contact:
                phone = extract_phone(text)
                if phone:
                    lead.contact = phone
            await db.commit()
        return True
    except Exception as exc:  # noqa: BLE001
        logger.warning("Message log failed: {}", exc)
        return False


async def fetch_context(
    user_id: str, limit: int = 40, *, channel: str = "instagram"
) -> dict | None:
    """History (oldest first) + known facts across all of the person's leads."""
    if not user_id:
        return None
    channel = _channel(channel)
    try:
        async with db_session.SessionLocal() as db:
            leads = (await db.execute(
                select(Lead)
                .where(Lead.channel == channel, Lead.external_id == user_id)
                .order_by(Lead.created_at)
            )).scalars().all()
            if not leads:
                return {"messages": []}
            rows = (await db.execute(
                select(LeadMessage)
                .where(LeadMessage.lead_id.in_([l.id for l in leads]),
                       LeadMessage.kind.in_(("dm", "comment")))
                .order_by(LeadMessage.created_at.desc())
                .limit(limit)
            )).scalars().all()
    except Exception as exc:  # noqa: BLE001
        logger.warning("Context fetch failed: {}", exc)
        return None

    def _last(field: str) -> Optional[str]:
        for lead in reversed(leads):
            value = getattr(lead, field, None)
            if value:
                return value
        return None

    return {
        "lead_id": str(leads[-1].id),
        "status": leads[-1].status,
        "name": _last("name"),
        "contact": _last("contact"),
        "course_interest": _last("course_interest"),
        "student_age": _last("student_age"),
        "preferred_time": _last("preferred_time"),
        "summary": _last("summary"),
        "messages": [
            {"role": m.role, "content": m.text, "at": m.created_at.isoformat()}
            for m in reversed(rows)
        ],
    }


def _fit(field: str, value: str) -> str:
    """Truncate to the column length so one long AI field can't fail the save."""
    length = getattr(Lead.__table__.c[field].type, "length", None)
    return value[:length] if length else value


def _aware(dt: datetime) -> datetime:
    return dt if dt.tzinfo else dt.replace(tzinfo=timezone.utc)


def _parse_time(value: str | datetime | None) -> Optional[datetime]:
    if value is None:
        return None
    if isinstance(value, datetime):
        return _aware(value)
    try:
        # Instagram format: 2026-08-01T10:00:00+0000
        text = value.replace("Z", "+00:00")
        if len(text) > 5 and text[-5] in "+-" and text[-3] != ":":
            text = text[:-2] + ":" + text[-2:]
        return _aware(datetime.fromisoformat(text))
    except ValueError:
        return None
