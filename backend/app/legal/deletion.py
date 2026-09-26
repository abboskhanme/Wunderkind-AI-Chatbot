"""User data deletion and Instagram disconnect (SPEC §12.2).

Called by the signed Meta callbacks in `app.instagram.meta_callbacks`. The work
is split so the callback can answer Meta quickly:
  * `create_request` + `delete_instagram_user` — DB only, run inside the request
    (Meta needs the confirmation code in the response);
  * `after_deletion` / `after_deauthorize` — Google Sheets erasure and the staff
    alert, run as a background task.
Logs and alerts carry the confirmation code and counts, never names/phones.
"""
from __future__ import annotations

import secrets
import string
import uuid
from dataclasses import dataclass, field
from html import escape
from typing import Optional

from loguru import logger
from sqlalchemy import delete, or_, select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import settings
from app.db.base import utcnow
from app.models.funnel import FunnelDelivery, FunnelEntry, InterviewBooking
from app.models.lead import Lead, LeadMessage
from app.models.legal import CONFIRMATION_CODE_LENGTH, DataDeletionRequest

# Settings the Instagram "Ulash" flow fills in; cleared on disconnect
IG_IDENTITY_KEYS = ("IG_ACCESS_TOKEN", "IG_USER_ID", "IG_ACCOUNT_ID", "IG_USERNAME",
                    "IG_TOKEN_ISSUED_AT")
_CODE_ALPHABET = string.ascii_letters + string.digits


@dataclass
class DeletionResult:
    leads: int = 0
    messages: int = 0
    entries: int = 0
    bookings: int = 0
    entry_ids: list[str] = field(default_factory=list)


def new_confirmation_code() -> str:
    """16 alphanumeric chars (~95 bits): URL-safe and unguessable."""
    return "".join(secrets.choice(_CODE_ALPHABET) for _ in range(CONFIRMATION_CODE_LENGTH))


def is_own_account(user_id: str) -> bool:
    """The signed request is about OUR connected Instagram account."""
    own = {settings.IG_USER_ID, settings.IG_ACCOUNT_ID} - {""}
    return bool(user_id) and user_id in own


async def create_request(db: AsyncSession, user_id: str,
                         source: str = "meta_callback") -> DataDeletionRequest:
    """Record the request as `received` (committed before anything is deleted,
    so a crash mid-way still leaves a visible, pending request)."""
    for _ in range(5):
        code = new_confirmation_code()
        taken = (await db.execute(select(DataDeletionRequest.id).where(
            DataDeletionRequest.confirmation_code == code))).first()
        if not taken:
            break
    row = DataDeletionRequest(confirmation_code=code, source=source,
                              external_user_id=user_id[:64], status="received")
    db.add(row)
    await db.commit()
    return row


async def mark_completed(db: AsyncSession, row: DataDeletionRequest) -> None:
    row.status = "completed"
    row.completed_at = utcnow()
    await db.commit()


async def delete_instagram_user(db: AsyncSession, ig_user_id: str) -> DeletionResult:
    """Delete everything we hold about one Instagram user and commit.

    Removed: their Instagram leads (+ messages), the funnel entries with this
    Instagram id (+ deliveries and interview bookings), and — because our funnel
    linked this Instagram user to a Telegram user — that same person's Telegram
    leads and funnel entries. Other people's rows only lose a dangling reference
    (lead_id -> NULL), exactly what the database's ON DELETE SET NULL does.
    Idempotent: a second call finds nothing and deletes nothing.
    """
    result = DeletionResult()
    entries = (await db.execute(
        select(FunnelEntry.id, FunnelEntry.lead_id, FunnelEntry.tg_user_id)
        .where(FunnelEntry.ig_user_id == ig_user_id)
    )).all()
    tg_ids = {row.tg_user_id for row in entries if row.tg_user_id}
    if tg_ids:
        entries += (await db.execute(
            select(FunnelEntry.id, FunnelEntry.lead_id, FunnelEntry.tg_user_id)
            .where(FunnelEntry.tg_user_id.in_(tg_ids),
                   FunnelEntry.id.notin_([row.id for row in entries]))
        )).all()
    entry_ids: set[uuid.UUID] = {row.id for row in entries}

    lead_filter = (Lead.channel == "instagram") & (Lead.external_id == ig_user_id)
    if tg_ids:
        lead_filter = or_(lead_filter,
                          (Lead.channel == "telegram") & Lead.external_id.in_(tg_ids))
    lead_ids: set[uuid.UUID] = set((await db.execute(select(Lead.id).where(lead_filter)))
                                   .scalars().all())
    lead_ids |= {row.lead_id for row in entries if row.lead_id}

    if entry_ids:
        await db.execute(delete(FunnelDelivery).where(FunnelDelivery.entry_id.in_(entry_ids)))
        booked = await db.execute(
            delete(InterviewBooking).where(InterviewBooking.entry_id.in_(entry_ids)))
        result.bookings = int(booked.rowcount or 0)
    if lead_ids:
        # Explicit SET NULL / CASCADE: SQLite (tests) does not enforce the FKs
        await db.execute(update(FunnelEntry).where(FunnelEntry.lead_id.in_(lead_ids))
                         .values(lead_id=None, updated_at=FunnelEntry.updated_at))
        await db.execute(update(InterviewBooking).where(InterviewBooking.lead_id.in_(lead_ids))
                         .values(lead_id=None, updated_at=InterviewBooking.updated_at))
        msgs = await db.execute(delete(LeadMessage).where(LeadMessage.lead_id.in_(lead_ids)))
        result.messages = int(msgs.rowcount or 0)
    if entry_ids:
        await db.execute(delete(FunnelEntry).where(FunnelEntry.id.in_(entry_ids)))
    if lead_ids:
        await db.execute(delete(Lead).where(Lead.id.in_(lead_ids)))
    await db.commit()

    result.leads = len(lead_ids)
    result.entries = len(entry_ids)
    result.entry_ids = sorted(str(i) for i in entry_ids)

    # Conversation cache (Redis / memory): Instagram keys have no prefix
    from app.state.store import store

    for key in [ig_user_id] + [f"tg:{tg}" for tg in sorted(tg_ids)]:
        try:
            await store.forget(key)
        except Exception as exc:  # noqa: BLE001
            logger.warning("Conversation cache not cleared: {}", exc)
    return result


async def disconnect_instagram() -> dict:
    """Clear the Instagram token and identity (persisted + live).

    Returns {"saved": bool, "env_token": bool}; env_token = the token also sits
    in `.env`, which the panel cannot clear (the next settings reload would bring
    it back), so staff must remove it there.
    """
    from app import runtime_config

    saved = await runtime_config.push_config({key: "" for key in IG_IDENTITY_KEYS})
    for key in IG_IDENTITY_KEYS:
        setattr(settings, key, "")
    env_token = "IG_ACCESS_TOKEN" in runtime_config.ENV_SET and bool(
        runtime_config.BASELINE.get("IG_ACCESS_TOKEN"))
    logger.warning("Instagram disconnected by a Meta callback (saved={}, env_token={})",
                   saved, env_token)
    return {"saved": saved, "env_token": env_token}


def _disconnect_lines(state: Optional[dict]) -> list[str]:
    if state is None:
        return []
    lines = ["Instagram akkaunt <b>uzildi</b> (token o'chirildi). Qayta ulash: "
             "Sozlamalar → Instagram → «Ulash»."]
    if not state.get("saved"):
        lines.append("⚠️ Sozlamalar bazasiga yozib bo'lmadi — tekshiring.")
    if state.get("env_token"):
        lines.append("⚠️ IG_ACCESS_TOKEN .env faylida ham bor — uni serverda o'chiring.")
    return lines


async def after_deletion(code: str, result: Optional[DeletionResult],
                         disconnected: Optional[dict]) -> None:
    """Background part: erase the Google Sheet rows, then alert staff."""
    from app.funnel import gsheet
    from app.telegram.notifier import send_text

    lines = ["🗑 <b>Ma'lumotlarni o'chirish so'rovi (Meta)</b>",
             f"Kod: <code>{escape(code)}</code>"]
    if result is None:
        lines.append("❌ Avtomatik o'chirish bajarilmadi (server xatosi). So'rov "
                     "«qabul qilindi» holatida — 30 kun ichida qo'lda o'chiring.")
    else:
        lines.append(f"O'chirildi: {result.leads} ta lead ({result.messages} xabar), "
                     f"{result.entries} ta voronka yozuvi, {result.bookings} ta suhbat.")
        sheet = await gsheet.erase_rows(result.entry_ids)
        if sheet["error"]:
            ids = ", ".join(result.entry_ids)
            lines.append("⚠️ Google Sheets qatorlarini o'chirib bo'lmadi — «ID» ustunida "
                         f"shu ID'lar bor qatorlarni qo'lda o'chiring: <code>{escape(ids)}</code>")
        elif sheet["erased"]:
            lines.append(f"Google Sheets: {sheet['erased']} ta qator tozalandi.")
    lines += _disconnect_lines(disconnected)
    try:
        await send_text("\n".join(lines))
    except Exception as exc:  # noqa: BLE001
        logger.warning("Data deletion alert failed: {}", exc)


async def after_deauthorize(disconnected: dict) -> None:
    from app.telegram.notifier import send_text

    lines = ["⚠️ <b>Instagram ilovaga ruxsat bekor qilindi</b> (Meta deauthorize)."]
    lines += _disconnect_lines(disconnected)
    try:
        await send_text("\n".join(lines))
    except Exception as exc:  # noqa: BLE001
        logger.warning("Deauthorize alert failed: {}", exc)
