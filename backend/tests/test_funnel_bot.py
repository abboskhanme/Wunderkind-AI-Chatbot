"""Funnel in the Telegram bot: /start → name → phone → grade → PDF, token binding
and merge, channel gate, /stop, group comments and the booking buttons."""
from __future__ import annotations

from datetime import date, datetime, time, timezone
from zoneinfo import ZoneInfo

import pytest

from app.config import settings
from app.funnel import repo, texts
from app.models.funnel import FunnelEntry, FunnelFile, InterviewBooking
from app.models.lead import Lead, LeadMessage
from tests.funnel_fakes import (  # noqa: F401  (fixtures)
    PDF_BYTES, add_pdf, callback, contact, db_add, db_all, fake_tg, feed, private_text, run,
)

TZ = ZoneInfo("Asia/Tashkent")


@pytest.fixture
def ai_calls(monkeypatch):
    """Free text that reaches the AI pipeline (recorded, not answered)."""
    from app.telegram_business import webhook

    calls: list[str] = []

    async def fake_process(event, **kwargs):
        calls.append(event.text)

    monkeypatch.setattr(webhook, "process_event", fake_process)
    import app.processing.pipeline as pipeline
    monkeypatch.setattr(pipeline, "process_event", fake_process)
    return calls


def entry_of(database, tg_user_id: int) -> FunnelEntry:
    (entry,) = db_all(database, FunnelEntry, FunnelEntry.tg_user_id == str(tg_user_id))
    return entry


def complete_funnel(user_id: int) -> None:
    feed(private_text(user_id, "/start"))
    feed(private_text(user_id, "Aliyeva Malika"))
    feed(contact(user_id, "998901234567"))
    feed(callback(user_id, "fb:g:5"))


# --------------------------------------------------------------------------- #
# State machine
# --------------------------------------------------------------------------- #
def test_full_collection_flow_sends_pdf_and_creates_lead(database, fake_tg, ai_calls):
    add_pdf(database)
    feed(private_text(101, "/start"))
    assert fake_tg.texts() == [settings.FUNNEL_BOT_WELCOME, settings.FUNNEL_ASK_NAME]
    entry = entry_of(database, 101)
    assert entry.source == "telegram_direct" and entry.step == "ask_name"

    feed(private_text(101, "A"))                               # too short -> re-ask
    assert fake_tg.texts()[-1] == texts.NAME_INVALID
    feed(private_text(101, "Aliyeva Malika"))
    ask_phone = fake_tg.of("message")[-1]
    assert ask_phone["text"] == settings.FUNNEL_ASK_PHONE
    assert ask_phone["reply_markup"]["keyboard"][0][0]["request_contact"] is True

    feed(private_text(101, "raqamim yo'q"))                     # invalid -> re-ask
    assert fake_tg.texts()[-1] == texts.PHONE_INVALID
    feed(private_text(101, "90 123 45 67"))                    # typed, normalized
    ack, ask_grade = fake_tg.of("message")[-2:]
    assert ack["reply_markup"] == {"remove_keyboard": True}
    buttons = [b["callback_data"] for row in ask_grade["reply_markup"]["inline_keyboard"]
               for b in row]
    assert "fb:g:Bog'cha" in buttons and "fb:g:11" in buttons
    assert entry_of(database, 101).phone == "+998901234567"

    feed(callback(101, "fb:g:5"))
    (doc,) = fake_tg.of("document")
    assert doc["document"] == (PDF_BYTES, "8 maslahat.pdf", "application/pdf")
    assert doc["caption"] == settings.FUNNEL_PDF_CAPTION
    assert doc["reply_markup"]["inline_keyboard"][0][0]["callback_data"] == "fb:start"
    assert any(c["text"].endswith("✅ 5-sinf") for c in fake_tg.of("edit"))

    entry = entry_of(database, 101)
    assert entry.step == "pdf_sent" and entry.pdf_sent_at and entry.grade == "5"
    assert entry.sheet_dirty is True
    (lead,) = db_all(database, Lead)
    assert (lead.channel, lead.external_id, lead.name, lead.contact, lead.student_age) == (
        "telegram", "101", "Aliyeva Malika", "+998901234567", "5-sinf")
    assert lead.source == "lead_magnet_telegram" and lead.stage == "offer"
    assert lead.lead_score == 60 and entry.lead_id == lead.id
    (log,) = db_all(database, LeadMessage)
    assert log.role == "system" and log.kind == "status" and "qo'llanma yuborildi" in log.text
    (pdf,) = db_all(database, FunnelFile)
    assert pdf.tg_file_id == "FILE-1"                            # cached for next time

    # After the PDF free text goes to the AI; /start resends the PDF by file_id
    feed(private_text(101, "Narxlar qancha?"))
    assert ai_calls == ["Narxlar qancha?"]
    feed(private_text(101, "/start"))
    assert fake_tg.of("document")[-1]["document"] == "FILE-1"
    assert entry_of(database, 101).step == "pdf_sent"


def test_funnel_log_lines_stay_out_of_ai_history(database, fake_tg):
    """IMPORTANT 8: funnel lines are kind=status — the AI history (and the
    first-message disclosure check) only sees real conversation."""
    from app.leads import client as leads_client

    add_pdf(database)
    complete_funnel(107)
    assert [m.kind for m in db_all(database, LeadMessage)] == ["status"]
    ctx = run(leads_client.fetch_context("107", channel="telegram"))
    assert ctx["messages"] == [] and ctx["name"] == "Aliyeva Malika"


def test_stop_pauses_questions_and_start_resumes(database, fake_tg, ai_calls):
    """IMPORTANT 1: /stop leaves the questions; free text goes to the AI; /start resumes."""
    feed(private_text(108, "/start"))
    feed(private_text(108, "/stop"))
    assert entry_of(database, 108).opted_out is True
    feed(private_text(108, "Aliyeva Malika"))
    assert ai_calls == ["Aliyeva Malika"] and entry_of(database, 108).full_name is None
    feed(private_text(108, "/start"))
    assert fake_tg.texts()[-1] == settings.FUNNEL_ASK_NAME
    feed(private_text(108, "Aliyeva Malika"))
    entry = entry_of(database, 108)
    assert entry.full_name == "Aliyeva Malika" and entry.step == "ask_phone"
    assert entry.opted_out is False and ai_calls == ["Aliyeva Malika"]


def test_questions_and_repeated_invalid_answers_go_to_ai(database, fake_tg, ai_calls):
    """IMPORTANT 1: "?" → AI (step kept); 1st invalid → hint, 2nd in a row → AI;
    a valid answer still continues the funnel."""
    feed(private_text(109, "/start"))
    feed(private_text(109, "Maktab qayerda joylashgan?"))
    assert ai_calls == ["Maktab qayerda joylashgan?"]
    assert entry_of(database, 109).step == "ask_name"
    feed(private_text(109, "Menga maktab haqida batafsil aytib bering"))   # 7 words: not a name
    assert fake_tg.texts()[-1] == texts.NAME_INVALID
    feed(private_text(109, "x"))                                          # 2nd invalid in a row
    assert ai_calls[-1] == "x"
    feed(private_text(109, "Karimova Dilnoza"))
    assert entry_of(database, 109).full_name == "Karimova Dilnoza"
    feed(private_text(109, "bilmadim"))                                   # counter was reset
    assert fake_tg.texts()[-1] == texts.PHONE_INVALID


def test_channel_gate_question_and_repeated_check_go_to_ai(database, fake_tg, ai_calls,
                                                          monkeypatch):
    monkeypatch.setattr(settings, "FUNNEL_TG_CHANNEL", "@wk_channel")
    fake_tg.member_status = "left"
    feed(private_text(110, "/start tgc"))
    feed(private_text(110, "Kanal nima uchun kerak?"))
    assert ai_calls == ["Kanal nima uchun kerak?"]
    gates = len([t for t in fake_tg.texts() if t == texts.CHANNEL_GATE])
    feed(private_text(110, "ok"))                                         # still not a member
    assert len([t for t in fake_tg.texts() if t == texts.CHANNEL_GATE]) == gates + 1
    feed(private_text(110, "ok"))                                         # 2nd time → AI
    assert ai_calls[-1] == "ok" and entry_of(database, 110).step == "tg_channel_gate"


def test_menu_keyboard_is_restored_not_wiped(database, fake_tg, monkeypatch):
    """IMPORTANT 2: after the phone and after /stop the menu keyboard comes back."""
    from app.telegram_business import menu as tg_menu
    from app.telegram_business.menu import Menu, MenuItem

    monkeypatch.setattr(tg_menu, "_state", tg_menu._State(
        menu=Menu(items=(MenuItem(id="1", command="narxlar", title="💰 Narxlar"),))))
    feed(private_text(111, "/start"))
    feed(private_text(111, "Aliyeva Malika"))
    feed(private_text(111, "+998901234567"))
    ack = next(m for m in fake_tg.of("message") if m["text"] == texts.PHONE_ACCEPTED)
    assert ack["reply_markup"]["keyboard"] == [[{"text": "💰 Narxlar"}]]
    feed(private_text(111, "/stop"))
    assert fake_tg.of("message")[-1]["reply_markup"]["keyboard"] == [[{"text": "💰 Narxlar"}]]


def test_pdf_send_failure_goes_pending_and_retries_with_backoff(database, fake_tg,
                                                              monkeypatch):
    """IMPORTANT 3: a Telegram error on the PDF never leaves the person stuck."""
    from datetime import timedelta

    from app.funnel import sales

    add_pdf(database)
    fake_tg.results["document"] = {"sent": False, "error": "Bad Gateway"}
    complete_funnel(112)
    entry = entry_of(database, 112)
    assert entry.step == "pdf_pending" and entry.pdf_attempts == 1 and entry.pdf_retry_at
    assert fake_tg.texts()[-1] == texts.PDF_PENDING
    assert "yuborib bo'lmadi" in fake_tg.of("alert")[-1]["text"]

    retry_at = entry.pdf_retry_at.replace(tzinfo=timezone.utc)
    assert run(sales.deliver_pending_pdfs(now=retry_at - timedelta(seconds=1))) == 0
    assert run(sales.deliver_pending_pdfs(now=retry_at)) == 0          # fails again
    entry = entry_of(database, 112)
    assert entry.pdf_attempts == 2
    assert entry.pdf_retry_at.replace(tzinfo=timezone.utc) > retry_at
    from app.funnel.delivery import retry_delay
    assert [retry_delay(n).seconds // 60 for n in (1, 2, 3, 7, 8, 20)] == [1, 2, 4, 60, 60, 60]
    assert [t for t in fake_tg.texts() if t == texts.PDF_PENDING] == [texts.PDF_PENDING]

    del fake_tg.results["document"]
    later = entry.pdf_retry_at.replace(tzinfo=timezone.utc)
    assert run(sales.deliver_pending_pdfs(now=later)) == 1
    entry = entry_of(database, 112)
    assert entry.step == "pdf_sent" and entry.pdf_attempts == 0 and entry.pdf_retry_at is None


def test_first_pdf_upload_is_serialized(database, fake_tg, monkeypatch):
    """MINOR 13: many people finishing at once → one upload, the rest use file_id."""
    import asyncio

    from app.funnel import delivery
    from app.telegram_business.client import telegram

    add_pdf(database)
    sent: list = []

    async def slow_document(chat_id, document, **kw):
        sent.append(document)
        await asyncio.sleep(0.01)
        return {"sent": True, "file_id": "FILE-X"}

    monkeypatch.setattr(telegram, "send_document", slow_document)

    async def both():
        await asyncio.gather(delivery.send_pdf_file("1", reply_markup=None),
                             delivery.send_pdf_file("2", reply_markup=None))
    run(both())
    assert [type(d).__name__ for d in sent] == ["tuple", "str"] and sent[1] == "FILE-X"


def test_typed_grade_and_contact_share(database, fake_tg, ai_calls):
    add_pdf(database)
    feed(private_text(102, "/start"))
    feed(private_text(102, "Karimov Jasur"))
    feed(contact(102, "+998 (93) 555-44-33"))
    feed(private_text(102, "zzzzzzzzzzzzzzzzzzzzzzzz"))       # > 20 chars -> re-ask
    assert fake_tg.texts()[-1] == texts.GRADE_INVALID
    feed(private_text(102, "7-sinf"))
    entry = entry_of(database, 102)
    assert (entry.phone, entry.grade, entry.step) == ("+998935554433", "7", "pdf_sent")
    assert ai_calls == []                                      # collection never hit the AI


def test_no_pdf_yet_is_pending_then_delivered_by_scheduler(database, fake_tg):
    from app.funnel import sales

    complete_funnel(103)
    entry = entry_of(database, 103)
    assert entry.step == "pdf_pending" and fake_tg.texts()[-1] == texts.PDF_PENDING
    assert len(fake_tg.of("alert")) == 1 and "PDF" in fake_tg.of("alert")[0]["text"]

    add_pdf(database)
    assert run(sales.deliver_pending_pdfs()) == 1
    assert entry_of(database, 103).step == "pdf_sent"
    assert run(sales.deliver_pending_pdfs()) == 0             # nothing left


def test_menu_deep_link_and_disabled_start_are_not_funnel(database, fake_tg, ai_calls,
                                                         monkeypatch):
    from app.telegram_business import menu as tg_menu
    from app.telegram_business.menu import Menu, MenuItem

    handled: list[str] = []

    async def fake_action(event, action):
        handled.append(event.text)

    monkeypatch.setattr(tg_menu, "_state", tg_menu._State(
        menu=Menu(items=(MenuItem(id="1", command="narxlar", title="💰 Narxlar"),))))
    monkeypatch.setattr(tg_menu, "handle_action", fake_action)
    feed(private_text(104, "/start narxlar"))
    assert handled == ["/start narxlar"] and db_all(database, FunnelEntry) == []

    monkeypatch.setattr(settings, "FUNNEL_BOT_START_FUNNEL", False)
    feed(private_text(104, "/start"))
    assert handled[-1] == "/start" and db_all(database, FunnelEntry) == []


def test_menu_button_during_collection_goes_to_menu(database, fake_tg, monkeypatch):
    from app.telegram_business import menu as tg_menu
    from app.telegram_business.menu import Menu, MenuItem

    handled: list[str] = []

    async def fake_action(event, action):
        handled.append(event.text)

    monkeypatch.setattr(tg_menu, "_state", tg_menu._State(
        menu=Menu(items=(MenuItem(id="1", command="narxlar", title="💰 Narxlar"),))))
    monkeypatch.setattr(tg_menu, "handle_action", fake_action)
    feed(private_text(105, "/start"))
    feed(private_text(105, "💰 Narxlar"))
    assert handled == ["💰 Narxlar"]
    assert entry_of(database, 105).full_name is None          # not taken as a name


def test_stop_opts_out_and_start_opts_back_in(database, fake_tg):
    feed(private_text(106, "/start"))
    feed(private_text(106, "/stop"))
    assert entry_of(database, 106).opted_out is True
    assert fake_tg.texts()[-1] == texts.STOPPED
    feed(private_text(106, "/start"))
    assert entry_of(database, 106).opted_out is False


# --------------------------------------------------------------------------- #
# Token binding and merge
# --------------------------------------------------------------------------- #
def ig_entry(token: str, igsid: str, **kw) -> FunnelEntry:
    fields = dict(source="instagram", start_token=token, ig_user_id=igsid,
                  ig_username=f"ig_{igsid}", step="ig_link_sent", link_sent_at=repo.now())
    return FunnelEntry(**{**fields, **kw})


def test_instagram_token_binds_to_telegram_user(database, fake_tg, monkeypatch):
    monkeypatch.setattr(settings, "FUNNEL_TG_CHANNEL", "@wk_channel")   # IG skips the TG gate
    fake_tg.member_status = "left"
    db_add(database, ig_entry("tokA123456789", "ig1"))
    feed(private_text(201, "/start tokA123456789"))
    (entry,) = db_all(database, FunnelEntry)
    assert entry.tg_user_id == "201" and entry.ig_user_id == "ig1"
    assert entry.source == "instagram" and entry.step == "ask_name"
    assert fake_tg.of("member") == []
    assert fake_tg.texts()[-1] == settings.FUNNEL_ASK_NAME


def test_existing_telegram_user_opening_ig_link_merges(database, fake_tg):
    add_pdf(database)
    complete_funnel(202)
    db_add(database, ig_entry("tokB123456789", "ig2"))
    feed(private_text(202, "/start tokB123456789"))

    (entry,) = db_all(database, FunnelEntry)                  # IG-only entry deleted
    assert entry.tg_user_id == "202" and entry.ig_user_id == "ig2"
    assert entry.ig_username == "ig_ig2" and entry.source == "instagram"
    assert entry.full_name == "Aliyeva Malika" and entry.step == "pdf_sent"
    assert len(fake_tg.of("document")) == 2                   # PDF re-sent, not re-asked


def test_forwarded_link_of_someone_else_starts_own_flow(database, fake_tg):
    db_add(database, ig_entry("tokC123456789", "ig3", tg_user_id="203", step="ask_phone"))
    feed(private_text(204, "/start tokC123456789"))
    owner, other = entry_of(database, 203), entry_of(database, 204)
    assert owner.start_token == "tokC123456789" and owner.step == "ask_phone"
    assert other.source == "telegram_direct" and other.ig_user_id is None


# --------------------------------------------------------------------------- #
# Channel gate and group comments
# --------------------------------------------------------------------------- #
def test_channel_gate_blocks_until_subscribed(database, fake_tg, monkeypatch):
    monkeypatch.setattr(settings, "FUNNEL_TG_CHANNEL", "@wk_channel")
    fake_tg.member_status = "left"
    feed(private_text(301, "/start tgc"))
    entry = entry_of(database, 301)
    assert entry.source == "telegram_channel" and entry.step == "tg_channel_gate"
    gate = fake_tg.of("message")[-1]
    assert gate["text"] == texts.CHANNEL_GATE
    assert gate["reply_markup"]["inline_keyboard"][0][0]["url"] == "https://t.me/wk_channel"

    feed(callback(301, "fb:chk"))                             # still not a member
    assert fake_tg.of("answer")[-1]["text"] == texts.CHANNEL_NOT_MEMBER
    assert entry_of(database, 301).step == "tg_channel_gate"

    fake_tg.member_status = "member"
    feed(callback(301, "fb:chk"))
    assert entry_of(database, 301).step == "ask_name"
    assert fake_tg.texts()[-1] == settings.FUNNEL_ASK_NAME


def test_channel_gate_passes_when_telegram_cannot_tell(database, fake_tg, monkeypatch):
    monkeypatch.setattr(settings, "FUNNEL_TG_CHANNEL", "-1001234567890")
    fake_tg.member_status = None                              # getChatMember error
    feed(private_text(302, "/start"))
    assert entry_of(database, 302).step == "ask_name"


def group_msg(user_id: int, text: str, **extra) -> dict:
    from tests.funnel_fakes import _ids

    return {"update_id": next(_ids), "message": {
        "message_id": 555, "text": text, "from": {"id": user_id, "is_bot": False},
        "chat": {"id": -100777, "type": "supergroup"}, **extra}}


def test_group_keyword_comment_gets_deep_link_once_per_10_min(database, fake_tg, monkeypatch):
    monkeypatch.setattr(settings, "FUNNEL_TG_DISCUSSION_CHAT_ID", "-100777")
    feed(group_msg(401, "Wunderkind 🙏"))
    (reply,) = fake_tg.of("message")
    assert reply["chat_id"] == "-100777" and reply["reply_to_message_id"] == 555
    assert reply["text"] == settings.FUNNEL_TG_COMMENT_REPLY
    assert reply["reply_markup"]["inline_keyboard"][0][0]["url"] == "https://t.me/wk_bot?start=tgc"

    feed(group_msg(401, "wunderkind"))                        # same person again
    feed(group_msg(402, "salom"))                             # no keyword
    feed(group_msg(403, "wunderkind", is_automatic_forward=True))   # the channel post itself
    assert len(fake_tg.of("message")) == 1

    monkeypatch.setattr(settings, "FUNNEL_TG_DISCUSSION_CHAT_ID", "")
    monkeypatch.setattr(settings, "TELEGRAM_CHAT_ID", "5, -100777")
    feed(group_msg(405, "wunderkind"))                        # the staff alert group
    assert len(fake_tg.of("message")) == 1
    monkeypatch.setattr(settings, "TELEGRAM_CHAT_ID", "")
    monkeypatch.setattr(settings, "FUNNEL_TG_DISCUSSION_CHAT_ID", "-100777")

    monkeypatch.setattr(settings, "FUNNEL_TG_DISCUSSION_CHAT_ID", "-100999")
    feed(group_msg(404, "wunderkind"))                        # other group
    assert len(fake_tg.of("message")) == 1


# --------------------------------------------------------------------------- #
# Booking
# --------------------------------------------------------------------------- #
FIXED_NOW = datetime(2030, 1, 7, 8, 0, tzinfo=TZ).astimezone(timezone.utc)   # Monday 08:00
TUESDAY = date(2030, 1, 8)


@pytest.fixture
def booked_setup(database, fake_tg, monkeypatch):
    monkeypatch.setattr(repo, "now", lambda: FIXED_NOW)
    monkeypatch.setattr(settings, "FUNNEL_LOCATION_LAT", "41.3")
    monkeypatch.setattr(settings, "FUNNEL_LOCATION_LON", "69.2")
    monkeypatch.setattr(settings, "FUNNEL_STAFF_NAME", "Malika opa")
    monkeypatch.setattr(settings, "TELEGRAM_CHAT_ID", "12345")
    add_pdf(database)
    complete_funnel(501)
    return fake_tg


def slot(day: date, hh: int, mm: int = 0) -> str:
    return datetime.combine(day, time(hh, mm), TZ).strftime("%Y%m%d%H%M")


def test_booking_flow_confirm_reschedule_cancel(database, booked_setup):
    tg = booked_setup
    feed(callback(501, "fb:start"))
    dates = tg.of("message")[-1]
    assert dates["text"] == texts.PICK_DATE
    first = dates["reply_markup"]["inline_keyboard"][0][0]
    assert first == {"text": "Bugun, 7-yanvar", "callback_data": "fb:d:20300107"}

    feed(callback(501, f"fb:d:{TUESDAY:%Y%m%d}", message_id=88))
    times = tg.of("edit")[-1]
    assert times["message_id"] == 88 and "8-yanvar (seshanba)" in times["text"]
    rows = times["reply_markup"]["inline_keyboard"]
    assert rows[0][0] == {"text": "09:00", "callback_data": f"fb:t:{slot(TUESDAY, 9)}"}
    assert rows[-1] == [{"text": texts.BACK_BUTTON, "callback_data": "fb:back"}]

    feed(callback(501, f"fb:t:{slot(TUESDAY, 10)}", message_id=88))
    feed(callback(501, f"fb:t:{slot(TUESDAY, 10)}", message_id=88))   # double tap
    assert len([m for m in tg.of("message") if "yozildingiz" in m["text"]]) == 1
    (booking,) = db_all(database, InterviewBooking)
    assert booking.status == "scheduled"
    assert booking.starts_at.replace(tzinfo=timezone.utc) == datetime(
        2030, 1, 8, 10, tzinfo=TZ).astimezone(timezone.utc)
    confirm = tg.of("message")[-1]
    assert "8-yanvar (seshanba)" in confirm["text"] and "10:00" in confirm["text"]
    assert "Malika opa" in confirm["text"] and "Manzil" not in confirm["text"]   # empty line dropped
    assert confirm["reply_markup"]["inline_keyboard"][0][0]["callback_data"] == "fb:resched"
    assert tg.of("location")[-1] == {"chat_id": "501", "lat": 41.3, "lon": 69.2}
    assert "Suhbatga yozilish" in tg.of("alert")[-1]["text"]
    (lead,) = db_all(database, Lead)
    assert (lead.status, lead.stage, lead.lead_score) == ("trial", "booked", 90)
    assert booking.lead_id == lead.id

    feed(callback(501, "fb:start"))                          # already booked
    assert tg.of("message")[-1]["text"].startswith("Siz 8-yanvar (seshanba) soat 10:00")

    feed(callback(501, "fb:resched"))
    feed(callback(501, f"fb:t:{slot(TUESDAY, 11)}"))
    statuses = sorted((b.status, b.rescheduled) for b in db_all(database, InterviewBooking))
    assert statuses == [("cancelled", True), ("scheduled", False)]
    assert "o'zgardi" in tg.of("alert")[-1]["text"]

    feed(callback(501, "fb:cancel"))
    assert {b.status for b in db_all(database, InterviewBooking)} == {"cancelled"}
    assert tg.of("message")[-1]["text"] == texts.CANCELLED
    assert "bekor" in tg.of("alert")[-1]["text"]
    assert entry_of(database, 501).sheet_dirty is True


def test_full_slot_is_refused_with_fresh_times(database, booked_setup):
    tg = booked_setup
    complete_funnel(502)
    feed(callback(501, f"fb:t:{slot(TUESDAY, 10)}"))
    feed(callback(502, f"fb:t:{slot(TUESDAY, 10)}", message_id=99))
    assert len(db_all(database, InterviewBooking, InterviewBooking.status == "scheduled")) == 1
    refused = tg.of("edit")[-1]
    assert refused["text"].startswith(texts.SLOT_TAKEN)
    offered = [b["text"] for row in refused["reply_markup"]["inline_keyboard"] for b in row]
    assert "10:00" not in offered and "10:30" in offered


def test_past_or_invalid_slot_is_not_booked(database, booked_setup):
    feed(callback(501, f"fb:t:{slot(date(2030, 1, 7), 8, 30)}"))   # inside the lead time
    feed(callback(501, f"fb:t:{slot(date(2030, 1, 13), 10)}"))     # Sunday
    feed(callback(501, "fb:t:nonsense"))
    assert db_all(database, InterviewBooking) == []


def test_booking_button_without_entry_asks_to_start(database, fake_tg):
    feed(callback(999, "fb:start"))
    assert fake_tg.texts() == [texts.START_FIRST]
