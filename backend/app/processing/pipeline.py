"""Pipeline — webhook event -> AI reply -> delivery -> memory -> lead -> alert.

Ported from NUR (WhatsApp removed, ERP calls replaced by the local DB).
Every stage has its own try/except: one failing stage never blocks the others
(e.g. a DB hiccup must not stop the reply from being sent).
"""
from __future__ import annotations

import asyncio

from loguru import logger

from app.agent.core import SalesAgent
from app.config import settings
from app.instagram.client import instagram
from app.instagram.models import IncomingEvent
from app.leads import client as leads_client
from app.models_ai import AgentOutput, LeadPayload
from app.state.store import store
from app.telegram import notifier
from app.telegram_business.client import telegram

_agent = SalesAgent()

# Circuit breaker: if the bot ever mistakes its own comment for a customer's,
# an endless reply loop could get the account flagged as spam. Normal traffic
# never hits these limits; a loop stops immediately.
_COMMENT_WINDOW = 600
_GLOBAL_WINDOW = 600
# A throttled comment is NOT dropped — it is retried once the window frees up.
_RETRY_DELAY = _COMMENT_WINDOW + 15
_MAX_RETRIES = 3
_MAX_PENDING = 300
_pending_retries = 0


def _comment_limit() -> int:
    return max(1, int(settings.CMT_LIMIT_PER_POST or 30))


def _global_limit() -> int:
    return max(1, int(settings.CMT_LIMIT_TOTAL or 100))


def ai_enabled_for(channel: str) -> bool:
    if channel == "telegram":
        return bool(settings.TG_SALES_ENABLED)
    return bool(settings.IG_AI_ENABLED)


# One lock per conversation: two quick messages ("Salom", "Narxi?") must not be
# answered in parallel (double replies, two leads). Single worker -> in-process.
_locks: dict[str, asyncio.Lock] = {}


def conversation_lock(key: str) -> asyncio.Lock:
    lock = _locks.get(key)
    if lock is None:
        if len(_locks) > 5000:  # drop idle locks
            for k in [k for k, v in _locks.items() if not v.locked()]:
                _locks.pop(k, None)
        lock = _locks[key] = asyncio.Lock()
    return lock


async def process_event(event: IncomingEvent, *, skip_dedup: bool = False,
                        attempt: int = 0, reply: bool | None = None) -> None:
    async with conversation_lock(event.store_key):
        await _process_event(event, skip_dedup=skip_dedup, attempt=attempt, reply=reply)


async def _process_event(event: IncomingEvent, *, skip_dedup: bool = False,
                         attempt: int = 0, reply: bool | None = None) -> None:
    """Fully process one incoming event.

    `reply=False` — only log the message (AI disabled for the channel); staff
    see it in the inbox and answer themselves. `None` = channel setting.
    """
    if reply is None:
        reply = ai_enabled_for(event.channel)

    # 0. Echo — a message sent from our account. Not sent by the bot means an
    #    operator typed it in the app -> pause the bot in that conversation.
    if event.kind == "echo":
        await _handle_echo(event)
        return

    # 1. Dedup
    try:
        if not skip_dedup and await store.seen_once(event.dedup_key, settings.DEDUP_TTL):
            logger.info("Duplicate skipped: {}", event.dedup_key)
            return
    except Exception as exc:  # noqa: BLE001
        logger.warning("Dedup error (continuing): {}", exc)

    # 1a. Comment rate limits (backup loop protection)
    if reply and event.kind == "comment" and not await _within_comment_limits(event):
        await _queue_comment_retry(event, attempt)
        return

    # 1b. Operator is handling this chat — the bot stays out, but still logs
    if event.kind == "dm":
        try:
            if await store.is_paused(event.store_key):
                logger.info("Bot paused (operator handling): {}", event.sender_id)
                reply = False
        except Exception as exc:  # noqa: BLE001
            logger.warning("Pause check failed (continuing): {}", exc)

    # 2. Context — history and facts we already know
    history: list[dict] = []
    known: dict = {}
    if event.sender_id:
        ctx = await leads_client.fetch_context(event.sender_id, channel=event.channel)
        if ctx is not None:
            history = ctx.get("messages") or []
            known = {k: ctx.get(k) for k in (
                "name", "contact", "course_interest", "student_age",
                "preferred_time", "summary",
            )}
        elif event.kind == "dm":
            try:
                history = await store.get_history(event.store_key)
            except Exception as exc:  # noqa: BLE001
                logger.warning("History cache read failed: {}", exc)

    # 2a. Log the customer message right away — never lost even if AI fails
    user_logged = await _log(event, event.text, role="user")

    if not reply:
        return

    # 3. AI reply
    try:
        out = await _agent.handle(
            event.text,
            is_comment=event.kind == "comment",
            username=event.username,
            media_caption=event.media_caption,
            history=history,
            known=known,
            has_attachment=event.has_attachment,
            channel=event.channel,
        )
    except Exception as exc:  # noqa: BLE001
        logger.exception("Agent failed to answer: {}", exc)
        return

    logger.info(
        "Reply ready: intent={} stage={} score={} hot={} dm={} esc={}\n  -> {}",
        out.intent, out.stage, out.lead_score, out.is_hot_lead, out.move_to_dm,
        out.escalate_to_human, out.reply,
    )

    # 4. Deliver
    delivered = False
    try:
        delivered = await _deliver(event, out, is_first=not history)
    except Exception as exc:  # noqa: BLE001
        logger.exception("Delivery failed: {}", exc)

    # 5. Memory — DB (primary) and Redis (fast cache)
    meta = None if delivered else {"delivery_failed": True}
    reply_logged = await _log(event, out.reply, role="assistant", meta=meta)
    if event.kind == "dm":
        try:
            await store.append_turn(event.store_key, "user", event.text)
            await store.append_turn(event.store_key, "assistant", out.reply)
        except Exception as exc:  # noqa: BLE001
            logger.warning("History cache write failed: {}", exc)

    # 6. Lead facts. Comments do not open leads on their own (every "🔥" would
    #    flood the list) — only when the AI found something worth keeping.
    if event.kind != "comment" or out.is_hot_lead or out.lead.contact:
        try:
            saved = await leads_client.push(_to_payload(event, out))
            # A comment lead was just created by push — attach the comment and
            # our reply so it shows up in the inbox with its context.
            if saved and event.kind == "comment":
                if not user_logged:
                    await _log(event, event.text, role="user", create_lead=True)
                if not reply_logged:
                    await _log(event, out.reply, role="assistant", meta=meta,
                               create_lead=True)
        except Exception as exc:  # noqa: BLE001
            logger.exception("Lead save failed: {}", exc)

    # 7. Staff alert
    try:
        if out.is_hot_lead or out.escalate_to_human:
            await notifier.notify_hot_lead(event.username, out, channel=event.channel,
                                           known=known)
    except Exception as exc:  # noqa: BLE001
        logger.warning("Telegram alert failed: {}", exc)


async def _log(event: IncomingEvent, text: str, *, role: str, meta: dict | None = None,
               create_lead: bool | None = None) -> bool:
    if not event.sender_id or not text:
        return False
    try:
        return await leads_client.log_message(
            user_id=event.sender_id,
            username=event.username,
            channel=event.channel,
            text=text,
            role=role,
            kind="comment" if event.kind == "comment" else "dm",
            ig_message_id=event.message_id if role == "user" else None,
            comment_id=event.comment_id,
            media_id=event.media_id,
            create_lead=(event.kind != "comment") if create_lead is None else create_lead,
            meta=meta,
        )
    except Exception as exc:  # noqa: BLE001
        logger.warning("Conversation log failed: {}", exc)
        return False


async def _handle_echo(event: IncomingEvent) -> None:
    if not event.sender_id:
        return
    try:
        if await store.was_sent_by_bot(event.store_key, event.text):
            return  # the bot's own reply coming back
        await _log(event, event.text, role="operator")
        await store.pause(event.store_key, settings.BOT_PAUSE_HOURS)
        logger.info("Operator replied manually — bot paused {}h: {}",
                    settings.BOT_PAUSE_HOURS, event.sender_id)
    except Exception as exc:  # noqa: BLE001
        logger.warning("Echo handling failed: {}", exc)


async def _deliver(event: IncomingEvent, out: AgentOutput, *, is_first: bool = False) -> bool:
    """Send the reply. Returns True when the main reply reached the customer."""
    if event.channel == "telegram":
        return await _deliver_telegram(event, out, is_first=is_first)
    if event.kind == "comment" and event.comment_id:
        ok = bool(await instagram.reply_to_comment(event.comment_id, out.reply))
        if out.move_to_dm:
            text = with_disclosure(
                "Assalomu alaykum! Batafsil ma'lumotni shu yerda yozib beraman 👇 "
                "Qaysi kurs va kim uchun (farzandingizmi yoki o'zingiz) qiziqyapsiz?"
            )
            await store.mark_sent(event.sender_id, text)
            await instagram.send_private_reply(event.comment_id, text)
        return ok
    if event.kind == "dm":
        text = with_disclosure(out.reply) if is_first else out.reply
        await store.mark_sent(event.store_key, text)
        return bool(await instagram.send_dm(event.sender_id, text))
    return False


async def _deliver_telegram(
    event: IncomingEvent, out: AgentOutput, *, is_first: bool = False
) -> bool:
    text = with_disclosure(out.reply) if is_first else out.reply
    chat_id = event.chat_id or event.sender_id
    # Answer through the SAME route the message came in: a bot-chat message
    # must not be answered from the owner's personal (Business) account.
    conn_id = event.business_connection_id
    # Mark before sending: in Business mode the echo may arrive before we return
    await store.mark_sent(event.store_key, text)
    result = await telegram.send_message(chat_id, text, business_connection_id=conn_id)
    if not result.get("sent"):
        logger.warning("Telegram reply not sent: {}", result.get("error"))
    return bool(result.get("sent"))


async def _within_comment_limits(event: IncomingEvent) -> bool:
    try:
        media = event.media_id or "unknown"
        per_media = await store.bump_rate(f"cmt:{media}", _COMMENT_WINDOW)
        if per_media > _comment_limit():
            logger.warning("LIMIT: {} comments under {} in {} min — queued",
                           per_media, media, _COMMENT_WINDOW // 60)
            await _alert_throttled(media, per_media)
            return False
        total = await store.bump_rate("cmt:all", _GLOBAL_WINDOW)
        if total > _global_limit():
            logger.warning("LIMIT: {} comments in {} min — queued",
                           total, _GLOBAL_WINDOW // 60)
            await _alert_throttled("all", total)
            return False
    except Exception as exc:  # noqa: BLE001
        logger.warning("Rate limit check failed (continuing): {}", exc)
    return True


async def _queue_comment_retry(event: IncomingEvent, attempt: int) -> None:
    global _pending_retries

    if attempt >= _MAX_RETRIES:
        logger.error("Comment not answered after {} attempts: {}", attempt, event.comment_id)
        return
    if _pending_retries >= _MAX_PENDING:
        logger.error("Comment retry queue full — skipped: {}", event.comment_id)
        return

    _pending_retries += 1

    async def _later() -> None:
        global _pending_retries
        try:
            await asyncio.sleep(_RETRY_DELAY)
            await process_event(event, skip_dedup=True, attempt=attempt + 1)
        except Exception as exc:  # noqa: BLE001
            logger.exception("Delayed comment failed: {}", exc)
        finally:
            _pending_retries -= 1

    asyncio.create_task(_later())


async def _alert_throttled(media: str, count: int) -> None:
    try:
        if await store.seen_once(f"cmt-alert:{media}", _COMMENT_WINDOW):
            return
        await notifier.notify_comments_throttled(media, count, _COMMENT_WINDOW // 60)
    except Exception as exc:  # noqa: BLE001
        logger.warning("Throttle alert failed: {}", exc)


def with_disclosure(text: str) -> str:
    """First message of a conversation says it is an AI assistant (Meta guideline)."""
    return (f"{text}\n\n🤖 Men {settings.COMPANY_NAME} o'quv markazining AI yordamchisiman. "
            "Administrator kerak bo'lsa yozing — ulab qo'yaman.")


# Backwards-compatible name used by the ported Telegram menu module
_with_disclosure = with_disclosure


def _to_payload(event: IncomingEvent, out: AgentOutput) -> LeadPayload:
    return LeadPayload(
        channel=event.channel,
        source=event.channel,
        user_id=event.sender_id or None,
        username=event.username,
        media_id=event.media_id,
        comment_id=event.comment_id,
        name=out.lead.name,
        contact=out.lead.contact,
        course_interest=out.lead.course_interest,
        student_age=out.lead.student_age,
        preferred_time=out.lead.preferred_time,
        language=out.language,
        intent=out.intent,
        stage=out.stage,
        lead_score=out.lead_score,
        summary=out.lead.summary,
        extra={"is_hot_lead": out.is_hot_lead, "escalate": out.escalate_to_human},
    )
