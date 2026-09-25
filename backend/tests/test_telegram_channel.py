"""Telegram kanali — update'ni o'qish, javob yuborish, operator aralashuvi."""
from __future__ import annotations

import asyncio

from fastapi.testclient import TestClient

from app.config import settings
from app.instagram.models import IncomingEvent
from app.models_ai import AgentOutput, LeadInfo
from app.telegram_business.client import telegram
from app.telegram_business.models import parse_update
from app.telegram_business.webhook import CHAT_KEY, CONN_KEY
from app.state.store import store

OWNER = 555001            # akkaunt egasi (biz)
CUSTOMER = 777002         # mijoz


def _msg(text=None, *, from_id=CUSTOMER, chat_id=CUSTOMER, conn="conn_1", **extra):
    msg = {
        "message_id": 11,
        "business_connection_id": conn,
        "from": {"id": from_id, "username": "mijoz_ali", "is_bot": False},
        "chat": {"id": chat_id, "type": "private", "username": "mijoz_ali"},
    }
    if text is not None:
        msg["text"] = text
    msg.update(extra)
    return msg


def _out(reply="Salom! Qanday yordam beray?") -> AgentOutput:
    return AgentOutput(
        reply=reply, language="uz-Latn", intent="greeting", lead_score=30,
        is_hot_lead=False, move_to_dm=False, escalate_to_human=False, lead=LeadInfo(),
    )


# --------------------------------------------------------------------------- #
# Update -> IncomingEvent
# --------------------------------------------------------------------------- #
def test_customer_message_becomes_dm_event():
    events = parse_update({"business_message": _msg("Narxi qancha?")}, owner_id=OWNER)
    assert len(events) == 1
    ev = events[0]
    assert ev.channel == "telegram" and ev.kind == "dm"
    assert ev.sender_id == str(CUSTOMER) and ev.chat_id == str(CUSTOMER)
    assert ev.business_connection_id == "conn_1"
    assert ev.username == "mijoz_ali"
    assert ev.store_key == f"tg:{CUSTOMER}"
    assert ev.dedup_key == f"tg:{CUSTOMER}:11"


def test_owner_message_becomes_echo():
    """Akkaunt egasi (operator) yozgan xabar — echo, ya'ni bot jim turishi kerak."""
    events = parse_update(
        {"business_message": _msg("Men menejerman", from_id=OWNER)}, owner_id=OWNER,
    )
    assert len(events) == 1 and events[0].kind == "echo"
    # Suhbatdosh — mijoz (chat egasi), operator emas
    assert events[0].sender_id == str(CUSTOMER)


def test_media_message_is_kept_with_placeholder():
    events = parse_update({"business_message": _msg(voice={"file_id": "x"})}, owner_id=OWNER)
    assert len(events) == 1
    assert "ovozli xabar" in events[0].text and events[0].has_attachment is True


def test_group_and_bot_messages_ignored():
    group = _msg("salom")
    group["chat"]["type"] = "group"
    assert parse_update({"business_message": group}, owner_id=OWNER) == []

    from_bot = _msg("salom")
    from_bot["from"]["is_bot"] = True
    assert parse_update({"business_message": from_bot}, owner_id=OWNER) == []


def test_plain_bot_chat_message_also_works():
    """Business ulanishisiz — mijoz botning o'ziga yozsa ham ishlaydi."""
    msg = _msg("Salom", conn=None)
    msg.pop("business_connection_id")
    events = parse_update({"message": msg}, owner_id=None)
    assert len(events) == 1 and events[0].kind == "dm"
    assert events[0].business_connection_id is None


# --------------------------------------------------------------------------- #
# Pipeline: Telegram orqali javob
# --------------------------------------------------------------------------- #
def test_pipeline_replies_via_telegram(monkeypatch):
    from app.processing import pipeline

    sent: list[dict] = []
    logged: list[dict] = []

    async def fake_send(chat_id, text, *, business_connection_id=None):
        sent.append({"chat_id": chat_id, "text": text, "conn": business_connection_id})
        return {"sent": True}

    async def fake_log(**kwargs):
        logged.append(kwargs)
        return True

    async def fake_context(user_id, limit=40, *, channel="instagram"):
        assert channel == "telegram"
        return None

    async def fake_handle(text, **kwargs):
        return _out()

    async def noop(*a, **k):
        return {}

    monkeypatch.setattr(pipeline.telegram, "send_message", fake_send)
    monkeypatch.setattr(pipeline.leads_client, "log_message", fake_log)
    monkeypatch.setattr(pipeline.leads_client, "fetch_context", fake_context)
    monkeypatch.setattr(pipeline.leads_client, "push", noop)
    monkeypatch.setattr(pipeline._agent, "handle", fake_handle)
    monkeypatch.setattr(pipeline.notifier, "notify_hot_lead", noop)

    event = IncomingEvent(
        kind="dm", text="Salom", sender_id=str(CUSTOMER), channel="telegram",
        chat_id=str(CUSTOMER), business_connection_id="conn_1", message_id="42",
    )
    asyncio.run(pipeline.process_event(event))

    assert len(sent) == 1, sent
    assert sent[0]["conn"] == "conn_1"
    assert "AI yordamchisi" in sent[0]["text"], "birinchi xabarda oshkorlik bo'lishi kerak"
    assert [item["channel"] for item in logged] == ["telegram", "telegram"]
    assert [item["role"] for item in logged] == ["user", "assistant"]

    # Bot yuborgan xabar echo bo'lib qaytsa — pauza bo'lmasligi kerak
    async def check():
        assert await store.was_sent_by_bot(f"tg:{CUSTOMER}", sent[0]["text"]) is True
    asyncio.run(check())


def test_operator_message_is_logged_but_does_not_pause_bot(monkeypatch):
    from app.processing import pipeline

    logged: list[dict] = []

    async def fake_log(**kwargs):
        logged.append(kwargs)
        return True

    monkeypatch.setattr(pipeline.leads_client, "log_message", fake_log)

    event = IncomingEvent(
        kind="echo", text="Men javob beraman", sender_id="900900",
        channel="telegram", chat_id="900900",
    )
    asyncio.run(pipeline.process_event(event))

    async def check():
        assert await store.is_paused("tg:900900") is False
    asyncio.run(check())
    assert [(m["role"], m["text"]) for m in logged] == [("operator", "Men javob beraman")]


# --------------------------------------------------------------------------- #
# Webhook va ERP uchun endpointlar
# --------------------------------------------------------------------------- #
def _client(monkeypatch) -> TestClient:
    monkeypatch.setattr(settings, "TG_SALES_BOT_TOKEN", "12345:token")
    monkeypatch.setattr(settings, "TG_SALES_ENABLED", True)
    monkeypatch.setattr(settings, "TG_WEBHOOK_SECRET", "s3cret")
    from app.main import app
    return TestClient(app)


def test_webhook_rejects_wrong_secret(monkeypatch):
    with _client(monkeypatch) as c:
        r = c.post("/webhook/telegram", json={"update_id": 1},
                   headers={"X-Telegram-Bot-Api-Secret-Token": "boshqa"})
        assert r.status_code == 403


def test_webhook_remembers_business_connection(monkeypatch):
    with _client(monkeypatch) as c:
        r = c.post("/webhook/telegram",
                   headers={"X-Telegram-Bot-Api-Secret-Token": "s3cret"},
                   json={"business_connection": {
                       "id": "conn_9", "user": {"id": OWNER}, "is_enabled": True}})
        assert r.status_code == 200

    async def check():
        assert await store.get_value(CONN_KEY.format("conn_9")) == str(OWNER)
    asyncio.run(check())
