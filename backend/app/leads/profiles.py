"""Customer account profiles (SPEC §13) — collected automatically.

  Telegram  — every private-chat update carries the person's first/last name,
              username, language and Premium flag; a shared contact carries the
              phone. Once a day `getChat` adds bio, birthdate, personal channel.
  Instagram — comments carry the username; the User Profile API adds name,
              username, photo, follower count and follow/verified flags (only
              after the person messaged us — Meta's consent rule).

Instagram never exposes phone numbers; Telegram only when the person shares
their contact. Everything here is best effort: a failure never blocks a reply.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any, Optional
from urllib.parse import urlparse

import httpx
from loguru import logger
from sqlalchemy import or_, select, update
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import settings
from app.db import session as db_session
from app.instagram.client import instagram
from app.instagram.models import IncomingEvent
from app.models.lead import CLOSED_STATUSES, Lead
from app.models.profile import CustomerProfile
from app.services.phone import extract_phone
from app.state.store import store
from app.telegram_business.client import telegram

# API reads per person are throttled (the data rarely changes)
_TG_REFRESH = 60 * 60 * 24
_IG_REFRESH = 60 * 60 * 6

# Keys an API read owns: a fresh read replaces them, so a bio or birthdate the
# person hid (or a photo they removed) disappears here too
_API_KEYS = {
    "telegram": ("bio", "birthdate", "personal_channel"),
    "instagram": ("followers", "is_verified", "follows_us", "we_follow", "profile_pic"),
}

# profile_pic URLs point at Meta's CDN; anything else is refused (no SSRF)
_IG_PIC_HOSTS = ("cdninstagram.com", "fbcdn.net")
_AVATAR_MAX = 5_000_000


@dataclass
class ProfileData:
    channel: str
    external_id: str
    username: Optional[str] = None
    full_name: Optional[str] = None
    phone: Optional[str] = None
    details: dict[str, Any] = field(default_factory=dict)
    fetched: bool = False  # came from an API read -> fetched_at

    def is_empty(self) -> bool:
        return not (self.username or self.full_name or self.phone or self.details)


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _clean(value: object, limit: int) -> Optional[str]:
    text = " ".join(str(value or "").split())
    return text[:limit] or None


def _join_name(src: dict) -> Optional[str]:
    return _clean(f"{src.get('first_name') or ''} {src.get('last_name') or ''}", 255)


def contact_phone(contact: dict) -> Optional[str]:
    """Phone from a Telegram Contact (digits, sometimes without the "+")."""
    digits = "".join(ch for ch in str(contact.get("phone_number") or "") if ch.isdigit())
    return extract_phone(f"+{digits}") if digits else None


# --------------------------------------------------------------------------- #
# What an incoming update tells about the customer
# --------------------------------------------------------------------------- #
def telegram_person(update: dict) -> Optional[ProfileData]:
    """The customer behind a private-chat update — never the account owner.

    In a Business chat the owner writes into the customer's chat: `chat` then
    describes the customer and `from` the owner, so the chat is the source.
    """
    msg = update.get("business_message") or update.get("message")
    if isinstance(msg, dict):
        chat, frm = msg.get("chat") or {}, msg.get("from") or {}
    else:
        callback = update.get("callback_query")
        if not isinstance(callback, dict):
            return None
        msg = {}
        chat = (callback.get("message") or {}).get("chat") or {}
        frm = callback.get("from") or {}
    if chat.get("type") != "private" or not chat.get("id"):
        return None
    customer_id = str(chat["id"])
    own = str(frm.get("id") or "") == customer_id
    if own and frm.get("is_bot"):
        return None
    src = frm if own else chat
    data = ProfileData("telegram", customer_id,
                       username=_clean(src.get("username"), 120),
                       full_name=_join_name(src))
    if own:
        if frm.get("language_code"):
            data.details["language_code"] = str(frm["language_code"])[:10]
        data.details["is_premium"] = bool(frm.get("is_premium"))
    contact = msg.get("contact") or {}
    # Only the person's OWN contact is their phone (not a card of someone else)
    if contact.get("phone_number") and str(contact.get("user_id") or "") == customer_id:
        data.phone = contact_phone(contact)
    return data


def instagram_person(event: IncomingEvent) -> Optional[ProfileData]:
    if event.channel != "instagram" or event.kind not in ("dm", "comment") \
            or not event.sender_id:
        return None
    return ProfileData("instagram", event.sender_id,
                       username=_clean(event.username, 120))


# --------------------------------------------------------------------------- #
# API reads
# --------------------------------------------------------------------------- #
def _tg_chat_details(chat: dict) -> dict[str, Any]:
    out: dict[str, Any] = {}
    bio = _clean(chat.get("bio"), 500)
    if bio:
        out["bio"] = bio
    birth = chat.get("birthdate")
    if isinstance(birth, dict) and birth.get("day") and birth.get("month"):
        text = f"{int(birth['day']):02d}.{int(birth['month']):02d}"
        out["birthdate"] = f"{text}.{birth['year']}" if birth.get("year") else text
    personal = chat.get("personal_chat")
    if isinstance(personal, dict):
        handle = personal.get("username")
        out["personal_channel"] = f"@{handle}" if handle else _clean(personal.get("title"), 120)
    return out


async def _fill_telegram(data: ProfileData) -> None:
    if not telegram.enabled:
        return
    chat = await telegram.get_chat(data.external_id)
    if not chat:
        return
    data.username = _clean(chat.get("username"), 120) or data.username
    data.full_name = _join_name(chat) or data.full_name
    data.details.update(_tg_chat_details(chat))
    data.fetched = True


async def _fill_instagram(data: ProfileData) -> None:
    if not settings.IG_ACCESS_TOKEN:
        return
    raw = await instagram.get_full_profile(data.external_id)
    if not raw:
        return
    data.username = _clean(raw.get("username"), 120) or data.username
    data.full_name = _clean(raw.get("name"), 255) or data.full_name
    for key, source in (("followers", "follower_count"), ("is_verified", "is_verified_user"),
                        ("follows_us", "is_user_follow_business"),
                        ("we_follow", "is_business_follow_user"),
                        ("profile_pic", "profile_pic")):
        if raw.get(source) is not None:
            data.details[key] = raw[source]
    data.fetched = True


# --------------------------------------------------------------------------- #
# Storage
# --------------------------------------------------------------------------- #
async def get(db: AsyncSession, channel: str, external_id: str) -> Optional[CustomerProfile]:
    return (await db.execute(select(CustomerProfile).where(
        CustomerProfile.channel == channel, CustomerProfile.external_id == external_id,
    ))).scalar_one_or_none()


async def save(data: ProfileData) -> Optional[CustomerProfile]:
    """Merge into the stored profile and copy username/phone to the person's leads."""
    if data.is_empty():
        return None
    async with db_session.SessionLocal() as db:
        row = await get(db, data.channel, data.external_id)
        if row is None:
            row = CustomerProfile(channel=data.channel, external_id=data.external_id,
                                  details={})
            try:
                async with db.begin_nested():  # a concurrent update may insert first
                    db.add(row)
            except IntegrityError:
                row = await get(db, data.channel, data.external_id)
                if row is None:
                    return None
        for attr in ("username", "full_name", "phone"):
            value = getattr(data, attr)
            # An API read is the whole truth for name/username (removed = gone);
            # other sources only add. A shared phone is never cleared.
            if (value or (data.fetched and attr != "phone")) and getattr(row, attr) != value:
                setattr(row, attr, value)
        old = dict(row.details or {})
        if data.fetched:
            for key in _API_KEYS.get(data.channel, ()):
                old.pop(key, None)
        details = {**old, **data.details}
        if details != (row.details or {}):
            row.details = details
        if data.fetched:
            row.fetched_at = _now()
        await _sync_leads(db, row)
        await db.commit()
        return row


async def _sync_leads(db: AsyncSession, row: CustomerProfile) -> None:
    """Instagram DMs carry no username — the lead gets it from the profile.
    A phone the person shared fills an empty contact of their open lead."""
    person = (Lead.channel == row.channel) & (Lead.external_id == row.external_id)
    if row.username:
        await db.execute(
            update(Lead).where(person, or_(Lead.username.is_(None),
                                           Lead.username != row.username))
            .values(username=row.username).execution_options(synchronize_session=False))
    if row.phone:
        await db.execute(
            update(Lead).where(person, Lead.contact.is_(None),
                               Lead.status.notin_(CLOSED_STATUSES))
            .values(contact=row.phone).execution_options(synchronize_session=False))


async def names(db: AsyncSession, leads: list[Lead]) -> dict[tuple[str, str], str]:
    """(channel, external_id) -> account name, for list views."""
    ids = {l.external_id for l in leads}
    if not ids:
        return {}
    rows = (await db.execute(
        select(CustomerProfile.channel, CustomerProfile.external_id, CustomerProfile.full_name)
        .where(CustomerProfile.channel.in_({l.channel for l in leads}),
               CustomerProfile.external_id.in_(ids), CustomerProfile.full_name.is_not(None))
    )).all()
    return {(r.channel, r.external_id): r.full_name for r in rows}


# --------------------------------------------------------------------------- #
# Entry points
# --------------------------------------------------------------------------- #
async def capture_telegram(data: ProfileData) -> None:
    """Background task per Telegram update. Never raises."""
    try:
        if not await store.seen_once(f"profile:tg:{data.external_id}", _TG_REFRESH):
            await _fill_telegram(data)
        await save(data)
    except Exception as exc:  # noqa: BLE001
        # Class name only: DB errors quote the bound values (names, phones)
        logger.warning("Telegram profile {} not saved: {}", data.external_id,
                       type(exc).__name__)


async def capture_instagram(event: IncomingEvent) -> None:
    """Background task per Instagram event. Never raises.

    The profile API is asked only for DMs: a commenter who never messaged us
    has given no consent (error 230), and every call would take a slot of the
    client's global 1 req/s throttle that replies need during comment bursts."""
    data = instagram_person(event)
    if data is None:
        return
    try:
        if event.kind == "dm" and not await store.seen_once(
                f"profile:ig:{data.external_id}", _IG_REFRESH):
            await _fill_instagram(data)
        await save(data)
    except Exception as exc:  # noqa: BLE001
        logger.warning("Instagram profile {} not saved: {}", data.external_id,
                       type(exc).__name__)


async def refresh(channel: str, external_id: str) -> Optional[CustomerProfile]:
    """Re-read the profile now (panel button), ignoring the throttle.
    None when the channel gave nothing (the stored profile stays as it was)."""
    data = ProfileData(channel, external_id)
    if channel == "telegram":
        await _fill_telegram(data)
    elif channel == "instagram":
        await _fill_instagram(data)
    return await save(data) if data.fetched else None


async def avatar(channel: str, external_id: str) -> Optional[tuple[bytes, str]]:
    """(image bytes, MIME type) of the person's profile photo, or None."""
    if channel == "telegram":
        return await _telegram_avatar(external_id)
    if channel == "instagram":
        async with db_session.SessionLocal() as db:
            row = await get(db, channel, external_id)
        url = (row.details or {}).get("profile_pic") if row else None
        image = await _download_ig(url) if url else None
        # profile_pic URLs expire after a few days (and old leads have no profile
        # yet) — read a fresh one. Own throttle key: a failed read here (a
        # commenter without consent) must not block the read when they DM us.
        if image is None and not await store.seen_once(
                f"profile:igpic:{external_id}", _IG_REFRESH):
            row = await refresh(channel, external_id)
            url = (row.details or {}).get("profile_pic") if row else None
            image = await _download_ig(url) if url else None
        return image
    return None


async def _telegram_avatar(user_id: str) -> Optional[tuple[bytes, str]]:
    if not telegram.enabled:
        return None
    photos = await telegram.get_user_profile_photos(user_id)
    sizes = ((photos or {}).get("photos") or [[]])[0]
    if not sizes:
        return None
    # Smallest size that is still sharp in a 64px circle
    pick = next((s for s in sizes if int(s.get("width") or 0) >= 160), sizes[-1])
    content = await telegram.download_file(str(pick.get("file_id") or ""), _AVATAR_MAX)
    return (content, "image/jpeg") if content else None


async def _download_ig(url: str) -> Optional[tuple[bytes, str]]:
    parsed = urlparse(url)
    host = (parsed.hostname or "").lower()
    if parsed.scheme != "https" or not any(
            host == h or host.endswith("." + h) for h in _IG_PIC_HOSTS):
        return None
    try:
        async with httpx.AsyncClient(timeout=10.0) as client:
            resp = await client.get(url)
    except httpx.HTTPError as exc:
        logger.info("Instagram avatar download failed: {}", exc)
        return None
    kind = resp.headers.get("content-type", "").split(";")[0].strip()
    if resp.status_code != 200 or not kind.startswith("image/") \
            or len(resp.content) > _AVATAR_MAX:
        return None
    return resp.content, kind
