"""Funnel admin API (SPEC §10.4): RBAC, sales sequence CRUD, PDF upload, bookings,
slots, stats, Sheets endpoints, test message and the funnel settings."""
from __future__ import annotations

import uuid
from datetime import datetime, timedelta, timezone
from zoneinfo import ZoneInfo

import pytest
from sqlalchemy import select

from app.config import settings
from app.models.funnel import FunnelEntry, InterviewBooking
from tests.conftest import auth_headers, make_user
from tests.funnel_fakes import PDF_BYTES, db_add, db_all, fake_tg  # noqa: F401  (fixture)

TZ = ZoneInfo("Asia/Tashkent")
ANY_ID = str(uuid.uuid4())


@pytest.fixture
def admin(client, database):
    make_user(database, "admin", "admin")
    return auth_headers(client, "admin")


@pytest.fixture
def operator(client, database):
    make_user(database, "opa", "operator")
    return auth_headers(client, "opa")


STAFF_ENDPOINTS = [
    ("get", "/api/funnel/stats", None),
    ("get", "/api/funnel/entries", None),
    ("get", "/api/funnel/bookings", None),
    ("get", "/api/funnel/slots?date=2030-01-08", None),
]
ADMIN_ENDPOINTS = [
    ("get", "/api/funnel/messages", None),
    ("post", "/api/funnel/messages", {"text": "x", "delay_minutes": 10}),
    ("patch", f"/api/funnel/messages/{ANY_ID}", {"text": "y"}),
    ("delete", f"/api/funnel/messages/{ANY_ID}", None),
    ("post", "/api/funnel/messages/reorder", {"ids": []}),
    ("delete", f"/api/funnel/messages/{ANY_ID}/image", None),
    ("get", f"/api/funnel/messages/{ANY_ID}/image", None),
    ("get", "/api/funnel/lead-magnet", None),
    ("get", "/api/funnel/lead-magnet/download", None),
    ("post", "/api/funnel/sheet/test", None),
    ("post", "/api/funnel/sheet/resync", None),
    ("post", "/api/funnel/test-message", {"tg_chat_id": "1", "kind": "confirm"}),
]


@pytest.mark.parametrize("method,path,body", STAFF_ENDPOINTS + ADMIN_ENDPOINTS + [
    ("patch", f"/api/funnel/bookings/{ANY_ID}", {"note": "x"}),
    ("put", "/api/funnel/lead-magnet", None),
    ("put", f"/api/funnel/messages/{ANY_ID}/image", None),
])
def test_requires_token(client, method, path, body):
    kwargs = {"json": body} if body is not None else {}
    assert getattr(client, method)(path, **kwargs).status_code == 401


@pytest.mark.parametrize("method,path,body", ADMIN_ENDPOINTS)
def test_operator_forbidden_on_admin_endpoints(client, operator, method, path, body):
    kwargs = {"headers": operator}
    if body is not None:
        kwargs["json"] = body
    r = getattr(client, method)(path, **kwargs)
    assert r.status_code == 403 and r.json()["detail"] == "Faqat administrator uchun"


def test_operator_forbidden_on_uploads(client, operator):
    files = {"file": ("a.pdf", PDF_BYTES, "application/pdf")}
    assert client.put("/api/funnel/lead-magnet", headers=operator, files=files).status_code == 403
    img = {"file": ("a.png", b"\x89PNG", "image/png")}
    assert client.put(f"/api/funnel/messages/{ANY_ID}/image", headers=operator,
                      files=img).status_code == 403


@pytest.mark.parametrize("method,path,body", STAFF_ENDPOINTS)
def test_operator_can_use_staff_endpoints(client, operator, method, path, body):
    assert getattr(client, method)(path, headers=operator).status_code == 200


# --------------------------------------------------------------------------- #
# Sales sequence
# --------------------------------------------------------------------------- #
def test_messages_crud_reorder_and_image(client, admin):
    a = client.post("/api/funnel/messages", headers=admin,
                    json={"text": " Birinchi ", "delay_minutes": 10}).json()
    b = client.post("/api/funnel/messages", headers=admin,
                    json={"text": "Ikkinchi", "delay_minutes": 1440, "is_active": False})
    assert b.status_code == 201
    b = b.json()
    assert a["text"] == "Birinchi" and a["has_image"] is False and b["sort_order"] > a["sort_order"]
    assert client.post("/api/funnel/messages", headers=admin,
                       json={"text": "", "delay_minutes": 1}).status_code == 422
    assert client.post("/api/funnel/messages", headers=admin,
                       json={"text": "x", "delay_minutes": -1}).status_code == 422
    # 4096 characters of emoji are 8192 UTF-16 units — Telegram would refuse it
    assert client.post("/api/funnel/messages", headers=admin,
                       json={"text": "🎁" * 4096, "delay_minutes": 1}).status_code == 422

    r = client.patch(f"/api/funnel/messages/{a['id']}", headers=admin,
                     json={"delay_minutes": 30, "is_active": False})
    assert r.json()["delay_minutes"] == 30 and r.json()["is_active"] is False
    order = client.post("/api/funnel/messages/reorder", headers=admin,
                        json={"ids": [b["id"], a["id"]]}).json()
    assert [m["id"] for m in order] == [b["id"], a["id"]]

    png = b"\x89PNG\r\n\x1a\n" + b"0" * 32
    r = client.put(f"/api/funnel/messages/{a['id']}/image", headers=admin,
                   files={"file": ("a.png", png, "image/png")})
    assert r.status_code == 200 and r.json()["has_image"] is True
    assert r.json()["image_content_type"] == "image/png"
    token = admin["Authorization"].split()[1]
    got = client.get(f"/api/funnel/messages/{a['id']}/image?token={token}&v=123")
    assert got.status_code == 200 and got.content == png
    assert client.put(f"/api/funnel/messages/{a['id']}/image", headers=admin,
                      files={"file": ("a.gif", b"GIF89a", "image/gif")}).status_code == 400
    assert client.delete(f"/api/funnel/messages/{a['id']}/image",
                         headers=admin).status_code == 204
    assert client.get(f"/api/funnel/messages/{a['id']}/image", headers=admin).status_code == 404

    assert client.delete(f"/api/funnel/messages/{a['id']}", headers=admin).status_code == 204
    assert [m["id"] for m in client.get("/api/funnel/messages", headers=admin).json()] == [b["id"]]
    r = client.patch(f"/api/funnel/messages/{a['id']}", headers=admin, json={"text": "z"})
    assert r.status_code == 404 and r.json()["detail"] == "Xabar topilmadi"


# --------------------------------------------------------------------------- #
# Lead-magnet PDF
# --------------------------------------------------------------------------- #
def test_lead_magnet_upload_validation_and_download(client, admin):
    assert client.get("/api/funnel/lead-magnet", headers=admin).json() is None
    bad = client.put("/api/funnel/lead-magnet", headers=admin,
                     files={"file": ("x.pdf", b"not a pdf", "application/pdf")})
    assert bad.status_code == 400 and bad.json()["detail"] == "Bu PDF fayl emas"
    assert client.put("/api/funnel/lead-magnet", headers=admin,
                      files={"file": ("x.png", PDF_BYTES, "image/png")}).status_code == 400

    r = client.put("/api/funnel/lead-magnet", headers=admin,
                   files={"file": ("8 maslahat.pdf", PDF_BYTES, "application/pdf")})
    assert r.status_code == 200, r.text
    assert r.json()["filename"] == "8 maslahat.pdf" and r.json()["size_bytes"] == len(PDF_BYTES)
    meta = client.get("/api/funnel/lead-magnet", headers=admin).json()
    assert meta["filename"] == "8 maslahat.pdf" and meta["updated_at"]

    token = admin["Authorization"].split()[1]
    got = client.get(f"/api/funnel/lead-magnet/download?token={token}")
    assert got.status_code == 200 and got.content == PDF_BYTES
    assert got.headers["content-type"] == "application/pdf"


def test_reupload_clears_telegram_file_id(client, admin, database):
    from app.models.funnel import FunnelFile

    client.put("/api/funnel/lead-magnet", headers=admin,
               files={"file": ("a.pdf", PDF_BYTES, "application/pdf")})

    import asyncio

    async def set_file_id():
        async with database() as s:
            (await s.execute(select(FunnelFile).where(FunnelFile.key == "lead_magnet"))
             ).scalar_one().tg_file_id = "OLD"
            await s.commit()
    asyncio.run(set_file_id())
    client.put("/api/funnel/lead-magnet", headers=admin,
               files={"file": ("b.pdf", PDF_BYTES + b"v2", "application/pdf")})
    (row,) = db_all(database, FunnelFile)
    assert row.tg_file_id is None and row.filename == "b.pdf"


# --------------------------------------------------------------------------- #
# Entries / bookings / slots / stats
# --------------------------------------------------------------------------- #
def local_utc(y, m, d, hh, mm=0) -> datetime:
    return datetime(y, m, d, hh, mm, tzinfo=TZ).astimezone(timezone.utc)


@pytest.fixture
def funnel_data(database):
    now = datetime.now(timezone.utc)
    ig = FunnelEntry(source="instagram", start_token="tokIG0000001", ig_user_id="ig1",
                     ig_username="mama_ali", step="ig_link_sent", link_sent_at=now)
    done = FunnelEntry(source="telegram_channel", start_token="tokTG0000001", tg_user_id="77",
                       tg_username="malika", step="pdf_sent", full_name="Aliyeva Malika",
                       phone="+998901234567", grade="5", bot_started_at=now, pdf_sent_at=now)
    direct = FunnelEntry(source="telegram_direct", start_token="tokTG0000002", tg_user_id="78",
                         step="ask_phone", full_name="Karimov Jasur", bot_started_at=now)
    db_add(database, ig, done, direct)
    tomorrow = datetime.now(TZ).date() + timedelta(days=1)
    first = InterviewBooking(entry_id=done.id, status="cancelled",
                             starts_at=local_utc(tomorrow.year, tomorrow.month, tomorrow.day, 9),
                             # older than `current`, but the same local day even
                             # right after midnight (per-day stats are asserted)
                             created_at=now - timedelta(milliseconds=1))
    current = InterviewBooking(entry_id=done.id, status="scheduled", note="Qo'ng'iroq qilindi",
                               starts_at=local_utc(tomorrow.year, tomorrow.month, tomorrow.day, 10))
    db_add(database, first, current)
    return {"ig": ig, "done": done, "direct": direct, "booking": current, "day": tomorrow}


def test_entries_list_filters_and_latest_booking(client, operator, funnel_data):
    body = client.get("/api/funnel/entries", headers=operator).json()
    assert body["total"] == 3
    by_source = {i["source"]: i for i in body["items"]}
    done = by_source["telegram_channel"]
    assert done["booking"]["status"] == "scheduled"               # newest, not the cancelled
    assert done["booking"]["full_name"] == "Aliyeva Malika" and done["messages_sent"] == 0
    assert by_source["instagram"]["ig_username"] == "mama_ali"
    assert by_source["instagram"]["booking"] is None

    assert client.get("/api/funnel/entries?source=instagram",
                      headers=operator).json()["total"] == 1
    assert client.get("/api/funnel/entries?step=ask_phone",
                      headers=operator).json()["items"][0]["full_name"] == "Karimov Jasur"
    assert client.get("/api/funnel/entries?search=+99890",
                      headers=operator).json()["total"] == 1
    page = client.get("/api/funnel/entries?page=2&page_size=2", headers=operator).json()
    assert page["total"] == 3 and len(page["items"]) == 1


def test_bookings_date_range_is_local_and_inclusive(client, operator, funnel_data):
    day = funnel_data["day"].isoformat()
    rows = client.get(f"/api/funnel/bookings?date_from={day}&date_to={day}",
                      headers=operator).json()
    assert [r["status"] for r in rows] == ["cancelled", "scheduled"]          # by starts_at
    assert rows[1]["phone"] == "+998901234567" and rows[1]["grade"] == "5"
    only = client.get(f"/api/funnel/bookings?date_from={day}&date_to={day}&status=scheduled",
                      headers=operator).json()
    assert len(only) == 1
    before = (funnel_data["day"] - timedelta(days=1)).isoformat()
    assert client.get(f"/api/funnel/bookings?date_to={before}", headers=operator).json() == []
    assert client.get("/api/funnel/bookings?status=nope", headers=operator).status_code == 422


def test_patch_booking_status_and_note(client, operator, database, funnel_data):
    bid = funnel_data["booking"].id
    r = client.patch(f"/api/funnel/bookings/{bid}", headers=operator,
                     json={"status": "attended", "note": "  Keldi, yoqdi  "})
    assert r.status_code == 200, r.text
    assert r.json()["status"] == "attended" and r.json()["note"] == "Keldi, yoqdi"
    r = client.patch(f"/api/funnel/bookings/{bid}", headers=operator, json={"note": ""})
    assert r.json()["note"] is None and r.json()["status"] == "attended"
    (entry,) = db_all(database, FunnelEntry, FunnelEntry.id == funnel_data["done"].id)
    assert entry.sheet_dirty is True
    assert client.patch(f"/api/funnel/bookings/{ANY_ID}", headers=operator,
                        json={"note": "x"}).status_code == 404


def test_status_back_to_scheduled_is_refused(client, operator, funnel_data):
    """MINOR 3: a booking cannot be revived from the panel — the person books again."""
    cancelled = [b for b in client.get("/api/funnel/bookings", headers=operator).json()
                 if b["status"] == "cancelled"][0]
    r = client.patch(f"/api/funnel/bookings/{cancelled['id']}", headers=operator,
                     json={"status": "scheduled"})
    assert r.status_code == 400 and "qayta tiklab bo'lmaydi" in r.json()["detail"]
    current = funnel_data["booking"].id           # unchanged "scheduled" + a note is fine
    assert client.patch(f"/api/funnel/bookings/{current}", headers=operator,
                        json={"status": "scheduled", "note": "ok"}).status_code == 200


def test_slots_show_free_capacity(client, operator, funnel_data, monkeypatch):
    monkeypatch.setattr(settings, "FUNNEL_WORK_DAYS", "1-7")
    day = funnel_data["day"].isoformat()
    slots = client.get(f"/api/funnel/slots?date={day}", headers=operator).json()
    assert slots[0] == {"time": "09:00", "free": 1}                # cancelled one frees it
    assert slots[2] == {"time": "10:00", "free": 0}
    assert slots[-1]["time"] == "15:30" and len(slots) == 14
    monkeypatch.setattr(settings, "FUNNEL_HOLIDAYS", day)
    assert client.get(f"/api/funnel/slots?date={day}", headers=operator).json() == []


def test_stats_steps_sources_and_bookings(client, operator, funnel_data):
    body = client.get("/api/funnel/stats?days=30", headers=operator).json()
    steps = {s["key"]: s for s in body["steps"]}
    assert [s["key"] for s in body["steps"]] == [
        "comments", "link_sent", "bot_started", "contact_collected", "pdf_sent", "booked",
        "attended"]
    assert all(s["label"] for s in body["steps"])
    assert steps["comments"]["count"] == 3 and steps["link_sent"]["count"] == 3
    assert steps["bot_started"]["count"] == 2 and steps["contact_collected"]["count"] == 1
    assert steps["pdf_sent"]["count"] == 1 and steps["booked"]["count"] == 1
    assert steps["attended"]["count"] == 0
    assert {s["source"]: s["count"] for s in body["by_source"]} == {
        "instagram": 1, "telegram_channel": 1, "telegram_direct": 1}
    assert body["bookings"] == {"scheduled": 1, "attended": 0, "no_show": 0, "cancelled": 1,
                                "today": 0}


def test_reschedule_cancellations_are_not_counted(client, operator, database, funnel_data):
    """MINOR 11: the old row of a reschedule is not a cancellation."""
    tomorrow = funnel_data["day"]
    db_add(database, InterviewBooking(
        entry_id=funnel_data["direct"].id, status="cancelled", rescheduled=True,
        starts_at=local_utc(tomorrow.year, tomorrow.month, tomorrow.day, 11)))
    body = client.get("/api/funnel/stats?days=30", headers=operator).json()
    assert body["bookings"]["cancelled"] == 1 and body["by_day"][-1]["bookings"] == 2
    assert len(body["by_day"]) == 30
    today = body["by_day"][-1]
    assert today["date"] == datetime.now(TZ).date().isoformat()
    assert (today["entries"], today["pdf"], today["bookings"]) == (3, 1, 2)


# --------------------------------------------------------------------------- #
# Sheets + test message
# --------------------------------------------------------------------------- #
def test_sheet_endpoints(client, admin, funnel_data, database):
    r = client.post("/api/funnel/sheet/test", headers=admin)
    assert r.status_code == 200 and r.json()["ok"] is False and r.json()["error"]
    assert client.post("/api/funnel/sheet/resync", headers=admin).json() == {"queued": 3}
    assert all(e.sheet_dirty for e in db_all(database, FunnelEntry))


def test_test_message_sends_confirm_and_sales(client, admin, fake_tg):
    r = client.post("/api/funnel/test-message", headers=admin,
                    json={"tg_chat_id": "123456", "kind": "confirm"})
    assert r.json() == {"sent": True, "error": None}
    assert fake_tg.of("message")[-1]["chat_id"] == "123456"
    assert "Admin" in fake_tg.of("message")[-1]["text"]

    r = client.post("/api/funnel/test-message", headers=admin,
                    json={"tg_chat_id": "123456", "kind": "sales"})
    assert r.status_code == 400 and r.json()["detail"] == "Faol sotuv xabari yo'q"
    mid = client.post("/api/funnel/messages", headers=admin,
                      json={"text": "Sotuv matni", "delay_minutes": 10}).json()["id"]
    r = client.post("/api/funnel/test-message", headers=admin,
                    json={"tg_chat_id": "123456", "kind": "sales", "message_id": mid})
    assert r.json()["sent"] is True and fake_tg.of("message")[-1]["text"] == "Sotuv matni"
    assert client.post("/api/funnel/test-message", headers=admin,
                       json={"tg_chat_id": "abc def", "kind": "confirm"}).status_code == 422


# --------------------------------------------------------------------------- #
# Settings
# --------------------------------------------------------------------------- #
def test_funnel_settings_groups_are_exposed(client, admin):
    groups = {g["id"]: g for g in client.get("/api/settings", headers=admin).json()["groups"]}
    assert groups["funnel"]["title"] == "Lead-magnet voronkasi"
    keys = {i["key"]: i for i in groups["funnel"]["items"]}
    assert keys["FUNNEL_ASK_NAME"]["value"] == settings.FUNNEL_ASK_NAME     # default shown
    assert {i["key"] for i in groups["gsheet"]["items"]} == {
        "GSHEET_SERVICE_ACCOUNT_JSON", "GSHEET_SPREADSHEET_ID", "GSHEET_WORKSHEET"}
    assert next(i for i in groups["gsheet"]["items"]
                if i["key"] == "GSHEET_SERVICE_ACCOUNT_JSON")["secret"] is True


@pytest.mark.parametrize("key,value", [
    ("FUNNEL_DAY_START", "25:00"), ("FUNNEL_REMINDER_TIME", "7"), ("FUNNEL_WORK_DAYS", "1-8"),
    ("FUNNEL_WORK_DAYS", "dushanba"), ("FUNNEL_LOCATION_LAT", "95.1"),
    ("FUNNEL_LOCATION_LON", "abc"), ("FUNNEL_HOLIDAYS", "2026-02-30"),
    ("FUNNEL_HOLIDAYS", "01.10.2026"), ("FUNNEL_SLOT_MINUTES", "5"),
    ("FUNNEL_SLOT_CAPACITY", "0"), ("FUNNEL_BOOK_DAYS_AHEAD", "100"),
    ("FUNNEL_TG_CHANNEL", "wk_channel"), ("FUNNEL_TG_DISCUSSION_CHAT_ID", "12345"),
    ("FUNNEL_KEYWORDS", " , "), ("FUNNEL_GRADES", "1," + "x" * 25),
    ("FUNNEL_PDF_CAPTION", "x" * 1025), ("FUNNEL_IG_LINK_MESSAGE", "x" * 641),
    ("GSHEET_SERVICE_ACCOUNT_JSON", "{not json"),
    ("GSHEET_SERVICE_ACCOUNT_JSON", '{"client_email": "a@b.c"}'),
    ("GSHEET_SPREADSHEET_ID", "abc"), ("GSHEET_WORKSHEET", "a/b"),
    ("FUNNEL_ENABLED", "maybe"),
])
def test_funnel_settings_validation_rejects(client, admin, key, value):
    r = client.put("/api/settings", headers=admin, json={"values": {key: value}})
    assert r.status_code == 400, (key, value, r.text)
    assert isinstance(r.json()["detail"], str)


def test_funnel_settings_accept_valid_values_and_apply_live(client, admin):
    r = client.put("/api/settings", headers=admin, json={"values": {
        "FUNNEL_DAY_START": "10:00", "FUNNEL_WORK_DAYS": "1-3,5", "FUNNEL_HOLIDAYS":
        "2026-10-01, 2026-12-08", "FUNNEL_LOCATION_LAT": "41.311081",
        "FUNNEL_LOCATION_LON": "69.240562", "FUNNEL_TG_CHANNEL": "@wk_channel",
        "FUNNEL_TG_DISCUSSION_CHAT_ID": "-1001234567890", "FUNNEL_SLOT_CAPACITY": "2",
        "FUNNEL_ENABLED": "yo'q", "GSHEET_WORKSHEET": "Ro'yxat",
        "GSHEET_SPREADSHEET_ID": "https://docs.google.com/spreadsheets/d/1AbCdEfGhIjKlMnOpQrStUvWxYz/edit",
        "GSHEET_SERVICE_ACCOUNT_JSON": '{"client_email": "a@b.iam.gserviceaccount.com", '
                                       '"private_key": "-----BEGIN PRIVATE KEY-----"}',
    }})
    assert r.status_code == 200, r.text
    assert settings.FUNNEL_SLOT_CAPACITY == 2 and settings.FUNNEL_ENABLED is False
    assert settings.FUNNEL_DAY_START == "10:00"


def test_reminder_time_change_reschedules_cron(client, admin, monkeypatch):
    import app.main as main_mod

    calls: list[int] = []
    monkeypatch.setattr(main_mod, "_schedule_funnel_reminders", lambda: calls.append(1))
    client.put("/api/settings", headers=admin, json={"values": {"FUNNEL_REMINDER_TIME": "06:30"}})
    assert calls == [1]
    client.put("/api/settings", headers=admin, json={"values": {"FUNNEL_ASK_NAME": "Ismingiz?"}})
    assert calls == [1]
