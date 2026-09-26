"""Pydantic schemas for the forms admin API (SPEC §15.4)."""
from __future__ import annotations

import uuid
from datetime import datetime
from typing import Any, Optional

from pydantic import BaseModel, Field

SLUG_FIELD = r"^[a-z0-9][a-z0-9-]{0,39}$"


class FormField(BaseModel):
    """One question; cleaned by app.forms.fields.clean_fields (Uzbek 400 errors)."""
    id: str = Field(default="", max_length=16)
    type: str
    label: str = Field(default="", max_length=300)
    required: bool = False
    placeholder: str = Field(default="", max_length=120)
    help: str = Field(default="", max_length=500)
    options: list[str] = Field(default_factory=list, max_length=30)
    lead_field: Optional[str] = None


class FormOut(BaseModel):
    id: uuid.UUID
    title: str
    slug: str
    description: str
    fields: list[FormField]
    submit_label: str
    success_message: str
    is_active: bool
    notify: bool
    sort_order: int
    url: str
    submissions: int = 0
    last_submission_at: Optional[datetime] = None
    created_at: datetime
    updated_at: datetime


class FormIn(BaseModel):
    title: str = Field(min_length=1, max_length=200)
    slug: Optional[str] = Field(default=None, pattern=SLUG_FIELD)
    description: str = Field(default="", max_length=5000)
    # Absent / empty → the default questions (name + phone)
    fields: Optional[list[FormField]] = Field(default=None, max_length=40)
    submit_label: str = Field(default="Yuborish", min_length=1, max_length=60)
    success_message: str = Field(default="", max_length=2000)
    is_active: bool = True
    notify: bool = True


class FormPatch(BaseModel):
    title: Optional[str] = Field(default=None, min_length=1, max_length=200)
    slug: Optional[str] = Field(default=None, pattern=SLUG_FIELD)
    description: Optional[str] = Field(default=None, max_length=5000)
    # Given = replaces the list
    fields: Optional[list[FormField]] = Field(default=None, max_length=40)
    submit_label: Optional[str] = Field(default=None, min_length=1, max_length=60)
    success_message: Optional[str] = Field(default=None, max_length=2000)
    is_active: Optional[bool] = None
    notify: Optional[bool] = None


class SubmissionOut(BaseModel):
    id: uuid.UUID
    created_at: datetime
    lead_id: Optional[uuid.UUID] = None
    lead_name: Optional[str] = None
    lead_contact: Optional[str] = None
    answers: list[dict[str, Any]]
    utm: dict[str, Any] = Field(default_factory=dict)


class SubmissionList(BaseModel):
    items: list[SubmissionOut]
    total: int


class LeadSourceOption(BaseModel):
    value: str
    label: str
    count: int = 0
