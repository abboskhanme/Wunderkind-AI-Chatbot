"""Meta `signed_request` parsing and verification (data deletion / deauthorize).

Format (verified 2026-09-26 against Meta's docs):
  https://developers.facebook.com/docs/development/create-an-app/app-dashboard/data-deletion-callback
  (page "Updated: Nov 7, 2025") — Meta POSTs a form field `signed_request`
  (the PHP sample reads `$_POST['signed_request']`) whose value is
  `<base64url(signature)>.<base64url(payload JSON)>`; the signature is
  HMAC-SHA256 over the still-encoded payload segment with the app secret; the
  payload is `{"algorithm": "HMAC-SHA256", "expires": ..., "issued_at": ...,
  "user_id": "<app-scoped id>"}`.
  https://developers.facebook.com/docs/instagram-platform/instagram-api-with-instagram-login/create-a-meta-app-with-instagram
  — for Instagram API with Instagram Login both the "Deauthorize callback URL"
  and the "Data deletion request URL" are set under Instagram → API setup with
  Instagram login → Set up Instagram business login → Business login settings,
  so they are signed with the Instagram app secret (IG_APP_SECRET), the same
  secret that signs our Instagram webhooks.
"""
from __future__ import annotations

import base64
import binascii
import hashlib
import hmac
import json
from typing import Any

# A real signed request is ~200-400 chars; anything huge is not from Meta
MAX_SIGNED_REQUEST_LENGTH = 4096


class SignedRequestError(ValueError):
    """Missing, malformed or wrongly signed request (the reason is for logs only)."""


def _b64url_decode(segment: str) -> bytes:
    padded = segment + "=" * (-len(segment) % 4)
    try:
        return base64.b64decode(padded, altchars=b"-_", validate=True)
    except (binascii.Error, ValueError) as exc:
        raise SignedRequestError("segment is not base64url") from exc


def parse_signed_request(signed_request: str | None, secret: str) -> dict[str, Any]:
    """Verify the HMAC and return the payload. Raises SignedRequestError."""
    if not secret:
        raise SignedRequestError("app secret is not configured")
    if not signed_request:
        raise SignedRequestError("signed_request is missing")
    if len(signed_request) > MAX_SIGNED_REQUEST_LENGTH:
        raise SignedRequestError("signed_request is too long")
    encoded_sig, sep, payload = signed_request.strip().partition(".")
    if not sep or not encoded_sig or not payload:
        raise SignedRequestError("signed_request has no '.' separator")

    signature = _b64url_decode(encoded_sig)
    expected = hmac.new(secret.encode(), payload.encode(), hashlib.sha256).digest()
    if not hmac.compare_digest(signature, expected):
        raise SignedRequestError("signature mismatch")

    try:
        data = json.loads(_b64url_decode(payload))
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise SignedRequestError("payload is not JSON") from exc
    if not isinstance(data, dict):
        raise SignedRequestError("payload is not an object")
    algorithm = str(data.get("algorithm") or "").upper()
    if algorithm != "HMAC-SHA256":
        raise SignedRequestError(f"unexpected algorithm {algorithm!r}")
    user_id = str(data.get("user_id") or "").strip()
    if not user_id or len(user_id) > 64:
        raise SignedRequestError("payload has no usable user_id")
    data["user_id"] = user_id
    return data


def build_signed_request(payload: dict[str, Any], secret: str) -> str:
    """The inverse (tests and the manual check in docs/META_APP_REVIEW.md)."""
    body = base64.urlsafe_b64encode(json.dumps(payload).encode()).rstrip(b"=").decode()
    sig = hmac.new(secret.encode(), body.encode(), hashlib.sha256).digest()
    return f"{base64.urlsafe_b64encode(sig).rstrip(b'=').decode()}.{body}"
