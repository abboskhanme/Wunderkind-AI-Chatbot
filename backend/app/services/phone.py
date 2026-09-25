"""Phone number extraction from free text (ported from NUR ERP leads API)."""
from __future__ import annotations

import re
from typing import Optional

_PHONE_CANDIDATE_RE = re.compile(r"(?<![\w+])(\+?\d[\d\s\-()]{6,20}\d)(?!\w)")

# O'zbek mobil/shahar kodlari — "+998"siz yozilgan 9 xonali raqam uchun
_UZ_CODES = {
    "20", "33", "50", "55", "71", "77", "78", "88",
    "90", "91", "93", "94", "95", "97", "98", "99",
}


def extract_phone(text: str) -> Optional[str]:
    """Xabar matnidan telefon raqamini ajratadi (xalqaro formatda qaytaradi).

    Qabul qilinadigan ko'rinishlar:
      +79145895911 / +7 914 589-59-11  -> +79145895911   (Rossiya/Qozog'iston)
      +998 90 111 22 33                -> +998901112233
      998901112233 / 901112233         -> +998901112233
      89145895911                      -> +79145895911   (RF ichki formati)
    Narx va boshqa sonlar («150000000», «12 000 000») rad etiladi.
    """
    for m in _PHONE_CANDIDATE_RE.finditer(text or ""):
        raw = m.group(1).strip()
        digits = re.sub(r"\D", "", raw)
        has_plus = raw.startswith("+")

        # 1) Xalqaro yozuv ("+" bilan) — davlat kodidan qat'i nazar
        if has_plus and 10 <= len(digits) <= 15:
            return f"+{digits}"
        # 2) "+"siz, lekin tanish davlat kodi bilan
        if len(digits) == 12 and digits[:3] in ("998", "996", "992"):
            return f"+{digits}"
        if len(digits) == 11 and digits[0] in ("7", "8") and digits[1] == "9":
            return f"+7{digits[1:]}"          # RF/KZ mobil (8 yoki 7 bilan)
        if len(digits) == 10 and digits[0] == "9":
            return f"+7{digits}"              # davlat kodisiz RF mobil
        # 3) O'zbek raqami davlat kodisiz — faqat haqiqiy operator kodi bilan
        if len(digits) == 9 and digits[:2] in _UZ_CODES:
            return f"+998{digits}"
    return None
