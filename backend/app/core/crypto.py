"""Encryption at rest for secret settings (Fernet, key derived from SECRET_KEY)."""
from __future__ import annotations

import base64
import hashlib

from cryptography.fernet import Fernet, InvalidToken

from app.config import settings

_PREFIX = "enc:"


def _fernet() -> Fernet:
    digest = hashlib.sha256(f"settings:{settings.SECRET_KEY}".encode()).digest()
    return Fernet(base64.urlsafe_b64encode(digest))


def encrypt_secret(plain: str) -> str:
    return _PREFIX + _fernet().encrypt(plain.encode()).decode()


def decrypt_secret(stored: str | None) -> str:
    if not stored:
        return ""
    if not stored.startswith(_PREFIX):
        return stored
    try:
        return _fernet().decrypt(stored[len(_PREFIX):].encode()).decode()
    except InvalidToken:
        # SECRET_KEY changed — the value is unreadable; treat as unset.
        return ""
