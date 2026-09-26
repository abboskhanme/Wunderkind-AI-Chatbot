"""Buttons under sales messages and click branching (SPEC §14): keyboards,
Telegram button clicks, tracked link redirects, the clicked / not_clicked
scheduler conditions and the admin API rules."""
from __future__ import annotations

import uuid
from datetime import datetime, timedelta, timezone
from zoneinfo import ZoneInfo

import pytest

from app.config import settings
from app.funnel import buttons, delivery, sales
from app.models.funnel import (
    FunnelButtonClick, FunnelDelivery, FunnelEntry, FunnelMessage, FunnelMessageButton,
    InterviewBooking,
)
from app.models.lead import Lead, LeadMessage
from tests.conftest import auth_headers, make_user
from tests.funnel_fakes import callback, db_add, db_all, fake_tg, feed, run  # noqa: F401

TZ = ZoneInfo("Asia/Tashkent")
NOON = datetime(2030, 3, 5, 12, tzinfo=TZ).astimezone(timezone.utc)


def pdf_entry(tg: str, sent_at: datetime, **kw) -> FunnelEntry:
    fields = dict(source="telegram_direct", start_token=f"tok{tg}", tg_user_id=tg,
                  tg_chat_id=tg, step="pdf_sent", full_name="Ali Valiyev", phone="+998901112233",
                  grade="4", pdf_sent_at=sent_at, sheet_dirty=False)
    return FunnelEntry(**{**fields, **kw})


@pytest.fixture
def branch(database):
    """A: "Ha" (plain) + "Sayt" (link) buttons; B: to those who pressed "Ha", at
    once; C: to those who did not press "Ha" within an hour."""
    ha = FunnelMessageButton(id=uuid.uuid4(), text="Ha", sort_order=0)
    site = FunnelMessageButton(id=uuid.uuid4(), text="Sayt", url="https://example.uz/x",
                               sort_order=1)
    a = FunnelMessage(id=uuid.uuid4(), text="A: qiziqasizmi?", delay_minutes=0, sort_order=0,
                      is_active=True, show_book_button=False, buttons=[ha, site])
    db_add(database, a)
    b = FunnelMessage(id=uuid.uuid4(), text="B: bosganlarga", delay_minutes=0, sort_order=1,
                      is_active=True, condition="clicked", condition_message_id=a.id,
                      condition_button_id=ha.id)
    c = FunnelMessage(id=uuid.uuid4(), text="C: bosmaganlarga", delay_minutes=60,
                      sort_order=2, is_active=True, condition="not_clicked",
                      condition_message_id=a.id, condition_button_id=ha.id)
    db_add(database, b, c)
    return a, b, c, ha, site


def got_a(database, tg: str, a: FunnelMessage, at: datetime, **kw) -> FunnelEntry:
    entry = pdf_entry(tg, at - timedelta(minutes=5), **kw)
    db_add(database, entry)
    db_add(database, FunnelDelivery(entry_id=entry.id, message_id=a.id, sent_at=at))
    return entry


def sent_texts(fake_tg) -> list[str]:
    return [m["text"] for m in fake_tg.of("message")]


# --------------------------------------------------------------------------- #
# Keyboard
# --------------------------------------------------------------------------- #
def test_keyboard_buttons_then_booking_and_tracked_links(database, branch, monkeypatch):
    a, _, _, ha, site = branch
    entry_id = uuid.uuid4()
    rows = delivery.message_keyboard(a, None, entry_id)["inline_keyboard"]
    assert rows == [[{"text": "Ha", "callback_data": f"fm:{ha.id.hex}"}],
                    [{"text": "Sayt", "url": "https://example.uz/x"}]]     # no PUBLIC_URL
    assert len(rows[0][0]["callback_data"].encode()) <= 64

    monkeypatch.setattr(settings, "PUBLIC_URL", "https://bot.example.uz/")
    tracked = delivery.message_keyboard(a, None, entry_id)["inline_keyboard"][1][0]["url"]
    assert tracked.startswith("https://bot.example.uz/go/b/")
    assert buttons.parse_token(tracked.rsplit("/", 1)[1]) == (entry_id, site.id)
    # A test message has no recipient entry: the plain link
    assert delivery.message_keyboard(a, None, None)["inline_keyboard"][1][0]["url"] == \
        "https://example.uz/x"

    a.show_book_button = True
    rows = delivery.message_keyboard(a, None, entry_id)["inline_keyboard"]
    assert rows[-1][0]["callback_data"] == "fb:start"
    plain = FunnelMessage(text="x", delay_minutes=0, show_book_button=False, buttons=[])
    assert delivery.message_keyboard(plain) is None


def test_click_token_rejects_tampering():
    entry_id, button_id = uuid.uuid4(), uuid.uuid4()
    token = buttons.click_token(entry_id, button_id)
    assert buttons.parse_token(token) == (entry_id, button_id)
    flipped = token[:-2] + ("A" if token[-2] != "A" else "B") + token[-1]
    assert buttons.parse_token(flipped) is None
    assert buttons.parse_token("abc") is None
    assert buttons.parse_token("!!!!") is None


# --------------------------------------------------------------------------- #
# Telegram button click
# --------------------------------------------------------------------------- #
def test_click_records_once_and_sends_the_instant_followup(database, fake_tg, branch):
    a, b, _, ha, _ = branch
    lead = Lead(channel="telegram", external_id="21", status="new")
    db_add(database, lead)
    entry = got_a(database, "21", a, NOON, lead_id=lead.id)

    feed(callback(21, f"fm:{ha.id.hex}"))
    (click,) = db_all(database, FunnelButtonClick)
    assert (click.entry_id, click.button_id, click.message_id) == (entry.id, ha.id, a.id)
    assert sent_texts(fake_tg) == ["B: bosganlarga"]
    assert fake_tg.of("answer")[-1]["text"] is None           # the message is the answer
    assert any("Tugma bosildi: «Ha»" in m.text for m in db_all(database, LeadMessage))

    feed(callback(21, f"fm:{ha.id.hex}"))                      # again: nothing new
    assert len(db_all(database, FunnelButtonClick)) == 1
    assert sent_texts(fake_tg) == ["B: bosganlarga"]
    assert fake_tg.of("answer")[-1]["text"] == buttons.CLICKED_NOTICE


def test_click_followup_respects_booking_and_opt_out(database, fake_tg, branch):
    a, _, _, ha, _ = branch
    booked = got_a(database, "22", a, NOON)
    db_add(database, InterviewBooking(entry_id=booked.id, starts_at=NOON + timedelta(days=1),
                                      status="scheduled"))
    got_a(database, "23", a, NOON, opted_out=True)
    feed(callback(22, f"fm:{ha.id.hex}"))
    feed(callback(23, f"fm:{ha.id.hex}"))
    assert len(db_all(database, FunnelButtonClick)) == 2       # clicks still recorded
    assert sent_texts(fake_tg) == []


def test_unknown_button_and_stranger_click(database, fake_tg, branch):
    _, _, _, ha, _ = branch
    feed(callback(24, f"fm:{uuid.uuid4().hex}"))
    assert fake_tg.of("answer")[-1]["text"] == buttons.STALE_NOTICE
    feed(callback(25, f"fm:{ha.id.hex}"))                      # no entry (staff test chat)
    assert db_all(database, FunnelButtonClick) == []
    assert sent_texts(fake_tg) == []


# --------------------------------------------------------------------------- #
# Link redirect
# --------------------------------------------------------------------------- #
def test_link_redirect_records_click_and_forwards(client, database, fake_tg, branch):
    a, _, _, _, site = branch
    entry = got_a(database, "26", a, NOON)
    token = buttons.click_token(entry.id, site.id)

    head = client.head(f"/go/b/{token}", follow_redirects=False)
    assert head.status_code == 302 and db_all(database, FunnelButtonClick) == []

    r = client.get(f"/go/b/{token}", follow_redirects=False)
    assert r.status_code == 302 and r.headers["location"] == "https://example.uz/x"
    (click,) = db_all(database, FunnelButtonClick)
    assert click.button_id == site.id and click.entry_id == entry.id
    assert client.get(f"/go/b/{token}", follow_redirects=False).status_code == 302
    assert len(db_all(database, FunnelButtonClick)) == 1

    bad = client.get(f"/go/b/{token[:-3]}xyz", follow_redirects=False)
    assert bad.status_code == 404
    assert client.get(f"/go/b/{buttons.click_token(entry.id, uuid.uuid4())}",
                      follow_redirects=False).status_code == 404


# --------------------------------------------------------------------------- #
# Scheduler conditions
# --------------------------------------------------------------------------- #
def test_not_clicked_goes_only_to_those_who_did_not_press(database, fake_tg, branch):
    a, _, _, ha, _ = branch
    clicked = got_a(database, "31", a, NOON - timedelta(hours=2))
    got_a(database, "32", a, NOON - timedelta(hours=2))
    got_a(database, "33", a, NOON - timedelta(minutes=30))       # hour not over yet
    db_add(database, FunnelButtonClick(entry_id=clicked.id, message_id=a.id, button_id=ha.id,
                                       clicked_at=NOON - timedelta(hours=1)))
    run(sales.run_sales(NOON))
    got = {(m["chat_id"], m["text"]) for m in fake_tg.of("message")}
    assert ("32", "C: bosmaganlarga") in got
    assert not any(chat == "33" for chat, _ in got)
    assert ("31", "C: bosmaganlarga") not in got
    # B (delay 0 after the click) is picked up by the scheduler too if it was missed
    assert ("31", "B: bosganlarga") in got


def test_clicked_delay_counts_from_the_click(database, fake_tg):
    ha = FunnelMessageButton(id=uuid.uuid4(), text="Ha", sort_order=0)
    a = FunnelMessage(id=uuid.uuid4(), text="A", delay_minutes=0, sort_order=0,
                      is_active=True, buttons=[ha])
    db_add(database, a)
    later = FunnelMessage(text="30 daqiqadan keyin", delay_minutes=30, sort_order=1,
                          is_active=True, condition="clicked", condition_message_id=a.id)
    db_add(database, later)                                      # any button of A
    entry = got_a(database, "41", a, NOON - timedelta(hours=3))
    db_add(database, FunnelButtonClick(entry_id=entry.id, message_id=a.id, button_id=ha.id,
                                       clicked_at=NOON - timedelta(minutes=10)))
    assert run(sales.run_sales(NOON)) == 0
    assert run(sales.run_sales(NOON + timedelta(minutes=21))) == 1
    assert sent_texts(fake_tg) == ["30 daqiqadan keyin"]


def test_conditional_message_with_a_missing_button_is_never_sent(database, fake_tg, branch):
    a, _, c, _, _ = branch
    got_a(database, "51", a, NOON - timedelta(hours=2))

    async def point_to_ghost():
        from app.db import session as db_session
        async with db_session.SessionLocal() as db:
            row = await db.get(FunnelMessage, c.id)
            row.condition_button_id = uuid.uuid4()
            await db.commit()
    run(point_to_ghost())
    assert run(sales.run_sales(NOON)) == 0


# --------------------------------------------------------------------------- #
# Admin API
# --------------------------------------------------------------------------- #
@pytest.fixture
def admin(client, database):
    make_user(database, "admin", "admin")
    return auth_headers(client, "admin")


def post(client, admin, **body):
    body = {"text": "Matn", "delay_minutes": 10, **body}
    return client.post("/api/funnel/messages", json=body, headers=admin)


def test_api_buttons_conditions_and_counts(client, admin, database):
    r = post(client, admin, buttons=[{"text": " Ha ", "url": ""},
                                     {"text": "Sayt", "url": "https://example.uz"}],
             show_book_button=False)
    assert r.status_code == 201, r.text
    a = r.json()
    assert [(b["text"], b["url"]) for b in a["buttons"]] == [("Ha", None),
                                                             ("Sayt", "https://example.uz")]
    assert a["show_book_button"] is False and a["condition"] == "none"
    ha = a["buttons"][0]["id"]

    r = post(client, admin, condition="clicked", condition_message_id=a["id"],
             condition_button_id=ha, delay_minutes=0)
    assert r.status_code == 201, r.text
    b = r.json()
    assert (b["condition"], b["condition_message_id"], b["condition_button_id"]) == \
        ("clicked", a["id"], ha)

    # Counts: one delivery of A, one click on "Ha"
    entry = pdf_entry("61", NOON)
    db_add(database, entry)
    db_add(database,
           FunnelDelivery(entry_id=entry.id, message_id=uuid.UUID(a["id"]), sent_at=NOON),
           FunnelButtonClick(entry_id=entry.id, message_id=uuid.UUID(a["id"]),
                             button_id=uuid.UUID(ha), clicked_at=NOON))
    listed = {m["id"]: m for m in client.get("/api/funnel/messages", headers=admin).json()}
    assert listed[a["id"]]["sent_count"] == 1
    assert [x["clicks"] for x in listed[a["id"]]["buttons"]] == [1, 0]

    # Renaming keeps the button (and its clicks); a new list without "Ha" is refused
    r = client.patch(f"/api/funnel/messages/{a['id']}", headers=admin, json={
        "buttons": [{"id": ha, "text": "Ha, albatta"}, {"text": "Yangi"}]})
    assert r.status_code == 200, r.text
    assert r.json()["buttons"][0] == {"id": ha, "text": "Ha, albatta", "url": None, "clicks": 1}
    r = client.patch(f"/api/funnel/messages/{a['id']}", headers=admin,
                     json={"buttons": [{"text": "Boshqa"}]})
    assert r.status_code == 400 and "shartida" in r.json()["detail"]

    # A referenced message cannot be deleted; its dependent can
    assert client.delete(f"/api/funnel/messages/{a['id']}", headers=admin).status_code == 409
    assert client.delete(f"/api/funnel/messages/{b['id']}", headers=admin).status_code == 204
    assert client.delete(f"/api/funnel/messages/{a['id']}", headers=admin).status_code == 204
    assert db_all(database, FunnelButtonClick) == []
    assert db_all(database, FunnelMessageButton) == []


def test_api_condition_validation(client, admin):
    a = post(client, admin, buttons=[{"text": "Ha"}]).json()
    plain = post(client, admin).json()
    other = post(client, admin, buttons=[{"text": "Yo'q"}]).json()

    def cond(**kw):
        return post(client, admin, **kw)

    assert cond(condition="clicked").status_code == 400                  # no source
    assert cond(condition="clicked", condition_message_id=plain["id"]).status_code == 400
    assert cond(condition="clicked", condition_message_id=a["id"],
                condition_button_id=other["buttons"][0]["id"]).status_code == 400
    r = cond(condition="not_clicked", condition_message_id=a["id"], delay_minutes=0)
    assert r.status_code == 400 and "kutish" in r.json()["detail"]
    assert post(client, admin, buttons=[{"text": "x", "url": "javascript:alert(1)"}]
                ).status_code == 422
    assert post(client, admin, buttons=[{"text": str(i)} for i in range(9)]).status_code == 422

    # Self and cycles
    r = client.patch(f"/api/funnel/messages/{a['id']}", headers=admin,
                     json={"condition": "clicked", "condition_message_id": a["id"]})
    assert r.status_code == 400
    b = cond(condition="clicked", condition_message_id=a["id"],
             buttons=[{"text": "Keyin"}]).json()
    r = client.patch(f"/api/funnel/messages/{a['id']}", headers=admin,
                     json={"condition": "clicked", "condition_message_id": b["id"]})
    assert r.status_code == 400 and "aylana" in r.json()["detail"]

    # Back to everyone clears the ids
    r = client.patch(f"/api/funnel/messages/{b['id']}", headers=admin, json={"condition": "none"})
    assert r.status_code == 200
    assert (r.json()["condition"], r.json()["condition_message_id"]) == ("none", None)


def test_copy_funnel_remaps_buttons_and_conditions(client, admin, database):
    source = client.post("/api/funnel/funnels", headers=admin,
                         json={"name": "Manba", "keywords": "manba"}).json()
    a = client.post(f"/api/funnel/messages?funnel_id={source['id']}", headers=admin, json={
        "text": "A", "delay_minutes": 0, "buttons": [{"text": "Ha"}]}).json()
    client.post(f"/api/funnel/messages?funnel_id={source['id']}", headers=admin, json={
        "text": "B", "delay_minutes": 5, "condition": "clicked",
        "condition_message_id": a["id"], "condition_button_id": a["buttons"][0]["id"]})
    copy = client.post("/api/funnel/funnels", headers=admin, json={
        "name": "Nusxa", "keywords": "nusxa", "copy_from_id": source["id"]}).json()
    copied = client.get(f"/api/funnel/messages?funnel_id={copy['id']}", headers=admin).json()
    ca, cb = sorted(copied, key=lambda m: m["text"])
    assert ca["id"] != a["id"] and ca["buttons"][0]["text"] == "Ha"
    assert ca["buttons"][0]["id"] != a["buttons"][0]["id"]
    assert (cb["condition"], cb["condition_message_id"], cb["condition_button_id"]) == \
        ("clicked", ca["id"], ca["buttons"][0]["id"])
    # The copy can be deleted cleanly
    assert client.delete(f"/api/funnel/funnels/{copy['id']}", headers=admin).status_code == 204


def test_link_previews_and_replays_do_not_count(client, database, fake_tg, branch):
    a, _, _, _, site = branch
    entry = got_a(database, "27", a, NOON)
    token = buttons.click_token(entry.id, site.id)
    preview = client.get(f"/go/b/{token}", follow_redirects=False,
                         headers={"User-Agent": "TelegramBot (like TwitterBot)"})
    assert preview.status_code == 302 and db_all(database, FunnelButtonClick) == []
    assert preview.headers["x-robots-tag"] == "noindex, nofollow"
    for _ in range(5):
        client.get(f"/go/b/{token}", follow_redirects=False)
    assert len(db_all(database, FunnelButtonClick)) == 1
    assert buttons._pending == set()


@pytest.mark.parametrize("url", ["https://a.uz/\x00", "https://a.uz/‮", "https://a.uz\\x",
                                 "http:///nohost"])
def test_button_url_rejects_hidden_characters(client, admin, url):
    assert post(client, admin, buttons=[{"text": "x", "url": url}]).status_code == 422


def test_any_button_dependent_blocks_removing_a_button(client, admin):
    a = post(client, admin, buttons=[{"text": "Ha"}, {"text": "Yo'q"}]).json()
    assert post(client, admin, condition="not_clicked", condition_message_id=a["id"],
                delay_minutes=60).status_code == 201                      # any button
    keep_one = [{"id": a["buttons"][0]["id"], "text": "Ha"}]
    r = client.patch(f"/api/funnel/messages/{a['id']}", headers=admin, json={"buttons": keep_one})
    assert r.status_code == 400 and "o'chirib bo'lmaydi" in r.json()["detail"]
    renamed = [{"id": b["id"], "text": b["text"] + "!"} for b in a["buttons"]]
    assert client.patch(f"/api/funnel/messages/{a['id']}", headers=admin,
                        json={"buttons": renamed}).status_code == 200


def test_not_clicked_is_rechecked_right_before_sending(database, fake_tg, branch, monkeypatch):
    a, _, c, ha, _ = branch
    entry = got_a(database, "71", a, NOON - timedelta(hours=2))
    real_claim = sales._claim

    async def claim_then_click(e, m, now):
        ok = await real_claim(e, m, now)
        async with database() as s:          # the person presses "Ha" just now
            s.add(FunnelButtonClick(entry_id=entry.id, message_id=a.id, button_id=ha.id,
                                    clicked_at=NOON))
            await s.commit()
        return ok
    monkeypatch.setattr(sales, "_claim", claim_then_click)
    assert run(sales.run_sales(NOON)) == 0
    assert db_all(database, FunnelDelivery, FunnelDelivery.message_id == c.id) == []
