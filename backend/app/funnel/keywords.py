"""Keyword matcher for funnel comments/DMs.

Case-insensitive and Latin/Cyrillic tolerant: both "Wunderkind" and "Вундеркинд"
normalize to "vunderkind" (Cyrillic transliterated, w→v). A keyword matches the
whole text or a word inside it; long keywords (6+ letters) also match with a
suffix, because Uzbek glues suffixes on ("wunderkindga", "вундеркинддан").
"""
from __future__ import annotations

import re
import unicodedata

from app.config import settings

_CYR = {
    "а": "a", "б": "b", "в": "v", "г": "g", "ғ": "g", "д": "d", "е": "e", "ё": "yo",
    "ж": "j", "з": "z", "и": "i", "й": "y", "к": "k", "қ": "q", "л": "l", "м": "m",
    "н": "n", "о": "o", "ў": "o", "п": "p", "р": "r", "с": "s", "т": "t", "у": "u",
    "ф": "f", "х": "x", "ҳ": "h", "ц": "ts", "ч": "ch", "ш": "sh", "щ": "sh", "ъ": "",
    "ы": "i", "ь": "", "э": "e", "ю": "yu", "я": "ya",
}
_WORD = re.compile(r"[a-z0-9]+")
_SUFFIX_MIN_LEN = 6
MAX_EXTRA_WORDS = 2


def normalize(text: str) -> str:
    """Lower-case Latin form used for comparison ("Вундеркинд!" -> "vunderkind!")."""
    low = unicodedata.normalize("NFKC", text or "").casefold()
    out = "".join(_CYR.get(ch, ch) for ch in low)
    # Strip accents (ö -> o) so "Wünderkind" still matches
    out = "".join(c for c in unicodedata.normalize("NFKD", out) if not unicodedata.combining(c))
    return out.replace("w", "v")


def _words(text: str) -> list[str]:
    return _WORD.findall(normalize(text))


def parse_keywords(value: str) -> list[str]:
    """"wunderkind, вундеркинд" -> ["wunderkind", "вундеркинд"] (as typed, deduplicated)."""
    out: list[str] = []
    for part in re.split(r"[,;\n]", value or ""):
        part = part.strip()
        if part and part not in out:
            out.append(part)
    return out


def _word_matches(word: str, keyword: str) -> bool:
    return word == keyword or (len(keyword) >= _SUFFIX_MIN_LEN and word.startswith(keyword))


def _matching_keywords(text: str, keywords: list[str] | None) -> list[list[str]]:
    """Normalized word lists of the keywords found in `text`."""
    words = _words(text)
    found: list[list[str]] = []
    if not words:
        return found
    for keyword in parse_keywords(settings.FUNNEL_KEYWORDS) if keywords is None else keywords:
        key_words = _words(keyword)
        if not key_words:
            continue
        span = len(key_words)
        for i in range(len(words) - span + 1):
            window = words[i:i + span]
            # Multi-word keywords: all but the last word must match exactly
            if window[:-1] == key_words[:-1] and _word_matches(window[-1], key_words[-1]):
                found.append(key_words)
                break
    return found


def matches(text: str, keywords: list[str] | None = None) -> bool:
    """Does `text` contain one of the keywords (default: FUNNEL_KEYWORDS)?"""
    return bool(_matching_keywords(text, keywords))


# "Where is the guide / the link does not open" — someone who already got the
# link asks again (the button may not work for them, e.g. on a computer)
_LINK_REQUEST = re.compile(r"llanma|havola|link|ssilka|ssylka|pdf|ochilma|ishlama|kelma")


def asks_for_link(text: str) -> bool:
    return bool(_LINK_REQUEST.search(normalize(text).replace("'", "")))


def is_keyword_request(text: str, keywords: list[str] | None = None,
                       max_extra_words: int = MAX_EXTRA_WORDS) -> bool:
    """Stricter check for DMs: essentially just the keyword ("Wunderkind",
    "wunderkind yuboring 🙏") — not a question that happens to mention it
    ("Wunderkind maktabida narxlar qancha?" goes to the AI)."""
    if "?" in (text or ""):
        return False
    words = [w for w in (text or "").split() if any(ch.isalnum() for ch in w)]
    return any(len(words) - len(key) <= max_extra_words
               for key in _matching_keywords(text, keywords))
