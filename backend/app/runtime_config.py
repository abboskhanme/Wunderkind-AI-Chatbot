"""Runtime configuration: DB settings overlaid on the `.env` baseline.

Replaces NUR's `remote_config` (which fetched config from the ERP over HTTP):
here the settings table is local, so `reload()` reads it directly and applies
values onto the shared `settings` object in place — no restart needed.
"""
from __future__ import annotations

import re
from typing import Any, Optional
from zoneinfo import ZoneInfo

from loguru import logger
from sqlalchemy import delete, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import Settings, settings
from app.core.crypto import decrypt_secret, encrypt_secret
from app.core.settings_catalog import ALLOWED_KEYS, CATALOG_BY_KEY
from app.db import session as db_session
from app.models.setting import Setting

# `.env` / default values captured once — used when a DB value is removed.
_ENV = Settings()
BASELINE: dict[str, Any] = {k: getattr(_ENV, k) for k in ALLOWED_KEYS}
# Keys actually given in the environment / .env (not just code defaults)
ENV_SET: frozenset[str] = frozenset(_ENV.model_fields_set) & ALLOWED_KEYS
_TRUE = {"ha", "true", "1", "yes", "on"}


def _field_type(key: str) -> type:
    return type(BASELINE.get(key, ""))


def coerce(key: str, raw: str) -> Any:
    """String from DB/UI -> the Python type of the settings field."""
    kind = _field_type(key)
    if kind is bool:
        return str(raw).strip().lower() in _TRUE
    if kind is int:
        return int(str(raw).strip())
    return raw


def display(value: Any) -> str:
    """Python value -> string shown in the panel."""
    if isinstance(value, bool):
        return "ha" if value else "yo'q"
    return "" if value is None else str(value)


# Sensible bounds for numeric settings
_RANGES: dict[str, tuple[int, int]] = {
    "AI_MAX_TOKENS": (1024, 16000),
    "FOLLOWUP_AFTER_HOURS": (1, 20),
    "BOT_PAUSE_HOURS": (1, 720),
    "CMT_LIMIT_PER_POST": (1, 1000),
    "CMT_LIMIT_TOTAL": (1, 5000),
    "FUNNEL_SLOT_MINUTES": (10, 240),
    "FUNNEL_SLOT_CAPACITY": (1, 50),
    "FUNNEL_BOOK_DAYS_AHEAD": (1, 60),
}
_HHMM = (r"([01]?\d|2[0-3]):[0-5]\d", "HH:MM ko'rinishida bo'lsin (masalan 09:00)")
# Format checks: (regex, Uzbek hint)
_PATTERNS: dict[str, tuple[str, str]] = {
    "TG_SALES_BOT_TOKEN": (r"\d{5,}:[A-Za-z0-9_-]{30,}",
                           "@BotFather bergan token ko'rinishida bo'lsin (123456:ABC...)"),
    "TELEGRAM_BOT_TOKEN": (r"\d{5,}:[A-Za-z0-9_-]{30,}",
                           "@BotFather bergan token ko'rinishida bo'lsin (123456:ABC...)"),
    "TG_WEBHOOK_SECRET": (r"[A-Za-z0-9_-]{16,256}",
                          "16+ belgi, faqat lotin harflari, raqam, _ va -"),
    "TELEGRAM_CHAT_ID": (r"\s*(-?\d+|@\w{4,})(\s*[,;]\s*(-?\d+|@\w{4,}))*\s*",
                         "chat ID raqamlarini vergul bilan yozing (masalan 123456789, -1001234567890)"),
    "IG_APP_ID": (r"\d{6,}", "faqat raqamlardan iborat bo'lsin"),
    "IG_APP_SECRET": (r"[A-Za-z0-9]{16,}", "Meta'dagi App Secret'ni aynan ko'chiring"),
    "ANTHROPIC_API_KEY": (r"sk-ant-[A-Za-z0-9_-]{20,}", "«sk-ant-» bilan boshlanadigan kalit bo'lsin"),
    "CLAUDE_MODEL": (r"claude-[a-z0-9.-]+", "masalan claude-sonnet-5"),
    "GEMINI_MODEL": (r"gemini-[a-z0-9.-]+", "masalan gemini-3.6-flash"),
    "COMPANY_NAME": (r".{1,80}", "1–80 belgi"),
    "FUNNEL_TG_CHANNEL": (r"@[A-Za-z][A-Za-z0-9_]{3,31}|-100\d{5,}",
                          "@username yoki -100 bilan boshlanadigan ID bo'lsin"),
    "FUNNEL_TG_DISCUSSION_CHAT_ID": (r"-\d{5,}", "guruh ID'si «-100…» ko'rinishida bo'lsin"),
    "FUNNEL_WORK_DAYS": (r"\s*[1-7](\s*-\s*[1-7])?(\s*,\s*[1-7](\s*-\s*[1-7])?)*\s*",
                         "1–7 raqamlari: «1-6» yoki «1,2,3,5» ko'rinishida"),
    "FUNNEL_DAY_START": _HHMM,
    "FUNNEL_DAY_END": _HHMM,
    "FUNNEL_REMINDER_TIME": _HHMM,
    "FUNNEL_HOLIDAYS": (r"\s*\d{4}-\d{2}-\d{2}([\s,;]+\d{4}-\d{2}-\d{2})*[\s,;]*",
                        "sanalarni YYYY-MM-DD ko'rinishida vergul bilan yozing"),
    "FUNNEL_LOCATION_LAT": (r"-?\d{1,2}(\.\d+)?", "son bo'lsin (masalan 41.311081)"),
    "FUNNEL_LOCATION_LON": (r"-?\d{1,3}(\.\d+)?", "son bo'lsin (masalan 69.240562)"),
    "FUNNEL_BOOK_BUTTON": (r".{1,64}", "1–64 belgi"),
    "FUNNEL_STAFF_NAME": (r".{1,80}", "1–80 belgi"),
    "FUNNEL_STAFF_PHONE": (r"[+\d][\d\s()-]{4,30}", "telefon raqami bo'lsin (masalan +998 90 123 45 67)"),
    "GSHEET_WORKSHEET": (r"[^\[\]*?:/\\]{1,100}", "1–100 belgi, [ ] * ? : / \\ belgilarisiz"),
}


def validate(key: str, val: str) -> None:
    """Reject values that would break the agent (raises ValueError, Uzbek text)."""
    item = CATALOG_BY_KEY[key]
    label = item.label
    if item.type == "select" and item.options and val not in item.options:
        raise ValueError(f"{label}: faqat {', '.join(item.options)}")
    if _field_type(key) is int:
        try:
            number = int(val)
        except ValueError:
            raise ValueError(f"{label}: butun son kiriting") from None
        if number < 0:
            raise ValueError(f"{label}: manfiy bo'lishi mumkin emas")
    if key in _RANGES:
        low, high = _RANGES[key]
        if not low <= int(val) <= high:
            raise ValueError(f"{label}: {low} dan {high} gacha bo'lsin")
    pattern = _PATTERNS.get(key)
    if pattern and not re.fullmatch(pattern[0], val):
        raise ValueError(f"{label}: {pattern[1]}")
    if key == "TIMEZONE":
        try:
            ZoneInfo(val)
        except Exception:  # noqa: BLE001
            raise ValueError("Vaqt mintaqasi noto'g'ri (masalan Asia/Tashkent)") from None
    if key == "DAILY_REPORT_TIME":
        match = re.fullmatch(r"(\d{1,2}):(\d{2})", val)
        if not match or int(match[1]) > 23 or int(match[2]) > 59:
            raise ValueError("Hisobot vaqti HH:MM ko'rinishida bo'lsin (masalan 20:00)")
    if key.startswith(("FUNNEL_", "GSHEET_")):
        from app.funnel.validation import validate_value

        validate_value(key, val, label)


async def db_values(db: AsyncSession) -> dict[str, str]:
    rows = (await db.execute(select(Setting))).scalars().all()
    return {r.key: decrypt_secret(r.value) for r in rows if r.value}


def apply(values: dict[str, str]) -> list[str]:
    """Apply DB values (missing -> baseline) onto `settings`. Returns changed keys."""
    changed: list[str] = []
    for key in ALLOWED_KEYS:
        raw = values.get(key)
        value = BASELINE[key]
        if raw not in (None, ""):
            try:
                value = coerce(key, raw)
            except (TypeError, ValueError):
                logger.warning("Setting {} has an invalid value, using default", key)
        if value != getattr(settings, key):
            setattr(settings, key, value)
            changed.append(key)
    if changed:
        logger.info("Settings applied: {}", ", ".join(sorted(changed)))
        from app.ai.factory import get_provider

        get_provider.cache_clear()
    return changed


async def reload(db: Optional[AsyncSession] = None) -> list[str]:
    if db is not None:
        return apply(await db_values(db))
    async with db_session.SessionLocal() as session:
        return apply(await db_values(session))


async def save(db: AsyncSession, values: dict[str, Optional[str]]) -> list[str]:
    """Upsert (or delete on empty) the given keys, commit and apply live."""
    unknown = set(values) - ALLOWED_KEYS
    if unknown:
        raise ValueError(f"Noma'lum kalit(lar): {', '.join(sorted(unknown))}")
    for key, val in values.items():
        if val is None or str(val).strip() == "":
            await db.execute(delete(Setting).where(Setting.key == key))
            continue
        item = CATALOG_BY_KEY[key]
        val = str(val).strip() if item.type != "textarea" else str(val)
        validate(key, val)
        stored = encrypt_secret(val) if CATALOG_BY_KEY[key].secret else val
        row = await db.get(Setting, key)
        if row:
            row.value = stored
        else:
            db.add(Setting(key=key, value=stored))
    await db.commit()
    return await reload(db)


async def push_config(values: dict[str, str]) -> bool:
    """Persist values the agent obtained itself (IG OAuth token, account ids)."""
    try:
        async with db_session.SessionLocal() as db:
            await save(db, values)
        return True
    except Exception as exc:  # noqa: BLE001
        logger.error("Could not persist settings {}: {}", sorted(values), exc)
        return False
