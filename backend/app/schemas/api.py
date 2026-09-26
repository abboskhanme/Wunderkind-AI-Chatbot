"""Pydantic schemas for the admin API (see docs/SPEC.md §6)."""
from __future__ import annotations

import uuid
from datetime import datetime
from typing import Any, Literal, Optional

from pydantic import BaseModel, ConfigDict, Field


class ORM(BaseModel):
    model_config = ConfigDict(from_attributes=True)


# --- Auth / users -------------------------------------------------------------
Role = Literal["admin", "operator"]


class UserOut(ORM):
    id: uuid.UUID
    username: str
    full_name: str
    role: str
    is_active: bool
    created_at: datetime


class LoginIn(BaseModel):
    username: str
    password: str


class LoginOut(BaseModel):
    access_token: str
    token_type: str = "bearer"
    user: UserOut


class UserCreate(BaseModel):
    username: str = Field(min_length=3, max_length=64, pattern=r"^[A-Za-z0-9_.-]+$")
    full_name: str = Field(default="", max_length=255)
    password: str = Field(min_length=6, max_length=128)
    role: Role = "operator"


class UserUpdate(BaseModel):
    full_name: Optional[str] = Field(default=None, max_length=255)
    password: Optional[str] = Field(default=None, min_length=6, max_length=128)
    role: Optional[Role] = None
    is_active: Optional[bool] = None


# --- Settings -----------------------------------------------------------------
class SettingsUpdate(BaseModel):
    values: dict[str, Optional[str]]


# --- Leads --------------------------------------------------------------------
LeadStatus = Literal["new", "contacted", "trial", "enrolled", "lost"]


class MessageOut(ORM):
    id: uuid.UUID
    kind: str
    role: str
    text: str
    meta: dict[str, Any] = {}
    created_at: datetime


class ProfileOut(ORM):
    """Account profile from the channel (SPEC §13)."""
    channel: str
    external_id: str
    username: Optional[str] = None
    full_name: Optional[str] = None
    phone: Optional[str] = None
    details: dict[str, Any] = {}
    fetched_at: Optional[datetime] = None
    updated_at: datetime


class LeadOut(ORM):
    id: uuid.UUID
    channel: str
    external_id: str
    username: Optional[str] = None
    source: str
    name: Optional[str] = None
    contact: Optional[str] = None
    course_interest: Optional[str] = None
    student_age: Optional[str] = None
    preferred_time: Optional[str] = None
    language: Optional[str] = None
    intent: Optional[str] = None
    stage: Optional[str] = None
    lead_score: int = 0
    summary: Optional[str] = None
    status: str
    note: Optional[str] = None
    assigned_to_id: Optional[uuid.UUID] = None
    assigned_to_name: Optional[str] = None
    message_count: int = 0
    last_customer_at: Optional[datetime] = None
    created_at: datetime
    updated_at: datetime
    # Account name from the channel profile (not the name the AI collected)
    profile_name: Optional[str] = None


class LeadDetail(LeadOut):
    messages: list[MessageOut] = []
    profile: Optional[ProfileOut] = None


class LeadList(BaseModel):
    items: list[LeadOut]
    total: int


class LeadUpdate(BaseModel):
    status: Optional[LeadStatus] = None
    name: Optional[str] = Field(default=None, max_length=255)
    contact: Optional[str] = Field(default=None, max_length=64)
    course_interest: Optional[str] = Field(default=None, max_length=255)
    student_age: Optional[str] = Field(default=None, max_length=64)
    preferred_time: Optional[str] = Field(default=None, max_length=255)
    note: Optional[str] = None
    assigned_to_id: Optional[uuid.UUID] = None


class InboxItem(BaseModel):
    lead_id: uuid.UUID
    channel: str
    username: Optional[str] = None
    name: Optional[str] = None
    profile_name: Optional[str] = None
    contact: Optional[str] = None
    status: str
    lead_score: int = 0
    stage: Optional[str] = None
    last_message: Optional[str] = None
    last_message_role: Optional[str] = None
    last_message_at: Optional[datetime] = None
    unread: int = 0
    window: Literal["open", "human_agent", "closed"]


class TextIn(BaseModel):
    text: str = Field(min_length=1, max_length=4000)


class ReplyOut(BaseModel):
    sent: bool
    error: Optional[str] = None
    message: Optional[MessageOut] = None


class BotToggleIn(BaseModel):
    enabled: bool


# --- Bot menu -----------------------------------------------------------------
class MenuImageOut(ORM):
    id: uuid.UUID
    content_type: str
    size_bytes: int
    sort_order: int


class MenuItemOut(ORM):
    id: uuid.UUID
    command: str
    title: str
    text: Optional[str] = None
    sort_order: int
    is_active: bool
    images: list[MenuImageOut] = []


class MenuOut(BaseModel):
    greeting: str
    items: list[MenuItemOut]


class MenuItemIn(BaseModel):
    command: str = Field(min_length=1, max_length=32, pattern=r"^[a-z0-9_]+$")
    title: str = Field(min_length=1, max_length=64)
    text: Optional[str] = Field(default=None, max_length=4096)
    is_active: bool = True


class MenuItemPatch(BaseModel):
    command: Optional[str] = Field(default=None, min_length=1, max_length=32,
                                   pattern=r"^[a-z0-9_]+$")
    title: Optional[str] = Field(default=None, min_length=1, max_length=64)
    text: Optional[str] = Field(default=None, max_length=4096)
    is_active: Optional[bool] = None


class GreetingIn(BaseModel):
    greeting: str = Field(default="", max_length=4096)


class ReorderIn(BaseModel):
    ids: list[uuid.UUID]


# --- Playground ---------------------------------------------------------------
class ChatTurn(BaseModel):
    role: Literal["user", "assistant"]
    content: str = Field(max_length=4000)


class PlaygroundIn(BaseModel):
    messages: list[ChatTurn] = Field(min_length=1, max_length=60)
    channel: Literal["instagram", "telegram"] = "instagram"
    is_comment: bool = False
