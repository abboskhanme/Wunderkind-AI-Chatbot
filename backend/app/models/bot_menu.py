"""Telegram bot menu — ready-made answers (text + photos) picked by button/command."""
from __future__ import annotations

import uuid
from typing import Optional

from sqlalchemy import Boolean, ForeignKey, Integer, LargeBinary, String, Text, Uuid
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base, TimestampMixin, UUIDPrimaryKeyMixin

MAX_IMAGES_PER_ITEM = 10  # Telegram sendMediaGroup limit
MAX_IMAGE_BYTES = 5 * 1024 * 1024
ALLOWED_IMAGE_TYPES = frozenset({"image/jpeg", "image/png", "image/webp"})
MAX_TEXT_LENGTH = 4096
RESERVED_COMMANDS = frozenset({"start", "menu"})


class BotMenuItem(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    __tablename__ = "bot_menu_items"

    command: Mapped[str] = mapped_column(String(32), unique=True, nullable=False)
    title: Mapped[str] = mapped_column(String(64), nullable=False)
    text: Mapped[Optional[str]] = mapped_column(Text)
    sort_order: Mapped[int] = mapped_column(Integer, default=0)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)

    images: Mapped[list["BotMenuImage"]] = relationship(
        back_populates="item",
        cascade="all, delete-orphan",
        order_by="BotMenuImage.sort_order",
        lazy="selectin",
    )


class BotMenuImage(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    __tablename__ = "bot_menu_images"

    item_id: Mapped[uuid.UUID] = mapped_column(
        Uuid, ForeignKey("bot_menu_items.id", ondelete="CASCADE"), index=True, nullable=False
    )
    content_type: Mapped[str] = mapped_column(String(64), nullable=False)
    size_bytes: Mapped[int] = mapped_column(Integer, nullable=False)
    sha256: Mapped[str] = mapped_column(String(64), nullable=False)
    sort_order: Mapped[int] = mapped_column(Integer, default=0)
    data: Mapped[bytes] = mapped_column(LargeBinary, nullable=False, deferred=True)

    item: Mapped[BotMenuItem] = relationship(back_populates="images")
