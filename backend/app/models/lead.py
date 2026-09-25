"""Leads (one per person per channel while open) and their conversation log."""
from __future__ import annotations

import uuid
from datetime import datetime
from typing import Any, Optional

from sqlalchemy import DateTime, ForeignKey, Index, Integer, String, Text, Uuid, text
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base, JSONType, TimestampMixin, UUIDPrimaryKeyMixin

CHANNELS = ("instagram", "telegram")
LEAD_STATUSES = ("new", "contacted", "trial", "enrolled", "lost")
CLOSED_STATUSES = ("enrolled", "lost")
STAGES = ("greeting", "discovery", "offer", "objection", "closing", "booked", "support")
STATUS_LABELS = {"new": "Yangi", "contacted": "Bog'lanildi", "trial": "Suhbatga yozildi",
                 "enrolled": "Qabul qilindi", "lost": "Yo'qotildi"}


class Lead(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    __tablename__ = "leads"
    __table_args__ = (
        Index("ix_leads_channel_external", "channel", "external_id"),
        # At most ONE open lead per person per channel (concurrent webhooks)
        Index("uq_leads_open_per_person", "channel", "external_id", unique=True,
              postgresql_where=text("status NOT IN ('enrolled', 'lost')"),
              sqlite_where=text("status NOT IN ('enrolled', 'lost')")),
    )

    channel: Mapped[str] = mapped_column(String(20), default="instagram")
    external_id: Mapped[str] = mapped_column(String(64))
    username: Mapped[Optional[str]] = mapped_column(String(120))
    source: Mapped[str] = mapped_column(String(30), default="instagram", index=True)

    # Facts collected by the AI (or typed by staff)
    name: Mapped[Optional[str]] = mapped_column(String(255))
    contact: Mapped[Optional[str]] = mapped_column(String(64))
    course_interest: Mapped[Optional[str]] = mapped_column(String(255), index=True)
    student_age: Mapped[Optional[str]] = mapped_column(String(64))
    preferred_time: Mapped[Optional[str]] = mapped_column(String(255))
    language: Mapped[Optional[str]] = mapped_column(String(10))
    intent: Mapped[Optional[str]] = mapped_column(String(30))
    stage: Mapped[Optional[str]] = mapped_column(String(20))
    lead_score: Mapped[int] = mapped_column(Integer, default=0, index=True)
    summary: Mapped[Optional[str]] = mapped_column(Text)

    # Staff pipeline
    status: Mapped[str] = mapped_column(String(20), default="new", index=True)
    note: Mapped[Optional[str]] = mapped_column(Text)
    assigned_to_id: Mapped[Optional[uuid.UUID]] = mapped_column(
        Uuid, ForeignKey("users.id", ondelete="SET NULL")
    )

    last_read_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True))
    last_customer_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True))
    last_message_at: Mapped[Optional[datetime]] = mapped_column(
        DateTime(timezone=True), index=True
    )
    last_followup_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True))

    extra: Mapped[dict[str, Any]] = mapped_column(JSONType, default=dict)

    messages: Mapped[list["LeadMessage"]] = relationship(
        back_populates="lead",
        cascade="all, delete-orphan",
        passive_deletes=True,
        order_by="LeadMessage.created_at",
    )


class LeadMessage(UUIDPrimaryKeyMixin, Base):
    __tablename__ = "lead_messages"
    __table_args__ = (Index("ix_lead_messages_lead_created", "lead_id", "created_at"),)

    lead_id: Mapped[uuid.UUID] = mapped_column(
        Uuid, ForeignKey("leads.id", ondelete="CASCADE"), nullable=False
    )
    kind: Mapped[str] = mapped_column(String(20), default="dm")  # dm|comment|note|status
    role: Mapped[str] = mapped_column(String(20))  # user|assistant|operator|system
    text: Mapped[str] = mapped_column(Text)
    # Instagram mids are ~150-170 chars of base64 — no length limit
    external_message_id: Mapped[Optional[str]] = mapped_column(Text, index=True)
    comment_id: Mapped[Optional[str]] = mapped_column(String(64))
    media_id: Mapped[Optional[str]] = mapped_column(String(64))
    meta: Mapped[dict[str, Any]] = mapped_column(JSONType, default=dict)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))

    lead: Mapped[Lead] = relationship(back_populates="messages")
