"""Holat saqlash — DM suhbat konteksti + dedup.

REDIS_URL berilgan bo'lsa Redis, aks holda ichki xotira fallback (bitta worker
uchun yetarli; prod'da bir nechта worker bo'lsa Redis tavsiya etiladi).
Suhbat tarixining ASOSIY manbasi PostgreSQL (lead_messages) — bu yerdagisi
tezkor kesh; dedup, pauza va tezlik cheklovlari esa faqat shu yerda.
"""
from __future__ import annotations

import hashlib
import json
import time

from loguru import logger

from app.config import settings

# Redis — fast cache (primary memory is the lead_messages table).
# Kept long so the bot has context even if the DB read fails.
_HISTORY_MAX = 40  # DM suhbatда saqlanadigan oxirgi xabarlar soni
_HISTORY_TTL = 60 * 60 * 24 * 30  # 30 kun
_SENT_TTL = 60 * 10  # bot yuborgan xabar izi (echo shu oraliqda qaytadi)
# Umumiy kalit-qiymat (masalan Telegram Business ulanishi) — uzoq saqlanadi
_VALUE_TTL = 60 * 60 * 24 * 180


def sent_key(user_id: str, text: str) -> str:
    """Bot yuborgan xabarni keyin echo'da tanib olish uchun barmoq izi."""
    return f"sent:{user_id}:{hashlib.sha1(text.strip().encode()).hexdigest()[:16]}"


class _MemoryStore:
    """Redis'siz ishlash uchun oddiy ichki xotira fallback."""

    def __init__(self) -> None:
        self._seen: dict[str, float] = {}
        self._history: dict[str, list[dict]] = {}
        self._paused: dict[str, float] = {}
        self._rate: dict[str, tuple[float, int]] = {}
        self._values: dict[str, tuple[float, str]] = {}

    async def seen_once(self, key: str, ttl: int) -> bool:
        now = time.time()
        # tozalash
        for k, exp in list(self._seen.items()):
            if exp < now:
                self._seen.pop(k, None)
        if key in self._seen:
            return True
        self._seen[key] = now + ttl
        return False

    async def bump_rate(self, key: str, window: int) -> int:
        """Oynadagi hisoblagichni oshiradi va yangi qiymatini qaytaradi."""
        now = time.time()
        exp, cnt = self._rate.get(key, (0.0, 0))
        if exp < now:
            exp, cnt = now + window, 0
        cnt += 1
        self._rate[key] = (exp, cnt)
        return cnt

    async def get_history(self, user_id: str) -> list[dict]:
        return list(self._history.get(user_id, []))

    async def append_turn(self, user_id: str, role: str, content: str) -> None:
        hist = self._history.setdefault(user_id, [])
        hist.append({"role": role, "content": content})
        del hist[:-_HISTORY_MAX]

    async def mark_sent(self, user_id: str, text: str) -> None:
        self._seen[sent_key(user_id, text)] = time.time() + _SENT_TTL

    async def was_sent_by_bot(self, user_id: str, text: str) -> bool:
        exp = self._seen.get(sent_key(user_id, text))
        return bool(exp and exp > time.time())

    async def pause(self, user_id: str, hours: int) -> None:
        self._paused[user_id] = time.time() + hours * 3600

    async def unpause(self, user_id: str) -> None:
        self._paused.pop(user_id, None)

    async def set_value(self, key: str, value: str, ttl: int = _VALUE_TTL) -> None:
        self._values[key] = (time.time() + ttl, value)

    async def get_value(self, key: str) -> str | None:
        item = self._values.get(key)
        if not item:
            return None
        exp, value = item
        if exp <= time.time():
            self._values.pop(key, None)
            return None
        return value

    async def forget(self, user_id: str) -> None:
        """Drop the cached conversation and pause flag (user data deletion)."""
        self._history.pop(user_id, None)
        self._paused.pop(user_id, None)

    async def is_paused(self, user_id: str) -> bool:
        exp = self._paused.get(user_id)
        if not exp:
            return False
        if exp <= time.time():
            self._paused.pop(user_id, None)
            return False
        return True


class _RedisStore:
    def __init__(self, url: str) -> None:
        import redis.asyncio as redis

        self._r = redis.from_url(url, decode_responses=True)

    async def seen_once(self, key: str, ttl: int) -> bool:
        # SET NX: kalit yo'q bo'lsa qo'yadi va True qaytaradi (ya'ni birinchi marta)
        was_set = await self._r.set(f"dedup:{key}", "1", nx=True, ex=ttl)
        return not was_set

    async def bump_rate(self, key: str, window: int) -> int:
        """Oynadagi hisoblagichni oshiradi va yangi qiymatini qaytaradi."""
        k = f"rate:{key}"
        cnt = await self._r.incr(k)
        if cnt == 1:
            await self._r.expire(k, window)
        return int(cnt)

    async def get_history(self, user_id: str) -> list[dict]:
        raw = await self._r.lrange(f"hist:{user_id}", 0, -1)
        return [json.loads(x) for x in raw]

    async def append_turn(self, user_id: str, role: str, content: str) -> None:
        key = f"hist:{user_id}"
        await self._r.rpush(key, json.dumps({"role": role, "content": content}))
        await self._r.ltrim(key, -_HISTORY_MAX, -1)
        await self._r.expire(key, _HISTORY_TTL)

    async def mark_sent(self, user_id: str, text: str) -> None:
        await self._r.set(sent_key(user_id, text), "1", ex=_SENT_TTL)

    async def was_sent_by_bot(self, user_id: str, text: str) -> bool:
        return bool(await self._r.get(sent_key(user_id, text)))

    async def pause(self, user_id: str, hours: int) -> None:
        await self._r.set(f"pause:{user_id}", "1", ex=max(1, hours) * 3600)

    async def unpause(self, user_id: str) -> None:
        await self._r.delete(f"pause:{user_id}")

    async def set_value(self, key: str, value: str, ttl: int = _VALUE_TTL) -> None:
        await self._r.set(f"kv:{key}", value, ex=ttl)

    async def get_value(self, key: str) -> str | None:
        return await self._r.get(f"kv:{key}")

    async def forget(self, user_id: str) -> None:
        """Drop the cached conversation and pause flag (user data deletion)."""
        await self._r.delete(f"hist:{user_id}", f"pause:{user_id}")

    async def is_paused(self, user_id: str) -> bool:
        return bool(await self._r.get(f"pause:{user_id}"))


def _build():
    if settings.REDIS_URL:
        logger.info("Holat: Redis ({})", settings.REDIS_URL)
        return _RedisStore(settings.REDIS_URL)
    logger.info("Holat: ichki xotira (Redis yo'q)")
    return _MemoryStore()


store = _build()
