"""Multiple funnels (SPEC §11): the funnel registry and routing.

All funnels share the §10 step template; each has its own keywords, optional
Instagram post filter, PDF, sales messages and text overrides. Flows work with
`FunnelView` — a plain snapshot of a funnel row (safe outside a DB session).

Routing (§11.2): active funnels only; for comments, funnels with a post filter
are checked before those without one, then by sort_order. The default funnel's
empty keyword list means FUNNEL_KEYWORDS.
"""
from __future__ import annotations

import re
import time
import unicodedata
import uuid
from dataclasses import dataclass, field
from typing import Mapping, Optional

from loguru import logger
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import settings
from app.db import session as db_session
from app.funnel import keywords as kw
from app.models.funnel import (
    DEFAULT_FUNNEL_NAME, DEFAULT_FUNNEL_SLUG, FUNNEL_TEXT_KEYS, Funnel,
)

SLUG_PATTERN = r"[a-z0-9_]{1,32}"
CHANNEL_PREFIX = "tgc"          # ?start=tgc (default) / ?start=tgc_<slug>
DIRECT_PREFIX = "f_"            # ?start=f_<slug> (ads / bio links)
_MEDIA_CACHE_KEY = "igmedia:{}"
_MEDIA_CACHE_TTL = 60 * 60 * 24 * 30
_SHORTCODE_URL = re.compile(r"instagram\.com/(?:[^/?#]+/)?(?:p|reel|reels|tv)/([A-Za-z0-9_-]+)")
_SHORTCODE = re.compile(r"[A-Za-z0-9_-]{5,64}")
_CACHE_TTL = 30.0               # seconds; funnel writes invalidate it at once
_cache: dict[int, tuple[float, list["FunnelView"]]] = {}


@dataclass(frozen=True)
class MediaFilter:
    ids: frozenset[str] = frozenset()
    shortcodes: frozenset[str] = frozenset()

    def __bool__(self) -> bool:
        return bool(self.ids or self.shortcodes)

    def overlaps(self, other: "MediaFilter") -> bool:
        return bool(self.ids & other.ids or self.shortcodes & other.shortcodes)


def parse_media(value: str) -> MediaFilter:
    """"17895…, https://www.instagram.com/p/C8xYz12/, C9abc" -> ids + shortcodes.
    Raises ValueError (Uzbek) on something that is neither."""
    ids: set[str] = set()
    codes: set[str] = set()
    for part in re.split(r"[,\s]+", value or ""):
        if not part:
            continue
        url = _SHORTCODE_URL.search(part)
        if url:
            codes.add(url[1])
        elif part.isdigit() and len(part) >= 5:
            ids.add(part)
        elif _SHORTCODE.fullmatch(part):
            codes.add(part)
        else:
            raise ValueError(f"«{part}» — Instagram post havolasi yoki media ID emas")
    return MediaFilter(frozenset(ids), frozenset(codes))


def normalize_media(value: str) -> str:
    """Canonical stored form: ids and shortcodes, comma separated, sorted."""
    media = parse_media(value)
    return ", ".join(sorted(media.ids) + sorted(media.shortcodes))


def normalize_keywords(value: str) -> str:
    return ", ".join(kw.parse_keywords(value))


@dataclass(frozen=True)
class FunnelView:
    id: uuid.UUID
    name: str
    slug: str
    is_active: bool
    is_default: bool
    keywords_raw: str = ""
    media_raw: str = ""
    texts: Mapping[str, str] = field(default_factory=dict)
    sort_order: int = 0

    @classmethod
    def of(cls, row: Funnel) -> "FunnelView":
        return cls(id=row.id, name=row.name, slug=row.slug, is_active=row.is_active,
                   is_default=row.is_default, keywords_raw=row.keywords or "",
                   media_raw=row.ig_media_ids or "", texts=dict(row.texts or {}),
                   sort_order=row.sort_order or 0)

    def text(self, key: str) -> str:
        """Per-funnel override, else the global setting (§11.1)."""
        value = self.texts.get(key) if key in FUNNEL_TEXT_KEYS else None
        if isinstance(value, str) and value.strip():
            return value
        return str(getattr(settings, key) or "")

    def keywords(self) -> list[str]:
        own = kw.parse_keywords(self.keywords_raw)
        if own or not self.is_default:
            return own
        return kw.parse_keywords(settings.FUNNEL_KEYWORDS)

    def media(self) -> MediaFilter:
        try:
            return parse_media(self.media_raw)
        except ValueError:
            logger.warning("Funnel {}: invalid Instagram post filter ignored", self.slug)
            return MediaFilter()

    def grade_options(self) -> list[str]:
        return [g.strip() for g in self.text("FUNNEL_GRADES").split(",") if g.strip()]

    @property
    def channel_payload(self) -> str:
        return CHANNEL_PREFIX if self.is_default else f"{CHANNEL_PREFIX}_{self.slug}"

    @property
    def direct_payload(self) -> str:
        return f"{DIRECT_PREFIX}{self.slug}"


# --------------------------------------------------------------------------- #
# Loading
# --------------------------------------------------------------------------- #
async def load_all(db: Optional[AsyncSession] = None) -> list[FunnelView]:
    """Every funnel, by sort_order (a handful of rows).

    Without `db` (webhooks, scheduler — every comment and group message routes
    through here) the list is cached for 30 s; funnel writes call `invalidate()`.
    With `db` it is always read fresh (admin API)."""
    if db is not None:
        rows = (await db.execute(select(Funnel).order_by(Funnel.sort_order, Funnel.created_at))
                ).scalars().all()
        return [FunnelView.of(r) for r in rows]
    key = id(db_session.SessionLocal)
    hit = _cache.get(key)
    if hit is not None and hit[0] > time.monotonic():
        return hit[1]
    async with db_session.SessionLocal() as session:
        views = await load_all(session)
    _cache.clear()
    _cache[key] = (time.monotonic() + _CACHE_TTL, views)
    return views


def invalidate() -> None:
    """Funnel created/changed/deleted/reordered: the next load_all() reads the DB."""
    _cache.clear()


async def get(db: AsyncSession, funnel_id: uuid.UUID) -> Optional[FunnelView]:
    row = await db.get(Funnel, funnel_id)
    return FunnelView.of(row) if row else None


async def default(db: AsyncSession) -> FunnelView:
    row = (await db.execute(select(Funnel).where(Funnel.is_default.is_(True)))).scalar_one_or_none()
    if row is None:
        row = await ensure_default(db)
    return FunnelView.of(row)


async def by_slug(db: AsyncSession, slug: str) -> Optional[FunnelView]:
    row = (await db.execute(select(Funnel).where(Funnel.slug == slug))).scalar_one_or_none()
    return FunnelView.of(row) if row else None


async def ensure_default(db: Optional[AsyncSession] = None) -> Funnel:
    """The default funnel always exists (the migration creates it; this is the
    safety net for empty databases, e.g. tests)."""
    if db is None:
        async with db_session.SessionLocal() as session:
            return await ensure_default(session)
    row = (await db.execute(select(Funnel).where(Funnel.is_default.is_(True)))).scalar_one_or_none()
    if row is None:
        row = Funnel(name=DEFAULT_FUNNEL_NAME, slug=DEFAULT_FUNNEL_SLUG, is_active=True,
                     is_default=True, keywords="", ig_media_ids="", texts={}, sort_order=0)
        db.add(row)
        await db.commit()
        invalidate()
        logger.info("Default funnel created")
    return row


async def from_payload(db: AsyncSession, payload: str) -> Optional[tuple[FunnelView, str]]:
    """Deep-link payload -> (funnel, entry source): tgc / tgc_<slug> / f_<slug>."""
    if payload == CHANNEL_PREFIX:
        return await default(db), "telegram_channel"
    if payload.startswith(f"{CHANNEL_PREFIX}_"):
        # A channel link with a renamed/deleted slug still counts as the channel
        funnel = await by_slug(db, payload[len(CHANNEL_PREFIX) + 1:])
        return (funnel or await default(db)), "telegram_channel"
    if payload.startswith(DIRECT_PREFIX):
        funnel = await by_slug(db, payload[len(DIRECT_PREFIX):])
        return (funnel, "telegram_direct") if funnel else None
    return None


# --------------------------------------------------------------------------- #
# Routing
# --------------------------------------------------------------------------- #
def _order(funnels: list[FunnelView], *, filtered_first: bool) -> list[FunnelView]:
    active = [f for f in funnels if f.is_active]
    return sorted(active, key=lambda f: (bool(f.media()) is not filtered_first, f.sort_order))


async def match_comment(funnels: list[FunnelView], text: str,
                        media_id: Optional[str]) -> Optional[FunnelView]:
    """Instagram comment: keyword AND (no post filter OR the post is listed)."""
    for funnel in _order(funnels, filtered_first=True):
        if not kw.matches(text, funnel.keywords()):
            continue
        media = funnel.media()
        if not media or await _media_listed(media, media_id):
            return funnel
    return None


def match_direct(funnels: list[FunnelView], text: str, *,
                 strict: bool) -> Optional[FunnelView]:
    """No post context (Instagram DM, Telegram group comment): unfiltered funnels
    first. `strict` = DM rule: only a (nearly) bare keyword counts."""
    check = kw.is_keyword_request if strict else kw.matches
    for funnel in _order(funnels, filtered_first=False):
        if check(text, funnel.keywords()):
            return funnel
    return None


async def _media_listed(media: MediaFilter, media_id: Optional[str]) -> bool:
    if not media_id:
        return False
    if media_id in media.ids:
        return True
    return bool(media.shortcodes) and await media_shortcode(media_id) in media.shortcodes


async def media_shortcode(media_id: str) -> Optional[str]:
    """Shortcode of an Instagram media (from its permalink), cached for 30 days."""
    from app.instagram.client import instagram
    from app.state.store import store

    key = _MEDIA_CACHE_KEY.format(media_id)
    try:
        cached = await store.get_value(key)
        if cached:
            return cached
    except Exception as exc:  # noqa: BLE001
        logger.warning("Media cache read failed: {}", exc)
    data = await instagram.get_media(media_id) or {}
    code = data.get("shortcode")
    if not code:
        match = _SHORTCODE_URL.search(str(data.get("permalink") or ""))
        code = match[1] if match else None
    if code:
        try:
            await store.set_value(key, code, ttl=_MEDIA_CACHE_TTL)
        except Exception as exc:  # noqa: BLE001
            logger.warning("Media cache write failed: {}", exc)
    return code


def keyword_collision(candidate: FunnelView,
                      others: list[FunnelView]) -> Optional[tuple[str, FunnelView]]:
    """(keyword, other funnel) when an active funnel with the same post scope would
    compete for the same comments (§11.2). Inactive funnels never collide."""
    if not candidate.is_active:
        return None
    mine = candidate.media()
    for other in others:
        if other.id == candidate.id or not other.is_active:
            continue
        theirs = other.media()
        same_scope = (not mine and not theirs) or mine.overlaps(theirs)
        if not same_scope:
            continue
        for a in candidate.keywords():
            for b in other.keywords():
                if kw.matches(a, [b]) or kw.matches(b, [a]):
                    return a, other
    return None


# --------------------------------------------------------------------------- #
# Slugs
# --------------------------------------------------------------------------- #
def slugify(name: str) -> str:
    """"Yozgi lager 2026" -> "yozgi_lager_2026" (Cyrillic transliterated)."""
    low = unicodedata.normalize("NFKC", name or "").casefold()
    text = "".join(kw._CYR.get(ch, ch) for ch in low)
    text = "".join(c for c in unicodedata.normalize("NFKD", text) if not unicodedata.combining(c))
    slug = re.sub(r"[^a-z0-9]+", "_", text).strip("_")[:32].strip("_")
    return slug or "voronka"


async def unique_slug(db: AsyncSession, base: str) -> str:
    taken = set((await db.execute(
        select(Funnel.slug).where(Funnel.slug.like(f"{base[:28]}%")))).scalars().all())
    if base not in taken:
        return base
    for n in range(2, 1000):
        candidate = f"{base[:28]}_{n}"
        if candidate not in taken:
            return candidate
    return f"{base[:20]}_{uuid.uuid4().hex[:8]}"


async def next_sort_order(db: AsyncSession) -> int:
    return int((await db.execute(select(func.max(Funnel.sort_order)))).scalar() or 0) + 1
