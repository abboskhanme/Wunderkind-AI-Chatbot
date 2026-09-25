"""Gemini provayder — google-genai, response_schema bilan strukturali JSON.

Asosiy provayder (gemini-3.6-flash — arzon/tez; 2.5 yangi kalitlarga yopilgan). Bilim tizim ko'rsatmasida
(system_instruction) uzatiladi.

Gemini 2.5 da fikrlash (thinking) `max_output_tokens` dan yeydi — cheklanmasa
JSON o'rtada kesiladi. Shu sabab fikrlash `AI_EFFORT` bo'yicha cheklanadi va
uning budjeti javob limitiga qo'shiladi. Gemini 3 modellari budjet o'rniga
`thinking_level` qabul qiladi.
"""
from __future__ import annotations

import asyncio

from google import genai
from google.genai import errors, types
from loguru import logger

from app.ai.base import AIProvider, T
from app.config import settings

# When the chosen model is overloaded (503/429/5xx) or too slow, the reply is
# retried once on this model instead of making the customer wait a minute.
FALLBACK_MODEL = "gemini-3.6-flash"
# Per-attempt limit: a normal reply takes 2-5 s; anything near this is a stuck call
ATTEMPT_TIMEOUT = 25.0
RETRY_PAUSE = 1.5
_RETRYABLE = {429, 500, 502, 503, 504}


# AI_EFFORT -> thinking budget (tokens) for Gemini 2.5 models
_BUDGET = {"low": 512, "medium": 2048, "high": 8192}
# AI_EFFORT -> thinking_level for Gemini 3+ models
_LEVEL = {"low": "LOW", "medium": "MEDIUM", "high": "HIGH"}


def _thinking(model: str, effort: str) -> tuple[types.ThinkingConfig | None, int]:
    """(thinking config, extra output tokens reserved for thinking)."""
    effort = (effort or "low").lower()
    if model.startswith("gemini-2.5"):
        budget = _BUDGET.get(effort, _BUDGET["low"])
        return types.ThinkingConfig(thinking_budget=budget), budget
    if model.startswith("gemini-2"):  # 2.0 — no thinking
        return None, 0
    return types.ThinkingConfig(thinking_level=_LEVEL.get(effort, "LOW")), _BUDGET["high"]


class GeminiProvider(AIProvider):
    def __init__(self) -> None:
        if not settings.GEMINI_API_KEY:
            raise RuntimeError("GEMINI_API_KEY o'rnatilmagan (AI_PROVIDER=gemini)")
        self._client = genai.Client(api_key=settings.GEMINI_API_KEY)

    async def generate(
        self, system: str, messages: list[dict], output_model: type[T]
    ) -> T:
        contents = [
            types.Content(
                # Gemini rollari: "user" | "model" (assistant -> model)
                role="model" if m["role"] == "assistant" else "user",
                parts=[types.Part(text=m["content"])],
            )
            for m in messages
        ]
        primary = settings.GEMINI_MODEL
        # Overload spikes are short: fallback model, then the fallback once more
        models = [primary] + ([FALLBACK_MODEL] if primary != FALLBACK_MODEL else []) \
            + [FALLBACK_MODEL]
        response = None
        for index, model in enumerate(models):
            last = index == len(models) - 1
            try:
                response = await self._call(model, system, contents, output_model)
                break
            except (asyncio.TimeoutError, errors.APIError) as exc:
                code = getattr(exc, "code", None)
                retryable = isinstance(exc, asyncio.TimeoutError) or code in _RETRYABLE
                if last or not retryable:
                    raise
                logger.warning("Gemini {} unavailable ({}) — retrying on {}",
                               model, code or "timeout", models[index + 1])
                if model == models[index + 1]:
                    await asyncio.sleep(RETRY_PAUSE)
        parsed = getattr(response, "parsed", None)
        if isinstance(parsed, output_model):
            return parsed
        text = response.text
        if not text:
            reason = None
            if response.candidates:
                reason = response.candidates[0].finish_reason
            raise RuntimeError(f"Gemini bo'sh javob qaytardi (finish_reason={reason})")
        # Fallback: xom JSON matnini validatsiya qilamiz
        return output_model.model_validate_json(text)

    async def _call(self, model: str, system: str, contents: list, output_model: type[T]):
        thinking, reserve = _thinking(model, settings.AI_EFFORT)
        return await asyncio.wait_for(
            self._client.aio.models.generate_content(
                model=model,
                contents=contents,
                config=types.GenerateContentConfig(
                    system_instruction=system,
                    max_output_tokens=settings.AI_MAX_TOKENS + reserve,
                    response_mime_type="application/json",
                    response_schema=output_model,
                    thinking_config=thinking,
                ),
            ),
            timeout=ATTEMPT_TIMEOUT,
        )
