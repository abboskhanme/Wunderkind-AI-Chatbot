"""Instagram side of the funnel (SPEC §10.1): keyword comments, the follow gate
and the Telegram deep link.

`handle_event()` is called by the Instagram webhook before the AI pipeline:
True = the funnel took the event (the AI never sees it).

Everything the bot sends is marked in the echo store first — Instagram echoes
our own messages back and an unmarked echo would look like an operator typing,
which pauses the AI in that chat.
"""
from __future__ import annotations

import random

from typing import Optional

from loguru import logger

from app.config import settings
from app.db import session as db_session
from app.funnel import keywords, locks, repo, texts
from app.instagram.client import instagram
from app.instagram.models import IncomingEvent, _attachment_text
from app.leads import client as leads_client
from app.models.funnel import FunnelEntry
from app.state.store import store
from app.telegram import notifier

MAX_FOLLOW_CHECKS = 5
# A button template comes back as an attachment echo with this placeholder text
_TEMPLATE_ECHO = _attachment_text([{"type": "template"}])
_COMMENT_WINDOW = 600


async def handle_event(event: IncomingEvent) -> bool:
    """Never raises: on any funnel error the event falls through to the AI."""
    try:
        return await _handle(event)
    except Exception as exc:  # noqa: BLE001
        logger.exception("Funnel Instagram hook failed: {}", exc)
        return False


async def _handle(event: IncomingEvent) -> bool:
    if event.channel != "instagram" or not event.sender_id:
        return False
    if event.kind == "comment":
        # Comments stay broad: any comment mentioning the keyword
        if not (settings.FUNNEL_ENABLED and event.comment_id and keywords.matches(event.text)):
            return False
        if not await _first_time(event):
            return True
        await _on_comment(event)
        return True
    if event.kind != "dm" or await _operator_handling(event):
        return False

    async with db_session.SessionLocal() as db:
        entry = await repo.entry_by_ig(db, event.sender_id)
    if entry is not None and entry.step == "ig_waiting_follow":
        if await _first_time(event):
            await _log_dm(event)
            await _on_waiting_dm(event)
        return True
    # DMs are strict: only a (nearly) bare keyword starts the funnel; a real
    # question that mentions it ("Wunderkind'da narxlar qancha?") is for the AI
    if not (settings.FUNNEL_ENABLED and keywords.is_keyword_request(event.text)):
        return False
    if entry is None:
        if await _first_time(event):
            await _log_dm(event)
            await _start_in_dm(event)
        return True
    if entry.step == "ig_link_sent":         # asked again — send the link again
        if await _first_time(event):
            await _log_dm(event)
            await _send_link(event.sender_id, {"id": event.sender_id}, entry.start_token)
        return True
    return False       # already in Telegram: free questions go to the AI


async def _operator_handling(event: IncomingEvent) -> bool:
    """An operator paused the bot in this chat: the funnel stays out too (the AI
    pipeline logs the message and does not answer)."""
    try:
        return await store.is_paused(event.store_key)
    except Exception as exc:  # noqa: BLE001
        logger.warning("Pause check failed (continuing): {}", exc)
        return False


async def _log_dm(event: IncomingEvent) -> None:
    """The person wrote to us: keep it in Suhbatlar like any DM (best effort)."""
    await leads_client.log_message(
        user_id=event.sender_id, username=event.username, channel="instagram",
        text=event.text, role="user", kind="dm", ig_message_id=event.message_id)


async def _first_time(event: IncomingEvent) -> bool:
    try:
        return not await store.seen_once(f"fnl:{event.dedup_key}", settings.DEDUP_TTL)
    except Exception as exc:  # noqa: BLE001
        logger.warning("Funnel dedup failed (continuing): {}", exc)
        return True


# --------------------------------------------------------------------------- #
# Flows
# --------------------------------------------------------------------------- #
async def _on_comment(event: IncomingEvent) -> None:
    """Public reply + one private reply: the link if already passed/following, else
    the welcome asking to follow."""
    igsid = event.sender_id
    async with locks.lock(f"ig:{igsid}"):
        entry = await _get_or_create(igsid, event.username, comment_id=event.comment_id)
        await _public_reply(event)
        recipient = {"comment_id": event.comment_id}
        passed = entry.step != "ig_waiting_follow"
        follows: Optional[bool] = None
        if settings.FUNNEL_IG_REQUIRE_FOLLOW and not passed:
            # Only a definite "yes" skips the welcome: commenters usually have not
            # messaged us yet, so the profile API often cannot answer here
            follows = (await _follow_status(entry)) is True
        if passed or follows or not settings.FUNNEL_IG_REQUIRE_FOLLOW:
            if await _send_link(igsid, recipient, entry.start_token):
                await _link_sent(entry, followed=bool(follows))
        else:
            await _send_quick(igsid, recipient, settings.FUNNEL_IG_DM_WELCOME)


async def _start_in_dm(event: IncomingEvent) -> None:
    """Keyword in a DM from someone new: same gate, no comment needed."""
    igsid = event.sender_id
    async with locks.lock(f"ig:{igsid}"):
        entry = await _get_or_create(igsid, event.username)
        if entry.step != "ig_waiting_follow":
            return
        await _gate(entry, count=False, not_following_text=settings.FUNNEL_IG_DM_WELCOME)


async def _on_waiting_dm(event: IncomingEvent) -> None:
    """Any DM (incl. the «✅ Obuna bo'ldim» quick reply) while waiting = check again."""
    async with locks.lock(f"ig:{event.sender_id}"):
        async with db_session.SessionLocal() as db:
            entry = await repo.entry_by_ig(db, event.sender_id)
        if entry is None or entry.step != "ig_waiting_follow":
            return
        await _gate(entry, count=True, not_following_text=settings.FUNNEL_IG_NOT_FOLLOWING)


async def _gate(entry: FunnelEntry, *, count: bool, not_following_text: str) -> None:
    """Follow check in a DM: follows → link; not → ask again (max 5, then link
    anyway); cannot tell → link if FAIL_OPEN, else "try later"."""
    igsid = str(entry.ig_user_id)
    recipient = {"id": igsid}
    checks = entry.follow_checks or 0
    if count:
        checks += 1
        async with db_session.SessionLocal() as db:
            fresh = await db.get(FunnelEntry, entry.id)
            if fresh is not None:
                fresh.follow_checks = checks
                await db.commit()
    if not settings.FUNNEL_IG_REQUIRE_FOLLOW:
        follows: Optional[bool] = True
    else:
        follows = await _follow_status(entry)
    give_link = (follows is True or checks >= MAX_FOLLOW_CHECKS
                 or (follows is None and settings.FUNNEL_IG_FOLLOW_FAIL_OPEN))
    if give_link:
        if await _send_link(igsid, recipient, entry.start_token):
            await _link_sent(entry, followed=follows is True)
    elif follows is False:
        await _send_quick(igsid, recipient, not_following_text)
    else:
        await _send_quick(igsid, recipient, texts.IG_TRY_LATER)


# --------------------------------------------------------------------------- #
# Helpers
# --------------------------------------------------------------------------- #
async def _get_or_create(igsid: str, username: Optional[str], *,
                         comment_id: Optional[str] = None) -> FunnelEntry:
    """Reuse the person's entry (one per Instagram user), else start one."""
    async with db_session.SessionLocal() as db:
        entry = await repo.entry_by_ig(db, igsid)
        if entry is None:
            entry = FunnelEntry(source="instagram", start_token=repo.new_token(),
                                ig_user_id=igsid, step="ig_waiting_follow", follow_checks=0,
                                opted_out=False, sheet_dirty=True)
            db.add(entry)
            logger.info("Funnel: new Instagram entry {}", igsid)
        if username:
            entry.ig_username = username
        if comment_id:
            entry.ig_comment_id = comment_id
        repo.touch(entry)
        await db.commit()
        return entry


async def _follow_status(entry: FunnelEntry) -> Optional[bool]:
    """True/False from the profile API, None when it cannot tell."""
    profile = await instagram.get_user_profile(str(entry.ig_user_id))
    if not profile:
        return None
    username = profile.get("username")
    if username and username != entry.ig_username:
        async with db_session.SessionLocal() as db:
            fresh = await db.get(FunnelEntry, entry.id)
            if fresh is not None:
                fresh.ig_username = username
                repo.touch(fresh)
                await db.commit()
        entry.ig_username = username
    value = profile.get("is_user_follow_business")
    return value if isinstance(value, bool) else None


async def _link_sent(entry: FunnelEntry, *, followed: bool) -> None:
    async with db_session.SessionLocal() as db:
        fresh = await db.get(FunnelEntry, entry.id)
        if fresh is None:
            return
        if fresh.step in ("ig_waiting_follow", "ig_link_sent"):
            fresh.step = "ig_link_sent"
        fresh.link_sent_at = fresh.link_sent_at or repo.now()
        if followed and not fresh.followed_at:
            fresh.followed_at = repo.now()
        repo.touch(fresh)
        await db.commit()


async def _public_reply(event: IncomingEvent) -> None:
    variants = [v.strip() for v in (settings.FUNNEL_IG_COMMENT_REPLY or "").split("|")]
    variants = [v for v in variants if v]
    if not variants:
        return
    text = random.choice(variants)
    try:
        # Same global budget as the AI's comment replies (loop protection)
        if await store.bump_rate("cmt:all", _COMMENT_WINDOW) > max(1, int(settings.CMT_LIMIT_TOTAL)):
            logger.warning("Funnel public reply skipped (comment rate limit): {}", event.comment_id)
            return
    except Exception as exc:  # noqa: BLE001
        logger.warning("Rate check failed (continuing): {}", exc)
    await instagram.reply_to_comment(str(event.comment_id), text)


async def _send_quick(igsid: str, recipient: dict, text: str) -> bool:
    """Text with the «✅ Obuna bo'ldim» quick reply; plain text if rejected
    (the text itself tells the person to write «tayyor»)."""
    await store.mark_sent(igsid, text)
    result = await instagram.send_quick_replies(recipient, text, [texts.FOLLOW_QUICK_REPLY])
    if not result.get("sent"):
        result = await instagram.send_message_to(recipient, {"text": text})
    return bool(result.get("sent"))


async def _send_link(igsid: str, recipient: dict, token: str) -> bool:
    """FUNNEL_IG_LINK_MESSAGE with a web_url button; plain text + URL as fallback."""
    url = await repo.bot_link(token)
    if not url:
        logger.error("Funnel: Telegram bot username unknown — Instagram link not sent")
        await _alert_no_bot()
        await store.mark_sent(igsid, texts.IG_LINK_UNAVAILABLE)
        await instagram.send_message_to(recipient, {"text": texts.IG_LINK_UNAVAILABLE})
        return False
    text = settings.FUNNEL_IG_LINK_MESSAGE.strip()
    await store.mark_sent(igsid, text)
    await store.mark_sent(igsid, _TEMPLATE_ECHO)
    result = await instagram.send_button_template(
        recipient, text, [{"type": "web_url", "url": url, "title": texts.LINK_BUTTON}])
    if not result.get("sent"):
        plain = f"{text}\n\n{url}"
        await store.mark_sent(igsid, plain)
        result = await instagram.send_message_to(recipient, {"text": plain})
    return bool(result.get("sent"))


async def _alert_no_bot() -> None:
    try:
        if not await store.seen_once("fnl:alert:no-bot", 3600):
            await notifier.send_text(
                "⚠️ <b>Voronka: Telegram bot ulanmagan</b>\nInstagram'dagi mijozlarga "
                "qo'llanma havolasini yuborib bo'lmayapti. Sozlamalar → Telegram → bot tokeni.")
    except Exception as exc:  # noqa: BLE001
        logger.warning("No-bot alert failed: {}", exc)
