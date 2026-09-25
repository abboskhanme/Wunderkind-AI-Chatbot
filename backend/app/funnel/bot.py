"""Telegram side of the funnel (SPEC §10.1): /start deep links, the collection
state machine (name → phone → grade → PDF), the channel gate, /stop and keyword
comments in the channel's discussion group.

Entry point: `claim_update()` is called by the Telegram webhook before the menu
and the AI. It decides cheaply whether the update belongs to the funnel and, if
so, queues the work and returns True. Everything else passes through untouched.
"""
from __future__ import annotations

import uuid
from typing import Optional

from fastapi import BackgroundTasks
from loguru import logger

from app.config import settings
from app.db import session as db_session
from app.funnel import booking, delivery, keywords, locks, repo, texts
from app.models.funnel import COLLECTION_STEPS, FunnelEntry
from app.services.phone import extract_phone
from app.state.store import store
from app.telegram.notifier import chat_ids
from app.telegram_business import menu
from app.telegram_business.client import telegram

CALLBACK_PREFIX = "fb:"
_TG_COMMENT_WINDOW = 600       # one group-comment reply per person per 10 min
_FAILS_KEY = "fnl:fails:{user}"
_FAILS_TTL = 3600
_MAX_FAILS = 2                 # the 2nd invalid answer in a row goes to the AI
_MEMBER_STATUSES = ("creator", "administrator", "member")


# --------------------------------------------------------------------------- #
# Webhook hook
# --------------------------------------------------------------------------- #
async def claim_update(update: dict, background: BackgroundTasks) -> bool:
    """True = the funnel handles this update (work queued on `background`)."""
    try:
        return await _claim(update, background)
    except Exception as exc:  # noqa: BLE001 — never break the regular bot
        logger.exception("Funnel claim failed (update goes to the regular flow): {}", exc)
        return False


async def _claim(update: dict, background: BackgroundTasks) -> bool:
    callback = update.get("callback_query")
    if isinstance(callback, dict):
        if str(callback.get("data") or "").startswith(CALLBACK_PREFIX):
            background.add_task(handle_callback, callback)
            return True
        return False

    msg = update.get("message")
    if not isinstance(msg, dict):
        return False
    chat = msg.get("chat") or {}
    sender = msg.get("from") or {}
    if sender.get("is_bot"):
        return False
    if chat.get("type") in ("group", "supergroup"):
        if _is_keyword_comment(msg):
            background.add_task(handle_group_comment, msg)
            return True
        return False
    if chat.get("type") != "private" or not sender.get("id"):
        return False

    user_id = str(sender["id"])
    text = str(msg.get("text") or "").strip()
    if text.startswith("/"):
        command, argument = _command(text)
        if command == "start" and await _start_is_funnel(user_id, argument):
            background.add_task(handle_start, msg, argument)
            return True
        if command == "stop" and await _state_of(user_id) is not None:
            background.add_task(handle_stop, msg)
            return True
        return False     # menu commands, /id, ... keep working
    state = await _state_of(user_id)
    if state is None or state[0] not in COLLECTION_STEPS or state[1]:
        return False     # not collecting, or paused by /stop (/start resumes)
    # Menu buttons stay menu buttons even mid-collection
    if text and not msg.get("contact") and menu.match(text, menu.current()):
        return False
    background.add_task(handle_collection, msg)
    return True


def _command(text: str) -> tuple[str, str]:
    parts = text[1:].split(maxsplit=1)
    command = parts[0].split("@", 1)[0].lower() if parts else ""
    return command, parts[1].strip() if len(parts) > 1 else ""


async def _state_of(user_id: str) -> Optional[tuple[str, bool]]:
    """(step, opted_out) of the person's entry. opted_out during a collection step
    means "paused by /stop": their text goes to the AI until /start resumes."""
    async with db_session.SessionLocal() as db:
        entry = await repo.entry_by_tg(db, user_id)
        return (entry.step, entry.opted_out) if entry else None


async def _start_is_funnel(user_id: str, argument: str) -> bool:
    """Which /start belongs to the funnel (the rest is the menu greeting / deep link)."""
    if argument == "tgc":
        return bool(settings.FUNNEL_ENABLED)
    async with db_session.SessionLocal() as db:
        if argument and await repo.entry_by_token(db, argument):
            return True     # an Instagram link — that person was promised the PDF
        entry = await repo.entry_by_tg(db, user_id)
    if argument and menu.current().by_command(argument):
        return False        # t.me/<bot>?start=narxlar — menu deep link
    if entry is not None and entry.step in COLLECTION_STEPS:
        return True         # resume the unfinished questions
    return bool(settings.FUNNEL_ENABLED and settings.FUNNEL_BOT_START_FUNNEL)


def _is_keyword_comment(msg: dict) -> bool:
    if not settings.FUNNEL_ENABLED or not telegram.enabled:
        return False
    chat_id = str((msg.get("chat") or {}).get("id"))
    wanted = (settings.FUNNEL_TG_DISCUSSION_CHAT_ID or "").strip()
    if wanted and chat_id != wanted:
        return False
    if chat_id in chat_ids(settings.TELEGRAM_CHAT_ID):
        return False     # the staff alert group is not a customer channel
    # The channel post itself is auto-forwarded into the group and contains the keyword
    if msg.get("is_automatic_forward") or msg.get("sender_chat"):
        return False
    return keywords.matches(str(msg.get("text") or msg.get("caption") or ""))


# --------------------------------------------------------------------------- #
# Helpers
# --------------------------------------------------------------------------- #
def _who(msg: dict) -> tuple[str, str, Optional[str]]:
    sender = msg.get("from") or {}
    chat = msg.get("chat") or {}
    username = (sender.get("username") or "").strip() or None
    return str(sender.get("id")), str(chat.get("id")), username


async def _duplicate(msg: dict) -> bool:
    chat_id = (msg.get("chat") or {}).get("id")
    try:
        return await store.seen_once(f"fnl:tgm:{chat_id}:{msg.get('message_id')}",
                                     settings.DEDUP_TTL)
    except Exception as exc:  # noqa: BLE001
        logger.warning("Funnel dedup failed (continuing): {}", exc)
        return False


def contact_keyboard() -> dict:
    return {"keyboard": [[{"text": texts.SHARE_PHONE_BUTTON, "request_contact": True}]],
            "resize_keyboard": True, "one_time_keyboard": True,
            "input_field_placeholder": "+998 90 123 45 67"}


def menu_keyboard() -> dict:
    """Give the bot menu keyboard back (the contact button replaced it);
    remove the keyboard only when there is no menu."""
    current = menu.current()
    return menu.reply_keyboard(current) if current.items else {"remove_keyboard": True}


def grade_keyboard() -> dict:
    buttons = [{"text": texts.grade_display(g), "callback_data": f"fb:g:{g}"}
               for g in texts.grade_options()]
    return {"inline_keyboard": [buttons[i:i + 4] for i in range(0, len(buttons), 4)]}


async def _save(entry_id: uuid.UUID, **fields: object) -> Optional[FunnelEntry]:
    async with db_session.SessionLocal() as db:
        entry = await db.get(FunnelEntry, entry_id)
        if entry is None:
            return None
        for key, value in fields.items():
            setattr(entry, key, value)
        repo.touch(entry)
        await db.commit()
        return entry


def _next_step(entry: FunnelEntry) -> str:
    if not entry.full_name:
        return "ask_name"
    if not entry.phone:
        return "ask_phone"
    if not entry.grade:
        return "ask_grade"
    return "pdf"


async def ask_next(entry_id: uuid.UUID) -> None:
    """Ask for the first missing field, or send the PDF when all are known."""
    async with db_session.SessionLocal() as db:
        entry = await db.get(FunnelEntry, entry_id)
        if entry is None or not entry.tg_chat_id:
            return
        step = _next_step(entry)
        if step != "pdf" and entry.step != step:
            entry.step = step
            repo.touch(entry)
            await db.commit()
        chat_id = entry.tg_chat_id
    if step == "ask_name":
        await telegram.send_message(chat_id, settings.FUNNEL_ASK_NAME)
    elif step == "ask_phone":
        await telegram.send_message(chat_id, settings.FUNNEL_ASK_PHONE,
                                    reply_markup=contact_keyboard())
    elif step == "ask_grade":
        await telegram.send_message(chat_id, settings.FUNNEL_ASK_GRADE,
                                    reply_markup=grade_keyboard())
    else:
        await delivery.deliver_pdf(entry_id)


# --------------------------------------------------------------------------- #
# Channel gate
# --------------------------------------------------------------------------- #
def _gate_applies(entry: FunnelEntry) -> bool:
    return bool((settings.FUNNEL_TG_CHANNEL or "").strip() and settings.FUNNEL_TG_REQUIRE_CHANNEL
                and entry.source in ("telegram_channel", "telegram_direct"))


async def _is_member(user_id: str) -> Optional[bool]:
    """True/False, or None when Telegram cannot tell (then the gate lets them pass)."""
    member = await telegram.get_chat_member(settings.FUNNEL_TG_CHANNEL.strip(), user_id)
    if member is None:
        return None
    status = member.get("status")
    if status == "restricted":
        return bool(member.get("is_member"))
    return status in _MEMBER_STATUSES


async def _channel_url() -> Optional[str]:
    channel = settings.FUNNEL_TG_CHANNEL.strip()
    if channel.startswith("@"):
        return f"https://t.me/{channel[1:]}"
    chat = await telegram.get_chat(channel)
    if chat and chat.get("username"):
        return f"https://t.me/{chat['username']}"
    return (chat or {}).get("invite_link") or None


async def _gate_blocks(entry: FunnelEntry) -> Optional[str]:
    """Channel URL when the person must subscribe first; None = go on."""
    if not _gate_applies(entry) or not entry.tg_user_id:
        return None
    if await _is_member(entry.tg_user_id) is not False:
        return None
    # No link to show -> no dead end: let them through
    return await _channel_url()


def _gate_keyboard(url: str) -> dict:
    return {"inline_keyboard": [[{"text": texts.CHANNEL_BUTTON, "url": url}],
                                [{"text": texts.CHECK_BUTTON, "callback_data": "fb:chk"}]]}


# --------------------------------------------------------------------------- #
# Handlers (background tasks)
# --------------------------------------------------------------------------- #
async def handle_start(msg: dict, argument: str) -> None:
    user_id, chat_id, username = _who(msg)
    if await _duplicate(msg):
        return
    async with locks.lock(f"tg:{user_id}"):
        async with db_session.SessionLocal() as db:
            entry = await _resolve_entry(db, user_id, argument)
            first_start = entry.bot_started_at is None
            entry.bot_started_at = entry.bot_started_at or repo.now()
            entry.tg_chat_id = chat_id
            entry.tg_username = username or entry.tg_username
            entry.opted_out = False      # pressing Start again = wants messages again
            if entry.step in ("ig_waiting_follow", "ig_link_sent"):
                entry.step = "ask_name"
            repo.touch(entry)
            await db.commit()
        logger.info("Funnel /start: tg={} source={} step={}", user_id, entry.source, entry.step)
        await _continue(entry, welcome=first_start)


async def _resolve_entry(db, user_id: str, argument: str) -> FunnelEntry:
    """Bind an Instagram token, merge into an existing Telegram entry, or create one."""
    tg_entry = await repo.entry_by_tg(db, user_id)
    if argument and argument != "tgc":
        ig_entry = await repo.entry_by_token(db, argument)
        if ig_entry is not None and ig_entry.tg_user_id and ig_entry.tg_user_id != user_id:
            ig_entry = None      # someone else's forwarded link: start their own flow
        if ig_entry is not None:
            if tg_entry is None or tg_entry.id == ig_entry.id:
                ig_entry.tg_user_id = user_id
                return ig_entry
            await repo.merge_into(db, ig_entry, tg_entry)
            return tg_entry
    if tg_entry is not None:
        return tg_entry
    entry = FunnelEntry(
        source="telegram_channel" if argument == "tgc" else "telegram_direct",
        start_token=repo.new_token(), tg_user_id=user_id, step="ask_name",
        follow_checks=0, opted_out=False, sheet_dirty=True,
    )
    db.add(entry)
    await db.flush()
    return entry


async def _continue(entry: FunnelEntry, *, welcome: bool) -> None:
    """After /start or a passed gate: resend the PDF, show the gate, or ask."""
    if entry.step in ("pdf_sent", "pdf_pending"):
        await delivery.deliver_pdf(entry.id)
        return
    chat_id = entry.tg_chat_id
    if welcome and settings.FUNNEL_BOT_WELCOME.strip():
        await telegram.send_message(chat_id, settings.FUNNEL_BOT_WELCOME)
    channel_url = await _gate_blocks(entry)
    if channel_url:
        await _save(entry.id, step="tg_channel_gate")
        await telegram.send_message(chat_id, texts.CHANNEL_GATE,
                                    reply_markup=_gate_keyboard(channel_url))
        return
    await ask_next(entry.id)


async def handle_stop(msg: dict) -> None:
    """/stop: no more sales messages; mid-collection it also pauses the questions
    (free text goes to the AI until /start resumes)."""
    user_id, chat_id, _ = _who(msg)
    if await _duplicate(msg):
        return
    async with locks.lock(f"tg:{user_id}"):
        async with db_session.SessionLocal() as db:
            entry = await repo.entry_by_tg(db, user_id)
            if entry is None:
                return
            entry.opted_out = True
            await db.commit()
    await telegram.send_message(chat_id, texts.STOPPED, reply_markup=menu_keyboard())


async def handle_collection(msg: dict) -> None:
    user_id, chat_id, _ = _who(msg)
    if await _duplicate(msg):
        return
    async with locks.lock(f"tg:{user_id}"):
        async with db_session.SessionLocal() as db:
            entry = await repo.entry_by_tg(db, user_id)
        if entry is None or entry.step not in COLLECTION_STEPS or entry.opted_out:
            to_ai = True     # finished or paused meanwhile
        else:
            to_ai = await _collect(entry, msg, chat_id)
    if to_ai:
        await _to_ai(msg)


async def _collect(entry: FunnelEntry, msg: dict, chat_id: str) -> bool:
    """Handle one answer. Returns True when the message belongs to the AI instead:
    a question ("?") or the 2nd invalid answer in a row — the step is kept, so the
    next valid answer continues the funnel."""
    text = str(msg.get("text") or "").strip()
    contact = msg.get("contact") or {}

    # A shared contact is welcome at any step
    if contact.get("phone_number") and not entry.phone:
        phone = _contact_phone(contact)
        if phone:
            await _reset_fails(entry.tg_user_id)
            await _save(entry.id, phone=phone)
            await telegram.send_message(chat_id, texts.PHONE_ACCEPTED,
                                        reply_markup=menu_keyboard())
            await _after_gate_or_ask(entry)
            return False

    if "?" in text:
        return True

    if entry.step == "tg_channel_gate":
        channel_url = await _gate_blocks(entry)
        if channel_url:
            if await _count_fail(entry.tg_user_id):
                return True
            await telegram.send_message(chat_id, texts.CHANNEL_GATE,
                                        reply_markup=_gate_keyboard(channel_url))
            return False
        await _reset_fails(entry.tg_user_id)
        await ask_next(entry.id)
    elif entry.step == "ask_name":
        name = texts.valid_name(text)
        if not name:
            return await _invalid(entry, chat_id, texts.NAME_INVALID)
        await _reset_fails(entry.tg_user_id)
        await _save(entry.id, full_name=name)
        await ask_next(entry.id)
    elif entry.step == "ask_phone":
        phone = extract_phone(text)
        if not phone:
            return await _invalid(entry, chat_id, texts.PHONE_INVALID, contact_keyboard())
        await _reset_fails(entry.tg_user_id)
        await _save(entry.id, phone=phone)
        await telegram.send_message(chat_id, texts.PHONE_ACCEPTED, reply_markup=menu_keyboard())
        await ask_next(entry.id)
    elif entry.step == "ask_grade":
        grade = texts.parse_grade(text)
        if not grade:
            return await _invalid(entry, chat_id, texts.GRADE_INVALID, grade_keyboard())
        await _reset_fails(entry.tg_user_id)
        await _save(entry.id, grade=grade)
        await ask_next(entry.id)
    return False


async def _invalid(entry: FunnelEntry, chat_id: str, hint: str,
                   markup: Optional[dict] = None) -> bool:
    """First invalid answer: re-ask with a hint. Second in a row: hand to the AI."""
    if await _count_fail(entry.tg_user_id):
        return True
    await telegram.send_message(chat_id, hint, reply_markup=markup)
    return False


async def _count_fail(user_id: Optional[str]) -> bool:
    """Count an invalid answer; True once it is the 2nd (or later) in a row."""
    key = _FAILS_KEY.format(user=user_id)
    try:
        count = int(await store.get_value(key) or 0) + 1
        await store.set_value(key, str(count), ttl=_FAILS_TTL)
    except Exception as exc:  # noqa: BLE001
        logger.warning("Funnel fail counter unavailable: {}", exc)
        return False
    return count >= _MAX_FAILS


async def _reset_fails(user_id: Optional[str]) -> None:
    try:
        await store.set_value(_FAILS_KEY.format(user=user_id), "0", ttl=_FAILS_TTL)
    except Exception as exc:  # noqa: BLE001
        logger.warning("Funnel fail counter unavailable: {}", exc)


async def _after_gate_or_ask(entry: FunnelEntry) -> None:
    if entry.step == "tg_channel_gate":
        await _recheck_gate(entry, entry.tg_chat_id)
    else:
        await ask_next(entry.id)


def _contact_phone(contact: dict) -> Optional[str]:
    digits = "".join(ch for ch in str(contact.get("phone_number") or "") if ch.isdigit())
    return extract_phone(f"+{digits}") if digits else None


async def _recheck_gate(entry: FunnelEntry, chat_id: str) -> bool:
    """Re-run the channel check; passes on to the questions when subscribed."""
    channel_url = await _gate_blocks(entry)
    if channel_url:
        await telegram.send_message(chat_id, texts.CHANNEL_GATE,
                                    reply_markup=_gate_keyboard(channel_url))
        return False
    await ask_next(entry.id)
    return True


async def _to_ai(msg: dict) -> None:
    from app.processing.pipeline import process_event
    from app.telegram_business.models import parse_update

    for event in parse_update({"message": msg}):
        await process_event(event)


async def handle_callback(callback: dict) -> None:
    """Inline buttons `fb:*` — grade, channel check and the booking flow."""
    callback_id = str(callback.get("id") or "")
    data = str(callback.get("data") or "")
    message = callback.get("message") or {}
    chat = message.get("chat") or {}
    user_id = str((callback.get("from") or {}).get("id") or "")
    notice: Optional[str] = None
    try:
        if chat.get("type") != "private" or not user_id:
            return
        if callback_id and await _seen_callback(callback_id):
            return
        chat_id = str(chat.get("id"))
        message_id = message.get("message_id")
        async with locks.lock(f"tg:{user_id}"):
            if data.startswith("fb:g:"):
                await _on_grade(user_id, chat_id, message_id, data[len("fb:g:"):])
            elif data == "fb:chk":
                notice = await _on_gate_check(user_id, chat_id)
            else:
                await booking.handle(user_id, chat_id, message_id, data)
    except Exception as exc:  # noqa: BLE001
        logger.exception("Funnel callback {} failed: {}", data, exc)
    finally:
        if callback_id:
            await telegram.answer_callback_query(callback_id, notice, show_alert=bool(notice))


async def _seen_callback(callback_id: str) -> bool:
    try:
        return await store.seen_once(f"fnl:tgcb:{callback_id}", settings.DEDUP_TTL)
    except Exception as exc:  # noqa: BLE001
        logger.warning("Funnel callback dedup failed (continuing): {}", exc)
        return False


async def _on_grade(user_id: str, chat_id: str, message_id: object, grade: str) -> None:
    async with db_session.SessionLocal() as db:
        entry = await repo.entry_by_tg(db, user_id)
    if entry is None or entry.step != "ask_grade":
        return      # stale button: this question was already answered
    if grade not in texts.grade_options():
        # The grade list was edited since this message was sent: show the current one
        await telegram.send_message(chat_id, texts.GRADE_INVALID, reply_markup=grade_keyboard())
        return
    await _save(entry.id, grade=grade, opted_out=False)
    await _reset_fails(user_id)
    if message_id:
        await telegram.edit_message_text(
            chat_id, message_id, f"{settings.FUNNEL_ASK_GRADE}\n\n✅ {texts.grade_display(grade)}")
    await ask_next(entry.id)


async def _on_gate_check(user_id: str, chat_id: str) -> Optional[str]:
    async with db_session.SessionLocal() as db:
        entry = await repo.entry_by_tg(db, user_id)
    if entry is None:
        await telegram.send_message(chat_id, texts.START_FIRST)
        return None
    if entry.step != "tg_channel_gate":
        return None
    if await _gate_blocks(entry):
        return texts.CHANNEL_NOT_MEMBER
    await _save(entry.id, opted_out=False)
    await ask_next(entry.id)
    return None


async def handle_group_comment(msg: dict) -> None:
    """Keyword comment under a channel post: reply with a deep-link button."""
    user_id = str((msg.get("from") or {}).get("id") or "")
    chat_id = str((msg.get("chat") or {}).get("id"))
    try:
        if await store.seen_once(f"fnl:tgc:{user_id}", _TG_COMMENT_WINDOW):
            return
    except Exception as exc:  # noqa: BLE001
        logger.warning("Funnel group rate check failed (continuing): {}", exc)
    link = await repo.bot_link("tgc")
    if not link:
        logger.warning("Funnel: bot username unknown — cannot reply to the group comment")
        return
    await telegram.send_message(
        chat_id, settings.FUNNEL_TG_COMMENT_REPLY,
        reply_to_message_id=msg.get("message_id"),
        reply_markup={"inline_keyboard": [[{"text": texts.LINK_BUTTON, "url": link}]]})
