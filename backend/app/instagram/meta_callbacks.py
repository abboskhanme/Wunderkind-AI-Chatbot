"""Meta callbacks required for App Review (SPEC §12.2) — public, signature-verified.

  POST /connect/data-deletion — "Data deletion request URL"
  POST /connect/deauthorize   — "Deauthorize callback URL"

Both are configured in the Meta App Dashboard under Instagram → API setup with
Instagram login → Business login settings. The `signed_request` format and its
verification are documented in `app.instagram.signed_request` (with sources).

Failure handling:
  * bad / missing signature, unknown algorithm, no user_id → 400 (Meta shows it
    as a failed callback; nothing is changed);
  * DB error after the request was recorded → still 200 with the confirmation
    code (the status page then shows "received") and staff are alerted to finish
    the deletion by hand; DB down before recording → 500 so Meta can retry;
  * repeated requests for the same user are harmless: a new code each time, the
    second deletion finds nothing to delete.
"""
from __future__ import annotations

import time
from typing import Optional
from urllib.parse import urlencode

from fastapi import APIRouter, BackgroundTasks, Request
from fastapi.responses import JSONResponse
from loguru import logger

from app.config import settings
from app.db import session as db_session
from app.instagram.signed_request import SignedRequestError, parse_signed_request
from app.legal import deletion

router = APIRouter(tags=["Meta callbacks"])


async def _read_signed_request(request: Request) -> Optional[str]:
    """Meta posts a form field; a JSON body is accepted too (manual tests/tools)."""
    ctype = (request.headers.get("content-type") or "").lower()
    try:
        if "application/json" in ctype:
            body = await request.json()
            value = body.get("signed_request") if isinstance(body, dict) else None
        else:
            form = await request.form()
            value = form.get("signed_request")
    except Exception:  # noqa: BLE001 — malformed body = missing field
        return None
    return value if isinstance(value, str) else None


async def _verified_payload(request: Request, name: str) -> dict | JSONResponse:
    try:
        return parse_signed_request(await _read_signed_request(request), settings.IG_APP_SECRET)
    except SignedRequestError as exc:
        if not settings.IG_APP_SECRET:
            logger.error("Meta {} callback refused: IG_APP_SECRET is not set", name)
        else:
            logger.warning("Meta {} callback refused: {}", name, exc)
        return JSONResponse({"detail": "Invalid signed_request"}, status_code=400)


def _status_url(request: Request, code: str) -> str:
    base = settings.PUBLIC_URL.rstrip("/") or str(request.base_url).rstrip("/")
    return f"{base}/data-deletion?{urlencode({'code': code})}"


@router.post("/connect/data-deletion", include_in_schema=False)
async def data_deletion_callback(request: Request, background: BackgroundTasks):
    started = time.monotonic()
    payload = await _verified_payload(request, "data-deletion")
    if isinstance(payload, JSONResponse):
        return payload
    user_id = payload["user_id"]
    own = deletion.is_own_account(user_id)

    async with db_session.SessionLocal() as db:
        row = await deletion.create_request(db, user_id)     # DB down → 500, Meta retries
        code = row.confirmation_code
        result: Optional[deletion.DeletionResult] = None
        try:
            result = await deletion.delete_instagram_user(db, user_id)
            await deletion.mark_completed(db, row)
        except Exception as exc:  # noqa: BLE001
            await db.rollback()
            logger.exception("Data deletion {} failed, left as 'received': {}", code, exc)

    disconnected = await deletion.disconnect_instagram() if own else None
    background.add_task(deletion.after_deletion, code, result, disconnected)
    logger.info(
        "Meta data deletion code={} outcome={} leads={} entries={} own_account={} {}ms",
        code, "completed" if result else "failed", result.leads if result else 0,
        result.entries if result else 0, own, int((time.monotonic() - started) * 1000),
    )
    return {"url": _status_url(request, code), "confirmation_code": code}


@router.post("/connect/deauthorize", include_in_schema=False)
async def deauthorize_callback(request: Request, background: BackgroundTasks):
    payload = await _verified_payload(request, "deauthorize")
    if isinstance(payload, JSONResponse):
        return payload
    own = deletion.is_own_account(payload["user_id"])
    if own:
        disconnected = await deletion.disconnect_instagram()
        background.add_task(deletion.after_deauthorize, disconnected)
    logger.info("Meta deauthorize own_account={}", own)
    return {"success": True}
