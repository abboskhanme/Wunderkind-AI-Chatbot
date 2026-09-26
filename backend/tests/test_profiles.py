"""Customer account profiles (SPEC §13): Telegram user data, Instagram User
Profile API, sync into leads, admin API (profile, search, refresh, avatar)."""
from __future__ import annotations

import asyncio

import pytest
from sqlalchemy import select

from app.config import settings
from app.instagram.client import instagram
from app.instagram.models import IncomingEvent
from app.leads import client as leads_client
from app.leads import profiles
from app.models.lead import Lead
from app.models.profile import CustomerProfile
from app.telegram_business.client import telegram
from app.telegram_business.models import parse_update
from tests.conftest import auth_headers, make_user

CUSTOMER = 777002
OWNER = 555001


def run(coro):
    return asyncio.run(coro)


def _bot_msg(**extra) -> dict:
    msg = {
        "message_id": 5,
        "from": {"id": CUSTOMER, "is_bot": False, "first_name": "Ali", "last_name": "Valiyev",
                 "username": "ali_v", "language_code": "uz", "is_premium": True},
        "chat": {"id": CUSTOMER, "type": "private", "first_name": "Ali",
                 "last_name": "Valiyev", "username": "ali_v"},
        "text": "Salom",
    }
    msg.update(extra)
    return msg


def _profile(database, channel="telegram", external_id=str(CUSTOMER)):
    async def _q():
        async with database() as s:
            return (await s.execute(select(CustomerProfile).where(
                CustomerProfile.channel == channel,
                CustomerProfile.external_id == external_id))).scalar_one_or_none()
    return run(_q())


def _leads(database):
    async def _q():
        async with database() as s:
            return (await s.execute(select(Lead).order_by(Lead.created_at))).scalars().all()
    return run(_q())


def _seed_lead(channel: str, external_id: str, username=None):
    run(leads_client.log_message(user_id=external_id, username=username, channel=channel,
                                 text="Salom", role="user"))


# --------------------------------------------------------------------------- #
# Update -> ProfileData
# --------------------------------------------------------------------------- #
def test_telegram_bot_chat_gives_name_username_language():
    data = profiles.telegram_person({"message": _bot_msg()})
    assert (data.channel, data.external_id) == ("telegram", str(CUSTOMER))
    assert (data.username, data.full_name) == ("ali_v", "Ali Valiyev")
    assert data.details == {"language_code": "uz", "is_premium": True}
    assert data.phone is None


def test_business_owner_message_describes_the_customer_not_the_owner():
    msg = _bot_msg(business_connection_id="c1")
    msg["from"] = {"id": OWNER, "is_bot": False, "first_name": "Menejer", "username": "boss"}
    data = profiles.telegram_person({"business_message": msg})
    assert data.external_id == str(CUSTOMER)
    assert (data.username, data.full_name) == ("ali_v", "Ali Valiyev")
    assert "language_code" not in data.details        # owner's language is not theirs


def test_own_shared_contact_is_the_phone_someone_elses_is_not():
    own = _bot_msg(contact={"phone_number": "998901234567", "user_id": CUSTOMER,
                            "first_name": "Ali"})
    own.pop("text")
    assert profiles.telegram_person({"message": own}).phone == "+998901234567"

    other = _bot_msg(contact={"phone_number": "998907776655", "user_id": 42})
    other.pop("text")
    assert profiles.telegram_person({"message": other}).phone is None


def test_group_and_bot_updates_are_ignored():
    group = _bot_msg()
    group["chat"] = {"id": -100, "type": "supergroup"}
    assert profiles.telegram_person({"message": group}) is None
    bot = _bot_msg()
    bot["from"]["is_bot"] = True
    assert profiles.telegram_person({"message": bot}) is None
    assert profiles.telegram_person({"update_id": 1}) is None


def test_callback_query_describes_the_clicker():
    update = {"callback_query": {"id": "cb", "from": _bot_msg()["from"],
                                 "message": {"chat": _bot_msg()["chat"]}}}
    assert profiles.telegram_person(update).full_name == "Ali Valiyev"


def test_shared_contact_text_keeps_the_number_for_the_log_and_ai():
    msg = _bot_msg(contact={"phone_number": "+998 90 123 45 67", "user_id": CUSTOMER,
                            "first_name": "Ali", "last_name": "Valiyev"})
    msg.pop("text")
    (event,) = parse_update({"message": msg})
    assert event.text == "[Mijoz kontakt yubordi: Ali Valiyev, +998901234567]"
    assert event.has_attachment is False


# --------------------------------------------------------------------------- #
# Capture -> DB, lead sync, throttling
# --------------------------------------------------------------------------- #
def test_telegram_capture_saves_profile_with_getchat_extras_once_a_day(database, monkeypatch):
    monkeypatch.setattr(settings, "TG_SALES_BOT_TOKEN", "1:t")
    calls = []

    async def get_chat(chat_id):
        calls.append(chat_id)
        return {"id": chat_id, "type": "private", "first_name": "Ali", "last_name": "Valiyev",
                "username": "ali_v", "bio": "Toshkent  ", "birthdate": {"day": 7, "month": 3},
                "personal_chat": {"title": "Blog", "username": "ali_blog"}}

    monkeypatch.setattr(telegram, "get_chat", get_chat)
    run(profiles.capture_telegram(profiles.telegram_person({"message": _bot_msg()})))
    run(profiles.capture_telegram(profiles.telegram_person({"message": _bot_msg()})))

    assert calls == [str(CUSTOMER)]                      # throttled
    row = _profile(database)
    assert (row.full_name, row.username) == ("Ali Valiyev", "ali_v")
    assert row.details == {"language_code": "uz", "is_premium": True, "bio": "Toshkent",
                           "birthdate": "07.03", "personal_channel": "@ali_blog"}
    assert row.fetched_at is not None


def test_shared_phone_fills_the_open_lead_and_future_leads(database):
    _seed_lead("telegram", str(CUSTOMER), username="ali_v")
    msg = _bot_msg(contact={"phone_number": "998901234567", "user_id": CUSTOMER})
    msg.pop("text")
    run(profiles.capture_telegram(profiles.telegram_person({"message": msg})))
    (lead,) = _leads(database)
    assert lead.contact == "+998901234567"

    # A later lead of the same person (old one closed) starts with it too
    async def _close():
        async with database() as s:
            (await s.get(Lead, lead.id)).status = "lost"
            await s.commit()
    run(_close())
    _seed_lead("telegram", str(CUSTOMER))
    assert [l.contact for l in _leads(database)] == ["+998901234567", "+998901234567"]


def test_staff_phone_is_not_overwritten_by_profile(database):
    _seed_lead("telegram", str(CUSTOMER))

    async def _set():
        async with database() as s:
            (await s.execute(select(Lead))).scalar_one().contact = "+998935554433"
            await s.commit()
    run(_set())
    msg = _bot_msg(contact={"phone_number": "998901234567", "user_id": CUSTOMER})
    msg.pop("text")
    run(profiles.capture_telegram(profiles.telegram_person({"message": msg})))
    assert _leads(database)[0].contact == "+998935554433"
    assert _profile(database).phone == "+998901234567"


IG_PROFILE = {"name": "Malika Aliyeva", "username": "malika.a", "follower_count": 312,
              "is_user_follow_business": True, "is_business_follow_user": False,
              "is_verified_user": False,
              "profile_pic": "https://scontent.cdninstagram.com/v/p.jpg"}


def test_instagram_dm_gets_name_and_username_from_profile_api(database, monkeypatch):
    monkeypatch.setattr(settings, "IG_ACCESS_TOKEN", "tok")
    calls = []

    async def get_full_profile(igsid):
        calls.append(igsid)
        return IG_PROFILE

    monkeypatch.setattr(instagram, "get_full_profile", get_full_profile)
    _seed_lead("instagram", "igsid-1")                    # DMs carry no username
    assert _leads(database)[0].username is None

    event = IncomingEvent(kind="dm", text="Salom", sender_id="igsid-1")
    run(profiles.capture_instagram(event))
    run(profiles.capture_instagram(event))

    assert calls == ["igsid-1"]                           # throttled
    row = _profile(database, "instagram", "igsid-1")
    assert (row.full_name, row.username) == ("Malika Aliyeva", "malika.a")
    assert row.details["followers"] == 312 and row.details["follows_us"] is True
    assert _leads(database)[0].username == "malika.a"


def test_instagram_comment_stores_username_without_calling_the_api(database, monkeypatch):
    """A commenter never gave consent (error 230) — the call would only take a
    slot of the global IG throttle that comment replies need."""
    monkeypatch.setattr(settings, "IG_ACCESS_TOKEN", "tok")
    calls = []

    async def get_full_profile(igsid):
        calls.append(igsid)
        return IG_PROFILE

    monkeypatch.setattr(instagram, "get_full_profile", get_full_profile)
    event = IncomingEvent(kind="comment", text="Narxi?", sender_id="igsid-2",
                          username="dilnoza")
    run(profiles.capture_instagram(event))
    assert calls == []
    row = _profile(database, "instagram", "igsid-2")
    assert (row.username, row.full_name, row.fetched_at) == ("dilnoza", None, None)

    # Once they DM us, the profile is read
    run(profiles.capture_instagram(IncomingEvent(kind="dm", text="Salom", sender_id="igsid-2")))
    assert calls == ["igsid-2"]
    assert _profile(database, "instagram", "igsid-2").full_name == "Malika Aliyeva"


def test_instagram_echo_and_empty_results_store_nothing(database, monkeypatch):
    run(profiles.capture_instagram(IncomingEvent(kind="echo", text="x", sender_id="igsid-3")))
    run(profiles.capture_instagram(IncomingEvent(kind="dm", text="x", sender_id="igsid-3")))
    assert _profile(database, "instagram", "igsid-3") is None


def test_capture_never_raises(database, monkeypatch):
    monkeypatch.setattr(settings, "TG_SALES_BOT_TOKEN", "1:t")

    async def boom(*_a):
        raise RuntimeError("network down")

    monkeypatch.setattr(telegram, "get_chat", boom)
    run(profiles.capture_telegram(profiles.telegram_person({"message": _bot_msg()})))


def test_telegram_webhook_update_captures_the_profile(client, database, monkeypatch):
    monkeypatch.setattr(settings, "TG_SALES_ENABLED", False)   # log only, no AI reply
    r = client.post("/webhook/telegram", json={"update_id": 1, "message": _bot_msg()},
                    headers={"X-Telegram-Bot-Api-Secret-Token": settings.tg_webhook_secret})
    assert r.status_code == 200
    assert _profile(database).full_name == "Ali Valiyev"


@pytest.mark.parametrize("url", [
    "http://scontent.cdninstagram.com/p.jpg",            # not https
    "https://evil.example.com/p.jpg",
    "https://cdninstagram.com.evil.io/p.jpg",
    "https://169.254.169.254/latest/meta-data",
    "https://fbcdn.net.attacker.io/p.jpg",
])
def test_instagram_avatar_refuses_non_meta_hosts_without_any_request(url, monkeypatch):
    import httpx

    async def no_network(self, *a, **k):
        raise AssertionError(f"network called for {url}")

    monkeypatch.setattr(httpx.AsyncClient, "get", no_network)
    assert run(profiles._download_ig(url)) is None


@pytest.mark.parametrize("url", ["https://scontent.cdninstagram.com/v/p.jpg",
                                 "https://scontent-fra5-1.xx.fbcdn.net/v/p.jpg"])
def test_instagram_avatar_downloads_from_meta_cdn(url, monkeypatch):
    import httpx

    seen = []

    async def fake_get(self, target, *a, **k):
        seen.append(target)
        return httpx.Response(200, content=b"IMG", headers={"content-type": "image/jpeg"})

    monkeypatch.setattr(httpx.AsyncClient, "get", fake_get)
    assert run(profiles._download_ig(url)) == (b"IMG", "image/jpeg")
    assert seen == [url]


def test_staff_contact_card_in_business_chat_is_not_the_customers_phone(database):
    """The manager sends the school's number into the customer's chat: labelled
    as staff, logged as an operator message, never the lead's phone."""
    msg = _bot_msg(business_connection_id="c1",
                   contact={"phone_number": "998712000000", "first_name": "Wunderkind",
                            "user_id": OWNER})
    msg.pop("text")
    msg["from"] = {"id": OWNER, "is_bot": False, "first_name": "Menejer"}
    (event,) = parse_update({"business_message": msg}, owner_id=OWNER)
    assert event.kind == "echo"
    assert event.text == "[Xodim kontakt yubordi: Wunderkind, +998712000000]"
    assert profiles.telegram_person({"business_message": msg}).phone is None


def test_instagram_webhook_reads_profiles_after_every_reply_of_the_batch(
        client, monkeypatch):
    """Meta may batch several DMs in one POST; background tasks run in order,
    so profile reads must not sit between two replies."""
    import hashlib
    import hmac
    import json

    from app.instagram import webhook

    monkeypatch.setattr(settings, "IG_APP_SECRET", "s3cret")
    order = []

    async def route(event):
        order.append(("reply", event.sender_id))

    async def capture(event):
        order.append(("profile", event.sender_id))

    monkeypatch.setattr(webhook, "_route", route)
    monkeypatch.setattr(profiles, "capture_instagram", capture)
    body = json.dumps({"object": "instagram", "entry": [{"id": "me", "messaging": [
        {"sender": {"id": "a"}, "recipient": {"id": "me"}, "message": {"mid": "1", "text": "Salom"}},
        {"sender": {"id": "b"}, "recipient": {"id": "me"}, "message": {"mid": "2", "text": "Narx?"}},
    ]}]}).encode()
    sig = hmac.new(b"s3cret", body, hashlib.sha256).hexdigest()
    r = client.post("/webhook/instagram", content=body,
                    headers={"X-Hub-Signature-256": f"sha256={sig}",
                             "Content-Type": "application/json"})
    assert r.status_code == 200
    assert order == [("reply", "a"), ("reply", "b"), ("profile", "a"), ("profile", "b")]


def test_profile_read_is_short_and_falls_back_to_documented_fields(monkeypatch):
    """One refused field fails the whole Graph read — retry once with the fields
    of Meta's example; never the long retry budget of the reply path."""
    from app.instagram import client as ig_client

    real = ig_client.InstagramClient.get_full_profile
    monkeypatch.setattr(ig_client.InstagramClient, "get_full_profile", real)
    asked = []

    async def fake_get(self, path, *, params=None, retries=3, timeout=20.0):
        asked.append((params["fields"], retries, timeout))
        return {} if "is_verified_user" in params["fields"] else {"username": "x"}

    monkeypatch.setattr(ig_client.InstagramClient, "_get", fake_get)
    assert run(ig_client.InstagramClient().get_full_profile("igsid")) == {"username": "x"}
    assert asked == [(ig_client.PROFILE_FIELDS, 1, 5.0),
                     (ig_client.PROFILE_FIELDS_BASIC, 1, 5.0)]


def test_fresh_api_read_drops_what_the_person_hid(database):
    run(profiles.save(profiles.ProfileData(
        "telegram", "42", username="old_u", full_name="Ali",
        details={"bio": "eski bio", "birthdate": "07.03", "language_code": "uz"},
        fetched=True)))
    # Next getChat: bio and birthdate hidden, username removed
    run(profiles.save(profiles.ProfileData("telegram", "42", full_name="Ali",
                                           details={}, fetched=True)))
    row = _profile(database, "telegram", "42")
    assert row.details == {"language_code": "uz"}        # message data stays
    assert row.username is None
    # A plain update (no API read) never removes anything
    run(profiles.save(profiles.ProfileData("telegram", "42", username="new_u")))
    run(profiles.save(profiles.ProfileData("telegram", "42", full_name="Ali")))
    assert _profile(database, "telegram", "42").username == "new_u"


def test_failed_avatar_read_does_not_block_the_profile_read_on_the_first_dm(
        client, database, operator, monkeypatch):
    """Staff open a commenter's lead (no consent -> the photo read fails); when
    that person DMs us minutes later, their profile is still read."""
    monkeypatch.setattr(settings, "IG_ACCESS_TOKEN", "tok")
    answers = [None, IG_PROFILE]
    calls = []

    async def get_full_profile(igsid):
        calls.append(igsid)
        return answers[len(calls) - 1]

    monkeypatch.setattr(instagram, "get_full_profile", get_full_profile)
    run(profiles.capture_instagram(IncomingEvent(kind="comment", text="?", sender_id="c1",
                                                 username="kommentchi")))
    _seed_lead("instagram", "c1")
    lead_id = str(_leads(database)[0].id)
    assert client.get(f"/api/leads/{lead_id}/avatar", headers=operator).status_code == 404
    run(profiles.capture_instagram(IncomingEvent(kind="dm", text="Salom", sender_id="c1")))
    assert calls == ["c1", "c1"]
    assert _profile(database, "instagram", "c1").full_name == "Malika Aliyeva"


def test_csv_export_neutralises_formulas(client, database, operator):
    _seed_lead("telegram", "13")
    run(profiles.save(profiles.ProfileData("telegram", "13",
                                           full_name='=HYPERLINK("http://x","y")')))
    text = client.get("/api/leads/export.csv", headers=operator).text
    assert "'=HYPERLINK" in text
    assert ",=HYPERLINK" not in text


# --------------------------------------------------------------------------- #
# Admin API
# --------------------------------------------------------------------------- #
@pytest.fixture
def operator(client, database):
    make_user(database, "opa", "operator")
    return auth_headers(client, "opa")


def _save_ig_profile():
    run(profiles.save(profiles.ProfileData(
        "instagram", "igsid-1", username="malika.a", full_name="Malika Aliyeva",
        details={"followers": 312, "profile_pic": "https://scontent.cdninstagram.com/p.jpg"},
        fetched=True)))


def test_lead_detail_list_and_inbox_show_the_account(client, database, operator):
    _seed_lead("instagram", "igsid-1")
    _save_ig_profile()
    lead_id = str(_leads(database)[0].id)

    detail = client.get(f"/api/leads/{lead_id}", headers=operator).json()
    assert detail["profile_name"] == "Malika Aliyeva"
    assert detail["username"] == "malika.a"
    assert detail["profile"]["details"] == {"followers": 312}     # CDN link not exposed

    (item,) = client.get("/api/leads", headers=operator).json()["items"]
    assert item["profile_name"] == "Malika Aliyeva"
    (row,) = client.get("/api/leads/inbox", headers=operator).json()
    assert row["profile_name"] == "Malika Aliyeva"

    # Search by the account name
    assert client.get("/api/leads/inbox?search=Aliyeva", headers=operator).json()
    assert client.get("/api/leads?search=Malika", headers=operator).json()["total"] == 1
    assert client.get("/api/leads?search=Boshqa", headers=operator).json()["total"] == 0

    csv_text = client.get("/api/leads/export.csv", headers=operator).text
    assert "Akkaunt nomi" in csv_text and "Malika Aliyeva" in csv_text


def test_lead_without_profile_still_works(client, database, operator):
    _seed_lead("telegram", "999")
    lead_id = str(_leads(database)[0].id)
    detail = client.get(f"/api/leads/{lead_id}", headers=operator).json()
    assert detail["profile"] is None and detail["profile_name"] is None
    assert client.get(f"/api/leads/{lead_id}/avatar", headers=operator).status_code == 404


def test_refresh_reads_the_profile_now(client, database, operator, monkeypatch):
    monkeypatch.setattr(settings, "IG_ACCESS_TOKEN", "tok")

    async def get_full_profile(igsid):
        return IG_PROFILE

    monkeypatch.setattr(instagram, "get_full_profile", get_full_profile)
    _seed_lead("instagram", "igsid-1")
    lead_id = str(_leads(database)[0].id)
    r = client.post(f"/api/leads/{lead_id}/profile/refresh", headers=operator)
    assert r.status_code == 200, r.text
    assert r.json()["full_name"] == "Malika Aliyeva"
    assert _leads(database)[0].username == "malika.a"


def test_refresh_without_data_returns_null_and_keeps_the_stored_profile(
        client, database, operator):
    _seed_lead("telegram", "999")
    run(profiles.save(profiles.ProfileData("telegram", "999", full_name="Eski Nom")))
    lead_id = str(_leads(database)[0].id)
    r = client.post(f"/api/leads/{lead_id}/profile/refresh", headers=operator)
    assert r.status_code == 200 and r.json() is None       # Telegram gave nothing
    assert _profile(database, "telegram", "999").full_name == "Eski Nom"


def test_telegram_avatar_is_proxied(client, database, operator, monkeypatch):
    monkeypatch.setattr(settings, "TG_SALES_BOT_TOKEN", "1:t")

    async def photos(user_id, limit=1):
        return {"total_count": 1, "photos": [[
            {"file_id": "small", "width": 160}, {"file_id": "big", "width": 640}]]}

    async def download(file_id, max_bytes=0):
        return b"JPEG-" + file_id.encode()

    monkeypatch.setattr(telegram, "get_user_profile_photos", photos)
    monkeypatch.setattr(telegram, "download_file", download)
    _seed_lead("telegram", str(CUSTOMER))
    lead_id = str(_leads(database)[0].id)
    r = client.get(f"/api/leads/{lead_id}/avatar", headers=operator)
    assert r.status_code == 200
    assert r.content == b"JPEG-small" and r.headers["content-type"] == "image/jpeg"


def test_expired_instagram_photo_link_is_renewed(client, database, operator, monkeypatch):
    monkeypatch.setattr(settings, "IG_ACCESS_TOKEN", "tok")
    fresh = "https://scontent.cdninstagram.com/v/fresh.jpg"

    async def get_full_profile(igsid):
        return {**IG_PROFILE, "profile_pic": fresh}

    async def download(url):
        return (b"PNG", "image/png") if url == fresh else None

    monkeypatch.setattr(instagram, "get_full_profile", get_full_profile)
    monkeypatch.setattr(profiles, "_download_ig", download)
    _seed_lead("instagram", "igsid-1")
    _save_ig_profile()                                    # holds the old (expired) link
    lead_id = str(_leads(database)[0].id)
    r = client.get(f"/api/leads/{lead_id}/avatar", headers=operator)
    assert r.status_code == 200 and r.content == b"PNG"


def test_profile_endpoints_need_login(client, database):
    _seed_lead("telegram", "999")
    lead_id = str(_leads(database)[0].id)
    assert client.get(f"/api/leads/{lead_id}/avatar").status_code == 401
    assert client.post(f"/api/leads/{lead_id}/profile/refresh").status_code == 401
