"""Instagram «Qo'llanmani olish» → /go/<token> landing page (Instagram's in-app
browser blocks t.me → Telegram app, so the DM button points to our page)."""
import asyncio

import httpx
import pytest
from fastapi.testclient import TestClient

from app.config import settings
from app.funnel import repo
from app.instagram import client as ig_client
from app.main import app
from app.services import agent_status


@pytest.fixture
def bot(monkeypatch):
    async def username():
        return "wk_bot"

    monkeypatch.setattr(agent_status, "telegram_bot_username", username)


def test_ig_link_goes_straight_to_telegram_by_default(monkeypatch, bot):
    monkeypatch.setattr(settings, "PUBLIC_URL", "https://chatbot.example.uz/")
    assert asyncio.run(repo.ig_link("abc123")) == "https://t.me/wk_bot?start=abc123"


def test_ig_link_uses_landing_page_when_enabled(monkeypatch, bot):
    monkeypatch.setattr(settings, "PUBLIC_URL", "https://chatbot.example.uz/")
    monkeypatch.setattr(settings, "FUNNEL_IG_LINK_VIA_PAGE", True)
    assert asyncio.run(repo.ig_link("abcDEF123_-x")) == "https://chatbot.example.uz/go/abcDEF123_-x"


def test_ig_link_falls_back_to_tme_without_public_url(monkeypatch, bot):
    monkeypatch.setattr(settings, "PUBLIC_URL", "")
    assert asyncio.run(repo.ig_link("abc123")) == "https://t.me/wk_bot?start=abc123"


def test_landing_page_offers_every_route_to_telegram(monkeypatch, bot):
    monkeypatch.setattr(settings, "PUBLIC_URL", "https://chatbot.example.uz")
    r = TestClient(app).get("/go/abcDEF123_-x")
    assert r.status_code == 200
    assert r.headers["content-type"].startswith("text/html")
    body = r.text
    assert "tg://resolve?domain=wk_bot&amp;start=abcDEF123_-x" in body
    assert "https://t.me/wk_bot?start=abcDEF123_-x" in body
    assert "intent://resolve?domain=wk_bot&start=abcDEF123_-x#Intent;scheme=tg;" in body
    assert "x-safari-https://chatbot.example.uz/go/abcDEF123_-x" in body
    assert "/start abcDEF123_-x" in body
    assert r.headers["cache-control"] == "no-store"
    # Computer: Telegram Web + a QR code to open the bot on the phone
    assert ("https://web.telegram.org/k/#?tgaddr=tg%3A%2F%2Fresolve%3Fdomain%3Dwk_bot"
            "%26start%3DabcDEF123_-x") in body
    assert "<svg" in body and 'class="segno"' in body


@pytest.mark.parametrize("token", ["a%22%3E%3Cscript%3E", "x" * 41, "a.b"])
def test_landing_rejects_bad_tokens(bot, token):
    r = TestClient(app).get(f"/go/{token}")
    assert r.status_code == 404
    assert "<script>" not in r.text


def test_landing_without_bot_is_503(monkeypatch):
    async def username():
        return ""

    monkeypatch.setattr(agent_status, "telegram_bot_username", username)
    assert TestClient(app).get("/go/abc123").status_code == 503


def test_profile_without_consent_is_not_retried(monkeypatch):
    """IG error 230 comes back as HTTP 500 — retrying only delayed the DM by ~7 s."""
    calls = {"n": 0}

    def handler(request: httpx.Request) -> httpx.Response:
        calls["n"] += 1
        return httpx.Response(500, json={"error": {
            "message": "User consent is required to access user profile",
            "type": "IGApiException", "code": 230}})

    real_client = httpx.AsyncClient
    monkeypatch.setattr(ig_client.httpx, "AsyncClient",
                        lambda **kw: real_client(transport=httpx.MockTransport(handler), **kw))
    monkeypatch.setattr(settings, "IG_ACCESS_TOKEN", "tok")
    assert asyncio.run(ig_client.instagram.get_user_profile("123")) is None
    assert calls["n"] == 1
