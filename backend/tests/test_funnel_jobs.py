"""Funnel scheduler jobs: sales sequence, booking-day reminders, Google Sheets
outbox (fake HTTP transport, real RS256-signed service-account JWT)."""
from __future__ import annotations

import json
import re
from datetime import datetime, timedelta, timezone
from urllib.parse import unquote
from zoneinfo import ZoneInfo

import httpx
import jwt
import pytest

from app.config import settings
from app.funnel import gsheet, reminders, sales
from app.models.funnel import FunnelDelivery, FunnelEntry, FunnelMessage, InterviewBooking
from tests.funnel_fakes import db_add, db_all, fake_tg, run  # noqa: F401  (fixtures)

TZ = ZoneInfo("Asia/Tashkent")


def at_local(y, m, d, hh, mm=0) -> datetime:
    return datetime(y, m, d, hh, mm, tzinfo=TZ).astimezone(timezone.utc)


NOON = at_local(2030, 3, 5, 12)          # inside the 09:00–21:00 window


def pdf_entry(tg: str, sent_at: datetime, **kw) -> FunnelEntry:
    fields = dict(source="telegram_direct", start_token=f"tok{tg}", tg_user_id=tg,
                  tg_chat_id=tg, step="pdf_sent", full_name="Ali Valiyev", phone="+998901112233",
                  grade="4", pdf_sent_at=sent_at, sheet_dirty=False)
    return FunnelEntry(**{**fields, **kw})


@pytest.fixture
def sequence(database):
    first = FunnelMessage(text="Birinchi", delay_minutes=10, sort_order=0, is_active=True)
    second = FunnelMessage(text="Ikkinchi", delay_minutes=60 * 24, sort_order=1, is_active=True)
    off = FunnelMessage(text="O'chirilgan", delay_minutes=0, sort_order=2, is_active=False)
    db_add(database, first, second, off)
    return first, second


# --------------------------------------------------------------------------- #
# Sales sequence
# --------------------------------------------------------------------------- #
def test_sales_respects_delay_and_never_sends_twice(database, fake_tg, sequence):
    db_add(database, pdf_entry("1", NOON - timedelta(minutes=5)))
    assert run(sales.run_sales(NOON)) == 0                          # 10 min not yet
    later = NOON + timedelta(minutes=6)
    assert run(sales.run_sales(later)) == 1
    assert run(sales.run_sales(later)) == 0                         # no double send
    (msg,) = fake_tg.of("message")
    assert msg["chat_id"] == "1" and msg["text"] == "Birinchi"
    assert msg["reply_markup"]["inline_keyboard"][0][0]["callback_data"] == "fb:start"
    next_day = NOON + timedelta(days=1)
    assert run(sales.run_sales(next_day)) == 1
    assert [m["text"] for m in fake_tg.of("message")] == ["Birinchi", "Ikkinchi"]
    assert run(sales.run_sales(next_day + timedelta(hours=1))) == 0  # inactive one skipped
    assert len(db_all(database, FunnelDelivery)) == 2


def test_sales_one_message_per_run_in_order(database, fake_tg, sequence):
    db_add(database, pdf_entry("2", NOON - timedelta(days=1, hours=1)))   # both are due
    assert run(sales.run_sales(NOON)) == 1
    assert fake_tg.of("message")[-1]["text"] == "Birinchi"
    assert run(sales.run_sales(NOON + timedelta(minutes=1))) == 1
    assert fake_tg.of("message")[-1]["text"] == "Ikkinchi"


def test_sales_quiet_hours(database, fake_tg, sequence):
    db_add(database, pdf_entry("3", NOON - timedelta(hours=1)))
    assert run(sales.run_sales(at_local(2030, 3, 5, 21, 30))) == 0
    assert run(sales.run_sales(at_local(2030, 3, 6, 8, 59))) == 0
    assert run(sales.run_sales(at_local(2030, 3, 6, 9, 0))) == 1


def test_sales_stop_on_booking_opt_out_and_stale(database, fake_tg, sequence):
    booked = pdf_entry("4", NOON - timedelta(hours=1))
    db_add(database, booked, pdf_entry("5", NOON - timedelta(hours=1), opted_out=True),
           pdf_entry("6", NOON - timedelta(days=30)))            # overdue long ago
    db_add(database, InterviewBooking(entry_id=booked.id, starts_at=NOON + timedelta(days=1),
                                      status="scheduled"))
    assert run(sales.run_sales(NOON)) == 0
    assert fake_tg.of("message") == []


def test_blocked_bot_opts_out_and_transient_error_retries(database, fake_tg, sequence):
    db_add(database, pdf_entry("7", NOON - timedelta(hours=1)))
    fake_tg.results["message"] = {"sent": False, "error": "Bad Gateway"}
    assert run(sales.run_sales(NOON)) == 0
    assert db_all(database, FunnelDelivery) == []                    # claim released
    fake_tg.results["message"] = {"sent": False,
                                  "error": "Forbidden: bot was blocked by the user"}
    run(sales.run_sales(NOON))
    (entry,) = db_all(database, FunnelEntry)
    assert entry.opted_out is True and len(db_all(database, FunnelDelivery)) == 1
    del fake_tg.results["message"]
    assert run(sales.run_sales(NOON + timedelta(days=1))) == 0


def test_sales_image_is_uploaded_once_then_cached(database, fake_tg):
    image_msg = FunnelMessage(text="Rasmli", delay_minutes=0, sort_order=0, is_active=True,
                              image=b"\x89PNG....", image_content_type="image/png")
    db_add(database, image_msg)
    db_add(database, pdf_entry("8", NOON - timedelta(minutes=1)),
           pdf_entry("9", NOON - timedelta(minutes=1)))
    assert run(sales.run_sales(NOON)) == 2
    first, second = fake_tg.of("photo")
    assert first["photo"] == (b"\x89PNG....", "image/png") and first["caption"] == "Rasmli"
    assert second["photo"] == "PHOTO-1"                              # Telegram file_id


# --------------------------------------------------------------------------- #
# Reminders
# --------------------------------------------------------------------------- #
def test_reminder_selection_and_single_send(database, fake_tg, monkeypatch):
    monkeypatch.setattr(settings, "FUNNEL_LOCATION_LAT", "41.3")
    monkeypatch.setattr(settings, "FUNNEL_LOCATION_LON", "69.2")
    now = at_local(2030, 3, 5, 7)
    entries = [pdf_entry(str(i), NOON - timedelta(days=2), full_name=f"Ism{i}")
               for i in range(10, 15)]
    db_add(database, *entries)
    yesterday = now - timedelta(days=1)

    def booking(entry, hh, created, **kw):
        return InterviewBooking(entry_id=entry.id, starts_at=at_local(2030, 3, 5, hh),
                                created_at=created, **{"status": "scheduled", **kw})

    db_add(database,
           booking(entries[0], 10, yesterday),                                  # due
           booking(entries[1], 11, now + timedelta(minutes=30)),                # booked after 07:00
           InterviewBooking(entry_id=entries[2].id, starts_at=at_local(2030, 3, 6, 10),
                            created_at=yesterday, status="scheduled"),          # tomorrow
           booking(entries[3], 12, yesterday, status="cancelled"),
           booking(entries[4], 13, yesterday, reminder_sent_at=yesterday))      # already sent
    due = run(reminders.due_reminders(now))
    assert [e.full_name for _, e in due] == ["Ism10"]

    assert run(reminders.run_reminders(now)) == 1
    assert run(reminders.run_reminders(now)) == 0
    (msg,) = fake_tg.of("message")
    assert msg["chat_id"] == "10" and "Ism10" in msg["text"] and "10:00" in msg["text"]
    assert msg["reply_markup"]["inline_keyboard"][1][0]["callback_data"] == "fb:cancel"
    assert fake_tg.of("location") == [{"chat_id": "10", "lat": 41.3, "lon": 69.2}]


def test_unfilled_placeholder_messages_are_never_sent(database, fake_tg):
    db_add(database, FunnelMessage(text="Bizda [raqam] nafar o'quvchi", delay_minutes=0,
                                   sort_order=0, is_active=True),
           FunnelMessage(text="Chegirma: [imtiyoz — masalan 10%]", delay_minutes=0,
                         sort_order=1, is_active=True))
    db_add(database, pdf_entry("15", NOON - timedelta(hours=1)))
    assert run(sales.run_sales(NOON)) == 0 and fake_tg.of("message") == []
    assert sales.has_placeholders("[Raqam]") and not sales.has_placeholders("[boshqa]")


@pytest.mark.parametrize("hh,mm,runs", [(6, 59, False), (7, 0, True), (11, 59, True),
                                        (12, 0, False)])
def test_reminder_catch_up_only_in_the_morning(monkeypatch, hh, mm, runs):
    calls: list = []

    async def fake_run(now=None):
        calls.append(now)
        return 1

    monkeypatch.setattr(reminders, "run_reminders", fake_run)
    run(reminders.catch_up(at_local(2030, 3, 5, hh, mm)))
    assert bool(calls) is runs


# --------------------------------------------------------------------------- #
# Google Sheets
# --------------------------------------------------------------------------- #
@pytest.fixture(scope="module")
def service_account() -> dict:
    from cryptography.hazmat.primitives import serialization
    from cryptography.hazmat.primitives.asymmetric import rsa

    key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    pem = key.private_bytes(serialization.Encoding.PEM, serialization.PrivateFormat.PKCS8,
                            serialization.NoEncryption()).decode()
    public = key.public_key().public_bytes(
        serialization.Encoding.PEM, serialization.PublicFormat.SubjectPublicKeyInfo).decode()
    return {"client_email": "bot@proj.iam.gserviceaccount.com", "private_key": pem,
            "private_key_id": "kid1", "token_uri": "https://oauth2.googleapis.com/token",
            "_public": public}


class FakeGoogle:
    """A tiny in-memory Google Sheet: rows by number (1 = header), column N = ID."""

    def __init__(self, public_key: str) -> None:
        self.public_key = public_key
        self.calls: list[tuple[str, str, object]] = []
        self.rows: dict[int, list[str]] = {}
        self.fail_status = 0              # every Sheets call answers with this
        self.fail_rows: set[int] = set()  # PUT to these rows -> 400
        self.on_append = None

    def ids(self) -> dict[str, int]:
        return {r[13]: n for n, r in self.rows.items() if len(r) > 13 and n > 1}

    async def __call__(self, request: httpx.Request) -> httpx.Response:
        url = unquote(str(request.url))
        body = json.loads(request.content) if request.content and \
            request.headers.get("content-type", "").startswith("application/json") else None
        if url.startswith("https://oauth2.googleapis.com/token"):
            form = dict(x.split("=", 1) for x in request.content.decode().split("&"))
            claims = jwt.decode(unquote(form["assertion"]), self.public_key, algorithms=["RS256"],
                                audience="https://oauth2.googleapis.com/token")
            assert claims["scope"] == gsheet.SCOPE
            return httpx.Response(200, json={"access_token": "tok", "expires_in": 3600})
        assert request.headers["authorization"] == "Bearer tok"
        self.calls.append((request.method, url, body))
        if self.fail_status:
            return httpx.Response(self.fail_status, json={"error": {"message": "google says no"}})
        if request.method == "GET" and "/values/" not in url:
            return httpx.Response(200, json={"properties": {"title": "Voronka"},
                                             "sheets": [{"properties": {"title": "Leadlar"}}]})
        if ":append" in url:
            if self.on_append:
                await self.on_append()
            number = max(self.rows, default=1) + 1
            self.rows[number] = body["values"][0]
            return httpx.Response(200, json={
                "updates": {"updatedRange": f"'Leadlar'!A{number}:N{number}"}})
        col, row = re.search(r"!([A-Z]+)(\d*)", url).groups()
        if request.method == "GET" and not row:            # whole ID column
            last = max(self.rows, default=0)
            column = [[self.rows.get(n, [""] * 14)[13]] if len(self.rows.get(n, [])) > 13
                      else [] for n in range(1, last + 1)]
            return httpx.Response(200, json={"values": column})
        if request.method == "GET":                          # header row
            return httpx.Response(200, json={"values": [self.rows[1]]} if 1 in self.rows else {})
        number = int(row)
        if number in self.fail_rows:
            return httpx.Response(400, json={"error": {"message": "range exceeds grid"}})
        if col == "A":
            self.rows[number] = body["values"][0]
        else:
            cells = self.rows.setdefault(number, [""] * 14)
            cells[ord(col) - ord("A")] = body["values"][0][0]
        return httpx.Response(200, json={})


@pytest.fixture
def google(service_account, monkeypatch):
    fake = FakeGoogle(service_account["_public"])
    account = {k: v for k, v in service_account.items() if not k.startswith("_")}
    monkeypatch.setattr(settings, "GSHEET_SERVICE_ACCOUNT_JSON", json.dumps(account))
    monkeypatch.setattr(settings, "GSHEET_SPREADSHEET_ID",
                        "https://docs.google.com/spreadsheets/d/1AbCdEfGhIjKlMnOpQrStUvWxYz/edit")
    monkeypatch.setattr(gsheet, "_transport", httpx.MockTransport(fake))
    gsheet._token_cache.clear()
    gsheet._ready_sheets.clear()
    return fake


def test_entry_row_mapping():
    import uuid

    entry_id = uuid.uuid4()
    entry = FunnelEntry(id=entry_id, source="instagram", start_token="t", step="pdf_sent",
                        full_name="Aliyeva Malika", phone="+998901234567", grade="5",
                        tg_username="malika", tg_user_id="777", ig_username="mama_ali",
                        created_at=at_local(2030, 3, 5, 9, 15), pdf_sent_at=NOON)
    item = InterviewBooking(starts_at=at_local(2030, 3, 7, 10, 30), status="attended")
    row = gsheet.entry_row(entry, item, now=at_local(2030, 3, 7, 11))
    assert row == ["2030-03-05 09:15", "Instagram", "Aliyeva Malika", "+998901234567",
                   "5-sinf", "@malika", "777", "@mama_ali", "Yuborildi", "2030-03-07",
                   "10:30", "Keldi", "2030-03-07 11:00", str(entry_id)]
    assert len(row) == len(gsheet.HEADER) and gsheet.HEADER[-1] == "ID"
    bare = FunnelEntry(source="telegram_channel", start_token="t2", step="pdf_pending",
                       created_at=NOON)
    assert gsheet.entry_row(bare, None)[1] == "Telegram kanal"
    assert gsheet.entry_row(bare, None)[8:12] == ["Kutilmoqda", "", "", ""]


def _touch(entry_id, **fields):
    async def change():
        from app.db import session as db_session
        from app.funnel import repo

        async with db_session.SessionLocal() as db:
            fresh = await db.get(FunnelEntry, entry_id)
            for key, value in fields.items():
                setattr(fresh, key, value)
            repo.touch(fresh)
            await db.commit()
    run(change())


def test_sheet_outbox_appends_then_updates_row(database, google):
    entry = pdf_entry("20", NOON, sheet_dirty=True)
    db_add(database, entry)
    assert run(gsheet.sync_dirty()) == 1
    assert google.rows[1] == gsheet.HEADER
    assert google.rows[2][2] == "Ali Valiyev" and google.rows[2][13] == str(entry.id)
    (saved,) = db_all(database, FunnelEntry)
    assert saved.sheet_row == 2 and saved.sheet_dirty is False
    assert run(gsheet.sync_dirty()) == 0                           # nothing dirty

    _touch(entry.id, phone="+998935554433")
    google.calls.clear()
    assert run(gsheet.sync_dirty()) == 1
    assert google.rows[2][3] == "+998935554433" and len(google.rows) == 2
    assert not [c for c in google.calls if ":append" in c[1]]
    # sheet structure checked once per process; only the ID column is read again
    assert [c[1].rsplit("!", 1)[-1] for c in google.calls if c[0] == "GET"] == ["N:N"]


def test_rows_found_by_id_after_the_sheet_was_sorted(database, google):
    first, second = pdf_entry("30", NOON, sheet_dirty=True), pdf_entry("31", NOON, sheet_dirty=True)
    db_add(database, first, second)
    assert run(gsheet.sync_dirty()) == 2
    google.rows[2], google.rows[3] = google.rows[3], google.rows[2]    # a manager sorted it
    _touch(first.id, full_name="Yangi Ism")
    assert run(gsheet.sync_dirty()) == 1
    rows = {r[13]: r for r in google.rows.values() if len(r) > 13}
    assert rows[str(first.id)][2] == "Yangi Ism" and rows[str(second.id)][2] == "Ali Valiyev"
    assert google.ids() == {str(second.id): 2, str(first.id): 3}
    assert db_all(database, FunnelEntry, FunnelEntry.id == first.id)[0].sheet_row == 3


def test_per_entry_4xx_is_skipped_and_the_batch_continues(database, google):
    bad, good = pdf_entry("32", NOON, sheet_dirty=True), pdf_entry("33", NOON, sheet_dirty=True)
    db_add(database, bad, good)
    run(gsheet.sync_dirty())
    _touch(bad.id, grade="6")
    _touch(good.id, grade="7")
    google.fail_rows = {google.ids()[str(bad.id)]}
    assert run(gsheet.sync_dirty()) == 1
    bad_now = db_all(database, FunnelEntry, FunnelEntry.id == bad.id)[0]
    good_now = db_all(database, FunnelEntry, FunnelEntry.id == good.id)[0]
    assert bad_now.sheet_row is None and bad_now.sheet_dirty is True
    assert good_now.sheet_dirty is False and google.rows[good_now.sheet_row][4] == "7-sinf"


@pytest.mark.parametrize("status", [503, 429, 403])
def test_google_outage_or_auth_stops_the_batch(database, google, status):
    db_add(database, pdf_entry("21", NOON, sheet_dirty=True))
    google.fail_status = status
    assert run(gsheet.sync_dirty()) == 0
    (entry,) = db_all(database, FunnelEntry)
    assert entry.sheet_dirty is True and entry.sheet_row is None
    google.fail_status = 0
    assert run(gsheet.sync_dirty()) == 1
    assert db_all(database, FunnelEntry)[0].sheet_dirty is False


def test_change_during_write_stays_dirty_but_keeps_row(database, google):
    """The entry changes while Google is writing the old values: the row number is
    kept (no duplicate append) but the entry stays dirty for the next run."""
    entry = pdf_entry("22", NOON, sheet_dirty=True)
    db_add(database, entry)

    async def concurrent_change():
        from app.db import session as db_session
        from app.funnel import repo

        async with db_session.SessionLocal() as db:
            fresh = await db.get(FunnelEntry, entry.id)
            fresh.grade = "6"
            repo.touch(fresh)
            await db.commit()

    google.on_append = concurrent_change
    assert run(gsheet.sync_dirty()) == 1
    (fresh,) = db_all(database, FunnelEntry)
    assert fresh.sheet_row == 2 and fresh.sheet_dirty is True
    google.on_append = None
    assert run(gsheet.sync_dirty()) == 1                          # next minute: update row 2
    (fresh,) = db_all(database, FunnelEntry)
    assert fresh.sheet_dirty is False and len(google.rows) == 2   # no second append


def _merge(ig_id, tg_id):
    async def go():
        from app.db import session as db_session
        from app.funnel import repo

        async with db_session.SessionLocal() as db:
            ig = await db.get(FunnelEntry, ig_id)
            tg = await db.get(FunnelEntry, tg_id)
            await repo.merge_into(db, ig, tg)
            await db.commit()
    run(go())


def test_merged_instagram_row_is_taken_over(database, google):
    ig = FunnelEntry(source="instagram", start_token="tokIG", ig_user_id="ig9",
                     ig_username="mama", step="ig_link_sent", sheet_dirty=True)
    db_add(database, ig)
    run(gsheet.sync_dirty())                                        # IG row 2
    tg = pdf_entry("40", NOON, sheet_dirty=False)
    db_add(database, tg)
    _merge(ig.id, tg.id)
    assert run(gsheet.sync_dirty()) == 1
    assert google.ids() == {str(tg.id): 2}                          # same row, now the TG entry
    assert google.rows[2][7] == "@mama" and len(google.rows) == 2
    assert db_all(database, FunnelEntry)[0].sheet_merged_id is None


def test_merged_instagram_row_is_marked_when_both_have_rows(database, google):
    ig = FunnelEntry(source="instagram", start_token="tokIG2", ig_user_id="ig8",
                     step="ig_link_sent", sheet_dirty=True)
    tg = pdf_entry("41", NOON, sheet_dirty=True)
    db_add(database, ig, tg)
    run(gsheet.sync_dirty())
    ig_row = google.ids()[str(ig.id)]
    _merge(ig.id, tg.id)
    assert run(gsheet.sync_dirty()) == 1
    assert google.rows[ig_row][1] == gsheet.MERGED_LABEL
    assert google.ids()[str(tg.id)] != ig_row


def test_target_change_resets_rows(database, google):
    import app.main as main_mod

    entry = pdf_entry("42", NOON, sheet_dirty=True)
    db_add(database, entry)
    run(gsheet.sync_dirty())
    run(main_mod.after_settings_change(["GSHEET_WORKSHEET"]))
    (fresh,) = db_all(database, FunnelEntry)
    assert fresh.sheet_row is None and fresh.sheet_dirty is True
    assert gsheet._ready_sheets == set()


def test_sheet_not_configured_is_silent(database, monkeypatch):
    monkeypatch.setattr(settings, "GSHEET_SERVICE_ACCOUNT_JSON", "")
    db_add(database, pdf_entry("23", NOON, sheet_dirty=True))
    assert run(gsheet.sync_dirty()) == 0


def test_sheet_connection_test_reports_title_and_hints(database, google):
    assert run(gsheet.test_connection()) == {"ok": True, "title": "Voronka"}
    google.fail_status = 404
    result = run(gsheet.test_connection())
    assert result["ok"] is False and "topilmadi" in result["error"]


def test_spreadsheet_id_from_link_or_id():
    assert gsheet.spreadsheet_id(
        "https://docs.google.com/spreadsheets/d/1AbCdEfGhIjKlMnOpQrStUvWxYz/edit#gid=0"
    ) == "1AbCdEfGhIjKlMnOpQrStUvWxYz"
    assert gsheet.spreadsheet_id("1AbCdEfGhIjKlMnOpQrStUvWxYz") == "1AbCdEfGhIjKlMnOpQrStUvWxYz"
    assert gsheet.spreadsheet_id("short") is None
    assert gsheet.row_number("'Ro''yxat'!A15:N15") == 15
