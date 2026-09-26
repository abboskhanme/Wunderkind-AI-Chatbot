"""Meta App Review readiness (SPEC §12): signed_request verification, the data
deletion + deauthorize callbacks, the public legal pages, legal settings."""
from __future__ import annotations

import base64
import hashlib
import hmac
import json
import time

import pytest

from app.config import settings
from app.instagram.signed_request import (
    SignedRequestError, build_signed_request, parse_signed_request,
)
from app.models.funnel import FunnelDelivery, FunnelEntry, FunnelMessage, InterviewBooking
from app.models.lead import Lead, LeadMessage
from app.models.legal import DataDeletionRequest
from app.models.profile import CustomerProfile
from app.models.setting import Setting
from tests.conftest import auth_headers, make_user
from tests.funnel_fakes import db_add, db_all, fake_tg, run, utc  # noqa: F401  (fixtures)
from tests.test_funnel_jobs import FakeGoogle, google, service_account  # noqa: F401

SECRET = "0123456789abcdef0123456789abcdef"


def signed(user_id: str = "ig-user-1", secret: str = SECRET, **extra) -> str:
    now = int(time.time())
    return build_signed_request({"algorithm": "HMAC-SHA256", "issued_at": now,
                                 "expires": now + 3600, "user_id": user_id, **extra}, secret)


@pytest.fixture
def app_secret(database):
    """IG_APP_SECRET stored like the panel does (a disconnect reloads settings from DB)."""
    from app import runtime_config

    async def save():
        async with database() as db:
            await runtime_config.save(db, {"IG_APP_SECRET": SECRET})
    run(save())
    return SECRET


@pytest.fixture
def admin(client, database):
    make_user(database, "admin", "admin")
    return auth_headers(client, "admin")


# --------------------------------------------------------------------------- #
# signed_request
# --------------------------------------------------------------------------- #
def test_signed_request_matches_meta_reference_algorithm():
    """Built independently, exactly as Meta's PHP sample verifies it: HMAC-SHA256
    over the still-encoded payload segment, base64url without padding."""
    payload = base64.urlsafe_b64encode(json.dumps(
        {"algorithm": "HMAC-SHA256", "expires": 1291840400, "issued_at": 1291836800,
         "user_id": "218471"}).encode()).rstrip(b"=")
    sig = base64.urlsafe_b64encode(
        hmac.new(SECRET.encode(), payload, hashlib.sha256).digest()).rstrip(b"=")
    data = parse_signed_request(f"{sig.decode()}.{payload.decode()}", SECRET)
    assert data["user_id"] == "218471"


@pytest.mark.parametrize("value,secret", [
    (None, SECRET),                                   # missing
    ("", SECRET),
    ("no-dot-here", SECRET),
    ("abc.", SECRET),
    ("!!!.???", SECRET),                              # not base64url
    (signed(secret="another-secret-another-secret"), SECRET),   # wrong key
    (signed(), ""),                                   # secret not configured
    (signed(algorithm="HMAC-MD5"), SECRET),
    (signed(user_id=""), SECRET),
    ("a" * 5000, SECRET),
])
def test_signed_request_rejects(value, secret):
    with pytest.raises(SignedRequestError):
        parse_signed_request(value, secret)


def test_signed_request_tampered_payload_is_rejected():
    sig, payload = signed("victim").split(".")
    forged = base64.urlsafe_b64encode(json.dumps(
        {"algorithm": "HMAC-SHA256", "user_id": "someone-else"}).encode()).rstrip(b"=").decode()
    with pytest.raises(SignedRequestError):
        parse_signed_request(f"{sig}.{forged}", SECRET)
    assert parse_signed_request(f"{sig}.{payload}", SECRET)["user_id"] == "victim"


# --------------------------------------------------------------------------- #
# Data deletion callback
# --------------------------------------------------------------------------- #
def _seed_people(database):
    """ig-user-1 (Instagram lead + IG entry merged with Telegram 555, plus a second
    funnel entry of Telegram 555 and that person's Telegram lead) and an unrelated
    person (Instagram ig-other, Telegram 777)."""
    target_ig = Lead(channel="instagram", external_id="ig-user-1", username="mama")
    target_tg = Lead(channel="telegram", external_id="555", username="mama_tg")
    other_ig = Lead(channel="instagram", external_id="ig-other", username="boshqa")
    other_tg = Lead(channel="telegram", external_id="777", username="boshqa_tg")
    db_add(database, target_ig, target_tg, other_ig, other_tg)
    db_add(database,
           LeadMessage(lead_id=target_ig.id, role="user", text="Salom", created_at=utc(2026, 9, 1)),
           LeadMessage(lead_id=target_tg.id, role="user", text="Men", created_at=utc(2026, 9, 1)),
           LeadMessage(lead_id=other_ig.id, role="user", text="Narx?", created_at=utc(2026, 9, 1)))
    message = db_add(database, FunnelMessage(text="Sotuv", delay_minutes=10, sort_order=0))
    merged = FunnelEntry(source="instagram", start_token="tok-a", ig_user_id="ig-user-1",
                         ig_username="mama", tg_user_id="555", step="pdf_sent",
                         full_name="Aliyeva Malika", phone="+998901112233", grade="5",
                         lead_id=target_tg.id)
    other = FunnelEntry(source="telegram_direct", start_token="tok-b", tg_user_id="777",
                        step="pdf_sent", full_name="Boshqa Odam", phone="+998907776655",
                        lead_id=other_tg.id)
    db_add(database, merged, other)
    db_add(database,
           FunnelDelivery(entry_id=merged.id, message_id=message.id),
           FunnelDelivery(entry_id=other.id, message_id=message.id),
           InterviewBooking(entry_id=merged.id, lead_id=target_tg.id,
                            starts_at=utc(2030, 3, 5, 5), status="scheduled"),
           InterviewBooking(entry_id=other.id, lead_id=other_tg.id,
                            starts_at=utc(2030, 3, 5, 6), status="scheduled"))
    return merged, other


def test_deletion_callback_rejects_missing_and_bad_signature(client, app_secret, database):
    assert client.post("/connect/data-deletion", data={}).status_code == 400
    assert client.post("/connect/data-deletion",
                       data={"signed_request": signed(secret="x" * 32)}).status_code == 400
    assert client.post("/connect/data-deletion", content=b"\xff\xfe",
                       headers={"content-type": "application/json"}).status_code == 400
    assert db_all(database, DataDeletionRequest) == []


def test_deletion_callback_refuses_when_app_secret_is_not_set(client, database):
    r = client.post("/connect/data-deletion", data={"signed_request": signed()})
    assert r.status_code == 400
    assert db_all(database, DataDeletionRequest) == []


def test_deletion_removes_only_that_person(client, app_secret, database, fake_tg, monkeypatch):
    monkeypatch.setattr(settings, "PUBLIC_URL", "https://agent.example.uz/")
    _merged, other = _seed_people(database)

    r = client.post("/connect/data-deletion", data={"signed_request": signed("ig-user-1")})
    assert r.status_code == 200, r.text
    body = r.json()
    code = body["confirmation_code"]
    assert len(code) == 16 and code.isalnum()
    assert body["url"] == f"https://agent.example.uz/data-deletion?code={code}"

    assert {lead.external_id for lead in db_all(database, Lead)} == {"ig-other", "777"}
    assert [m.text for m in db_all(database, LeadMessage)] == ["Narx?"]
    assert [e.id for e in db_all(database, FunnelEntry)] == [other.id]
    assert [d.entry_id for d in db_all(database, FunnelDelivery)] == [other.id]
    assert [b.entry_id for b in db_all(database, InterviewBooking)] == [other.id]
    (row,) = db_all(database, DataDeletionRequest)
    assert (row.confirmation_code, row.status, row.external_user_id, row.source) == \
        (code, "completed", "ig-user-1", "meta_callback")
    assert row.completed_at is not None

    (alert,) = fake_tg.of("alert")
    assert code in alert["text"] and "2 ta lead" in alert["text"]
    assert "Aliyeva" not in alert["text"] and "+99890" not in alert["text"]   # no PII
    assert "uzildi" not in alert["text"]                  # not our account

    page = client.get(f"/data-deletion?code={code}")
    assert page.status_code == 200 and code in page.text
    assert "Request completed" in page.text
    assert page.headers["cache-control"] == "no-store"


def test_repeated_deletion_is_harmless(client, app_secret, database, fake_tg):
    _seed_people(database)
    first = client.post("/connect/data-deletion", data={"signed_request": signed("ig-user-1")})
    # JSON bodies are accepted as well as Meta's form post
    second = client.post("/connect/data-deletion", json={"signed_request": signed("ig-user-1")})
    assert first.status_code == second.status_code == 200
    assert first.json()["confirmation_code"] != second.json()["confirmation_code"]
    assert {r.status for r in db_all(database, DataDeletionRequest)} == {"completed"}
    assert {lead.external_id for lead in db_all(database, Lead)} == {"ig-other", "777"}


def test_deletion_removes_account_profiles(client, app_secret, database, fake_tg):
    """SPEC §13: the account profile (name, username, phone, photo link) goes too —
    the Instagram one and the Telegram one the funnel linked to it."""
    _seed_people(database)
    db_add(database,
           CustomerProfile(channel="instagram", external_id="ig-user-1", full_name="Malika",
                           details={}),
           CustomerProfile(channel="telegram", external_id="555", phone="+998901112233",
                           details={}),
           CustomerProfile(channel="telegram", external_id="777", full_name="Boshqa",
                           details={}))
    r = client.post("/connect/data-deletion", data={"signed_request": signed("ig-user-1")})
    assert r.status_code == 200, r.text
    assert [(p.channel, p.external_id) for p in db_all(database, CustomerProfile)] == \
        [("telegram", "777")]


def test_deletion_clears_the_conversation_cache(client, app_secret, fresh_state):
    run(fresh_state.append_turn("ig-user-1", "user", "Salom"))
    run(fresh_state.append_turn("ig-other", "user", "Salom"))
    client.post("/connect/data-deletion", data={"signed_request": signed("ig-user-1")})
    assert run(fresh_state.get_history("ig-user-1")) == []
    assert run(fresh_state.get_history("ig-other")) != []


def _connect_instagram(database):
    from app import runtime_config

    async def save():
        async with database() as db:
            await runtime_config.save(db, {
                "IG_ACCESS_TOKEN": "IGAAtoken1234567890", "IG_USER_ID": "own-user",
                "IG_ACCOUNT_ID": "own-account", "IG_USERNAME": "wunderkind_school",
                "IG_TOKEN_ISSUED_AT": "2026-09-20T10:00:00+00:00"})
    run(save())
    assert settings.IG_ACCESS_TOKEN == "IGAAtoken1234567890"


@pytest.mark.parametrize("own_id", ["own-user", "own-account"])
def test_own_account_deletion_disconnects_instagram(client, app_secret, database, fake_tg,
                                                    own_id):
    _connect_instagram(database)
    r = client.post("/connect/data-deletion", data={"signed_request": signed(own_id)})
    assert r.status_code == 200
    for key in ("IG_ACCESS_TOKEN", "IG_USER_ID", "IG_ACCOUNT_ID", "IG_USERNAME",
                "IG_TOKEN_ISSUED_AT"):
        assert getattr(settings, key) == "", key
    stored = {s.key for s in db_all(database, Setting)}
    assert stored == {"IG_APP_SECRET"}                   # the app config itself stays
    assert settings.IG_APP_SECRET == SECRET
    (alert,) = fake_tg.of("alert")
    assert "uzildi" in alert["text"]


def test_deletion_failure_keeps_request_received_and_alerts(client, app_secret, database,
                                                            fake_tg, monkeypatch):
    from app.legal import deletion

    async def boom(db, user_id):
        raise RuntimeError("db exploded")

    monkeypatch.setattr(deletion, "delete_instagram_user", boom)
    r = client.post("/connect/data-deletion", data={"signed_request": signed("ig-user-1")})
    assert r.status_code == 200
    code = r.json()["confirmation_code"]
    (row,) = db_all(database, DataDeletionRequest)
    assert row.status == "received" and row.completed_at is None
    assert "qo'lda" in fake_tg.of("alert")[0]["text"]
    page = client.get(f"/data-deletion?code={code}")
    assert page.status_code == 200 and "Request received" in page.text


def test_deletion_erases_google_sheet_rows(client, app_secret, database, fake_tg, google):
    from app.funnel import gsheet

    merged, other = _seed_people(database)
    google.rows[1] = list(gsheet.HEADER)
    google.rows[2] = ["d", "Instagram", "Aliyeva Malika", "+998901112233"] + [""] * 9 + \
        [str(merged.id), "Asosiy"]
    google.rows[3] = ["d", "Telegram", "Boshqa Odam", "+998907776655"] + [""] * 9 + \
        [str(other.id), "Asosiy"]
    r = client.post("/connect/data-deletion", data={"signed_request": signed("ig-user-1")})
    assert r.status_code == 200
    assert google.rows[2] == ["", gsheet.DELETED_LABEL] + [""] * 13
    assert google.rows[3][2] == "Boshqa Odam"
    assert "1 ta qator" in fake_tg.of("alert")[0]["text"]


def test_sheet_erase_failure_tells_staff_which_rows(client, app_secret, database, fake_tg,
                                                    google, monkeypatch):
    from app.funnel import gsheet

    async def no_wait(_):
        return None

    monkeypatch.setattr(gsheet.asyncio, "sleep", no_wait)
    merged, _ = _seed_people(database)
    google.fail_status = 503
    client.post("/connect/data-deletion", data={"signed_request": signed("ig-user-1")})
    text = fake_tg.of("alert")[0]["text"]
    assert str(merged.id) in text and "qo'lda" in text
    reads = [c for c in google.calls if c[0] == "GET"]
    assert len(reads) == 3                                # retried with backoff, then gave up


def test_sheet_erase_does_not_retry_permission_errors(database, google):
    from app.funnel import gsheet

    google.fail_status = 403
    out = run(gsheet.erase_rows(["x"]))
    assert out["error"] and len(google.calls) == 1


# --------------------------------------------------------------------------- #
# Deauthorize callback
# --------------------------------------------------------------------------- #
def test_deauthorize_own_account_disconnects(client, app_secret, database, fake_tg):
    _connect_instagram(database)
    assert client.post("/connect/deauthorize",
                       data={"signed_request": signed("bad", secret="z" * 32)}).status_code == 400
    assert settings.IG_ACCESS_TOKEN                        # untouched by a forged request
    r = client.post("/connect/deauthorize", data={"signed_request": signed("own-user")})
    assert r.status_code == 200
    assert settings.IG_ACCESS_TOKEN == "" and settings.IG_USER_ID == ""
    assert "bekor qilindi" in fake_tg.of("alert")[0]["text"]


def test_deauthorize_other_user_changes_nothing(client, app_secret, database, fake_tg):
    _connect_instagram(database)
    r = client.post("/connect/deauthorize", data={"signed_request": signed("someone")})
    assert r.status_code == 200
    assert settings.IG_ACCESS_TOKEN == "IGAAtoken1234567890"
    assert fake_tg.of("alert") == []
    assert db_all(database, DataDeletionRequest) == []


# --------------------------------------------------------------------------- #
# Public pages
# --------------------------------------------------------------------------- #
@pytest.mark.parametrize("path", ["/privacy", "/terms", "/data-deletion"])
def test_pages_are_public_html(client, path):
    r = client.get(path)
    assert r.status_code == 200
    assert r.headers["content-type"].startswith("text/html")
    assert '<html lang="uz">' in r.text and 'lang="en"' in r.text
    assert "<script" not in r.text                          # no JS
    assert 'name="viewport"' in r.text
    for link in ("/privacy", "/terms", "/data-deletion"):
        assert f'href="{link}"' in r.text
    assert "Last updated: September 26, 2026" in r.text
    assert client.head(path).status_code == 200


def test_privacy_describes_the_real_processors(client):
    text = client.get("/privacy").text
    for fact in ("Gemini", "Google Sheets", "Instagram API", "Telegram", "DigitalOcean",
                 "Frankfurt", "24 months", "30 days", "under 13", "never sell",
                 "follow our account", "member of our Telegram channel"):
        assert fact in text, fact


def test_pages_escape_settings_and_use_fallbacks(client, admin, monkeypatch):
    evil = '<script>alert("x")</script>'
    r = client.put("/api/settings", headers=admin, json={"values": {
        "LEGAL_ENTITY_NAME": evil, "LEGAL_ADDRESS": "Toshkent <b>1</b>\nChilonzor"}})
    assert r.status_code == 200, r.text
    monkeypatch.setattr(settings, "FUNNEL_STAFF_PHONE", "+998 90 123 45 67")
    monkeypatch.setattr(settings, "IG_USERNAME", 'x"onmouseover="y')
    for path in ("/privacy", "/terms"):
        text = client.get(path).text
        assert "<script" not in text and "&lt;script&gt;" in text
        assert "<b>1</b>" not in text and "&lt;b&gt;1&lt;/b&gt;<br>Chilonzor" in text
        assert '"onmouseover="' not in text
        assert "+998 90 123 45 67" in text                 # phone falls back to the staff phone
        assert "E-mail" not in text                        # no email → no empty label


def test_pages_fall_back_to_company_name(client, monkeypatch):
    monkeypatch.setattr(settings, "COMPANY_NAME", "Wunderkind")
    text = client.get("/privacy").text
    assert "«Wunderkind» xususiy maktabi" in text and "Wunderkind private school" in text
    assert "Telefon" not in text and "Manzil" not in text   # nothing configured → not shown
    monkeypatch.setattr(settings, "LEGAL_CONTACT_EMAIL", "info@maktab.uz")
    assert 'href="mailto:info@maktab.uz"' in client.get("/data-deletion").text


def test_status_lookup_unknown_and_malformed_codes(client, database):
    assert client.get("/data-deletion?code=AAAAAAAAAAAAAAAA").status_code == 404
    r = client.get('/data-deletion?code="><script>x</script>')
    assert r.status_code == 404 and "<script>x" not in r.text and "&lt;script&gt;" in r.text


# --------------------------------------------------------------------------- #
# Settings + status
# --------------------------------------------------------------------------- #
@pytest.mark.parametrize("key,value", [
    ("LEGAL_CONTACT_EMAIL", "not-an-email"),
    ("LEGAL_CONTACT_EMAIL", "a@b"),
    ("LEGAL_CONTACT_PHONE", "call me"),
    ("LEGAL_ENTITY_NAME", "two\nlines"),
    ("LEGAL_ADDRESS", "x" * 301),
])
def test_legal_settings_validation(client, admin, key, value):
    r = client.put("/api/settings", headers=admin, json={"values": {key: value}})
    assert r.status_code == 400, (key, r.text)


def test_legal_settings_saved_and_listed(client, admin):
    r = client.put("/api/settings", headers=admin, json={"values": {
        "LEGAL_CONTACT_EMAIL": "info@wunderkind.uz", "LEGAL_CONTACT_PHONE": "+998 71 200 00 00",
        "LEGAL_ENTITY_NAME": "«Wunderkind» MChJ", "LEGAL_ADDRESS": "Toshkent"}})
    assert r.status_code == 200, r.text
    legal = next(g for g in r.json()["groups"] if g["id"] == "legal")
    assert legal["title"] == "Yuridik ma'lumotlar"
    assert {i["key"]: i["value"] for i in legal["items"]}["LEGAL_CONTACT_EMAIL"] == \
        "info@wunderkind.uz"


def test_status_has_legal_urls(client, admin, monkeypatch):
    status = client.get("/api/settings/status", headers=admin).json()
    assert status["legal_urls"] == {k: None for k in (
        "privacy", "terms", "data_deletion_page", "data_deletion_callback", "deauthorize")}
    monkeypatch.setattr(settings, "PUBLIC_URL", "https://agent.example.uz")
    urls = client.get("/api/settings/status", headers=admin).json()["legal_urls"]
    assert urls == {
        "privacy": "https://agent.example.uz/privacy",
        "terms": "https://agent.example.uz/terms",
        "data_deletion_page": "https://agent.example.uz/data-deletion",
        "data_deletion_callback": "https://agent.example.uz/connect/data-deletion",
        "deauthorize": "https://agent.example.uz/connect/deauthorize",
    }


def test_memory_store_forget(fresh_state):
    run(fresh_state.append_turn("u1", "user", "hi"))
    run(fresh_state.pause("u1", 1))
    run(fresh_state.forget("u1"))
    assert run(fresh_state.get_history("u1")) == [] and not run(fresh_state.is_paused("u1"))
