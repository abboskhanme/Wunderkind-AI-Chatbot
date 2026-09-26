"""Shared fakes for the funnel tests: Telegram, Instagram and staff alerts are
recorded in memory — no network. Import the fixtures into a test module."""
from __future__ import annotations

import asyncio
import hashlib
from datetime import datetime, timezone
from typing import Any

import pytest
from fastapi import BackgroundTasks
from sqlalchemy import select

from app.config import settings

BOT_TOKEN = "12345:" + "x" * 35
PDF_BYTES = b"%PDF-1.4 test lead magnet"


class Recorder:
    def __init__(self) -> None:
        self.calls: list[tuple[str, dict[str, Any]]] = []
        self.member_status: Any = "member"        # str | None (API error)
        self.results: dict[str, dict] = {}        # method -> forced result

    def of(self, method: str) -> list[dict[str, Any]]:
        return [c for m, c in self.calls if m == method]

    def texts(self) -> list[str]:
        return [c["text"] for m, c in self.calls if m in ("message", "edit") and c.get("text")]


@pytest.fixture
def fake_tg(monkeypatch):
    """Telegram bot client + alerts; bot username "wk_bot"."""
    from app.services import agent_status
    from app.telegram import notifier
    from app.telegram_business.client import telegram

    rec = Recorder()
    monkeypatch.setattr(settings, "TG_SALES_BOT_TOKEN", BOT_TOKEN)
    agent_status._bot_cache.clear()

    def forced(method: str, default: dict) -> dict:
        return rec.results.get(method, default)

    async def send_message(chat_id, text, **kw):
        rec.calls.append(("message", {"chat_id": str(chat_id), "text": text, **kw}))
        return forced("message", {"sent": True, "message_id": "900"})

    async def send_document(chat_id, document, **kw):
        rec.calls.append(("document", {"chat_id": str(chat_id), "document": document, **kw}))
        return forced("document", {"sent": True, "file_id": "FILE-1"})

    async def send_photo(chat_id, photo, **kw):
        rec.calls.append(("photo", {"chat_id": str(chat_id), "photo": photo, **kw}))
        return forced("photo", {"sent": True, "file_ids": ["PHOTO-1"]})

    async def send_location(chat_id, latitude, longitude, **kw):
        rec.calls.append(("location", {"chat_id": str(chat_id), "lat": latitude,
                                       "lon": longitude}))
        return {"sent": True}

    async def edit_message_text(chat_id, message_id, text, **kw):
        rec.calls.append(("edit", {"chat_id": str(chat_id), "message_id": message_id,
                                   "text": text, **kw}))
        return {"sent": True}

    async def answer_callback_query(callback_id, text=None, **kw):
        rec.calls.append(("answer", {"id": callback_id, "text": text}))
        return True

    async def get_chat_member(chat_id, user_id):
        rec.calls.append(("member", {"chat_id": chat_id, "user_id": str(user_id)}))
        return None if rec.member_status is None else {"status": rec.member_status}

    async def get_chat(chat_id):
        # Channels have negative ids; a private chat (customer profile) -> no extras
        if str(chat_id).startswith("-"):
            return {"id": chat_id, "username": "wk_channel"}
        return None

    async def get_me():
        return {"username": "wk_bot"}

    async def alert(text):
        rec.calls.append(("alert", {"text": text}))
        return {"sent": True}

    for name, fn in (("send_message", send_message), ("send_document", send_document),
                     ("send_photo", send_photo), ("send_location", send_location),
                     ("edit_message_text", edit_message_text),
                     ("answer_callback_query", answer_callback_query),
                     ("get_chat_member", get_chat_member), ("get_chat", get_chat),
                     ("get_me", get_me)):
        monkeypatch.setattr(telegram, name, fn)
    monkeypatch.setattr(notifier, "send_text", alert)
    yield rec
    agent_status._bot_cache.clear()


@pytest.fixture
def fake_ig(monkeypatch):
    """Instagram client: quick replies, templates, profile (follow status)."""
    from app.instagram.client import instagram

    rec = Recorder()
    rec.profile = None          # dict | None (None = API error)
    monkeypatch.setattr(settings, "IG_ACCESS_TOKEN", "ig-token")

    async def send_message_to(recipient, message):
        rec.calls.append(("send", {"recipient": recipient, "message": message}))
        return rec.results.get("send", {"sent": True})

    async def send_quick_replies(recipient, text, quick_replies):
        rec.calls.append(("quick", {"recipient": recipient, "text": text,
                                    "quick_replies": quick_replies}))
        return rec.results.get("quick", {"sent": True})

    async def send_button_template(recipient, text, buttons):
        rec.calls.append(("template", {"recipient": recipient, "text": text,
                                       "buttons": buttons}))
        return rec.results.get("template", {"sent": True})

    async def reply_to_comment(comment_id, message):
        rec.calls.append(("public", {"comment_id": comment_id, "text": message}))
        return {"id": "r1"}

    async def get_user_profile(igsid):
        rec.calls.append(("profile", {"igsid": igsid}))
        return rec.profile

    async def get_full_profile(igsid):
        return rec.profile       # account profile capture (not recorded)

    for name, fn in (("send_message_to", send_message_to),
                     ("send_quick_replies", send_quick_replies),
                     ("send_button_template", send_button_template),
                     ("reply_to_comment", reply_to_comment),
                     ("get_user_profile", get_user_profile),
                     ("get_full_profile", get_full_profile)):
        monkeypatch.setattr(instagram, name, fn)
    return rec


# --------------------------------------------------------------------------- #
# Helpers
# --------------------------------------------------------------------------- #
def feed(update: dict) -> None:
    """Run one Telegram update through the real webhook handler + its tasks."""
    from app.telegram_business import webhook

    async def run():
        background = BackgroundTasks()
        await webhook.handle_update(update, background)
        await background()

    asyncio.run(run())


_ids = iter(range(1000, 10**6))


def private_text(user_id: int, text: str, **extra) -> dict:
    return {"update_id": next(_ids), "message": {
        "message_id": next(_ids), "text": text,
        "from": {"id": user_id, "is_bot": False, "username": f"user{user_id}"},
        "chat": {"id": user_id, "type": "private"}, **extra}}


def contact(user_id: int, phone: str) -> dict:
    return {"update_id": next(_ids), "message": {
        "message_id": next(_ids), "contact": {"phone_number": phone, "user_id": user_id},
        "from": {"id": user_id, "is_bot": False}, "chat": {"id": user_id, "type": "private"}}}


def callback(user_id: int, data: str, message_id: int = 77) -> dict:
    return {"update_id": next(_ids), "callback_query": {
        "id": f"cb{next(_ids)}", "data": data, "from": {"id": user_id},
        "message": {"message_id": message_id, "chat": {"id": user_id, "type": "private"}}}}


def run(coro):
    return asyncio.run(coro)


def db_all(database, model, *where):
    async def q():
        async with database() as s:
            return list((await s.execute(select(model).where(*where))).scalars().all())
    return run(q())


def db_add(database, *objects):
    async def q():
        async with database() as s:
            for obj in objects:
                s.add(obj)
            await s.commit()
    run(q())
    return objects[0] if len(objects) == 1 else objects


def add_pdf(database) -> None:
    from app.models.funnel import LEAD_MAGNET_KEY, FunnelFile

    db_add(database, FunnelFile(key=LEAD_MAGNET_KEY, filename="8 maslahat.pdf",
                                content_type="application/pdf", size_bytes=len(PDF_BYTES),
                                data=PDF_BYTES, sha256=hashlib.sha256(PDF_BYTES).hexdigest()))


def utc(*args) -> datetime:
    return datetime(*args, tzinfo=timezone.utc)
