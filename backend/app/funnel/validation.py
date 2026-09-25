"""Panel validation for FUNNEL_* / GSHEET_* settings beyond simple regexes.

Called from `runtime_config.validate` after the generic range/pattern checks.
Raises ValueError with an Uzbek message (shown in the panel as-is).
"""
from __future__ import annotations

import json
import re
from datetime import date

from app.funnel.keywords import _words, parse_keywords

# Channel limits: Instagram DM text 1000, button template text 640; Telegram
# message 4096, media caption 1024.
_MAX_LEN = {
    "FUNNEL_IG_COMMENT_REPLY": 1000,
    "FUNNEL_IG_DM_WELCOME": 1000,
    "FUNNEL_IG_NOT_FOLLOWING": 1000,
    "FUNNEL_IG_LINK_MESSAGE": 640,
    "FUNNEL_TG_COMMENT_REPLY": 4000,
    "FUNNEL_BOT_WELCOME": 4000,
    "FUNNEL_ASK_NAME": 4000,
    "FUNNEL_ASK_PHONE": 4000,
    "FUNNEL_ASK_GRADE": 4000,
    "FUNNEL_PDF_CAPTION": 1024,
    "FUNNEL_CONFIRM_TEXT": 4000,
    "FUNNEL_REMINDER_TEXT": 4000,
    "FUNNEL_ADDRESS": 300,
    "FUNNEL_KEYWORDS": 500,
    "FUNNEL_GRADES": 400,
}
_TELEGRAM_KEYS = frozenset({
    "FUNNEL_TG_COMMENT_REPLY", "FUNNEL_BOT_WELCOME", "FUNNEL_ASK_NAME", "FUNNEL_ASK_PHONE",
    "FUNNEL_ASK_GRADE", "FUNNEL_PDF_CAPTION", "FUNNEL_CONFIRM_TEXT", "FUNNEL_REMINDER_TEXT",
})
_MAX_GRADES = 24


def _tg_len(text: str) -> int:
    from app.telegram_business.menu import tg_len

    return tg_len(text)
_MAX_GRADE_LEN = 20            # keeps callback_data "fb:g:<grade>" under 64 bytes


def validate_value(key: str, val: str, label: str) -> None:
    limit = _MAX_LEN.get(key)
    # Telegram limits are in UTF-16 units (an emoji counts 2); Instagram in characters
    length = _tg_len(val) if key in _TELEGRAM_KEYS else len(val)
    if limit and length > limit:
        raise ValueError(f"{label}: {limit} belgidan oshmasin (hozir {length})")

    if key == "FUNNEL_KEYWORDS":
        if not any(len("".join(_words(k))) >= 3 for k in parse_keywords(val)):
            raise ValueError(f"{label}: kamida bitta 3+ harfli kalit so'z kiriting")
    elif key == "FUNNEL_GRADES":
        grades = [g.strip() for g in val.split(",") if g.strip()]
        if not grades or len(grades) > _MAX_GRADES:
            raise ValueError(f"{label}: 1–{_MAX_GRADES} ta qiymat, vergul bilan")
        if any(len(g) > _MAX_GRADE_LEN for g in grades):
            raise ValueError(f"{label}: har bir qiymat {_MAX_GRADE_LEN} belgidan oshmasin")
    elif key == "FUNNEL_HOLIDAYS":
        for raw in re.findall(r"\d{4}-\d{2}-\d{2}", val):
            try:
                date.fromisoformat(raw)
            except ValueError:
                raise ValueError(f"{label}: {raw} — bunday sana yo'q") from None
    elif key in ("FUNNEL_LOCATION_LAT", "FUNNEL_LOCATION_LON"):
        bound = 90 if key.endswith("LAT") else 180
        if not -bound <= float(val) <= bound:
            raise ValueError(f"{label}: -{bound} dan {bound} gacha bo'lsin")
    elif key == "GSHEET_SERVICE_ACCOUNT_JSON":
        try:
            data = json.loads(val)
        except ValueError:
            raise ValueError(f"{label}: JSON o'qib bo'lmadi — faylni to'liq ko'chiring") from None
        if not isinstance(data, dict) or not all(
                isinstance(data.get(k), str) and data.get(k) for k in ("client_email", "private_key")):
            raise ValueError(f"{label}: «client_email» va «private_key» bo'lishi shart")
    elif key == "GSHEET_SPREADSHEET_ID":
        from app.funnel.gsheet import spreadsheet_id

        if not spreadsheet_id(val):
            raise ValueError(f"{label}: jadval havolasi yoki ID'sini to'liq ko'chiring")
