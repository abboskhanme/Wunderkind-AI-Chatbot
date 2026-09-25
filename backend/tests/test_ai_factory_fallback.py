"""Tanlangan AI provayder sozlanmagan bo'lsa — ikkinchisiga o'tadi.

Real hodisa: sozlamada provayder «claude» ga o'zgartirilgan, lekin Anthropic
kaliti kiritilmagan edi — agent har bir xabarda yiqilib, mijozga umuman javob
bermay qoldi. To'g'ri xatti-harakat: sozlangan boshqa provayder bilan ishlashda
davom etish.
"""
import pytest

from app.ai import factory
from app.config import settings


@pytest.fixture(autouse=True)
def _reset():
    """Har testdan oldin/keyin singleton keshi va sozlamalarni tozalaymiz."""
    factory.get_provider.cache_clear()
    saved = (settings.AI_PROVIDER, settings.ANTHROPIC_API_KEY, settings.GEMINI_API_KEY)
    yield
    settings.AI_PROVIDER, settings.ANTHROPIC_API_KEY, settings.GEMINI_API_KEY = saved
    factory.get_provider.cache_clear()


def test_falls_back_to_gemini_when_claude_key_missing():
    settings.AI_PROVIDER = "claude"
    settings.ANTHROPIC_API_KEY = ""
    settings.GEMINI_API_KEY = "test-key"

    provider = factory.get_provider()
    assert type(provider).__name__ == "GeminiProvider"


def test_falls_back_to_claude_when_gemini_key_missing():
    settings.AI_PROVIDER = "gemini"
    settings.GEMINI_API_KEY = ""
    settings.ANTHROPIC_API_KEY = "test-key"

    provider = factory.get_provider()
    assert type(provider).__name__ == "ClaudeProvider"


def test_uses_chosen_provider_when_configured():
    """Ikkalasi ham sozlangan bo'lsa — tanlangani ishlatiladi."""
    settings.AI_PROVIDER = "gemini"
    settings.GEMINI_API_KEY = "test-key"
    settings.ANTHROPIC_API_KEY = "test-key"

    assert type(factory.get_provider()).__name__ == "GeminiProvider"


def test_clear_error_when_nothing_configured():
    """Hech qaysi kalit yo'q bo'lsa — tushunarli xato, qayerga yozishni ko'rsatadi."""
    settings.AI_PROVIDER = "claude"
    settings.ANTHROPIC_API_KEY = ""
    settings.GEMINI_API_KEY = ""

    with pytest.raises(RuntimeError) as exc:
        factory.get_provider()
    assert "Sozlamalar" in str(exc.value)


def test_mock_is_never_used_as_fallback():
    """Mock ataylab tanlanadi — avtomatik o'tilmaydi (mijozga soxta javob ketmasin)."""
    settings.AI_PROVIDER = "claude"
    settings.ANTHROPIC_API_KEY = ""
    settings.GEMINI_API_KEY = ""

    with pytest.raises(RuntimeError):
        factory.get_provider()


def test_gemini_is_default_provider():
    """Provayder tanlanmagan bo'lsa — Gemini."""
    settings.AI_PROVIDER = ""
    settings.GEMINI_API_KEY = "test-key"
    settings.ANTHROPIC_API_KEY = "test-key"

    assert type(factory.get_provider()).__name__ == "GeminiProvider"


def test_gemini_thinking_is_capped_and_reserved():
    """Fikrlash budjeti cheklanadi va javob limitiga qo'shiladi (JSON kesilmasin)."""
    from app.ai.gemini_provider import _thinking

    cfg, reserve = _thinking("gemini-2.5-flash", "low")
    assert cfg.thinking_budget == 512 and reserve == 512
    cfg, reserve = _thinking("gemini-2.0-flash", "low")
    assert cfg is None and reserve == 0
    cfg, _ = _thinking("gemini-3-flash", "high")
    assert cfg.thinking_level == "HIGH"
