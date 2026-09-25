"""Admin API: auth, RBAC, settings, leads/inbox, bot menu, playground."""
from __future__ import annotations

import asyncio

import pytest
from sqlalchemy import select

from tests.conftest import auth_headers, make_user


@pytest.fixture
def admin(client, database):
    make_user(database, "admin", "admin")
    return auth_headers(client, "admin")


@pytest.fixture
def operator(client, database):
    make_user(database, "opa", "operator")
    return auth_headers(client, "opa")


def _seed_conversation(channel="instagram", user_id="cust1", text="Salom, IELTS bormi?"):
    from app.leads import client as leads_client

    asyncio.run(leads_client.log_message(user_id=user_id, username="ali", channel=channel,
                                         text=text, role="user", ig_message_id="m1"))
    asyncio.run(leads_client.log_message(user_id=user_id, username="ali", channel=channel,
                                         text="Bor! Yoshingiz nechada?", role="assistant"))


def _lead_id(database):
    from app.models.lead import Lead

    async def _get():
        async with database() as s:
            return (await s.execute(select(Lead.id))).scalar_one()

    return str(asyncio.run(_get()))


# --- Auth / RBAC ------------------------------------------------------------------
def test_login_wrong_password(client, database):
    make_user(database, "admin", "admin")
    r = client.post("/api/auth/login", json={"username": "admin", "password": "nope"})
    assert r.status_code == 401


@pytest.mark.parametrize("method,path", [
    ("get", "/api/auth/me"), ("get", "/api/leads"), ("get", "/api/leads/inbox"),
    ("get", "/api/dashboard"), ("get", "/api/settings"), ("get", "/api/users"),
    ("get", "/api/bot-menu"), ("get", "/api/settings/status"),
])
def test_requires_auth(client, method, path):
    assert getattr(client, method)(path).status_code == 401


@pytest.mark.parametrize("method,path,body", [
    ("get", "/api/settings", None),
    ("put", "/api/settings", {"values": {"COMPANY_NAME": "X"}}),
    ("get", "/api/users", None),
    ("post", "/api/users", {"username": "zz", "password": "secret123"}),
    ("get", "/api/bot-menu", None),
    ("post", "/api/playground", {"messages": [{"role": "user", "content": "salom"}]}),
    ("post", "/api/settings/instagram/connect-url", None),
    ("post", "/api/settings/telegram/test", None),
])
def test_operator_forbidden_on_admin_endpoints(client, operator, method, path, body):
    kwargs = {"headers": operator}
    if body is not None:
        kwargs["json"] = body
    assert getattr(client, method)(path, **kwargs).status_code == 403


def test_operator_can_use_inbox_and_dashboard(client, operator):
    assert client.get("/api/leads/inbox", headers=operator).status_code == 200
    assert client.get("/api/dashboard", headers=operator).status_code == 200
    assert client.get("/api/settings/status", headers=operator).status_code == 200


def test_operator_cannot_delete_lead(client, operator, database):
    _seed_conversation()
    assert client.delete(f"/api/leads/{_lead_id(database)}", headers=operator).status_code == 403


# --- Users --------------------------------------------------------------------------
def test_user_crud_and_self_protection(client, admin):
    r = client.post("/api/users", headers=admin,
                    json={"username": "op1", "full_name": "Op", "password": "secret123",
                          "role": "operator"})
    assert r.status_code == 201, r.text
    uid = r.json()["id"]
    assert client.post("/api/users", headers=admin, json={
        "username": "op1", "password": "secret123"}).status_code == 400
    assert client.patch(f"/api/users/{uid}", headers=admin,
                        json={"is_active": False}).json()["is_active"] is False
    me = client.get("/api/auth/me", headers=admin).json()
    assert client.delete(f"/api/users/{me['id']}", headers=admin).status_code == 400
    assert client.delete(f"/api/users/{uid}", headers=admin).status_code == 204


# --- Settings -----------------------------------------------------------------------
def test_settings_secret_is_encrypted_masked_and_applied(client, admin, database):
    from app.config import settings
    from app.models.setting import Setting

    r = client.put("/api/settings", headers=admin,
                   json={"values": {"ANTHROPIC_API_KEY": "sk-ant-api03-1234567890abcdefghijabcd",
                                    "COMPANY_NAME": "Wunderkind Test",
                                    "FOLLOWUP_AFTER_HOURS": "5"}})
    assert r.status_code == 200, r.text
    items = {i["key"]: i for g in r.json()["groups"] for i in g["items"]}
    assert items["ANTHROPIC_API_KEY"]["value"] == ""
    assert items["ANTHROPIC_API_KEY"]["masked"].endswith("abcd")
    assert items["COMPANY_NAME"]["value"] == "Wunderkind Test"
    # applied live
    assert settings.ANTHROPIC_API_KEY == "sk-ant-api03-1234567890abcdefghijabcd"
    assert settings.FOLLOWUP_AFTER_HOURS == 5

    async def raw():
        async with database() as s:
            return (await s.get(Setting, "ANTHROPIC_API_KEY")).value

    stored = asyncio.run(raw())
    assert stored.startswith("enc:") and "abcd" not in stored

    # empty value removes the DB row -> baseline
    client.put("/api/settings", headers=admin, json={"values": {"COMPANY_NAME": ""}})
    assert settings.COMPANY_NAME == "Wunderkind"


def test_settings_rejects_unknown_and_bad_number(client, admin):
    assert client.put("/api/settings", headers=admin,
                      json={"values": {"DATABASE_URL": "x"}}).status_code == 400
    assert client.put("/api/settings", headers=admin,
                      json={"values": {"BOT_PAUSE_HOURS": "abc"}}).status_code == 400


def test_knowledge_reaches_system_prompt(client, admin):
    from app.agent import knowledge

    client.put("/api/settings", headers=admin,
               json={"values": {"KB_COURSES": "IELTS — 900 000 so'm"}})
    assert "IELTS — 900 000 so'm" in knowledge.get_knowledge()


def test_instagram_connect_url_needs_config_then_has_state(client, admin):
    from app.core.security import decode_token

    assert client.post("/api/settings/instagram/connect-url", headers=admin).status_code == 400
    client.put("/api/settings", headers=admin,
               json={"values": {"IG_APP_ID": "1234567", "IG_APP_SECRET": "a1b2c3d4e5f6a7b8c9d0"}})
    from app.config import settings
    settings.PUBLIC_URL = "https://agent.example.uz"
    try:
        url = client.post("/api/settings/instagram/connect-url", headers=admin).json()["url"]
    finally:
        settings.PUBLIC_URL = ""
    state = url.split("state=")[1].split("&")[0]
    assert decode_token(state, purpose="ig_connect")


def test_oauth_callback_rejects_missing_state(client):
    r = client.get("/connect/callback?code=abc")
    assert r.status_code == 400 and "eskirgan" in r.text


# --- Leads / inbox ---------------------------------------------------------------
def test_inbox_detail_read_and_status_change(client, admin, database):
    _seed_conversation()
    inbox = client.get("/api/leads/inbox", headers=admin).json()
    assert len(inbox) == 1
    item = inbox[0]
    assert item["unread"] == 1 and item["window"] == "open"
    assert item["last_message_role"] == "assistant"

    lid = item["lead_id"]
    detail = client.get(f"/api/leads/{lid}", headers=admin).json()
    assert [m["role"] for m in detail["messages"]] == ["user", "assistant"]

    assert client.post(f"/api/leads/{lid}/read", headers=admin).status_code == 204
    assert client.get("/api/leads/inbox", headers=admin).json()[0]["unread"] == 0

    r = client.patch(f"/api/leads/{lid}", headers=admin,
                     json={"status": "trial", "contact": "+998901112233"})
    assert r.status_code == 200 and r.json()["status"] == "trial"
    msgs = client.get(f"/api/leads/{lid}", headers=admin).json()["messages"]
    assert msgs[-1]["kind"] == "status" and msgs[-1]["meta"]["to"] == "trial"

    lst = client.get("/api/leads?has_contact=true", headers=admin).json()
    assert lst["total"] == 1
    csv = client.get("/api/leads/export.csv", headers=admin)
    assert csv.status_code == 200 and "+998901112233" in csv.text


def test_operator_reply_sends_logs_and_keeps_ai_on(client, operator, database, monkeypatch):
    from app.config import settings
    from app.services import channels
    from app.state.store import store

    _seed_conversation()
    lid = _lead_id(database)
    sent = []

    async def fake_send(recipient, text, *, human_agent=False):
        sent.append((recipient, text, human_agent))
        return {"sent": True}

    monkeypatch.setattr(settings, "IG_ACCESS_TOKEN", "tok")
    monkeypatch.setattr(channels.instagram, "send_dm_result", fake_send)
    r = client.post(f"/api/leads/{lid}/reply", headers=operator, json={"text": "Men administrator"})
    assert r.status_code == 200 and r.json()["sent"] is True, r.text
    assert sent == [("cust1", "Men administrator", False)]
    # AI keeps answering after an operator reply (no auto-pause)
    assert asyncio.run(store.is_paused("cust1")) is False
    detail = client.get(f"/api/leads/{lid}", headers=operator).json()
    assert detail["status"] == "contacted"
    assert detail["messages"][-1]["role"] == "operator"

    # Manual AI toggle still works
    assert client.post(f"/api/leads/{lid}/bot", headers=operator,
                       json={"enabled": False}).json()["paused"] is True
    assert client.post(f"/api/leads/{lid}/bot", headers=operator,
                       json={"enabled": True}).json()["paused"] is False
    assert client.get(f"/api/leads/{lid}/bot", headers=operator).json()["paused"] is False


def test_reply_refused_when_instagram_not_connected(client, admin, database):
    _seed_conversation()
    r = client.post(f"/api/leads/{_lead_id(database)}/reply", headers=admin, json={"text": "x"})
    assert r.json()["sent"] is False and "ulanmagan" in r.json()["error"]


def test_notes(client, admin, database):
    _seed_conversation()
    lid = _lead_id(database)
    r = client.post(f"/api/leads/{lid}/notes", headers=admin, json={"text": "Ertaga qo'ng'iroq"})
    assert r.status_code == 201 and r.json()["kind"] == "note"


def test_dashboard_counts(client, admin):
    _seed_conversation()
    d = client.get("/api/dashboard?days=7", headers=admin).json()
    assert d["totals"]["conversations"] == 1
    assert d["totals"]["ai_replies"] == 1
    assert d["today"]["new_leads"] == 1
    assert len(d["by_day"]) == 7
    assert d["status"]["ai_provider"] == "mock"


# --- Bot menu ----------------------------------------------------------------------
def test_bot_menu_crud_with_images(client, admin):
    r = client.post("/api/bot-menu/items", headers=admin,
                    json={"command": "kurslar", "title": "📚 Kurslar", "text": "Bizning kurslar"})
    assert r.status_code == 201, r.text
    item = r.json()
    assert client.post("/api/bot-menu/items", headers=admin,
                       json={"command": "start", "title": "x"}).status_code == 400
    assert client.post("/api/bot-menu/items", headers=admin,
                       json={"command": "kurslar", "title": "y"}).status_code == 400

    png = b"\x89PNG\r\n\x1a\n" + b"0" * 64
    r = client.post(f"/api/bot-menu/items/{item['id']}/images", headers=admin,
                    files=[("files", ("a.png", png, "image/png"))])
    assert r.status_code == 200, r.text
    img = r.json()["images"][0]
    token = admin["Authorization"].split()[1]
    got = client.get(f"/api/bot-menu/images/{img['id']}?token={token}")
    assert got.status_code == 200 and got.content == png
    bad = client.post(f"/api/bot-menu/items/{item['id']}/images", headers=admin,
                      files=[("files", ("a.gif", b"GIF89a", "image/gif"))])
    assert bad.status_code == 400

    assert client.put("/api/bot-menu/greeting", headers=admin,
                      json={"greeting": "Xush kelibsiz!"}).json()["greeting"] == "Xush kelibsiz!"
    menu = client.get("/api/bot-menu", headers=admin).json()
    assert menu["greeting"] == "Xush kelibsiz!" and len(menu["items"]) == 1

    from app.telegram_business import menu as tg_menu

    loaded = asyncio.run(tg_menu.refresh())
    assert loaded.items[0].command == "kurslar" and len(loaded.items[0].images) == 1
    assert client.delete(f"/api/bot-menu/items/{item['id']}", headers=admin).status_code == 204


# --- Playground ------------------------------------------------------------------
def test_playground_uses_agent(client, admin):
    r = client.post("/api/playground", headers=admin, json={
        "messages": [{"role": "user", "content": "IELTS narxi qancha?"}],
        "channel": "telegram"})
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["reply"] and "lead_score" in body and "stage" in body


@pytest.mark.parametrize("key,value", [
    ("TG_SALES_BOT_TOKEN", "not-a-token"),
    ("TELEGRAM_CHAT_ID", "abc, 12"),
    ("AI_MAX_TOKENS", "100"),
    ("FOLLOWUP_AFTER_HOURS", "0"),
    ("TIMEZONE", "Tashkent"),
    ("DAILY_REPORT_TIME", "25:00"),
    ("AI_PROVIDER", "mock"),
    ("TG_WEBHOOK_SECRET", "short"),
])
def test_settings_validation_rejects_bad_values(client, admin, key, value):
    r = client.put("/api/settings", headers=admin, json={"values": {key: value}})
    assert r.status_code == 400, (key, r.text)


def test_settings_accepts_valid_telegram_values(client, admin):
    r = client.put("/api/settings", headers=admin, json={"values": {
        "TG_SALES_BOT_TOKEN": "1234567890:AAH" + "x" * 32,
        "TELEGRAM_CHAT_ID": "123456789, -1001234567890",
        "DAILY_REPORT_TIME": "21:30",
    }})
    assert r.status_code == 200, r.text
    items = {i["key"]: i for g in r.json()["groups"] for i in g["items"]}
    assert items["DAILY_REPORT_TIME"]["value"] == "21:30"
    # code default, not .env -> no ".env dan" badge
    assert items["CLAUDE_MODEL"]["from_env"] is False  # conftest sets AI_PROVIDER in env


def test_ai_test_endpoint_reports_missing_key(client, admin, monkeypatch):
    from app.config import settings

    monkeypatch.setattr(settings, "AI_PROVIDER", "claude")
    from app.ai.factory import get_provider
    get_provider.cache_clear()
    r = client.post("/api/settings/ai/test", headers=admin)
    get_provider.cache_clear()
    assert r.status_code == 200 and r.json()["ok"] is False
