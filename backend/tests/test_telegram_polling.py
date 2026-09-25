"""Local long polling: updates from getUpdates reach the webhook handler."""
from __future__ import annotations

import asyncio

import httpx
import pytest

from app.config import settings
from app.telegram_business import polling


def test_polling_only_without_public_url(monkeypatch):
    monkeypatch.setattr(settings, "TG_POLLING", True)
    monkeypatch.setattr(settings, "TG_SALES_BOT_TOKEN", "123:abc")
    monkeypatch.setattr(settings, "PUBLIC_URL", "")
    assert polling.polling_active()

    monkeypatch.setattr(settings, "PUBLIC_URL", "https://agent.example.uz")
    assert not polling.polling_active()  # webhook takes over

    monkeypatch.setattr(settings, "PUBLIC_URL", "")
    monkeypatch.setattr(settings, "TG_SALES_BOT_TOKEN", "")
    assert not polling.polling_active()


def test_poll_loop_dispatches_updates_and_advances_offset(monkeypatch):
    monkeypatch.setattr(settings, "TG_POLLING", True)
    monkeypatch.setattr(settings, "TG_SALES_BOT_TOKEN", "123:abc")
    monkeypatch.setattr(settings, "PUBLIC_URL", "")

    calls: list[tuple[str, dict]] = []
    handled: list[dict] = []

    def transport(request: httpx.Request) -> httpx.Response:
        import json

        method = request.url.path.rsplit("/", 1)[-1]
        body = json.loads(request.content or b"{}")
        calls.append((method, body))
        if method == "getUpdates" and body.get("offset", 0) == 0:
            return httpx.Response(200, json={"ok": True, "result": [
                {"update_id": 41, "message": {"text": "salom"}},
                {"update_id": 42, "message": {"text": "narx?"}},
            ]})
        if method == "getUpdates":
            raise asyncio.CancelledError  # stop the loop after the 2nd poll
        return httpx.Response(200, json={"ok": True, "result": True})

    real_client = httpx.AsyncClient
    monkeypatch.setattr(polling.httpx, "AsyncClient",
                        lambda **kw: real_client(transport=httpx.MockTransport(transport)))

    async def fake_handle(update, background):
        handled.append(update)

    monkeypatch.setattr(polling, "handle_update", fake_handle)

    async def run():
        with pytest.raises(asyncio.CancelledError):
            await polling.run_polling()
        await asyncio.sleep(0)  # let dispatched tasks finish

    asyncio.run(run())

    methods = [m for m, _ in calls]
    assert methods[0] == "deleteWebhook"  # getUpdates is refused while a webhook is set
    assert calls[-1] == ("getUpdates", calls[-1][1]) and calls[-1][1]["offset"] == 43
    assert [u["update_id"] for u in handled] == [41, 42]
