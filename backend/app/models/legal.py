"""User data deletion requests (SPEC §12.2): one row per request received from
Meta's data deletion callback. The confirmation code lets the person check the
status on the public /data-deletion page."""
from __future__ import annotations

from datetime import datetime
from typing import Optional

from sqlalchemy import DateTime, String, func
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base, UUIDPrimaryKeyMixin, utcnow

DELETION_STATUSES = ("received", "completed")
DELETION_SOURCES = ("meta_callback",)
CONFIRMATION_CODE_LENGTH = 16


class DataDeletionRequest(UUIDPrimaryKeyMixin, Base):
    __tablename__ = "data_deletion_requests"

    # 16 alphanumeric chars: URL-safe and matches Meta's "alphanumeric code"
    confirmation_code: Mapped[str] = mapped_column(String(CONFIRMATION_CODE_LENGTH),
                                                   unique=True, nullable=False)
    source: Mapped[str] = mapped_column(String(20), nullable=False)
    # Instagram-scoped id from the signed request (kept as proof of what was deleted)
    external_user_id: Mapped[Optional[str]] = mapped_column(String(64), index=True)
    status: Mapped[str] = mapped_column(String(12), default="received", nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utcnow, server_default=func.now(), nullable=False
    )
    completed_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True))
