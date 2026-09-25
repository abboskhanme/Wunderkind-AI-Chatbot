"""Funnel on Instagram: keyword comments, the follow gate (true / false / error),
fallbacks, echo protection and routing past the AI pipeline."""
from __future__ import annotations

import pytest

from app.config import settings
from app.funnel import instagram_gate, texts
from app.instagram.models import IncomingEvent
from app.models.funnel import FunnelEntry
from app.state.store import store
from tests.funnel_fakes import db_all, fake_ig, fake_tg, run  # noqa: F401  (fixtures)

_n = iter(range(10**6))


def comment(igsid="u1", text="Wunderkind!", username="mama_ali") -> IncomingEvent:
    return IncomingEvent(kind="comment", text=text, sender_id=igsid, username=username,
                         comment_id=f"c{next(_n)}", media_id="m1")


def dm(igsid="u1", text="✅ Obuna bo'ldim") -> IncomingEvent:
    return IncomingEvent(kind="dm", text=text, sender_id=igsid, message_id=f"mid{next(_n)}")


def handle(event) -> bool:
    return run(instagram_gate.handle_event(event))


def entry(database, igsid="u1") -> FunnelEntry:
    (found,) = db_all(database, FunnelEntry, FunnelEntry.ig_user_id == igsid)
    return found


@pytest.fixture
def ig(fake_ig, fake_tg):
    return fake_ig


def test_comment_gets_public_reply_and_welcome_with_quick_reply(database, ig):
    event = comment()
    assert handle(event) is True
    (public,) = ig.of("public")
    variants = [v.strip() for v in settings.FUNNEL_IG_COMMENT_REPLY.split("|")]
    assert public["comment_id"] == event.comment_id
    assert public["text"] in variants
    assert all(v.startswith("Shaxsiydan javob berdik") for v in variants)
    (quick,) = ig.of("quick")
    assert quick["recipient"] == {"comment_id": event.comment_id}
    assert quick["text"] == settings.FUNNEL_IG_DM_WELCOME
    assert quick["quick_replies"] == [texts.FOLLOW_QUICK_REPLY]
    found = entry(database)
    assert (found.source, found.step, found.ig_username) == ("instagram", "ig_waiting_follow",
                                                             "mama_ali")
    assert len(found.start_token) == 12 and found.ig_comment_id == event.comment_id
    # Our own DM comes back as an echo — it must not look like an operator
    assert run(store.was_sent_by_bot("u1", settings.FUNNEL_IG_DM_WELCOME))


def test_non_keyword_comment_and_duplicate_webhook(database, ig):
    assert handle(comment(text="Narxi qancha?")) is False       # -> AI pipeline
    event = comment()
    assert handle(event) is True and handle(event) is True      # Meta retried
    assert len(ig.of("quick")) == 1


def test_follow_true_sends_link_button(database, ig):
    handle(comment())
    ig.profile = {"username": "mama_ali", "is_user_follow_business": True}
    assert handle(dm()) is True
    (template,) = ig.of("template")
    token = entry(database).start_token
    assert template["recipient"] == {"id": "u1"}
    assert template["buttons"] == [{"type": "web_url", "title": texts.LINK_BUTTON,
                                    "url": f"https://t.me/wk_bot?start={token}"}]
    found = entry(database)
    assert found.step == "ig_link_sent" and found.link_sent_at and found.followed_at
    assert found.follow_checks == 1


def test_follow_false_asks_again_then_gives_link_after_5_checks(database, ig):
    handle(comment())
    ig.profile = {"is_user_follow_business": False}
    for _ in range(4):
        handle(dm(text="tayyor"))
    assert [q["text"] for q in ig.of("quick")[1:]] == [settings.FUNNEL_IG_NOT_FOLLOWING] * 4
    assert entry(database).step == "ig_waiting_follow"
    handle(dm(text="tayyor"))                                  # 5th check: no dead end
    assert len(ig.of("template")) == 1
    found = entry(database)
    assert found.step == "ig_link_sent" and found.follow_checks == 5
    assert found.followed_at is None


def test_follow_check_error_fail_open_and_closed(database, ig, monkeypatch):
    handle(comment(igsid="u2"))
    ig.profile = None                                          # API error / field missing
    handle(dm(igsid="u2"))
    assert len(ig.of("template")) == 1 and entry(database, "u2").step == "ig_link_sent"

    monkeypatch.setattr(settings, "FUNNEL_IG_FOLLOW_FAIL_OPEN", False)
    handle(comment(igsid="u3"))
    handle(dm(igsid="u3"))
    assert ig.of("quick")[-1]["text"] == texts.IG_TRY_LATER
    assert entry(database, "u3").step == "ig_waiting_follow"


def test_comment_from_follower_gets_link_directly(database, ig):
    ig.profile = {"is_user_follow_business": True}
    handle(comment())
    assert ig.of("quick") == []
    (template,) = ig.of("template")
    assert "comment_id" in template["recipient"]
    assert entry(database).step == "ig_link_sent"


def test_follow_not_required_skips_the_gate(database, ig, monkeypatch):
    monkeypatch.setattr(settings, "FUNNEL_IG_REQUIRE_FOLLOW", False)
    handle(comment())
    assert ig.of("profile") == [] and len(ig.of("template")) == 1


def test_rejected_quick_reply_and_template_fall_back_to_plain_text(database, ig):
    ig.results["quick"] = {"sent": False, "error": "unsupported"}
    ig.results["template"] = {"sent": False, "error": "unsupported"}
    handle(comment())
    assert ig.of("send")[0]["message"] == {"text": settings.FUNNEL_IG_DM_WELCOME}
    ig.profile = {"is_user_follow_business": True}
    handle(dm())
    plain = ig.of("send")[-1]["message"]["text"]
    assert plain.startswith(settings.FUNNEL_IG_LINK_MESSAGE.strip())
    assert f"https://t.me/wk_bot?start={entry(database).start_token}" in plain


def test_keyword_dm_without_entry_starts_the_flow(database, ig):
    ig.profile = {"is_user_follow_business": False}
    assert handle(dm(igsid="u4", text="wunderkind")) is True
    assert ig.of("quick")[0]["text"] == settings.FUNNEL_IG_DM_WELCOME
    assert entry(database, "u4").step == "ig_waiting_follow"


def test_other_dms_go_to_the_ai(database, ig):
    assert handle(dm(igsid="u5", text="Salom, narxlar?")) is False
    ig.profile = {"is_user_follow_business": True}
    handle(comment(igsid="u6"))                                 # link sent at once
    assert handle(dm(igsid="u6", text="rahmat")) is False       # free text after the link
    assert handle(dm(igsid="u6", text="wunderkind")) is True    # asked again -> link again
    assert len(ig.of("template")) == 2


def test_second_comment_reuses_entry_and_sends_new_private_reply(database, ig):
    handle(comment())
    handle(comment())
    assert len(db_all(database, FunnelEntry)) == 1
    assert len(ig.of("quick")) == 2


def test_webhook_routes_funnel_before_ai(monkeypatch, ig):
    from app.instagram import webhook

    to_ai: list[str] = []

    async def fake_process(event, **kwargs):
        to_ai.append(event.text)

    monkeypatch.setattr(webhook, "process_event", fake_process)
    run(webhook._route(comment()))
    run(webhook._route(comment(text="Qancha turadi?")))
    assert to_ai == ["Qancha turadi?"]


def test_no_bot_configured_does_not_crash(database, ig, monkeypatch):
    from app.services import agent_status

    monkeypatch.setattr(settings, "TG_SALES_BOT_TOKEN", "")
    agent_status._bot_cache.clear()
    ig.profile = {"is_user_follow_business": True}
    handle(comment())
    assert ig.of("send")[-1]["message"]["text"] == texts.IG_LINK_UNAVAILABLE
    assert entry(database).step == "ig_waiting_follow"         # retried on the next DM


# --------------------------------------------------------------------------- #
# qa-review regressions
# --------------------------------------------------------------------------- #
@pytest.mark.parametrize("text,claimed", [
    ("Wunderkind", True), ("wunderkind yuboring 🙏", True), ("Вундеркинд пожалуйста", True),
    ("Wunderkind maktabida narxlar qancha?", False), ("wunderkind?", False),
    ("Menga Wunderkind maktabi haqida batafsil aytib bering", False),
])
def test_dm_starts_funnel_only_when_it_is_just_the_keyword(database, ig, text, claimed):
    """IMPORTANT 6: a DM question mentioning the keyword belongs to the AI."""
    ig.profile = {"is_user_follow_business": False}
    assert handle(dm(igsid="u7", text=text)) is claimed
    assert len(db_all(database, FunnelEntry)) == int(claimed)


def test_comments_stay_broad(database, ig):
    assert handle(comment(text="Wunderkind maktabida narxlar qancha?")) is True


def test_paused_chat_is_left_to_the_operator(database, ig):
    """IMPORTANT 7: operator paused the bot in this chat → the funnel stays out."""
    handle(comment(igsid="u8"))
    run(store.pause("u8", 12))
    assert handle(dm(igsid="u8", text="tayyor")) is False
    assert handle(dm(igsid="u9", text="wunderkind")) is True        # others unaffected
    run(store.pause("u9", 12))
    assert handle(dm(igsid="u9", text="wunderkind")) is False


def test_funnel_dms_are_logged_but_comments_are_not(database, ig):
    """IMPORTANT 7: people who DM us appear in Suhbatlar; commenters alone do not."""
    from app.models.lead import Lead, LeadMessage

    handle(comment(igsid="u10"))
    assert db_all(database, Lead) == []
    handle(dm(igsid="u10", text="✅ Obuna bo'ldim"))
    (lead,) = db_all(database, Lead)
    assert (lead.channel, lead.external_id) == ("instagram", "u10")
    (msg,) = db_all(database, LeadMessage)
    assert (msg.role, msg.kind, msg.text) == ("user", "dm", "✅ Obuna bo'ldim")
