"""Account profile of a customer as the channel reports it (Telegram user data,
Instagram User Profile API) — one row per person per channel.

Kept apart from `leads`: a lead is one sales attempt (a person can have several
over time), while the profile describes the account itself. It is filled in
automatically from incoming updates, even before the first lead exists.
"""
from __future__ import annotations

from datetime import datetime
from typing import Any, Optional

from sqlalchemy import DateTime, String, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base, JSONType, TimestampMixin, UUIDPrimaryKeyMixin


class CustomerProfile(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    __tablename__ = "customer_profiles"
    __table_args__ = (UniqueConstraint("channel", "external_id",
                                       name="uq_customer_profiles_channel_external"),)

    channel: Mapped[str] = mapped_column(String(20))
    external_id: Mapped[str] = mapped_column(String(64))
    username: Mapped[Optional[str]] = mapped_column(String(120))
    # Telegram: first + last name; Instagram: the profile "name"
    full_name: Mapped[Optional[str]] = mapped_column(String(255))
    # Only a phone the person shared themselves (Telegram contact button)
    phone: Mapped[Optional[str]] = mapped_column(String(32))
    # Channel-specific extras: language_code, is_premium, bio, birthdate,
    # followers, is_verified, follows_us, profile_pic, ...
    details: Mapped[dict[str, Any]] = mapped_column(JSONType, default=dict)
    # Last successful API read (Telegram getChat / Instagram profile API)
    fetched_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True))
