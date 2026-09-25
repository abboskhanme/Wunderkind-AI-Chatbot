"""Pydantic schemas for the funnel admin API (SPEC §10.4)."""
from __future__ import annotations

import uuid
from datetime import datetime
from typing import Literal, Optional

from pydantic import BaseModel, ConfigDict, Field, field_validator

BookingStatus = Literal["scheduled", "cancelled", "attended", "no_show"]
MAX_DELAY_MINUTES = 60 * 24 * 60          # 60 days
TELEGRAM_TEXT_LIMIT = 4096


class ORM(BaseModel):
    model_config = ConfigDict(from_attributes=True)


# --- Stats ------------------------------------------------------------------------
class StepCount(BaseModel):
    key: str
    label: str
    count: int


class SourceCount(BaseModel):
    source: str
    count: int


class BookingCounts(BaseModel):
    scheduled: int
    attended: int
    no_show: int
    cancelled: int
    today: int


class DayStats(BaseModel):
    date: str
    entries: int
    pdf: int
    bookings: int


class FunnelStats(BaseModel):
    steps: list[StepCount]
    by_source: list[SourceCount]
    bookings: BookingCounts
    by_day: list[DayStats]


# --- Entries / bookings -----------------------------------------------------------
class BookingOut(BaseModel):
    id: uuid.UUID
    entry_id: uuid.UUID
    lead_id: Optional[uuid.UUID] = None
    full_name: Optional[str] = None
    phone: Optional[str] = None
    grade: Optional[str] = None
    starts_at: datetime
    status: str
    note: Optional[str] = None
    reminder_sent_at: Optional[datetime] = None
    created_at: datetime


class FunnelEntryOut(BaseModel):
    id: uuid.UUID
    source: str
    step: str
    full_name: Optional[str] = None
    phone: Optional[str] = None
    grade: Optional[str] = None
    ig_username: Optional[str] = None
    tg_username: Optional[str] = None
    lead_id: Optional[uuid.UUID] = None
    pdf_sent_at: Optional[datetime] = None
    opted_out: bool
    booking: Optional[BookingOut] = None
    messages_sent: int = 0
    created_at: datetime


class FunnelEntryList(BaseModel):
    items: list[FunnelEntryOut]
    total: int


class BookingUpdate(BaseModel):
    status: Optional[BookingStatus] = None
    # "" clears the note
    note: Optional[str] = Field(default=None, max_length=2000)


class SlotOut(BaseModel):
    time: str
    free: int


# --- Sales sequence -----------------------------------------------------------------
class FunnelMessageOut(ORM):
    id: uuid.UUID
    sort_order: int
    text: str
    delay_minutes: int
    is_active: bool
    has_image: bool
    image_content_type: Optional[str] = None


def _telegram_text(value: Optional[str]) -> Optional[str]:
    """Telegram counts 4096 in UTF-16 units (an emoji is 2), not characters."""
    from app.telegram_business.menu import tg_len

    if value is not None and tg_len(value) > TELEGRAM_TEXT_LIMIT:
        raise ValueError(f"Matn Telegram chegarasidan uzun ({TELEGRAM_TEXT_LIMIT})")
    return value


class FunnelMessageIn(BaseModel):
    text: str = Field(min_length=1, max_length=TELEGRAM_TEXT_LIMIT)
    delay_minutes: int = Field(ge=0, le=MAX_DELAY_MINUTES)
    is_active: bool = True

    _text_fits = field_validator("text")(_telegram_text)


class FunnelMessagePatch(BaseModel):
    text: Optional[str] = Field(default=None, min_length=1, max_length=TELEGRAM_TEXT_LIMIT)
    delay_minutes: Optional[int] = Field(default=None, ge=0, le=MAX_DELAY_MINUTES)
    is_active: Optional[bool] = None

    _text_fits = field_validator("text")(_telegram_text)


# --- Lead magnet / sheet / test ---------------------------------------------------
class LeadMagnetOut(ORM):
    filename: str
    size_bytes: int
    updated_at: datetime


class SheetTestOut(BaseModel):
    ok: bool
    error: Optional[str] = None
    title: Optional[str] = None


class ResyncOut(BaseModel):
    queued: int


class TestMessageIn(BaseModel):
    tg_chat_id: str = Field(min_length=1, max_length=64, pattern=r"^\s*(-?\d+|@\w{4,})\s*$")
    kind: Literal["reminder", "confirm", "sales"]
    message_id: Optional[uuid.UUID] = None


class SentOut(BaseModel):
    sent: bool
    error: Optional[str] = None
