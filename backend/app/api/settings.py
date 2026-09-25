"""Settings management (admin) + agent status."""
from __future__ import annotations

from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException

from app.core.deps import DB, AdminUser, CurrentUser, require_admin
from app.core.security import create_token
from app.core.settings_catalog import CATALOG, GROUPS
from app import runtime_config
from app.schemas.api import SettingsUpdate
from app.services.agent_status import agent_status

router = APIRouter(prefix="/settings", tags=["Settings"])


def _mask(value: str) -> str:
    if not value:
        return ""
    return "••••" + value[-4:] if len(value) > 8 else "••••"


async def _payload(db) -> dict:
    dbv = await runtime_config.db_values(db)
    groups = []
    for gid, title in GROUPS.items():
        items = []
        for item in CATALOG:
            if item.group != gid or item.hidden:
                continue
            baseline = runtime_config.display(runtime_config.BASELINE[item.key])
            resolved = dbv.get(item.key) or baseline
            entry = {
                "key": item.key, "label": item.label, "type": item.type,
                "secret": item.secret, "options": list(item.options),
                "placeholder": item.placeholder, "help": item.help,
                "is_set": bool(resolved),
                # Only when .env really provides it (code defaults are not ".env")
                "from_env": item.key in runtime_config.ENV_SET and item.key not in dbv,
                "default": runtime_config.display(runtime_config.BASELINE[item.key])
                if item.key not in runtime_config.ENV_SET and not item.secret else "",
            }
            if item.secret:
                entry["value"] = ""
                entry["masked"] = _mask(resolved)
            else:
                entry["value"] = resolved
                entry["masked"] = ""
            items.append(entry)
        groups.append({"id": gid, "title": title, "items": items})
    return {"groups": groups, "status": await agent_status()}


@router.get("", dependencies=[Depends(require_admin)])
async def get_settings(db: DB):
    return await _payload(db)


@router.put("", dependencies=[Depends(require_admin)])
async def update_settings(payload: SettingsUpdate, db: DB):
    try:
        changed = await runtime_config.save(db, payload.values)
    except ValueError as exc:
        raise HTTPException(400, str(exc) or "Qiymat noto'g'ri") from None
    from app.main import after_settings_change

    await after_settings_change(changed)
    return await _payload(db)


@router.get("/status")
async def status(_: CurrentUser):
    return await agent_status()


@router.post("/instagram/connect-url")
async def instagram_connect_url(user: AdminUser):
    from app.instagram.oauth import build_authorize_url, missing_config

    missing = missing_config()
    if missing:
        raise HTTPException(400, "Avval to'ldiring: " + ", ".join(missing))
    state = create_token(str(user.id), purpose="ig_connect", minutes=15)
    return {"url": build_authorize_url(state)}


@router.post("/instagram/import", dependencies=[Depends(require_admin)])
async def instagram_import(background: BackgroundTasks):
    from app.config import settings
    from app.instagram.importer import import_and_notify

    if not settings.IG_ACCESS_TOKEN:
        raise HTTPException(400, "Instagram ulanmagan")
    background.add_task(import_and_notify)
    return {"started": True}


@router.post("/ai/test", dependencies=[Depends(require_admin)])
async def ai_test():
    """Tiny real request: proves the key/model work (not just that a key is set)."""
    import asyncio

    from pydantic import BaseModel

    from app.ai.factory import get_provider
    from app.config import settings

    class Ping(BaseModel):
        reply: str

    try:
        provider = get_provider()
        out = await asyncio.wait_for(provider.generate(
            "Reply with one short Uzbek greeting word in `reply`.",
            [{"role": "user", "content": "Salom"}], Ping), timeout=60)
    except Exception as exc:  # noqa: BLE001
        return {"ok": False, "error": _short_error(exc)}
    model = settings.CLAUDE_MODEL if type(provider).__name__ == "ClaudeProvider" \
        else settings.GEMINI_MODEL
    return {"ok": True, "provider": type(provider).__name__.replace("Provider", "").lower(),
            "model": model, "reply": out.reply}


def _short_error(exc: Exception) -> str:
    text = str(exc) or type(exc).__name__
    low = text.lower()
    if "sozlanmagan" in low or "o'rnatilmagan" in low:
        return "AI kaliti kiritilmagan — Anthropic yoki Gemini kalitini kiriting va saqlang"
    if "authentication" in low or "invalid x-api-key" in low or "401" in low:
        return "API kaliti noto'g'ri yoki bekor qilingan"
    if "not_found" in low or "model" in low and "not" in low and "found" in low:
        return "Model nomi noto'g'ri — Claude modeli maydonini tekshiring"
    if "credit" in low or "billing" in low or "quota" in low:
        return "Hisobda mablag' yoki limit tugagan"
    if isinstance(exc, TimeoutError):
        return "AI javob bermadi (60 soniya)"
    return text[:200]


@router.post("/telegram/webhook", dependencies=[Depends(require_admin)])
async def telegram_webhook_reset():
    """Re-register the Telegram webhook now (e.g. after fixing PUBLIC_URL)."""
    from app.main import _tg_webhook_state, setup_telegram_webhook

    _tg_webhook_state.clear()
    await setup_telegram_webhook()
    return await agent_status()


@router.post("/telegram/test", dependencies=[Depends(require_admin)])
async def telegram_test():
    from app.telegram.notifier import send_text

    return await send_text("✅ Test xabar: AI agent bildirishnomalari ishlayapti.")
