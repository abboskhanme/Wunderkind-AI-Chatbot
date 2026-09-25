"""Instagram webhook — GET verify + POST (HMAC-SHA256 imzo tekshiruvi).

Meta 5 soniya ichida 200 kutadi, shuning uchun og'ir ish (AI + javob + baza)
BackgroundTasks'ga topshiriladi va 200 DARHOL qaytariladi.
"""
from __future__ import annotations

import hashlib
import hmac
import json
from typing import Optional

from fastapi import APIRouter, BackgroundTasks, Header, Request, Response
from loguru import logger

from app.config import settings
from app.funnel import instagram_gate as funnel_instagram
from app.instagram.models import IncomingEvent, parse_webhook
from app.processing.pipeline import process_event

router = APIRouter(prefix="/webhook", tags=["Instagram webhook"])


@router.get("/instagram")
async def verify(request: Request):
    """Meta webhook tasdiqlash: hub.challenge ni qaytaramiz."""
    params = request.query_params
    mode = params.get("hub.mode")
    token = params.get("hub.verify_token")
    challenge = params.get("hub.challenge")
    if mode == "subscribe" and settings.IG_VERIFY_TOKEN and token == settings.IG_VERIFY_TOKEN:
        logger.info("Webhook tasdiqlandi")
        return Response(content=challenge or "", media_type="text/plain")
    logger.warning("Webhook tasdiqlash rad etildi (token mos emas)")
    return Response(content="forbidden", status_code=403)


def _valid_signature(raw: bytes, signature: str | None) -> bool:
    if not settings.IG_APP_SECRET:
        # Without the app secret we cannot verify the sender — reject.
        logger.warning("IG_APP_SECRET is not set — webhook rejected")
        return False
    if not signature or not signature.startswith("sha256="):
        return False
    expected = hmac.new(
        settings.IG_APP_SECRET.encode(), raw, hashlib.sha256
    ).hexdigest()
    return hmac.compare_digest(signature.split("=", 1)[1], expected)


@router.post("/instagram")
async def receive(
    request: Request,
    background: BackgroundTasks,
    x_hub_signature_256: Optional[str] = Header(default=None),
):
    raw = await request.body()
    if not _valid_signature(raw, x_hub_signature_256):
        logger.warning("Webhook imzosi noto'g'ri")
        return Response(content="invalid signature", status_code=403)

    try:
        payload = json.loads(raw)
    except json.JSONDecodeError:
        return Response(content="bad json", status_code=400)

    # BARCHA ma'lum ID'larimizni beramiz: Instagram webhook'da qaysi birini
    # yuborishiga ishonib bo'lmaydi, mos kelmasa esa bot o'z izohiga javob
    # berib cheksiz halqaga tushadi.
    events = parse_webhook(
        payload,
        {settings.IG_USER_ID, settings.IG_ACCOUNT_ID},
        settings.IG_USERNAME,
    )
    for event in events:
        background.add_task(_route, event)

    # Meta'га darhol 200
    return Response(content="EVENT_RECEIVED", media_type="text/plain")


async def _route(event: IncomingEvent) -> None:
    """Lead-magnet funnel first (keyword comments, follow-gate DMs); the rest -> AI."""
    if await funnel_instagram.handle_event(event):
        return
    await process_event(event)
