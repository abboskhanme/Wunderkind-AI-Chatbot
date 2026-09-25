"""Operator actions on a conversation: send a reply, pause/resume the AI."""
from __future__ import annotations

from datetime import datetime, timedelta, timezone
from typing import Optional

from app.config import settings
from app.instagram.client import instagram
from app.models.lead import Lead
from app.state.store import store
from app.telegram_business.client import telegram

_FREE = timedelta(hours=24)
_HUMAN_AGENT = timedelta(days=7)


def store_key(lead: Lead) -> str:
    return f"tg:{lead.external_id}" if lead.channel == "telegram" else lead.external_id


def window(channel: str, last_customer_at: Optional[datetime]) -> str:
    """open | human_agent | closed — can staff still write to this person?"""
    if channel == "telegram":
        return "open"
    if not last_customer_at:
        return "closed"
    if last_customer_at.tzinfo is None:
        last_customer_at = last_customer_at.replace(tzinfo=timezone.utc)
    age = datetime.now(timezone.utc) - last_customer_at
    if age <= _FREE:
        return "open"
    if age <= _HUMAN_AGENT:
        return "human_agent"
    return "closed"


async def send_reply(lead: Lead, text: str) -> dict:
    """Send an operator message. Returns {"sent", "error"?, "tag"?}."""
    key = store_key(lead)
    if lead.channel == "telegram":
        if not telegram.enabled:
            return {"sent": False, "error": "Telegram bot sozlanmagan"}
        from app.telegram_business.webhook import connection_for_chat

        await store.mark_sent(key, text)
        result = await telegram.send_message(
            lead.external_id, text,
            business_connection_id=await connection_for_chat(lead.external_id),
        )
    else:
        if not settings.IG_ACCESS_TOKEN:
            return {"sent": False, "error": "Instagram ulanmagan"}
        win = window("instagram", lead.last_customer_at)
        if win == "closed":
            return {"sent": False, "error": (
                "Instagram javob oynasi yopilgan (mijozning oxirgi xabaridan 7 kun "
                "o'tgan). Telefon orqali bog'laning.")}
        await store.mark_sent(key, text)
        result = await instagram.send_dm_result(
            lead.external_id, text, human_agent=win == "human_agent")
    # No auto-pause after an operator reply: the AI keeps answering
    # (client's choice 2026-09-25). Use the per-chat AI toggle to silence it.
    return result


async def is_paused(lead: Lead) -> bool:
    return await store.is_paused(store_key(lead))


# Manual "AI off" from the panel lasts until switched back on (not 12h)
_MANUAL_OFF_HOURS = 24 * 365 * 5


async def set_ai(lead: Lead, enabled: bool) -> bool:
    key = store_key(lead)
    if enabled:
        await store.unpause(key)
    else:
        await store.pause(key, _MANUAL_OFF_HOURS)
    return await store.is_paused(key)
