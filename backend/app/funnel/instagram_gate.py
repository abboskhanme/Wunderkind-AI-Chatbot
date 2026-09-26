"""Instagram side of the funnels (SPEC §10.1, §11.2): keyword comments, the
follow gate and the Telegram deep link. Each comment/DM is routed to one funnel
(keywords + optional post filter); that funnel's texts are used.

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
from app.funnel import funnels, locks, repo, texts
from app.funnel.funnels import FunnelView
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
        # Comments stay broad: any comment mentioning a funnel's keyword
        if not (settings.FUNNEL_ENABLED and event.comment_id):
            return False
        funnel = await funnels.match_comment(await funnels.load_all(), event.text,
                                             event.media_id)
        if funnel is None:
            return False
        if await _first_time(event):
            await _on_comment(event, funnel)
        return True
    if event.kind != "dm" or await _operator_handling(event):
        return False

    async with db_session.SessionLocal() as db:
        latest = await repo.entry_by_ig(db, event.sender_id)
    # A DM is a follow-check answer only if the person's LATEST entry (any funnel)
    # waits for it — an older waiting entry must not swallow later DMs
    if latest is not None and latest.step == "ig_waiting_follow":
        if await _first_time(event):
            await _log_dm(event)
            await _on_waiting_dm(event)
        return True
    # DMs are strict: only a (nearly) bare keyword starts a funnel; a real
    # question that mentions it ("Wunderkind'da narxlar qancha?") is for the AI
    if not settings.FUNNEL_ENABLED:
        return False
    funnel = funnels.match_direct(await funnels.load_all(), event.text, strict=True)
    if funnel is None:
        return False
    async with db_session.SessionLocal() as db:
        entry = await repo.entry_by_ig(db, event.sender_id, funnel.id)
    if entry is None:
        if await _first_time(event):
            await _log_dm(event)
            await _start_in_dm(event, funnel)
        return True
    if entry.step == "ig_link_sent":         # asked again — send the link again
        if await _first_time(event):
            await _log_dm(event)
            await _send_link(event.sender_id, {"id": event.sender_id}, entry.start_token,
                             funnel)
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
async def _on_comment(event: IncomingEvent, funnel: FunnelView) -> None:
    """Public reply + one private reply: the link if already passed/following, else
    the welcome asking to follow."""
    igsid = event.sender_id
    async with locks.lock(f"ig:{igsid}"):
        entry = await _get_or_create(igsid, event.username, funnel,
                                     comment_id=event.comment_id)
        await _public_reply(event, funnel)
        recipient = {"comment_id": event.comment_id}
        passed = entry.step != "ig_waiting_follow"
        follows: Optional[bool] = None
        if settings.FUNNEL_IG_REQUIRE_FOLLOW and not passed:
            # Only a definite "yes" skips the welcome: commenters usually have not
            # messaged us yet, so the profile API often cannot answer here
            follows = (await _follow_status(entry)) is True
        if passed or follows or not settings.FUNNEL_IG_REQUIRE_FOLLOW:
            if await _send_link(igsid, recipient, entry.start_token, funnel):
                await _link_sent(entry, followed=bool(follows))
        else:
            await _send_quick(igsid, recipient, funnel.text("FUNNEL_IG_DM_WELCOME"))


async def _start_in_dm(event: IncomingEvent, funnel: FunnelView) -> None:
    """Keyword in a DM from someone new to this funnel: same gate, no comment needed."""
    igsid = event.sender_id
    async with locks.lock(f"ig:{igsid}"):
        entry = await _get_or_create(igsid, event.username, funnel)
        if entry.step != "ig_waiting_follow":
            return
        await _gate(entry, funnel, count=False,
                    not_following_text=funnel.text("FUNNEL_IG_DM_WELCOME"))


async def _on_waiting_dm(event: IncomingEvent) -> None:
    """Any DM (incl. the «✅ Obuna bo'ldim» quick reply) while waiting = check again."""
    async with locks.lock(f"ig:{event.sender_id}"):
        async with db_session.SessionLocal() as db:
            entry = await repo.entry_by_ig(db, event.sender_id)
            funnel = await funnels.get(db, entry.funnel_id) if entry else None
        if entry is None or funnel is None or entry.step != "ig_waiting_follow":
            return
        await _gate(entry, funnel, count=True,
                    not_following_text=funnel.text("FUNNEL_IG_NOT_FOLLOWING"))


async def _gate(entry: FunnelEntry, funnel: FunnelView, *, count: bool,
                not_following_text: str) -> None:
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
        if await _send_link(igsid, recipient, entry.start_token, funnel):
            await _link_sent(entry, followed=follows is True)
    elif follows is False:
        await _send_quick(igsid, recipient, not_following_text)
    else:
        await _send_quick(igsid, recipient, texts.IG_TRY_LATER)


# --------------------------------------------------------------------------- #
# Helpers
# --------------------------------------------------------------------------- #
async def _get_or_create(igsid: str, username: Optional[str], funnel: FunnelView, *,
                         comment_id: Optional[str] = None) -> FunnelEntry:
    """Reuse the person's entry in this funnel, else start one."""
    async with db_session.SessionLocal() as db:
        entry = await repo.entry_by_ig(db, igsid, funnel.id)
        if entry is None:
            entry = FunnelEntry(funnel_id=funnel.id, source="instagram",
                                start_token=repo.new_token(), ig_user_id=igsid,
                                step="ig_waiting_follow", follow_checks=0, opted_out=False,
                                sheet_dirty=True)
            db.add(entry)
            logger.info("Funnel {}: new Instagram entry {}", funnel.slug, igsid)
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


async def _public_reply(event: IncomingEvent, funnel: FunnelView) -> None:
    variants = [v.strip() for v in funnel.text("FUNNEL_IG_COMMENT_REPLY").split("|")]
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


async def _send_link(igsid: str, recipient: dict, token: str, funnel: FunnelView) -> bool:
    """FUNNEL_IG_LINK_MESSAGE with a web_url button; plain text + URL as fallback."""
    url = await repo.ig_link(token)
    if not url:
        logger.error("Funnel: Telegram bot username unknown — Instagram link not sent")
        await _alert_no_bot()
        await store.mark_sent(igsid, texts.IG_LINK_UNAVAILABLE)
        await instagram.send_message_to(recipient, {"text": texts.IG_LINK_UNAVAILABLE})
        return False
    text = funnel.text("FUNNEL_IG_LINK_MESSAGE").strip()
    plain = f"{text}\n\n{url}"
    if "comment_id" in recipient:
        # A private reply allows ONE message per comment and nothing more until
        # the person answers — so it must work everywhere: plain text + link
        # (instagram.com on a computer shows no buttons at all)
        await store.mark_sent(igsid, plain)
        result = await instagram.send_message_to(recipient, {"text": plain})
        return bool(result.get("sent"))
    await store.mark_sent(igsid, text)
    await store.mark_sent(igsid, _TEMPLATE_ECHO)
    result = await instagram.send_button_template(
        recipient, text, [{"type": "web_url", "url": url, "title": texts.LINK_BUTTON}])
    if result.get("sent"):
        # Buttons exist only in the Instagram mobile app — the plain link follows
        fallback = texts.IG_LINK_TEXT_FALLBACK.format(url=url)
        await store.mark_sent(igsid, fallback)
        await instagram.send_message_to(recipient, {"text": fallback})
    else:
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
