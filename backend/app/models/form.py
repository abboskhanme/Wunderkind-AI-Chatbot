"""Forms («Formalar», SPEC §15): Google-Forms-like pages whose submissions
become leads with the form as their source."""
from __future__ import annotations

import uuid
from datetime import datetime
from typing import Any, Optional

from sqlalchemy import Boolean, DateTime, ForeignKey, Integer, String, Text, Uuid
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base, JSONType, TimestampMixin, UUIDPrimaryKeyMixin, utcnow

FIELD_TYPES = ("short_text", "long_text", "phone", "email", "number", "date",
               "single_choice", "multiple_choice", "dropdown")
CHOICE_TYPES = ("single_choice", "multiple_choice", "dropdown")
# Lead columns a form answer may fill ("phone" → Lead.contact)
LEAD_FIELDS = ("name", "phone", "student_age", "course_interest", "preferred_time")
MAX_FIELDS = 40
MAX_OPTIONS = 30


class Form(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    __tablename__ = "forms"

    title: Mapped[str] = mapped_column(String(200), nullable=False)
    # Public link: /f/<slug>
    slug: Mapped[str] = mapped_column(String(40), unique=True, nullable=False)
    description: Mapped[str] = mapped_column(Text, default="", server_default="",
                                             nullable=False)
    # [{id, type, label, required, placeholder?, help?, options?, lead_field?}]
    fields: Mapped[list[dict[str, Any]]] = mapped_column(JSONType, default=list,
                                                         nullable=False)
    submit_label: Mapped[str] = mapped_column(String(60), default="Yuborish",
                                              server_default="Yuborish", nullable=False)
    success_message: Mapped[str] = mapped_column(Text, default="", server_default="",
                                                 nullable=False)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True, server_default="true",
                                            nullable=False)
    # Telegram staff alert on every submission
    notify: Mapped[bool] = mapped_column(Boolean, default=True, server_default="true",
                                         nullable=False)
    sort_order: Mapped[int] = mapped_column(Integer, default=0, server_default="0",
                                            nullable=False)


class FormSubmission(UUIDPrimaryKeyMixin, Base):
    """One filled form. Labels are snapshotted so later edits keep old answers readable."""

    __tablename__ = "form_submissions"

    form_id: Mapped[uuid.UUID] = mapped_column(
        Uuid, ForeignKey("forms.id", ondelete="CASCADE"), index=True, nullable=False
    )
    lead_id: Mapped[Optional[uuid.UUID]] = mapped_column(
        Uuid, ForeignKey("leads.id", ondelete="SET NULL"), index=True
    )
    # [{field_id, label, type, value: str | list[str]}]
    answers: Mapped[list[dict[str, Any]]] = mapped_column(JSONType, default=list,
                                                          nullable=False)
    # utm_* / ref from the page URL
    utm: Mapped[dict[str, Any]] = mapped_column(JSONType, default=dict, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow,
                                                 index=True, nullable=False)
