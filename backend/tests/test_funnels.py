"""Multiple funnels (SPEC §11): routing by keyword and Instagram post, deep links
tgc_<slug> / f_<slug>, one person in two funnels, per-funnel texts / PDF / sales
messages, and the shared one-interview-per-person rule."""
from __future__ import annotations

import hashlib
from datetime import date, datetime, time, timedelta, timezone
from zoneinfo import ZoneInfo

import pytest

from app.config import settings
from app.funnel import funnels, instagram_gate, repo, sales, texts
from app.funnel.funnels import FunnelView, MediaFilter
from app.instagram.models import IncomingEvent
from app.models.funnel import (
    LEAD_MAGNET_KEY, Funnel, FunnelEntry, FunnelFile, FunnelMessage, InterviewBooking,
)
from tests.funnel_fakes import (  # noqa: F401  (fixtures)
    PDF_BYTES, add_pdf, callback, contact, db_add, db_all, fake_ig, fake_tg, feed,
    private_text, run,
)

TZ = ZoneInfo("Asia/Tashkent")
LAGER_PDF = b"%PDF-1.4 yozgi lager"


def add_funnel(database, **kw) -> Funnel:
    fields = dict(name="Yozgi lager", slug="yozgi", is_active=True, is_default=False,
                  keywords="lager", ig_media_ids="", texts={}, sort_order=1)
    return db_add(database, Funnel(**{**fields, **kw}))


def default_funnel(database) -> Funnel:
    (row,) = db_all(database, Funnel, Funnel.is_default.is_(True))
    return row


def add_pdf_for(database, funnel_id, data=LAGER_PDF, name="lager.pdf") -> None:
    db_add(database, FunnelFile(funnel_id=funnel_id, key=LEAD_MAGNET_KEY, filename=name,
                                content_type="application/pdf", size_bytes=len(data),
                                data=data, sha256=hashlib.sha256(data).hexdigest()))


def view(**kw) -> FunnelView:
    import uuid

    fields = dict(id=uuid.uuid4(), name="F", slug="f", is_active=True, is_default=False,
                  keywords_raw="", media_raw="", texts={}, sort_order=0)
    return FunnelView(**{**fields, **kw})


# --------------------------------------------------------------------------- #
# Routing units
# --------------------------------------------------------------------------- #
def test_media_filter_accepts_ids_links_and_shortcodes():
    media = funnels.parse_media("17895695668004550, https://www.instagram.com/p/C8xYz12/ "
                                "https://instagram.com/wunderkind/reel/DAbc_9-x/?igsh=1, C9abcde")
    assert media.ids == {"17895695668004550"}
    assert media.shortcodes == {"C8xYz12", "DAbc_9-x", "C9abcde"}
    assert funnels.normalize_media(" C9abcde ,17895695668004550") == "17895695668004550, C9abcde"
    with pytest.raises(ValueError):
        funnels.parse_media("salom dunyo!")


def test_comment_routing_by_keyword_and_post(monkeypatch):
    from app.instagram.client import instagram

    default = view(name="Asosiy", slug="asosiy", is_default=True)          # FUNNEL_KEYWORDS
    lager_any = view(name="Lager", slug="lager", keywords_raw="lager", sort_order=2)
    lager_post = view(name="Lager post", slug="lager_post", keywords_raw="wunderkind",
                      media_raw="C8xYz12", sort_order=5)
    calls: list[str] = []

    async def get_media(media_id):
        calls.append(media_id)
        return {"permalink": f"https://www.instagram.com/p/{'C8xYz12' if media_id == '1' else 'ZZZZZZ'}/"}

    monkeypatch.setattr(instagram, "get_media", get_media)
    all_funnels = [default, lager_any, lager_post]
    # Post filter first: "wunderkind" under the listed post goes to that funnel
    assert run(funnels.match_comment(all_funnels, "Wunderkind!", "1")) is lager_post
    assert run(funnels.match_comment(all_funnels, "Wunderkind!", "1")) is lager_post
    assert calls == ["1"]                                  # shortcode cached after one lookup
    # Other posts: the unfiltered default funnel
    assert run(funnels.match_comment(all_funnels, "Wunderkind!", "2")) is default
    assert run(funnels.match_comment(all_funnels, "lager haqida", "2")) is lager_any
    assert run(funnels.match_comment(all_funnels, "salom", "2")) is None
    # Inactive funnels never match
    off = view(name="Off", slug="off", keywords_raw="lager", is_active=False)
    assert run(funnels.match_comment([off], "lager", "2")) is None


def test_direct_routing_and_default_keyword_fallback(monkeypatch):
    monkeypatch.setattr(settings, "FUNNEL_KEYWORDS", "wunderkind")
    default = view(is_default=True)
    lager = view(slug="lager", keywords_raw="lager")
    assert default.keywords() == ["wunderkind"] and lager.keywords() == ["lager"]
    assert view(is_default=True, keywords_raw="maktab").keywords() == ["maktab"]
    assert view(keywords_raw="").keywords() == []           # deep-link-only funnel
    assert funnels.match_direct([default, lager], "lager", strict=True) is lager
    assert funnels.match_direct([default, lager], "lager narxi qancha?", strict=True) is None
    assert funnels.match_direct([default, lager], "lager narxi qancha?", strict=False) is lager


def test_keyword_collision_rules():
    a = view(slug="a", keywords_raw="wunderkind")
    assert funnels.keyword_collision(view(slug="b", keywords_raw="Вундеркинд"), [a])
    assert funnels.keyword_collision(view(slug="b", keywords_raw="wunderkind maktab"), [a])
    assert funnels.keyword_collision(view(slug="b", keywords_raw="lager"), [a]) is None
    # Different posts = different scope; inactive funnels never collide
    posted = view(slug="p", keywords_raw="wunderkind", media_raw="C8xYz12")
    assert funnels.keyword_collision(posted, [a]) is None
    assert funnels.keyword_collision(view(slug="q", keywords_raw="wunderkind",
                                          media_raw="C8xYz12"), [posted])
    assert funnels.keyword_collision(view(slug="b", keywords_raw="wunderkind",
                                          is_active=False), [a]) is None
    assert MediaFilter(frozenset({"1"})).overlaps(MediaFilter(frozenset({"1", "2"})))


def test_slugify():
    assert funnels.slugify("Yozgi lager 2026!") == "yozgi_lager_2026"
    assert funnels.slugify("Ёзги лагер") == "yozgi_lager"
    assert funnels.slugify("🔥🔥") == "voronka"
    assert len(funnels.slugify("x" * 80)) == 32


def test_per_funnel_text_override_and_fallback():
    f = view(texts={"FUNNEL_ASK_NAME": "Ismingizni yozing 😊", "FUNNEL_ASK_PHONE": "  ",
                    "NOT_WHITELISTED": "x"})
    assert f.text("FUNNEL_ASK_NAME") == "Ismingizni yozing 😊"
    assert f.text("FUNNEL_ASK_PHONE") == settings.FUNNEL_ASK_PHONE       # empty → global
    assert f.text("FUNNEL_ASK_GRADE") == settings.FUNNEL_ASK_GRADE
    assert view(texts={"FUNNEL_GRADES": "1,2,3"}).grade_options() == ["1", "2", "3"]


# --------------------------------------------------------------------------- #
# Instagram
# --------------------------------------------------------------------------- #
def comment(text, media="m1", igsid="u1"):
    return IncomingEvent(kind="comment", text=text, sender_id=igsid, username="mama",
                         comment_id=f"c-{text}-{media}-{igsid}", media_id=media)


def test_instagram_comment_goes_to_the_matching_funnel_with_its_texts(database, fake_ig,
                                                                       fake_tg):
    lager = add_funnel(database, ig_media_ids="1789000001",
                       texts={"FUNNEL_IG_DM_WELCOME": "Lager uchun obuna bo'ling!",
                              "FUNNEL_IG_COMMENT_REPLY": "Lager: Direct'ni tekshiring"})
    assert run(instagram_gate.handle_event(comment("lager", media="1789000001"))) is True
    assert fake_ig.of("quick")[-1]["text"] == "Lager uchun obuna bo'ling!"
    assert fake_ig.of("public")[-1]["text"] == "Lager: Direct'ni tekshiring"
    assert run(instagram_gate.handle_event(comment("lager", media="999"))) is False   # other post
    assert run(instagram_gate.handle_event(comment("wunderkind", media="999"))) is True
    assert fake_ig.of("quick")[-1]["text"] == settings.FUNNEL_IG_DM_WELCOME         # global text
    by_funnel = {e.funnel_id: e for e in db_all(database, FunnelEntry)}
    assert set(by_funnel) == {lager.id, default_funnel(database).id}    # same person, 2 funnels


def test_inactive_funnel_takes_no_new_instagram_entries(database, fake_ig, fake_tg):
    add_funnel(database, is_active=False)
    assert run(instagram_gate.handle_event(comment("lager"))) is False
    assert db_all(database, FunnelEntry) == []


# --------------------------------------------------------------------------- #
# Telegram deep links, two funnels per person
# --------------------------------------------------------------------------- #
def entries_of(database, tg: int) -> dict:
    return {e.funnel_id: e for e in db_all(database, FunnelEntry,
                                          FunnelEntry.tg_user_id == str(tg))}


def test_channel_and_direct_deep_links(database, fake_tg):
    lager = add_funnel(database, texts={"FUNNEL_ASK_NAME": "Lager: ismingiz?"})
    feed(private_text(701, "/start tgc_yozgi"))
    (entry,) = entries_of(database, 701).values()
    assert entry.funnel_id == lager.id and entry.source == "telegram_channel"
    assert fake_tg.texts()[-1] == "Lager: ismingiz?"                     # override
    feed(private_text(702, "/start f_yozgi"))
    assert entries_of(database, 702)[lager.id].source == "telegram_direct"
    feed(private_text(703, "/start tgc"))
    assert entries_of(database, 703)[default_funnel(database).id].source == "telegram_channel"
    assert fake_tg.texts()[-1] == settings.FUNNEL_ASK_NAME                # global text
    feed(private_text(704, "/start f_nomalum"))                           # unknown slug
    assert entries_of(database, 704)[default_funnel(database).id].source == "telegram_direct"


def test_inactive_funnel_link_only_resumes(database, fake_tg, monkeypatch):
    from app.telegram_business import menu as tg_menu

    handled: list[str] = []

    async def fake_action(event, action):
        handled.append(event.text)

    monkeypatch.setattr(tg_menu, "handle_action", fake_action)
    lager = add_funnel(database)
    feed(private_text(705, "/start f_yozgi"))                             # in-flight entry
    add_funnel(database, name="Qishki", slug="qishki", keywords="qish", is_active=False)
    feed(private_text(706, "/start f_qishki"))                            # new person: no entry
    assert entries_of(database, 706) == {}

    async def deactivate():
        from app.db import session as db_session

        async with db_session.SessionLocal() as db:
            (await db.get(Funnel, lager.id)).is_active = False
            await db.commit()
    run(deactivate())
    feed(private_text(705, "/start f_yozgi"))                             # in-flight finishes
    assert fake_tg.texts()[-1] == settings.FUNNEL_ASK_NAME
    feed(private_text(705, "Aliyeva Malika"))
    assert entries_of(database, 705)[lager.id].full_name == "Aliyeva Malika"


def complete(user: int, start: str) -> None:
    feed(private_text(user, start))
    feed(private_text(user, "Aliyeva Malika"))
    feed(contact(user, "998901234567"))
    feed(callback(user, "fb:g:5"))


def test_person_in_two_funnels_gets_each_pdf_without_retyping(database, fake_tg):
    lager = add_funnel(database, texts={"FUNNEL_PDF_CAPTION": "Lager qo'llanmasi 🎁"})
    add_pdf(database)                                     # default funnel's PDF
    add_pdf_for(database, lager.id)
    complete(710, "/start")
    feed(private_text(710, "/start f_yozgi"))
    lager_entry = entries_of(database, 710)[lager.id]
    assert (lager_entry.full_name, lager_entry.phone) == ("Aliyeva Malika", "+998901234567")
    assert lager_entry.step == "ask_grade"                # only the grade is asked again
    feed(callback(710, "fb:g:7"))
    first, second = fake_tg.of("document")
    assert first["document"][0] == PDF_BYTES and first["caption"] == settings.FUNNEL_PDF_CAPTION
    assert second["document"][0] == LAGER_PDF and second["caption"] == "Lager qo'llanmasi 🎁"
    both = entries_of(database, 710)
    assert {e.step for e in both.values()} == {"pdf_sent"} and len(both) == 2


def test_missing_pdf_is_per_funnel(database, fake_tg):
    add_funnel(database)
    add_pdf(database)                                     # only the default funnel has one
    complete(711, "/start f_yozgi")
    assert fake_tg.of("document") == [] and fake_tg.texts()[-1] == texts.PDF_PENDING
    assert "Yozgi lager" in fake_tg.of("alert")[-1]["text"]


def test_collection_answers_go_to_the_current_funnel(database, fake_tg):
    lager = add_funnel(database, texts={"FUNNEL_GRADES": "1-sinf,2-sinf,3-sinf"})
    feed(private_text(712, "/start"))
    feed(private_text(712, "/start f_yozgi"))             # the newer one is current
    feed(private_text(712, "Karimov Jasur"))
    both = entries_of(database, 712)
    assert both[lager.id].full_name == "Karimov Jasur"
    assert both[default_funnel(database).id].full_name is None
    feed(contact(712, "+998935554433"))
    grades = [b["callback_data"] for row in fake_tg.of("message")[-1]["reply_markup"]
              ["inline_keyboard"] for b in row]
    assert grades == ["fb:g:1-sinf", "fb:g:2-sinf", "fb:g:3-sinf"]      # funnel's own list


def test_group_comment_links_to_the_funnel(database, fake_tg):
    add_funnel(database, texts={"FUNNEL_TG_COMMENT_REPLY": "Lager qo'llanmasi 👇"})
    feed({"update_id": 1, "message": {
        "message_id": 9, "text": "lager", "from": {"id": 720, "is_bot": False},
        "chat": {"id": -100555, "type": "supergroup"}}})
    reply = fake_tg.of("message")[-1]
    assert reply["text"] == "Lager qo'llanmasi 👇"
    assert reply["reply_markup"]["inline_keyboard"][0][0]["url"] == \
        "https://t.me/wk_bot?start=tgc_yozgi"


# --------------------------------------------------------------------------- #
# qa-review regressions (§11)
# --------------------------------------------------------------------------- #
def test_bare_start_resumes_the_persons_own_funnel(database, fake_tg):
    """Item 2: someone who came through funnel B presses /start → B's PDF again,
    no entry in the default funnel; only newcomers get the default funnel."""
    lager = add_funnel(database)
    add_pdf_for(database, lager.id)
    complete(750, "/start f_yozgi")
    feed(private_text(750, "/start"))
    assert set(entries_of(database, 750)) == {lager.id}
    assert [d["document"] for d in fake_tg.of("document")][-1] == "FILE-1"   # lager's PDF
    feed(private_text(751, "/start"))
    assert set(entries_of(database, 751)) == {default_funnel(database).id}


def test_start_after_stop_keeps_the_started_entry_current(database, fake_tg):
    """Item 3: re-enabling the other entries must not make them "current"."""
    lager = add_funnel(database)
    feed(private_text(752, "/start"))                     # default: ask_name
    feed(private_text(752, "/start f_yozgi"))             # lager: ask_name (current)
    feed(private_text(752, "/stop"))
    feed(private_text(752, "/start tgc"))                 # back to the default funnel
    feed(private_text(752, "Aliyeva Malika"))
    both = entries_of(database, 752)
    assert both[default_funnel(database).id].full_name == "Aliyeva Malika"
    assert both[lager.id].full_name is None
    assert not any(e.opted_out for e in both.values())


def test_switched_off_channel_link_only_resumes_unfinished_questions(database, fake_tg,
                                                                    monkeypatch):
    """Item 4: FUNNEL_ENABLED off → /start tgc resumes questions, anything else is
    the menu greeting as before."""
    from app.telegram_business import menu as tg_menu
    from app.telegram_business.menu import Menu, MenuItem

    handled: list[str] = []

    async def fake_action(event, action):
        handled.append(event.text)

    monkeypatch.setattr(tg_menu, "_state", tg_menu._State(
        menu=Menu(items=(MenuItem(id="1", command="narxlar", title="💰 Narxlar"),))))
    monkeypatch.setattr(tg_menu, "handle_action", fake_action)
    add_pdf(database)
    complete(753, "/start tgc")                           # pdf_sent
    feed(private_text(754, "/start tgc"))                 # ask_name
    documents = len(fake_tg.of("document"))
    monkeypatch.setattr(settings, "FUNNEL_ENABLED", False)
    feed(private_text(753, "/start tgc"))
    assert handled == ["/start tgc"] and len(fake_tg.of("document")) == documents
    feed(private_text(754, "/start tgc"))
    assert handled == ["/start tgc"] and fake_tg.texts()[-1] == settings.FUNNEL_ASK_NAME


def test_follow_check_only_for_the_latest_instagram_entry(database, fake_ig, fake_tg):
    """Item 5: an older waiting entry must not swallow DMs after a newer funnel."""
    add_funnel(database)
    run(instagram_gate.handle_event(comment("wunderkind", media="1", igsid="u9")))   # waiting
    fake_ig.profile = {"is_user_follow_business": True}
    run(instagram_gate.handle_event(comment("lager", media="2", igsid="u9")))        # link sent
    dm = IncomingEvent(kind="dm", text="rahmat!", sender_id="u9", message_id="mid-u9")
    assert run(instagram_gate.handle_event(dm)) is False                           # → AI


def test_forwarded_link_of_an_archived_funnel_goes_to_default(database, fake_tg):
    """Item 7: an archived funnel takes no one new, even through a forwarded link."""
    lager = add_funnel(database, is_active=False)
    db_add(database, FunnelEntry(funnel_id=lager.id, source="instagram",
                                 start_token="tokARCHIVED01", ig_user_id="ig7",
                                 tg_user_id="760", step="pdf_sent"))
    feed(private_text(761, "/start tokARCHIVED01"))
    (entry,) = entries_of(database, 761).values()
    assert entry.funnel_id == default_funnel(database).id and entry.source == "telegram_direct"


def test_unknown_channel_slug_counts_as_the_channel(database, fake_tg):
    """Item 8: ?start=tgc_<old slug> → default funnel, source telegram_channel."""
    feed(private_text(762, "/start tgc_eski_nom"))
    (entry,) = entries_of(database, 762).values()
    assert entry.funnel_id == default_funnel(database).id
    assert entry.source == "telegram_channel"


def test_funnel_list_is_cached_until_invalidated(database, monkeypatch):
    """Item 8: webhooks read funnels from a short cache; writes invalidate it."""
    first = run(funnels.load_all())
    add_funnel(database)
    assert run(funnels.load_all()) == first               # cached (30 s)
    funnels.invalidate()
    assert {f.slug for f in run(funnels.load_all())} == {"asosiy", "yozgi"}


# --------------------------------------------------------------------------- #
# One interview per person; sales per funnel
# --------------------------------------------------------------------------- #
FIXED_NOW = datetime(2030, 1, 7, 8, 0, tzinfo=TZ).astimezone(timezone.utc)   # Monday 08:00


def slot(day: date, hh: int) -> str:
    return datetime.combine(day, time(hh), TZ).strftime("%Y%m%d%H%M")


def test_one_scheduled_interview_across_funnels(database, fake_tg, monkeypatch):
    monkeypatch.setattr(repo, "now", lambda: FIXED_NOW)
    add_funnel(database)
    add_pdf(database)
    complete(730, "/start")
    feed(callback(730, f"fb:t:{slot(date(2030, 1, 8), 10)}"))
    feed(private_text(730, "/start f_yozgi"))
    feed(callback(730, "fb:g:5"))                        # lager PDF pending (no PDF): fine
    feed(callback(730, "fb:start"))                       # button from the other funnel
    assert fake_tg.of("message")[-1]["text"].startswith("Siz 8-yanvar")
    feed(callback(730, f"fb:t:{slot(date(2030, 1, 9), 11)}"))
    bookings = db_all(database, InterviewBooking)
    assert sorted(b.status for b in bookings) == ["cancelled", "scheduled"]
    assert sum(b.status == "scheduled" for b in bookings) == 1
    assert "o'zgardi" in fake_tg.of("alert")[-1]["text"]


def pdf_entry(funnel_id, tg: str, sent_at: datetime) -> FunnelEntry:
    return FunnelEntry(funnel_id=funnel_id, source="telegram_direct",
                       start_token=f"tok{tg}{str(funnel_id)[:8]}",
                       tg_user_id=tg, tg_chat_id=tg, step="pdf_sent", full_name="Ali",
                       phone="+998901112233", grade="4", pdf_sent_at=sent_at, sheet_dirty=False)


def test_sales_sequences_run_per_funnel_and_stop_on_any_booking(database, fake_tg):
    noon = datetime(2030, 3, 5, 12, tzinfo=TZ).astimezone(timezone.utc)
    lager = add_funnel(database, texts={"FUNNEL_BOOK_BUTTON": "🏕 Lagerga yozilish"})
    default_id = default_funnel(database).id
    db_add(database, FunnelMessage(funnel_id=default_id, text="Maktab xabari", delay_minutes=0,
                                   sort_order=0, is_active=True),
           FunnelMessage(funnel_id=lager.id, text="Lager xabari", delay_minutes=0, sort_order=0,
                         is_active=True))
    a = pdf_entry(default_id, "740", noon - timedelta(minutes=5))
    b = pdf_entry(lager.id, "740", noon - timedelta(minutes=5))
    db_add(database, a, b)
    assert run(sales.run_sales(noon)) == 2
    sent = {m["text"]: m for m in fake_tg.of("message")}
    assert set(sent) == {"Maktab xabari", "Lager xabari"}
    assert sent["Lager xabari"]["reply_markup"]["inline_keyboard"][0][0]["text"] == \
        "🏕 Lagerga yozilish"
    assert sent["Maktab xabari"]["reply_markup"]["inline_keyboard"][0][0]["text"] == \
        settings.FUNNEL_BOOK_BUTTON

    db_add(database, FunnelMessage(funnel_id=lager.id, text="Lager 2", delay_minutes=0,
                                   sort_order=1, is_active=True))
    db_add(database, InterviewBooking(entry_id=a.id, starts_at=noon + timedelta(days=1),
                                      status="scheduled"))
    assert run(sales.run_sales(noon + timedelta(minutes=1))) == 0         # booked via A stops B


# --------------------------------------------------------------------------- #
# Migration (real PostgreSQL only: PG_MIGRATION_URL = a throwaway database)
# --------------------------------------------------------------------------- #
@pytest.mark.skipif(not __import__("os").environ.get("PG_MIGRATION_URL"),
                    reason="needs PG_MIGRATION_URL (throwaway PostgreSQL database)")
def test_migration_backfills_existing_rows_into_the_default_funnel():
    import os
    import subprocess
    import sys

    from pathlib import Path

    import app

    url = os.environ["PG_MIGRATION_URL"]
    env = {**os.environ, "DATABASE_URL": url}
    backend_dir = Path(app.__file__).resolve().parents[1]      # where alembic.ini lives

    def alembic(*args):
        subprocess.run([sys.executable, "-m", "alembic", *args], check=True, env=env,
                       capture_output=True, cwd=backend_dir)

    async def sql(statement: str, *, script: bool = False):
        import asyncpg

        conn = await asyncpg.connect(url.replace("postgresql+asyncpg", "postgresql"))
        try:
            return await (conn.execute(statement) if script else conn.fetch(statement))
        finally:
            await conn.close()

    alembic("downgrade", "base")                 # re-runnable on the same database
    alembic("upgrade", "087311873265")
    run(sql("""
        INSERT INTO funnel_entries (id, source, start_token, tg_user_id, step, follow_checks,
                                    opted_out, sheet_dirty, pdf_attempts)
        VALUES (gen_random_uuid(), 'telegram_direct', 'tokMIG000001', '1', 'pdf_sent', 0,
                false, false, 0);
        INSERT INTO funnel_files (key, filename, content_type, size_bytes, data, sha256,
                                  updated_at)
        VALUES ('lead_magnet', 'a.pdf', 'application/pdf', 4, '\\x25504446', 's', now());
    """, script=True))
    alembic("upgrade", "head")
    rows = run(sql("""
        SELECT (SELECT count(*) FROM funnels WHERE is_default) AS defaults,
               (SELECT count(*) FROM funnel_entries WHERE funnel_id =
                    (SELECT id FROM funnels WHERE is_default)) AS entries,
               (SELECT count(*) FROM funnel_messages WHERE funnel_id =
                    (SELECT id FROM funnels WHERE is_default)) AS messages,
               (SELECT count(*) FROM funnel_files WHERE funnel_id =
                    (SELECT id FROM funnels WHERE is_default)) AS files
    """))
    assert dict(rows[0]) == {"defaults": 1, "entries": 1, "messages": 3, "files": 1}
    alembic("downgrade", "087311873265")
    alembic("upgrade", "head")
