"""Bilim bazasi — KNOWLEDGE_DIR ichidagi .md fayllarni yuklaydi va keshlaydi.

Foydalanuvchi mahsulot/narx/FAQ ni shu papkaga qo'yadi. Kesh xotirada saqlanadi;
fayl o'zgargach `reload()` chaqirib yangilash mumkin (yoki konteynerni restart).
"""
from __future__ import annotations

from pathlib import Path

from loguru import logger

from app.config import settings

_cache: str | None = None


def _load_from_disk() -> str:
    base = Path(settings.KNOWLEDGE_DIR)
    if not base.exists():
        logger.warning("Bilim papkasi topilmadi: {}", base.resolve())
        return ""
    parts: list[str] = []
    for path in sorted(base.rglob("*.md")):
        try:
            parts.append(path.read_text(encoding="utf-8"))
        except OSError as exc:  # noqa: PERF203
            logger.error("Bilim faylini o'qib bo'lmadi {}: {}", path, exc)
    text = "\n\n---\n\n".join(p.strip() for p in parts if p.strip())
    logger.info("Bilim bazasi yuklandi: {} fayl, {} belgi", len(parts), len(text))
    return text


def _from_settings() -> str:
    """Knowledge text from the panel's "Bilim bazasi" settings ("" if empty)."""
    sections = [
        ("Maktab haqida", settings.KB_COMPANY),
        ("Sinflar, ta'lim dasturi va to'lov", settings.KB_COURSES),
        ("Qabul tartibi va kun tartibi", settings.KB_SCHEDULE),
        ("Aksiyalar va chegirmalar", settings.KB_PROMO),
        ("Ko'p so'raladigan savol-javoblar", settings.KB_FAQ),
        ("Muloqot qoidalari", settings.KB_RULES),
    ]
    parts = [f"## {title}\n{val.strip()}" for title, val in sections if val and val.strip()]
    return "\n\n".join(parts)


def get_knowledge() -> str:
    # Panel knowledge first; files in KNOWLEDGE_DIR are the fallback.
    remote = _from_settings()
    if remote:
        return remote
    global _cache
    if _cache is None:
        _cache = _load_from_disk()
    return _cache


def reload() -> str:
    """Bilim faylini diskdan qayta o'qiydi (keshni yangilaydi)."""
    global _cache
    _cache = _load_from_disk()
    return _cache
