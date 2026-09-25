"""Lead-magnet funnels (SPEC §10.2, §11.1): the funnels, who entered them, their
sales sequences and deliveries, one lead-magnet PDF per funnel and the
admission-interview bookings."""
from __future__ import annotations

import uuid
from datetime import datetime
from typing import Optional

from sqlalchemy import (
    Boolean, DateTime, ForeignKey, Index, Integer, LargeBinary, String, Text,
    UniqueConstraint, Uuid, select, text,
)
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base, JSONType, TimestampMixin, UUIDPrimaryKeyMixin, utcnow

FUNNEL_SOURCES = ("instagram", "telegram_channel", "telegram_direct")
FUNNEL_STEPS = (
    "ig_waiting_follow", "ig_link_sent", "tg_channel_gate",
    "ask_name", "ask_phone", "ask_grade", "pdf_pending", "pdf_sent",
)
# Steps where the person's Telegram text belongs to the funnel, not to the AI
COLLECTION_STEPS = ("tg_channel_gate", "ask_name", "ask_phone", "ask_grade")
BOOKING_STATUSES = ("scheduled", "cancelled", "attended", "no_show")

LEAD_MAGNET_KEY = "lead_magnet"
MAX_PDF_BYTES = 20 * 1024 * 1024
START_TOKEN_LENGTH = 12

DEFAULT_FUNNEL_NAME = "Asosiy voronka"
DEFAULT_FUNNEL_SLUG = "asosiy"
# Text settings a funnel may override; missing/empty = the global setting (§11.1)
FUNNEL_TEXT_KEYS = (
    "FUNNEL_IG_COMMENT_REPLY", "FUNNEL_IG_DM_WELCOME", "FUNNEL_IG_NOT_FOLLOWING",
    "FUNNEL_IG_LINK_MESSAGE", "FUNNEL_TG_COMMENT_REPLY", "FUNNEL_BOT_WELCOME",
    "FUNNEL_ASK_NAME", "FUNNEL_ASK_PHONE", "FUNNEL_ASK_GRADE", "FUNNEL_GRADES",
    "FUNNEL_PDF_CAPTION", "FUNNEL_BOOK_BUTTON",
)


class Funnel(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    """A funnel: its own keywords, Instagram posts, PDF, sales messages and texts;
    the step template, schedule, staff and Google Sheet are shared (SPEC §11)."""

    __tablename__ = "funnels"
    __table_args__ = (
        # Exactly one default funnel (the migration inserts it; never deleted)
        Index("uq_funnels_one_default", "is_default", unique=True,
              postgresql_where=text("is_default"), sqlite_where=text("is_default")),
    )

    name: Mapped[str] = mapped_column(String(120), nullable=False)
    # Used in deep links: ?start=tgc_<slug> / ?start=f_<slug>
    slug: Mapped[str] = mapped_column(String(32), unique=True, nullable=False)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True, server_default="true",
                                            nullable=False)
    is_default: Mapped[bool] = mapped_column(Boolean, default=False, server_default="false",
                                             nullable=False)
    # Comma separated; empty on the default funnel = FUNNEL_KEYWORDS
    keywords: Mapped[str] = mapped_column(Text, default="", server_default="", nullable=False)
    # Comma separated media ids / permalink shortcodes; empty = any post
    ig_media_ids: Mapped[str] = mapped_column(Text, default="", server_default="",
                                              nullable=False)
    # {FUNNEL_TEXT_KEYS item: text} overrides
    texts: Mapped[dict] = mapped_column(JSONType, default=dict, nullable=False)
    sort_order: Mapped[int] = mapped_column(Integer, default=0, server_default="0",
                                            nullable=False)


def _default_funnel_id():
    """Rows created without an explicit funnel land in the default funnel — the
    same fallback the migration's backfill uses. New code always sets it."""
    return (select(Funnel.id).where(Funnel.is_default.is_(True)).limit(1)
            .scalar_subquery())


class FunnelEntry(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    """One person going through the funnel (merged across Instagram and Telegram)."""

    __tablename__ = "funnel_entries"
    __table_args__ = (
        # One entry per person per funnel (tg_user_id first: lookups by person)
        UniqueConstraint("tg_user_id", "funnel_id", name="uq_funnel_entries_tg_user_funnel"),
    )

    funnel_id: Mapped[uuid.UUID] = mapped_column(
        Uuid, ForeignKey("funnels.id"), index=True, nullable=False, default=_default_funnel_id()
    )
    source: Mapped[str] = mapped_column(String(20), index=True, nullable=False)
    # Deep-link payload: t.me/<bot>?start=<start_token>
    start_token: Mapped[str] = mapped_column(String(24), unique=True, nullable=False)

    ig_user_id: Mapped[Optional[str]] = mapped_column(String(64), index=True)
    ig_username: Mapped[Optional[str]] = mapped_column(String(120))
    ig_comment_id: Mapped[Optional[str]] = mapped_column(String(64))
    follow_checks: Mapped[int] = mapped_column(Integer, default=0, server_default="0",
                                               nullable=False)

    tg_user_id: Mapped[Optional[str]] = mapped_column(String(32))
    tg_chat_id: Mapped[Optional[str]] = mapped_column(String(32))
    tg_username: Mapped[Optional[str]] = mapped_column(String(120))

    lead_id: Mapped[Optional[uuid.UUID]] = mapped_column(
        Uuid, ForeignKey("leads.id", ondelete="SET NULL"), index=True
    )
    step: Mapped[str] = mapped_column(String(24), index=True, nullable=False)

    full_name: Mapped[Optional[str]] = mapped_column(String(120))
    phone: Mapped[Optional[str]] = mapped_column(String(32))
    grade: Mapped[Optional[str]] = mapped_column(String(32))

    followed_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True))
    link_sent_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True))
    bot_started_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True))
    pdf_sent_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True),
                                                            index=True)
    opted_out: Mapped[bool] = mapped_column(Boolean, default=False, server_default="false",
                                            nullable=False)
    # PDF delivery retries (Telegram error): attempt count + when to try next
    pdf_attempts: Mapped[int] = mapped_column(Integer, default=0, server_default="0",
                                              nullable=False)
    pdf_retry_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True))

    # Google Sheets outbox: last known row; dirty = needs (re)sync. The sheet's
    # "ID" column is the source of truth for which row belongs to which entry.
    sheet_row: Mapped[Optional[int]] = mapped_column(Integer)
    sheet_dirty: Mapped[bool] = mapped_column(Boolean, default=True, server_default="true",
                                              index=True, nullable=False)
    # Instagram-only entry merged into this one: its sheet row is taken over or
    # marked "Birlashtirildi" on the next sync (no FK: that entry is deleted)
    sheet_merged_id: Mapped[Optional[uuid.UUID]] = mapped_column(Uuid)


class FunnelMessage(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    """One message of the sales sequence sent after the PDF."""

    __tablename__ = "funnel_messages"

    funnel_id: Mapped[uuid.UUID] = mapped_column(
        Uuid, ForeignKey("funnels.id", ondelete="CASCADE"), index=True, nullable=False,
        default=_default_funnel_id(),
    )
    sort_order: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    text: Mapped[str] = mapped_column(Text, nullable=False)
    delay_minutes: Mapped[int] = mapped_column(Integer, nullable=False)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True, server_default="true",
                                            nullable=False)
    # Deferred: lists never load the bytes; `image_content_type` tells if one exists
    image: Mapped[Optional[bytes]] = mapped_column(LargeBinary, deferred=True)
    image_content_type: Mapped[Optional[str]] = mapped_column(String(64))

    @property
    def has_image(self) -> bool:
        return self.image_content_type is not None


class FunnelDelivery(UUIDPrimaryKeyMixin, Base):
    """A sales message delivered to an entry — the unique pair makes it at-most-once."""

    __tablename__ = "funnel_deliveries"
    __table_args__ = (
        UniqueConstraint("entry_id", "message_id", name="uq_funnel_deliveries_entry_message"),
    )

    entry_id: Mapped[uuid.UUID] = mapped_column(
        Uuid, ForeignKey("funnel_entries.id", ondelete="CASCADE"), nullable=False
    )
    message_id: Mapped[uuid.UUID] = mapped_column(
        Uuid, ForeignKey("funnel_messages.id", ondelete="CASCADE"), index=True, nullable=False
    )
    sent_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow,
                                              nullable=False)


class FunnelFile(Base):
    """The lead-magnet PDF (one row per key). `tg_file_id` avoids re-uploading."""

    __tablename__ = "funnel_files"

    # One lead magnet per funnel: primary key (funnel_id, key)
    funnel_id: Mapped[uuid.UUID] = mapped_column(
        Uuid, ForeignKey("funnels.id", ondelete="CASCADE"), primary_key=True,
        default=_default_funnel_id(),
    )
    key: Mapped[str] = mapped_column(String(32), primary_key=True)
    filename: Mapped[str] = mapped_column(String(255), nullable=False)
    content_type: Mapped[str] = mapped_column(String(100), nullable=False)
    size_bytes: Mapped[int] = mapped_column(Integer, nullable=False)
    data: Mapped[bytes] = mapped_column(LargeBinary, deferred=True, nullable=False)
    sha256: Mapped[str] = mapped_column(String(64), nullable=False)
    tg_file_id: Mapped[Optional[str]] = mapped_column(String(255))
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utcnow, onupdate=utcnow, nullable=False
    )


class InterviewBooking(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    """Admission interview slot taken by an entry."""

    __tablename__ = "interview_bookings"
    __table_args__ = (
        # One active booking per entry (reschedule = cancel old + create new)
        Index("uq_interview_bookings_one_scheduled", "entry_id", unique=True,
              postgresql_where=text("status = 'scheduled'"),
              sqlite_where=text("status = 'scheduled'")),
    )

    entry_id: Mapped[uuid.UUID] = mapped_column(
        Uuid, ForeignKey("funnel_entries.id", ondelete="CASCADE"), index=True, nullable=False
    )
    lead_id: Mapped[Optional[uuid.UUID]] = mapped_column(
        Uuid, ForeignKey("leads.id", ondelete="SET NULL")
    )
    starts_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), index=True,
                                                nullable=False)
    status: Mapped[str] = mapped_column(String(20), default="scheduled",
                                        server_default="scheduled", index=True, nullable=False)
    reminder_sent_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True))
    note: Mapped[Optional[str]] = mapped_column(Text)
    # Cancelled because the person picked another time (not a real cancellation)
    rescheduled: Mapped[bool] = mapped_column(Boolean, default=False, server_default="false",
                                              nullable=False)
