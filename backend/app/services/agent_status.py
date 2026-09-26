"""What is connected / missing — shown on the dashboard and settings page."""
from __future__ import annotations

import time

from app.config import settings
from app.telegram_business.client import telegram

_bot_cache: dict[str, str] = {}


async def telegram_bot_username() -> str:
    token = settings.TG_SALES_BOT_TOKEN
    if not token:
        return ""
    if token not in _bot_cache:
        me = await telegram.get_me()
        if not me:
            return ""
        _bot_cache.clear()
        _bot_cache[token] = str(me.get("username") or "")
    return _bot_cache[token]


def ai_ready() -> bool:
    provider = (settings.AI_PROVIDER or "gemini").lower()
    if provider == "mock":
        return True
    return bool(settings.ANTHROPIC_API_KEY or settings.GEMINI_API_KEY)


async def telegram_webhook_state(expected_url: str | None) -> dict:
    """Is Telegram really delivering to us? {state, error} for the panel.

    state: not_configured | no_public_url | polling | ok | wrong_url | error
    """
    if not settings.TG_SALES_BOT_TOKEN:
        return {"state": "not_configured", "error": None}
    if not expected_url:
        from app.telegram_business.polling import polling_active

        if polling_active():
            return {"state": "polling", "error": None}
        return {"state": "no_public_url", "error": None}
    info = await telegram.get_webhook_info()
    if not info:
        return {"state": "error", "error": "Bot tokeni noto'g'ri yoki Telegram javob bermadi"}
    if info.get("url") != expected_url:
        return {"state": "wrong_url", "error": f"Hozirgi manzil: {info.get('url') or 'yo`q'}"}
    last = info.get("last_error_message")
    if last and info.get("last_error_date", 0) > time.time() - 3600:
        return {"state": "error", "error": last}
    return {"state": "ok", "error": None}


def legal_urls(base: str) -> dict:
    """Public URLs Meta asks for in the App Dashboard (SPEC §12.4)."""
    def url(path: str) -> str | None:
        return f"{base}{path}" if base else None

    return {
        "privacy": url("/privacy"),
        "terms": url("/terms"),
        "data_deletion_page": url("/data-deletion"),
        "data_deletion_callback": url("/connect/data-deletion"),
        "deauthorize": url("/connect/deauthorize"),
    }


async def agent_status() -> dict:
    base = settings.PUBLIC_URL.rstrip("/")
    tg_url = f"{base}/webhook/telegram" if base else None
    return {
        "ai_provider": settings.AI_PROVIDER,
        "ai_ready": ai_ready(),
        "instagram_connected": bool(settings.IG_ACCESS_TOKEN and settings.IG_USER_ID),
        "instagram_username": settings.IG_USERNAME or None,
        "instagram_token_issued_at": settings.IG_TOKEN_ISSUED_AT or None,
        "telegram_connected": telegram.enabled,
        "telegram_bot_username": (await telegram_bot_username()) or None,
        "notifications_ready": bool(settings.alert_bot_token and settings.TELEGRAM_CHAT_ID),
        "public_url": base or None,
        "webhooks": {
            "instagram": f"{base}/webhook/instagram" if base else None,
            "telegram": tg_url,
        },
        "legal_urls": legal_urls(base),
        "telegram_webhook": await telegram_webhook_state(tg_url),
        "instagram_ready": bool(settings.IG_APP_ID and settings.IG_APP_SECRET
                                and settings.IG_VERIFY_TOKEN and base),
    }
