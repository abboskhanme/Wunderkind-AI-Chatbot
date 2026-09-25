"""AI provayder fabrikasi — `AI_PROVIDER` bo'yicha birini beradi (singleton).

Tanlangan provayder sozlanmagan bo'lsa (kalit yo'q), agent YIQILMAYDI:
ikkinchisi sozlangan bo'lsa o'shanga o'tadi va logga ogohlantirish yozadi.
Sababi amaliy — sozlamada provayder almashtirilib, kalit kiritilmay qolsa
butun agent jim bo'lib qolardi va buni faqat traceback'dan bilish mumkin edi.
"""
from __future__ import annotations

from functools import lru_cache

from loguru import logger

from app.ai.base import AIProvider
from app.config import settings


def _build(name: str) -> AIProvider:
    if name == "claude":
        from app.ai.claude_provider import ClaudeProvider

        return ClaudeProvider()
    if name == "gemini":
        from app.ai.gemini_provider import GeminiProvider

        return GeminiProvider()
    if name == "mock":
        # Kalitsiz sinash uchun (tashqi API chaqirmaydi)
        from app.ai.mock_provider import MockProvider

        return MockProvider()
    raise RuntimeError(f"Noma'lum AI_PROVIDER: {name!r} (claude|gemini|mock)")


@lru_cache
def get_provider() -> AIProvider:
    want = (settings.AI_PROVIDER or "gemini").strip().lower()

    # "mock" ataylab tanlanadi — unga avtomatik o'tib ketish noto'g'ri bo'lardi
    # (mijozga soxta javob ketardi), shuning uchun zaxira ro'yxatida yo'q.
    order = [want] + [p for p in ("gemini", "claude") if p != want]

    problems: list[str] = []
    for name in order:
        try:
            provider = _build(name)
        except Exception as exc:  # noqa: BLE001
            problems.append(f"{name}: {exc}")
            continue
        if name != want:
            logger.warning(
                "AI provayder «{}» sozlanmagan ({}) — «{}» ga o'tildi. "
                "Sozlamalarda kalitni to'ldiring.",
                want, problems[-1] if problems else "?", name,
            )
        return provider

    raise RuntimeError(
        "Hech qaysi AI provayder sozlanmagan. Admin panel > Sozlamalar > "
        "Sun'iy intellekt bo'limida kalit kiriting. Sabablar: "
        + "; ".join(problems)
    )
