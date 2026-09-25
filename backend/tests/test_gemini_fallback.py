"""Overloaded Gemini model (503) or a stuck call → one retry on the fallback model."""
import asyncio

import pytest
from google.genai import errors

from app.ai import gemini_provider as gp
from app.config import settings
from app.models_ai import AgentOutput, LeadInfo

_OUT = AgentOutput(reply="ok", language="uz-Latn", intent="greeting", stage="greeting",
                   lead_score=10, is_hot_lead=False, move_to_dm=False,
                   escalate_to_human=False, lead=LeadInfo())


class _Resp:
    parsed = _OUT
    text = ""
    candidates = []


def _provider(monkeypatch, behaviour):
    monkeypatch.setattr(settings, "GEMINI_API_KEY", "k")
    monkeypatch.setattr(settings, "GEMINI_MODEL", "gemini-3.5-flash-lite")
    provider = gp.GeminiProvider()
    calls: list[str] = []

    async def fake_call(model, system, contents, output_model):
        calls.append(model)
        return await behaviour(model)

    monkeypatch.setattr(provider, "_call", fake_call)
    return provider, calls


def _run(provider):
    return asyncio.run(provider.generate("sys", [{"role": "user", "content": "salom"}], AgentOutput))


def test_overloaded_model_falls_back(monkeypatch):
    async def behaviour(model):
        if model == "gemini-3.5-flash-lite":
            raise errors.ServerError(503, {"error": {"message": "high demand"}})
        return _Resp()

    provider, calls = _provider(monkeypatch, behaviour)
    assert _run(provider).reply == "ok"
    assert calls == ["gemini-3.5-flash-lite", gp.FALLBACK_MODEL]


def test_timeout_falls_back(monkeypatch):
    async def behaviour(model):
        if model == "gemini-3.5-flash-lite":
            raise asyncio.TimeoutError
        return _Resp()

    provider, calls = _provider(monkeypatch, behaviour)
    assert _run(provider).reply == "ok"
    assert calls == ["gemini-3.5-flash-lite", gp.FALLBACK_MODEL]


def test_non_retryable_error_is_raised(monkeypatch):
    async def behaviour(model):
        raise errors.ClientError(400, {"error": {"message": "bad request"}})

    provider, calls = _provider(monkeypatch, behaviour)
    with pytest.raises(errors.ClientError):
        _run(provider)
    assert calls == ["gemini-3.5-flash-lite"]


def test_fallback_retried_once_when_also_overloaded(monkeypatch):
    monkeypatch.setattr(gp, "RETRY_PAUSE", 0)
    attempts = {"n": 0}

    async def behaviour(model):
        attempts["n"] += 1
        if attempts["n"] < 3:
            raise errors.ServerError(503, {"error": {"message": "high demand"}})
        return _Resp()

    provider, calls = _provider(monkeypatch, behaviour)
    assert _run(provider).reply == "ok"
    assert calls == ["gemini-3.5-flash-lite", gp.FALLBACK_MODEL, gp.FALLBACK_MODEL]
