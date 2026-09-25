"""Bildirishnoma — vergul bilan berilgan har bir chat ID ga alohida yuboriladi."""
from __future__ import annotations

import asyncio

import httpx

from app.config import settings
from app.telegram import notifier


def test_chat_ids_parsing():
    assert notifier.chat_ids("") == []
    assert notifier.chat_ids("123") == ["123"]
    assert notifier.chat_ids("123, 456") == ["123", "456"]
    assert notifier.chat_ids(" 123 ;456,, -100789 ,123") == ["123", "456", "-100789"]


def test_send_goes_to_every_chat_even_if_one_fails(monkeypatch):
    sent: list[str] = []

    def handler(request: httpx.Request) -> httpx.Response:
        import json

        chat_id = json.loads(request.content)["chat_id"]
        sent.append(chat_id)
        if chat_id == "111":
            return httpx.Response(400, json={"ok": False, "description": "chat not found"})
        return httpx.Response(200, json={"ok": True})

    real_client = httpx.AsyncClient

    def fake_client(*args, **kwargs):
        kwargs["transport"] = httpx.MockTransport(handler)
        return real_client(*args, **kwargs)

    monkeypatch.setattr(notifier.httpx, "AsyncClient", fake_client)
    monkeypatch.setattr(settings, "TELEGRAM_BOT_TOKEN", "test-token")
    monkeypatch.setattr(settings, "TELEGRAM_CHAT_ID", "111, 222")

    asyncio.run(notifier._send("salom"))

    assert sent == ["111", "222"]
