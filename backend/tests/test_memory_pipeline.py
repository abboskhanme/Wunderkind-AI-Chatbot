"""Pipeline + DB memory: messages logged, facts saved, follow-ups."""
from __future__ import annotations

import asyncio
import os
from datetime import datetime, timedelta, timezone

import pytest
from sqlalchemy import select

from app.instagram.models import IncomingEvent
from app.models_ai import AgentOutput, LeadInfo


def _out(**lead) -> AgentOutput:
    return AgentOutput(
        reply="Ajoyib! Farzandingiz necha yoshda?", language="uz-Latn", intent="course_question",
        stage="discovery", lead_score=90 if lead.get("contact") else 40,
        is_hot_lead=bool(lead.get("contact")), move_to_dm=False, escalate_to_human=False,
        lead=LeadInfo(**lead),
    )


def _patch_io(monkeypatch, out: AgentOutput):
    from app.processing import pipeline

    sent, alerts = [], []

    async def fake_dm(recipient, text):
        sent.append((recipient, text))
        return {}

    async def fake_handle(*a, **k):
        fake_handle.calls.append(k)
        return out
    fake_handle.calls = []

    async def fake_alert(*a, **k):
        alerts.append(a)

    monkeypatch.setattr(pipeline.instagram, "send_dm", fake_dm)
    monkeypatch.setattr(pipeline._agent, "handle", fake_handle)
    monkeypatch.setattr(pipeline.notifier, "notify_hot_lead", fake_alert)
    return sent, alerts, fake_handle


def _leads(database):
    from app.models.lead import Lead, LeadMessage

    async def _q():
        async with database() as s:
            leads = (await s.execute(select(Lead))).scalars().all()
            msgs = (await s.execute(select(LeadMessage).order_by(LeadMessage.created_at))
                    ).scalars().all()
            return leads, msgs

    return asyncio.run(_q())


def test_dm_flow_logs_and_saves_facts(monkeypatch, database):
    from app.processing import pipeline

    sent, alerts, handle = _patch_io(monkeypatch, _out(
        name="Dilnoza", contact="+998901234567", course_interest="Ingliz tili",
        student_age="9 yosh"))
    ev = IncomingEvent(kind="dm", text="Qizim uchun ingliz tili, raqamim 90 123 45 67",
                       sender_id="c1", username="dilnoza", message_id="mid1")
    asyncio.run(pipeline.process_event(ev))

    assert len(sent) == 1 and "AI yordamchisi" in sent[0][1]  # first message disclosure
    leads, msgs = _leads(database)
    assert len(leads) == 1
    lead = leads[0]
    assert lead.contact == "+998901234567" and lead.course_interest == "Ingliz tili"
    assert lead.student_age == "9 yosh" and lead.lead_score == 90 and lead.stage == "discovery"
    assert [m.role for m in msgs] == ["user", "assistant"]
    assert len(alerts) == 1

    # Second message: history + known facts are passed to the agent, no disclosure
    ev2 = IncomingEvent(kind="dm", text="Qachon boshlanadi?", sender_id="c1", message_id="mid2")
    asyncio.run(pipeline.process_event(ev2))
    call = handle.calls[-1]
    assert [m["role"] for m in call["history"]] == ["user", "assistant"]
    assert call["known"]["contact"] == "+998901234567"
    assert "AI yordamchisi" not in sent[-1][1]


def test_phone_extracted_without_ai(monkeypatch, database):
    from app.processing import pipeline

    _patch_io(monkeypatch, _out())
    ev = IncomingEvent(kind="dm", text="mening raqamim +998 93 555 44 33", sender_id="c2",
                       message_id="m9")
    asyncio.run(pipeline.process_event(ev))
    leads, _ = _leads(database)
    assert leads[0].contact == "+998935554433"


def test_ai_disabled_only_logs(monkeypatch, database):
    from app.config import settings
    from app.processing import pipeline

    sent, _, handle = _patch_io(monkeypatch, _out())
    monkeypatch.setattr(settings, "IG_AI_ENABLED", False)
    asyncio.run(pipeline.process_event(IncomingEvent(kind="dm", text="Salom", sender_id="c3",
                                                      message_id="x1")))
    assert sent == [] and handle.calls == []
    _, msgs = _leads(database)
    assert [m.role for m in msgs] == ["user"]


def test_paused_chat_still_logged_but_not_answered(monkeypatch, database, fresh_state):
    from app.processing import pipeline

    sent, _, _ = _patch_io(monkeypatch, _out())
    asyncio.run(fresh_state.pause("c4", 12))
    asyncio.run(pipeline.process_event(IncomingEvent(kind="dm", text="Hello", sender_id="c4",
                                                      message_id="p1")))
    assert sent == []
    _, msgs = _leads(database)
    assert [m.role for m in msgs] == ["user"]


def test_cold_comment_does_not_open_lead(monkeypatch, database):
    from app.processing import pipeline

    async def noop(*a, **k):
        return {}

    _patch_io(monkeypatch, _out())
    monkeypatch.setattr(pipeline.instagram, "reply_to_comment", noop)
    asyncio.run(pipeline.process_event(IncomingEvent(
        kind="comment", text="🔥🔥", sender_id="c5", comment_id="cm1", media_id="md1")))
    leads, _ = _leads(database)
    assert leads == []


def test_followup_sent_once_for_silent_customer(monkeypatch, database):
    from app.leads import client as leads_client
    from app.processing import followup

    past = datetime.now(timezone.utc) - timedelta(hours=5)
    asyncio.run(leads_client.log_message(user_id="c6", channel="instagram", text="IELTS?",
                                         role="user", sent_at=past))
    asyncio.run(leads_client.log_message(user_id="c6", channel="instagram",
                                         text="Darajangiz qanday?", role="assistant",
                                         sent_at=past + timedelta(minutes=1)))
    sent = []

    async def fake_send(recipient, text, *, human_agent=False, allow_tag_fallback=True):
        assert allow_tag_fallback is False  # automated: never HUMAN_AGENT
        sent.append(text)
        return {"sent": True}

    async def fake_handle(*a, **k):
        assert k["task"]
        return _out()

    monkeypatch.setattr(followup.instagram, "send_dm_result", fake_send)
    monkeypatch.setattr(followup._agent, "handle", fake_handle)

    assert asyncio.run(followup.run_followups()) == 1
    assert asyncio.run(followup.run_followups()) == 0  # only once
    assert len(sent) == 1
    leads, msgs = _leads(database)
    assert msgs[-1].meta.get("followup") is True and leads[0].last_followup_at


def test_followup_skips_when_contact_known_or_window_closed(monkeypatch, database):
    from app.leads import client as leads_client
    from app.processing import followup

    old = datetime.now(timezone.utc) - timedelta(hours=30)   # IG window closed
    for uid, when, text in (("c7", old, "salom"),
                            ("c8", datetime.now(timezone.utc) - timedelta(hours=5), "90 111 22 33")):
        asyncio.run(leads_client.log_message(user_id=uid, channel="instagram", text=text,
                                             role="user", sent_at=when))
        asyncio.run(leads_client.log_message(user_id=uid, channel="instagram", text="?",
                                             role="assistant", sent_at=when + timedelta(minutes=1)))
    assert asyncio.run(followup.due_leads()) == []


def test_business_bot_echo_is_not_a_customer_message():
    """Lost owner mapping must not make the bot answer its own Business messages."""
    from app.telegram_business.models import event_from_message

    msg = {"message_id": 5, "business_connection_id": "conn", "text": "Salom!",
           "chat": {"id": 555, "type": "private"}, "from": {"id": 999},
           "sender_business_bot": {"id": 42, "is_bot": True}}
    ev = event_from_message(msg, owner_id=None)
    assert ev.kind == "echo" and ev.sender_id == "555"


@pytest.mark.skipif(not os.environ.get("PG_TEST_URL"),
                    reason="needs PostgreSQL (PG_TEST_URL) — SQLite shares one connection")
def test_concurrent_messages_share_one_lead(monkeypatch):
    """Parallel webhooks for a new person create ONE open lead (unique index)."""
    from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

    from app.db import session as db_session
    from app.db.base import Base
    from app.leads import client as leads_client
    from app.models.lead import Lead, LeadMessage

    async def run():
        engine = create_async_engine(os.environ["PG_TEST_URL"])
        async with engine.begin() as conn:
            await conn.run_sync(Base.metadata.drop_all)
            await conn.run_sync(Base.metadata.create_all)
        factory = async_sessionmaker(engine, expire_on_commit=False)
        monkeypatch.setattr(db_session, "SessionLocal", factory)
        await asyncio.gather(*[
            leads_client.log_message(user_id="c9", channel="instagram", text=f"m{i}",
                                     role="user", ig_message_id=f"id{i}")
            for i in range(8)
        ])
        async with factory() as s:
            leads = (await s.execute(select(Lead))).scalars().all()
            msgs = (await s.execute(select(LeadMessage))).scalars().all()
        async with engine.begin() as conn:
            await conn.run_sync(Base.metadata.drop_all)
        await engine.dispose()
        return leads, msgs

    leads, msgs = asyncio.run(run())
    assert len(leads) == 1 and len(msgs) == 8
