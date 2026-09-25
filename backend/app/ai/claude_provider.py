"""Claude provayder — AsyncAnthropic, strukturali chiqish + prompt caching.

`messages.parse(output_format=...)` Pydantic modelidan sxema quradi (ixtiyoriy
maydonlarni to'g'ri hal qiladi), API'ga yuboradi va javobni avtomatik validatsiya
qiladi. Tizim ko'rsatmasi (persona + bilim) `cache_control: ephemeral` bilan
keshlanadi — har javobda bilim keshdan o'qiladi (arzon/tez).

Opus 5'da fikrlash (thinking) sukut bo'yicha YOQIQ va u ham `max_tokens` dan
yeydi — shu sabab AI_MAX_TOKENS 2048 dan past bo'lmasin, aks holda javob
o'rtada kesiladi. Tezlik/narxni `AI_EFFORT` (low/medium/high) boshqaradi.
Arzonroq kerak bo'lsa CLAUDE_MODEL=claude-sonnet-5 yoki claude-haiku-4-5.
"""
from __future__ import annotations

from anthropic import AsyncAnthropic

from app.ai.base import AIProvider, T
from app.config import settings


class ClaudeProvider(AIProvider):
    def __init__(self) -> None:
        if not settings.ANTHROPIC_API_KEY:
            raise RuntimeError("ANTHROPIC_API_KEY o'rnatilmagan (AI_PROVIDER=claude)")
        self._client = AsyncAnthropic(api_key=settings.ANTHROPIC_API_KEY)

    async def generate(
        self, system: str, messages: list[dict], output_model: type[T]
    ) -> T:
        response = await self._client.messages.parse(
            model=settings.CLAUDE_MODEL,
            max_tokens=settings.AI_MAX_TOKENS,
            # Sotuv javobi qisqa — past "effort" tez va arzon javob beradi.
            output_config={"effort": settings.AI_EFFORT},
            system=[
                {
                    "type": "text",
                    "text": system,
                    "cache_control": {"type": "ephemeral"},
                }
            ],
            output_format=output_model,
            messages=messages,
        )
        parsed = response.parsed_output
        if parsed is None:
            raise RuntimeError(
                f"Claude javobi sxemaga mos kelmadi (stop_reason={response.stop_reason})"
            )
        return parsed
