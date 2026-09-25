"""Per-key asyncio locks (single worker): one person, one booking slot at a time."""
from __future__ import annotations

import asyncio

_MAX_IDLE = 5000
_locks: dict[str, asyncio.Lock] = {}
_loop: asyncio.AbstractEventLoop | None = None


def lock(key: str) -> asyncio.Lock:
    """The lock for `key` (e.g. "tg:123", "ig:456", "slot:202609261000")."""
    global _loop, _locks
    loop = asyncio.get_running_loop()
    if loop is not _loop:
        # A lock is bound to the loop it was first awaited on (tests run many loops)
        _loop, _locks = loop, {}
    found = _locks.get(key)
    if found is None:
        if len(_locks) > _MAX_IDLE:
            # Drop only idle locks: unlocked AND nobody queued on them
            for k in [k for k, v in _locks.items()
                      if not v.locked() and not getattr(v, "_waiters", None)]:
                _locks.pop(k, None)
        found = _locks[key] = asyncio.Lock()
    return found
