"""Izoh cheklovi — javob TASHLANMAYDI, navbatga qo'yiladi."""
from __future__ import annotations

import asyncio

from app.config import settings
from app.instagram.models import IncomingEvent
from app.models_ai import AgentOutput, LeadInfo
from app.state.store import store


def _out() -> AgentOutput:
    return AgentOutput(
        reply="Salom!", language="uz-Latn", intent="greeting", lead_score=20,
        is_hot_lead=False, move_to_dm=False, escalate_to_human=False, lead=LeadInfo(),
    )


def _event(key: str, media: str = "med_x") -> IncomingEvent:
    return IncomingEvent(kind="comment", text=f"Izoh {key}", sender_id=f"u{key}",
                         username=f"user{key}", comment_id=f"c{key}", media_id=media)


def _patch(monkeypatch, pipeline, replies, alerts):
    async def fake_reply(comment_id, message):
        replies.append(comment_id)
        return {}

    async def fake_handle(text, **kwargs):
        return _out()

    async def fake_alert(media, count, minutes):
        alerts.append((media, count))

    async def noop(*a, **k):
        return {}

    monkeypatch.setattr(pipeline.instagram, "reply_to_comment", fake_reply)
    monkeypatch.setattr(pipeline.instagram, "send_private_reply", noop)
    monkeypatch.setattr(pipeline._agent, "handle", fake_handle)
    monkeypatch.setattr(pipeline.leads_client, "log_message", noop)
    monkeypatch.setattr(pipeline.leads_client, "push", noop)
    monkeypatch.setattr(pipeline.notifier, "notify_hot_lead", noop)
    monkeypatch.setattr(pipeline.notifier, "notify_comments_throttled", fake_alert)

    async def fake_context(user_id, limit=40, *, channel="instagram"):
        return None
    monkeypatch.setattr(pipeline.leads_client, "fetch_context", fake_context)


def test_limit_queues_instead_of_dropping(monkeypatch):
    """Chegaradan oshgan izoh yo'qolmaydi — oyna bo'shagach javob beriladi."""
    from app.processing import pipeline

    replies, alerts = [], []
    _patch(monkeypatch, pipeline, replies, alerts)
    monkeypatch.setattr(settings, "CMT_LIMIT_PER_POST", 3)
    monkeypatch.setattr(settings, "CMT_LIMIT_TOTAL", 100)
    monkeypatch.setattr(pipeline, "_RETRY_DELAY", 0)      # testda kutmaymiz

    # Hisoblagichni boshqaramiz: "oyna bo'shadi" holatini simulyatsiya qilamiz
    counts: dict[str, int] = {}
    window = {"free": False}

    async def fake_bump(key: str, seconds: int) -> int:
        if window["free"]:
            return 1
        counts[key] = counts.get(key, 0) + 1
        return counts[key]

    monkeypatch.setattr(pipeline.store, "bump_rate", fake_bump)

    async def scenario():
        for i in range(5):                       # chegara 3, biz 5 ta yuboramiz
            await pipeline.process_event(_event(f"q{i}", "med_q"))
        assert sorted(replies) == ["cq0", "cq1", "cq2"], replies
        assert pipeline._pending_retries == 2, "ikkitasi navbatga tushishi kerak"
        window["free"] = True                    # 10 daqiqa o'tdi deb hisoblaymiz
        await asyncio.sleep(0.05)                # navbatdagilar ishga tushsin

    asyncio.run(scenario())

    assert sorted(replies) == ["cq0", "cq1", "cq2", "cq3", "cq4"], replies
    assert alerts and alerts[0][0] == "med_q", alerts


def test_alert_sent_once_per_window(monkeypatch):
    from app.processing import pipeline

    replies, alerts = [], []
    _patch(monkeypatch, pipeline, replies, alerts)
    monkeypatch.setattr(settings, "CMT_LIMIT_PER_POST", 1)
    monkeypatch.setattr(pipeline, "_RETRY_DELAY", 0)

    counts: dict[str, int] = {}

    async def fake_bump(key: str, seconds: int) -> int:
        counts[key] = counts.get(key, 0) + 1
        return counts[key]

    monkeypatch.setattr(pipeline.store, "bump_rate", fake_bump)

    async def scenario():
        for i in range(4):
            await pipeline.process_event(_event(f"a{i}", "med_alert"))
        await asyncio.sleep(0.02)

    asyncio.run(scenario())
    assert len(alerts) == 1, alerts        # oynaga bitta ogohlantirish


def test_limit_is_configurable(monkeypatch):
    from app.processing import pipeline

    monkeypatch.setattr(settings, "CMT_LIMIT_PER_POST", 7)
    monkeypatch.setattr(settings, "CMT_LIMIT_TOTAL", 55)
    assert pipeline._comment_limit() == 7
    assert pipeline._global_limit() == 55


def test_queue_has_a_ceiling(monkeypatch):
    """Navbat cheksiz o'smaydi — xotira to'lib ketmasin."""
    from app.processing import pipeline

    monkeypatch.setattr(pipeline, "_MAX_PENDING", 0)

    async def scenario():
        await pipeline._queue_comment_retry(_event("z9"), attempt=0)
        assert pipeline._pending_retries == 0

    asyncio.run(scenario())


def test_gives_up_after_max_retries(monkeypatch):
    from app.processing import pipeline

    async def scenario():
        before = pipeline._pending_retries
        await pipeline._queue_comment_retry(_event("z1"), attempt=pipeline._MAX_RETRIES)
        assert pipeline._pending_retries == before   # navbatga qo'yilmadi

    asyncio.run(scenario())
