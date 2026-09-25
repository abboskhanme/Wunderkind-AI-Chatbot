"""Sending the lead-magnet PDF and sales-sequence messages to Telegram."""
from __future__ import annotations

import html
import uuid
from datetime import timedelta
from typing import Optional

from loguru import logger
from sqlalchemy import select, update

from app.config import settings
from app.db import session as db_session
from app.funnel import locks, repo, texts
from app.models.funnel import LEAD_MAGNET_KEY, FunnelEntry, FunnelFile, FunnelMessage
from app.state.store import store
from app.telegram import notifier
from app.telegram_business.client import telegram
from app.telegram_business.menu import tg_len

CAPTION_LIMIT = 1024
_IMAGE_CACHE_KEY = "fnlimg:{bot}:{message}:{version}"
_NO_PDF_ALERT_KEY = "fnl:alert:no-pdf"
_PDF_FAILED_ALERT_KEY = "fnl:alert:pdf-failed"


def book_keyboard() -> dict:
    return {"inline_keyboard": [[{"text": settings.FUNNEL_BOOK_BUTTON or "📝 Suhbatga yozilish",
                                  "callback_data": "fb:start"}]]}


def _is_file_id_error(result: dict) -> bool:
    error = str(result.get("error") or "").lower()
    return "file identifier" in error or "file_id" in error or "wrong remote file" in error


def _bot_id() -> str:
    return settings.TG_SALES_BOT_TOKEN.split(":", 1)[0]


async def _pdf_bytes(key: str) -> Optional[bytes]:
    async with db_session.SessionLocal() as db:
        data = (await db.execute(select(FunnelFile.data).where(FunnelFile.key == key))
                ).scalar_one_or_none()
    return bytes(data) if data else None


def fit_caption(text: str) -> Optional[str]:
    """Telegram counts caption length in UTF-16 units (emoji = 2): cut to fit."""
    text = (text or "").strip()
    while text and tg_len(text) > CAPTION_LIMIT:
        text = text[:-1]
    return text or None


def retry_delay(attempts: int) -> timedelta:
    """1, 2, 4, 8, … minutes, at most an hour — keeps retrying, never gives up."""
    return timedelta(minutes=min(2 ** max(0, attempts - 1), 60))


async def send_pdf_file(chat_id: str, *, reply_markup: Optional[dict]) -> dict:
    """Send the lead-magnet PDF (cached file_id first, bytes as fallback).

    The first upload is serialized: when many people finish at once only one
    upload happens, the rest reuse its file_id. Result: {"sent", "missing"?, "error"?}.
    """
    async with db_session.SessionLocal() as db:
        meta = await db.get(FunnelFile, LEAD_MAGNET_KEY)
    if meta is None:
        return {"sent": False, "missing": True}
    caption = fit_caption(settings.FUNNEL_PDF_CAPTION)
    if meta.tg_file_id:
        result = await telegram.send_document(chat_id, meta.tg_file_id, caption=caption,
                                              reply_markup=reply_markup)
        if result.get("sent") or not _is_file_id_error(result):
            return result
        logger.info("Cached PDF file_id rejected (bot changed?) — uploading again")
        stale_file_id: Optional[str] = meta.tg_file_id
    else:
        stale_file_id = None
    async with locks.lock("pdf-upload"):
        async with db_session.SessionLocal() as db:
            meta = await db.get(FunnelFile, LEAD_MAGNET_KEY)
        if meta is None:
            return {"sent": False, "missing": True}
        if meta.tg_file_id and meta.tg_file_id != stale_file_id:
            # Someone else's upload finished while we waited
            return await telegram.send_document(chat_id, meta.tg_file_id, caption=caption,
                                                reply_markup=reply_markup)
        data = await _pdf_bytes(meta.key)
        if not data:
            return {"sent": False, "missing": True}
        result = await telegram.send_document(
            chat_id, (data, meta.filename, meta.content_type), caption=caption,
            reply_markup=reply_markup)
        if result.get("sent") and result.get("file_id"):
            # Cache only for the same file version (a re-upload clears it)
            async with db_session.SessionLocal() as db:
                await db.execute(update(FunnelFile)
                                 .where(FunnelFile.key == meta.key,
                                        FunnelFile.sha256 == meta.sha256)
                                 .values(tg_file_id=result["file_id"]))
                await db.commit()
    return result


async def deliver_pdf(entry_id: uuid.UUID, *, notify: bool = True) -> str:
    """Send the PDF to an entry and move it to `pdf_sent` (first time: lead upsert).

    `notify=False` (retry job): the "coming soon" text is sent only on the first
    move to pdf_pending, never on every retry.

    Returns "sent" | "pending" (no PDF uploaded yet, or Telegram failed and a retry
    is scheduled) | "blocked" | "failed" (a re-send to someone who already has it).
    Caller holds the person's lock.
    """
    async with db_session.SessionLocal() as db:
        entry = await db.get(FunnelEntry, entry_id)
        if entry is None or not entry.tg_chat_id:
            return "failed"
        booked = await repo.active_booking(db, entry.id) is not None
    result = await send_pdf_file(entry.tg_chat_id, reply_markup=None if booked else book_keyboard())

    if result.get("missing"):
        if await _set_pending(entry_id, failed=False) or notify:
            await telegram.send_message(entry.tg_chat_id, texts.PDF_PENDING)
        await _alert_once(_NO_PDF_ALERT_KEY,
                          "⚠️ <b>Lead-magnet PDF yuklanmagan</b>\nMijozlar qo'llanmani kutmoqda. "
                          "Admin panel → Voronka → Sozlamalar → PDF yuklang — ular avtomatik oladi.")
        return "pending"
    if not result.get("sent"):
        if repo.is_blocked(result):
            await repo.set_opted_out(entry_id)
            return "blocked"
        logger.warning("PDF not delivered to {}: {}", entry.tg_chat_id, result.get("error"))
        if entry.step == "pdf_sent":
            return "failed"          # they already have it; nothing to retry
        if await _set_pending(entry_id, failed=True) or notify:
            await telegram.send_message(entry.tg_chat_id, texts.PDF_PENDING)
        await _alert_once(_PDF_FAILED_ALERT_KEY,
                          "⚠️ <b>Qo'llanmani Telegram'ga yuborib bo'lmadi</b>\n"
                          f"Xato: {html.escape(str(result.get('error') or '')[:200])}\n"
                          "Tizim avtomatik qayta urinadi.")
        return "pending"

    if entry.step != "pdf_sent":
        await _mark_pdf_sent(entry_id)
    return "sent"


async def _set_pending(entry_id: uuid.UUID, *, failed: bool) -> bool:
    """Move to pdf_pending (a failure also schedules the next retry).
    Returns True when the person was not waiting yet (so tell them once)."""
    async with db_session.SessionLocal() as db:
        entry = await db.get(FunnelEntry, entry_id)
        if entry is None or entry.step == "pdf_sent":
            return False
        newly = entry.step != "pdf_pending"
        entry.step = "pdf_pending"
        if failed:
            entry.pdf_attempts = (entry.pdf_attempts or 0) + 1
            entry.pdf_retry_at = repo.now() + retry_delay(entry.pdf_attempts)
        repo.touch(entry)
        await db.commit()
        return newly


async def _mark_pdf_sent(entry_id: uuid.UUID) -> None:
    """Step first (the PDF went out — never lose that), then the lead in its own
    transaction so a lead problem cannot roll the step back."""
    async with db_session.SessionLocal() as db:
        entry = await db.get(FunnelEntry, entry_id)
        if entry is None:
            return
        entry.step = "pdf_sent"
        entry.pdf_sent_at = entry.pdf_sent_at or repo.now()
        entry.pdf_attempts = 0
        entry.pdf_retry_at = None
        repo.touch(entry)
        await db.commit()
    try:
        async with db_session.SessionLocal() as db:
            entry = await db.get(FunnelEntry, entry_id)
            if entry is None or not entry.tg_user_id:
                return
            lead = await repo.ensure_lead(db, entry)
            if lead.stage != "booked":
                lead.stage = "offer"
            lead.lead_score = max(lead.lead_score or 0, repo.LEAD_SCORE_PDF)
            source = texts.SOURCE_LABELS.get(entry.source, entry.source)
            if entry.ig_username:
                source += f" (@{entry.ig_username})"
            repo.log_system(
                db, lead,
                "🎁 Lead-magnet: qo'llanma yuborildi\n"
                f"Manba: {source}\nIsm: {entry.full_name or '—'}\n"
                f"Telefon: {entry.phone or '—'}\n"
                f"Sinf: {texts.grade_display(entry.grade) or '—'}",
                step="pdf_sent")
            await db.commit()
    except Exception as exc:  # noqa: BLE001
        logger.exception("Funnel lead upsert failed for {}: {}", entry_id, exc)


async def _alert_once(key: str, text: str) -> None:
    """Staff alert at most once an hour per kind."""
    try:
        if await store.seen_once(key, 3600):
            return
        await notifier.send_text(text)
    except Exception as exc:  # noqa: BLE001
        logger.warning("Funnel alert failed: {}", exc)


async def send_sales_message(chat_id: str, message: FunnelMessage) -> dict:
    """One sales-sequence message (optional image) with the booking button."""
    text = (message.text or "").strip()
    markup = book_keyboard()
    if not message.has_image:
        return await telegram.send_message(chat_id, text, reply_markup=markup)

    caption = text if tg_len(text) <= CAPTION_LIMIT else None
    version = int(message.updated_at.timestamp()) if message.updated_at else 0
    cache_key = _IMAGE_CACHE_KEY.format(bot=_bot_id(), message=message.id, version=version)
    photo = await store.get_value(cache_key)
    result: dict = {"sent": False}
    if photo:
        result = await telegram.send_photo(chat_id, photo, caption=caption,
                                           reply_markup=markup if caption else None)
    if not result.get("sent") and (not photo or _is_file_id_error(result)):
        async with db_session.SessionLocal() as db:
            data = (await db.execute(
                select(FunnelMessage.image).where(FunnelMessage.id == message.id)
            )).scalar_one_or_none()
        if data:
            result = await telegram.send_photo(
                chat_id, (bytes(data), message.image_content_type or "image/jpeg"),
                caption=caption, reply_markup=markup if caption else None)
            file_ids = result.get("file_ids") or []
            if result.get("sent") and file_ids and file_ids[0]:
                await store.set_value(cache_key, file_ids[0])
    if result.get("sent") and caption is None:
        # Text too long for a caption: image first, then the text with the button
        result = await telegram.send_message(chat_id, text, reply_markup=markup)
    elif not result.get("sent") and not repo.is_blocked(result):
        logger.warning("Sales image not sent ({}), sending text only", result.get("error"))
        result = await telegram.send_message(chat_id, text, reply_markup=markup)
    return result
