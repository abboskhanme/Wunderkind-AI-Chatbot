"""Buttons under sales messages (SPEC §14): recording who pressed what.

- A plain button is a callback `fm:<button id hex>`; the bot records the click.
- A link button points at `/go/b/<token>` (when PUBLIC_URL is set): the token
  carries the entry and the button, signed with SECRET_KEY; the redirect records
  the click and forwards to the link. Without PUBLIC_URL (or without an entry,
  e.g. a test message) the plain link is used and the click is not tracked.

Only the first click of an entry per button is stored; it is what the
`clicked` / `not_clicked` conditions of other messages read. A new click at once
sends the "clicked" follow-ups with no delay (app.funnel.sales).
"""
from __future__ import annotations

import base64
import binascii
import hashlib
import hmac
import re
import uuid
from typing import Optional

from fastapi import APIRouter, BackgroundTasks, Request
from fastapi.responses import HTMLResponse, RedirectResponse, Response
from loguru import logger
from sqlalchemy.exc import IntegrityError

from app.config import settings
from app.db import session as db_session
from app.funnel import locks, repo
from sqlalchemy import select

from app.models.funnel import FunnelButtonClick, FunnelEntry, FunnelMessage, FunnelMessageButton
from app.models.lead import Lead
from app.state.store import store
from app.telegram_business.client import telegram

CALLBACK_PREFIX = "fm:"
# Link previews (a forwarded message, a pasted link) fetch with GET too — they are
# not the recipient opening the link
_PREVIEW_UA = re.compile(
    r"TelegramBot|WhatsApp|facebookexternalhit|Facebot|meta-externalagent|Twitterbot|"
    r"Slackbot|Discordbot|LinkedInBot|SkypeUriPreview|Viber|vkShare|Googlebot|bingbot|"
    r"Applebot|YandexBot|redditbot|Embedly|bot\b|crawler|spider", re.IGNORECASE)
# (entry, button) link clicks queued but not recorded yet: a replayed link must not
# pile up background tasks behind the person's lock
_pending: set[tuple[uuid.UUID, uuid.UUID]] = set()
_MAC_BYTES = 12
_TOKEN_BYTES = 16 + 16 + _MAC_BYTES
CLICKED_NOTICE = "✅ Qabul qilindi"
STALE_NOTICE = "Bu tugma endi ishlamaydi"

router = APIRouter(tags=["Funnel buttons"])


# --------------------------------------------------------------------------- #
# Link tokens
# --------------------------------------------------------------------------- #
def _key() -> bytes:
    return hmac.new(settings.SECRET_KEY.encode(), b"funnel-button-click",
                    hashlib.sha256).digest()


def click_token(entry_id: uuid.UUID, button_id: uuid.UUID) -> str:
    raw = entry_id.bytes + button_id.bytes
    mac = hmac.new(_key(), raw, hashlib.sha256).digest()[:_MAC_BYTES]
    return base64.urlsafe_b64encode(raw + mac).rstrip(b"=").decode()


def parse_token(token: str) -> Optional[tuple[uuid.UUID, uuid.UUID]]:
    """(entry id, button id), or None for anything not signed by us."""
    try:
        data = base64.urlsafe_b64decode(token + "=" * (-len(token) % 4))
    except (binascii.Error, ValueError):
        return None
    if len(data) != _TOKEN_BYTES:
        return None
    raw, mac = data[:32], data[32:]
    if not hmac.compare_digest(mac, hmac.new(_key(), raw, hashlib.sha256).digest()[:_MAC_BYTES]):
        return None
    return uuid.UUID(bytes=raw[:16]), uuid.UUID(bytes=raw[16:])


def button_url(button: FunnelMessageButton, entry_id: Optional[uuid.UUID]) -> str:
    """The link a person gets: tracked through our redirect when possible."""
    if entry_id is None or not settings.PUBLIC_URL:
        return str(button.url)
    return f"{settings.PUBLIC_URL.rstrip('/')}/go/b/{click_token(entry_id, button.id)}"


def callback_data(button: FunnelMessageButton) -> str:
    return f"{CALLBACK_PREFIX}{button.id.hex}"          # 35 bytes (Telegram: ≤ 64)


# --------------------------------------------------------------------------- #
# Recording
# --------------------------------------------------------------------------- #
async def record_click(entry_id: uuid.UUID, button: FunnelMessageButton) -> bool:
    """Store the first click of this entry on this button (+ a line on the lead).
    Returns False when it was already clicked before."""
    try:
        async with db_session.SessionLocal() as db:
            db.add(FunnelButtonClick(entry_id=entry_id, message_id=button.message_id,
                                     button_id=button.id, clicked_at=repo.now()))
            await db.commit()
    except IntegrityError:
        return False
    try:
        async with db_session.SessionLocal() as db:
            entry = await db.get(FunnelEntry, entry_id)
            lead = await db.get(Lead, entry.lead_id) if entry and entry.lead_id else None
            if lead is not None:
                repo.log_system(db, lead, f"🔘 Tugma bosildi: «{button.text}»",
                                step="button_click", button_id=str(button.id))
                await db.commit()
    except Exception as exc:  # noqa: BLE001 — the click itself is already stored
        logger.warning("Button click lead log failed for {}: {}", entry_id, exc)
    return True


async def _click_and_follow_up(entry_id: uuid.UUID, button: FunnelMessageButton,
                               on_new_click=None) -> bool:
    """Record the click; a new click sends its instant follow-ups. Returns True
    for a new click. `on_new_click` runs before the follow-ups (stop the button
    spinner at once). Caller holds the person's lock."""
    from app.funnel import sales

    if not await record_click(entry_id, button):
        return False
    if on_new_click is not None:
        await on_new_click()
    await sales.send_click_followups(entry_id, button)
    return True


async def _seen_callback(callback_id: str) -> bool:
    try:
        return await store.seen_once(f"fnl:tgcb:{callback_id}", settings.DEDUP_TTL)
    except Exception as exc:  # noqa: BLE001 — a store outage must not drop the click
        logger.warning("Button callback dedup failed (continuing): {}", exc)
        return False


# --------------------------------------------------------------------------- #
# Telegram callback (`fm:*`)
# --------------------------------------------------------------------------- #
def _parse_callback(data: str) -> Optional[uuid.UUID]:
    try:
        return uuid.UUID(hex=data[len(CALLBACK_PREFIX):])
    except ValueError:
        return None


async def handle_callback(callback: dict) -> None:
    callback_id = str(callback.get("id") or "")
    chat = (callback.get("message") or {}).get("chat") or {}
    user_id = str((callback.get("from") or {}).get("id") or "")
    notice: Optional[str] = CLICKED_NOTICE
    answered = False

    async def answer_now() -> None:
        nonlocal answered
        answered = True
        if callback_id:
            await telegram.answer_callback_query(callback_id, None)

    try:
        if chat.get("type") != "private" or not user_id:
            return
        if callback_id and await _seen_callback(callback_id):
            notice = None
            return
        button_id = _parse_callback(str(callback.get("data") or ""))
        async with locks.lock(f"tg:{user_id}"):
            async with db_session.SessionLocal() as db:
                button = await db.get(FunnelMessageButton, button_id) if button_id else None
                message = await db.get(FunnelMessage, button.message_id) if button else None
                entry = (await repo.entry_by_tg(db, user_id, message.funnel_id)
                         if message else None)
            if button is None:
                notice = STALE_NOTICE
                return
            if entry is None:
                return             # a test message in a staff chat: nothing to record
            await _click_and_follow_up(entry.id, button, on_new_click=answer_now)
    except Exception as exc:  # noqa: BLE001
        logger.exception("Funnel button callback failed: {}", exc)
    finally:
        if callback_id and not answered:
            await telegram.answer_callback_query(callback_id, notice)


# --------------------------------------------------------------------------- #
# Link redirect
# --------------------------------------------------------------------------- #
def _gone() -> HTMLResponse:
    from app.funnel.landing import _page

    return _page("Havola eskirgan", "<div class=\"card\"><h1>Havola eskirgan</h1>"
                 "<p>Bu tugma endi ishlamaydi. Telegram botdagi yangi xabarlarni ko'ring.</p>"
                 "</div>", 404)


async def _after_link_click(entry_id: uuid.UUID, button: FunnelMessageButton,
                            tg_user_id: str) -> None:
    try:
        async with locks.lock(f"tg:{tg_user_id}"):
            await _click_and_follow_up(entry_id, button)
    except Exception as exc:  # noqa: BLE001
        logger.exception("Funnel link click handling failed: {}", exc)
    finally:
        _pending.discard((entry_id, button.id))


def _is_person(request: Request) -> bool:
    """HEAD requests and link-preview fetchers are not the recipient's click."""
    if request.method != "GET":
        return False
    return not _PREVIEW_UA.search(request.headers.get("user-agent") or "")


@router.api_route("/go/b/{token}", methods=["GET", "HEAD"], include_in_schema=False)
async def button_redirect(token: str, request: Request,
                          background: BackgroundTasks) -> Response:
    parsed = parse_token(token) if len(token) <= 80 else None
    if parsed is None:
        return _gone()
    entry_id, button_id = parsed
    async with db_session.SessionLocal() as db:
        button = await db.get(FunnelMessageButton, button_id)
        entry = await db.get(FunnelEntry, entry_id)
        clicked = entry is not None and (await db.execute(
            select(FunnelButtonClick.id).where(FunnelButtonClick.entry_id == entry_id,
                                               FunnelButtonClick.button_id == button_id)
            .limit(1))).first() is not None
    if button is None or not button.url:
        return _gone()
    key = (entry_id, button_id)
    if (_is_person(request) and entry is not None and entry.tg_user_id and not clicked
            and key not in _pending):
        _pending.add(key)
        background.add_task(_after_link_click, entry_id, button, entry.tg_user_id)
    return RedirectResponse(button.url, status_code=302, headers={
        "Cache-Control": "no-store", "Referrer-Policy": "no-referrer",
        "X-Robots-Tag": "noindex, nofollow"})
