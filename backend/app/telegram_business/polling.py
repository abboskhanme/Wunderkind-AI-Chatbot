"""Local long polling for the Telegram sales bot.

Telegram webhooks need a public HTTPS URL. On a developer machine without one
(`PUBLIC_URL` empty) the bot pulls updates with `getUpdates` instead and feeds
them into the same handler the webhook uses. As soon as `PUBLIC_URL` is set,
polling steps aside and the webhook takes over (the two are mutually exclusive
in the Bot API).
"""
from __future__ import annotations

import asyncio

import httpx
from fastapi import BackgroundTasks
from loguru import logger

from app.config import settings
from app.telegram_business.client import telegram
from app.telegram_business.webhook import handle_update

_POLL_TIMEOUT = 25  # seconds Telegram holds the request open
_IDLE_SLEEP = 5
_ALLOWED = [
    "message", "edited_message", "callback_query",
    "business_connection", "business_message", "edited_business_message",
]

_running: set[asyncio.Task] = set()


def polling_active() -> bool:
    return settings.TG_POLLING and telegram.enabled and not settings.PUBLIC_URL


async def _dispatch(update: dict) -> None:
    background = BackgroundTasks()
    try:
        await handle_update(update, background)
        await background()
    except Exception:  # noqa: BLE001
        logger.exception("Telegram update {} failed", update.get("update_id"))


async def run_polling() -> None:
    """Runs for the app's lifetime; idles while polling is not applicable."""
    offset = 0
    webhook_cleared_for = ""
    async with httpx.AsyncClient(timeout=_POLL_TIMEOUT + 10) as http:
        while True:
            if not polling_active():
                webhook_cleared_for = ""
                await asyncio.sleep(_IDLE_SLEEP)
                continue
            token = settings.TG_SALES_BOT_TOKEN
            base = f"{settings.TG_API_BASE.rstrip('/')}/bot{token}"
            try:
                if webhook_cleared_for != token:
                    # getUpdates is refused while a webhook is set
                    await http.post(f"{base}/deleteWebhook")
                    webhook_cleared_for = token
                    offset = 0
                    logger.info("Telegram long polling started (no PUBLIC_URL)")
                resp = await http.post(f"{base}/getUpdates", json={
                    "offset": offset, "timeout": _POLL_TIMEOUT, "allowed_updates": _ALLOWED,
                })
                data = resp.json()
            except (httpx.HTTPError, ValueError) as exc:
                logger.warning("Telegram getUpdates failed: {}", exc)
                await asyncio.sleep(_IDLE_SLEEP)
                continue
            if not data.get("ok"):
                logger.warning("Telegram getUpdates error: {}", data.get("description"))
                await asyncio.sleep(_IDLE_SLEEP)
                continue
            for update in data.get("result") or []:
                offset = max(offset, int(update.get("update_id", 0)) + 1)
                task = asyncio.create_task(_dispatch(update))
                _running.add(task)
                task.add_done_callback(_running.discard)
