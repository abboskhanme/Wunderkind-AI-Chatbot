"""Funnel management API and funnel_id scoping (SPEC §11.3)."""
from __future__ import annotations

import uuid
from datetime import datetime, timedelta, timezone

import pytest

from app.models.funnel import Funnel, FunnelEntry, FunnelFile, FunnelMessage, InterviewBooking
from tests.conftest import auth_headers, make_user
from tests.funnel_fakes import PDF_BYTES, db_add, db_all, fake_tg  # noqa: F401  (fixture)

ANY_ID = str(uuid.uuid4())


@pytest.fixture
def admin(client, database):
    make_user(database, "admin", "admin")
    return auth_headers(client, "admin")


@pytest.fixture
def operator(client, database):
    make_user(database, "opa", "operator")
    return auth_headers(client, "opa")


def default_id(database) -> str:
    (row,) = db_all(database, Funnel, Funnel.is_default.is_(True))
    return str(row.id)


def create(client, admin, **body) -> dict:
    r = client.post("/api/funnel/funnels", headers=admin,
                    json={"name": "Yozgi lager", "keywords": "lager", **body})
    assert r.status_code == 201, r.text
    return r.json()


# --------------------------------------------------------------------------- #
# RBAC
# --------------------------------------------------------------------------- #
ADMIN_ONLY = [
    ("post", "/api/funnel/funnels", {"name": "X", "keywords": "xyz"}),
    ("patch", f"/api/funnel/funnels/{ANY_ID}", {"name": "Y"}),
    ("delete", f"/api/funnel/funnels/{ANY_ID}", None),
    ("post", "/api/funnel/funnels/reorder", {"ids": []}),
]


@pytest.mark.parametrize("method,path,body", ADMIN_ONLY + [("get", "/api/funnel/funnels", None)])
def test_funnel_endpoints_require_token(client, method, path, body):
    kwargs = {"json": body} if body is not None else {}
    assert getattr(client, method)(path, **kwargs).status_code == 401


@pytest.mark.parametrize("method,path,body", ADMIN_ONLY)
def test_operator_cannot_manage_funnels(client, operator, method, path, body):
    kwargs = {"headers": operator, **({"json": body} if body is not None else {})}
    assert getattr(client, method)(path, **kwargs).status_code == 403


def test_operator_can_list_funnels(client, operator, database):
    body = client.get("/api/funnel/funnels", headers=operator).json()
    assert [(f["name"], f["slug"], f["is_default"]) for f in body] == [
        ("Asosiy voronka", "asosiy", True)]


# --------------------------------------------------------------------------- #
# CRUD + validation
# --------------------------------------------------------------------------- #
def test_create_funnel_with_auto_slug_links_and_stats(client, admin, fake_tg):
    body = create(client, admin, name="Yozgi lager 2026", keywords="lager, Лагерь",
                  ig_media_ids="https://www.instagram.com/p/C8xYz12/, 17895695668004550",
                  texts={"FUNNEL_ASK_NAME": "Lager: ismingiz?", "FUNNEL_ASK_PHONE": ""})
    assert body["slug"] == "yozgi_lager_2026" and body["is_default"] is False
    assert body["keywords"] == "lager, Лагерь"
    assert body["ig_media_ids"] == "17895695668004550, C8xYz12"
    assert body["texts"] == {"FUNNEL_ASK_NAME": "Lager: ismingiz?"}          # empty dropped
    assert body["links"] == {"telegram_channel": "https://t.me/wk_bot?start=tgc_yozgi_lager_2026",
                             "telegram_direct": "https://t.me/wk_bot?start=f_yozgi_lager_2026"}
    assert body["stats"] == {"entries": 0, "pdf_sent": 0, "booked": 0} and body["has_pdf"] is False
    again = create(client, admin, name="Yozgi lager 2026", keywords="qish")
    assert again["slug"] == "yozgi_lager_2026_2"
    default = next(f for f in client.get("/api/funnel/funnels", headers=admin).json()
                   if f["is_default"])
    assert default["links"]["telegram_channel"] == "https://t.me/wk_bot?start=tgc"


@pytest.mark.parametrize("body,fragment", [
    ({"slug": "asosiy"}, "band"),
    ({"slug": "Bad Slug"}, None),                                  # 422 pattern
    ({"texts": {"FUNNEL_FOO": "x"}}, "Noma'lum"),
    ({"texts": {"FUNNEL_PDF_CAPTION": "x" * 1100}}, "1024"),
    ({"texts": {"FUNNEL_GRADES": "1," + "x" * 30}}, "20"),
    ({"keywords": "a, b"}, "3+"),
    ({"ig_media_ids": "salom dunyo!"}, "Instagram"),
    ({"keywords": "Wunderkind"}, "Asosiy voronka"),               # collides with the default
])
def test_create_funnel_validation(client, admin, body, fragment):
    r = client.post("/api/funnel/funnels", headers=admin,
                    json={"name": "Yangi", "keywords": "yangi", **body})
    if fragment is None:
        assert r.status_code == 422
    else:
        assert r.status_code == 400 and fragment in r.json()["detail"], r.text


def test_same_keyword_is_fine_on_other_posts_or_when_archived(client, admin):
    create(client, admin, name="Post", keywords="wunderkind", ig_media_ids="C8xYz12")
    create(client, admin, name="Arxiv", keywords="wunderkind", is_active=False)
    r = client.post("/api/funnel/funnels", headers=admin,
                    json={"name": "Post 2", "keywords": "wunderkind", "ig_media_ids": "C8xYz12"})
    assert r.status_code == 400                                     # same post scope


def test_patch_rules(client, admin, database):
    lager = create(client, admin, keywords="lager")
    r = client.patch(f"/api/funnel/funnels/{lager['id']}", headers=admin,
                     json={"name": "Lager 2", "texts": {"FUNNEL_BOOK_BUTTON": "🏕 Yozilish"},
                           "is_active": False})
    assert r.status_code == 200 and r.json()["texts"] == {"FUNNEL_BOOK_BUTTON": "🏕 Yozilish"}
    assert r.json()["is_active"] is False and r.json()["name"] == "Lager 2"
    # texts merge: set one key, clear another, keep the rest
    r = client.patch(f"/api/funnel/funnels/{lager['id']}", headers=admin,
                     json={"texts": {"FUNNEL_ASK_NAME": "Ism?"}})
    assert r.json()["texts"] == {"FUNNEL_BOOK_BUTTON": "🏕 Yozilish", "FUNNEL_ASK_NAME": "Ism?"}
    r = client.patch(f"/api/funnel/funnels/{lager['id']}", headers=admin,
                     json={"texts": {"FUNNEL_BOOK_BUTTON": ""}})
    assert r.json()["texts"] == {"FUNNEL_ASK_NAME": "Ism?"}
    r = client.patch(f"/api/funnel/funnels/{default_id(database)}", headers=admin,
                     json={"is_active": False})
    assert r.status_code == 400 and "Asosiy" in r.json()["detail"]
    # Re-activating a funnel whose keyword now collides is refused
    create(client, admin, name="Boshqa", keywords="lager")
    assert client.patch(f"/api/funnel/funnels/{lager['id']}", headers=admin,
                        json={"is_active": True}).status_code == 400
    assert client.patch(f"/api/funnel/funnels/{ANY_ID}", headers=admin,
                        json={"name": "x"}).status_code == 404


def test_delete_rules(client, admin, database):
    assert client.delete(f"/api/funnel/funnels/{default_id(database)}",
                         headers=admin).status_code == 400
    used = create(client, admin, keywords="lager")
    db_add(database, FunnelEntry(funnel_id=uuid.UUID(used["id"]), source="telegram_direct",
                                 start_token="tokUSED00001", step="ask_name"))
    r = client.delete(f"/api/funnel/funnels/{used['id']}", headers=admin)
    assert r.status_code == 409 and "arxivlang" in r.json()["detail"]
    empty = create(client, admin, name="Bo'sh", keywords="qish")
    client.post(f"/api/funnel/messages?funnel_id={empty['id']}", headers=admin,
                json={"text": "x", "delay_minutes": 1})
    client.put(f"/api/funnel/lead-magnet?funnel_id={empty['id']}", headers=admin,
               files={"file": ("a.pdf", PDF_BYTES, "application/pdf")})
    assert client.delete(f"/api/funnel/funnels/{empty['id']}", headers=admin).status_code == 204
    assert db_all(database, FunnelMessage, FunnelMessage.funnel_id == uuid.UUID(empty["id"])) == []
    assert db_all(database, FunnelFile, FunnelFile.funnel_id == uuid.UUID(empty["id"])) == []


def test_reorder_funnels(client, admin, database):
    a = create(client, admin, name="A", keywords="aaa")
    b = create(client, admin, name="B", keywords="bbb")
    order = client.post("/api/funnel/funnels/reorder", headers=admin,
                        json={"ids": [b["id"], a["id"], default_id(database)]}).json()
    assert [f["name"] for f in order] == ["B", "A", "Asosiy voronka"]


def test_copy_from_duplicates_texts_messages_and_pdf(client, admin, database):
    source = create(client, admin, name="Manba", keywords="manba",
                    texts={"FUNNEL_ASK_NAME": "Manba: ismingiz?"})
    client.post(f"/api/funnel/messages?funnel_id={source['id']}", headers=admin,
                json={"text": "Birinchi", "delay_minutes": 10})
    client.put(f"/api/funnel/lead-magnet?funnel_id={source['id']}", headers=admin,
               files={"file": ("manba.pdf", PDF_BYTES, "application/pdf")})
    copy = create(client, admin, name="Nusxa", keywords="nusxa", copy_from_id=source["id"],
                  texts={"FUNNEL_ASK_PHONE": "Raqam?"})
    assert copy["texts"] == {"FUNNEL_ASK_NAME": "Manba: ismingiz?", "FUNNEL_ASK_PHONE": "Raqam?"}
    assert copy["has_pdf"] is True
    msgs = client.get(f"/api/funnel/messages?funnel_id={copy['id']}", headers=admin).json()
    assert [(m["text"], m["funnel_id"]) for m in msgs] == [("Birinchi", copy["id"])]


# --------------------------------------------------------------------------- #
# funnel_id on the §10.4 endpoints
# --------------------------------------------------------------------------- #
def test_messages_and_lead_magnet_default_to_the_default_funnel(client, admin, database):
    lager = create(client, admin)
    client.post("/api/funnel/messages", headers=admin, json={"text": "Asosiy", "delay_minutes": 1})
    client.post(f"/api/funnel/messages?funnel_id={lager['id']}", headers=admin,
                json={"text": "Lager", "delay_minutes": 1})
    plain = client.get("/api/funnel/messages", headers=admin).json()
    assert [(m["text"], m["funnel_id"]) for m in plain] == [("Asosiy", default_id(database))]
    assert [m["text"] for m in client.get(f"/api/funnel/messages?funnel_id={lager['id']}",
                                          headers=admin).json()] == ["Lager"]

    client.put(f"/api/funnel/lead-magnet?funnel_id={lager['id']}", headers=admin,
               files={"file": ("lager.pdf", PDF_BYTES, "application/pdf")})
    assert client.get("/api/funnel/lead-magnet", headers=admin).json() is None
    meta = client.get(f"/api/funnel/lead-magnet?funnel_id={lager['id']}", headers=admin).json()
    assert meta["filename"] == "lager.pdf"
    token = admin["Authorization"].split()[1]
    assert client.get(f"/api/funnel/lead-magnet/download?funnel_id={lager['id']}&token={token}"
                      ).content == PDF_BYTES
    assert client.get(f"/api/funnel/messages?funnel_id={ANY_ID}", headers=admin).status_code == 404


def test_entries_bookings_and_stats_scope(client, operator, database):
    lager = db_add(database, Funnel(name="Yozgi lager", slug="yozgi", keywords="lager", texts={},
                                    sort_order=1))
    now = datetime.now(timezone.utc)
    a = FunnelEntry(source="telegram_direct", start_token="tokSCOPE0001", tg_user_id="1",
                    step="pdf_sent", pdf_sent_at=now, full_name="Asosiy odam")
    b = FunnelEntry(funnel_id=lager.id, source="telegram_direct", start_token="tokSCOPE0002",
                    tg_user_id="1", step="ask_name", full_name="Lager odam")
    db_add(database, a, b)
    db_add(database, InterviewBooking(entry_id=b.id, starts_at=now + timedelta(days=1),
                                      status="scheduled"))
    all_entries = client.get("/api/funnel/entries", headers=operator).json()
    assert all_entries["total"] == 2
    assert {i["funnel_name"] for i in all_entries["items"]} == {"Asosiy voronka", "Yozgi lager"}
    only = client.get(f"/api/funnel/entries?funnel_id={lager.id}", headers=operator).json()
    assert [i["full_name"] for i in only["items"]] == ["Lager odam"]
    assert only["items"][0]["booking"]["funnel_name"] == "Yozgi lager"

    bookings = client.get(f"/api/funnel/bookings?funnel_id={lager.id}", headers=operator).json()
    assert len(bookings) == 1 and bookings[0]["funnel_id"] == str(lager.id)
    assert client.get(f"/api/funnel/bookings?funnel_id={default_id(database)}",
                      headers=operator).json() == []

    stats = client.get(f"/api/funnel/stats?funnel_id={lager.id}", headers=operator).json()
    steps = {s["key"]: s["count"] for s in stats["steps"]}
    assert steps["comments"] == 1 and steps["booked"] == 1 and steps["pdf_sent"] == 0
    assert stats["bookings"]["scheduled"] == 1
    total = client.get("/api/funnel/stats", headers=operator).json()
    assert {s["key"]: s["count"] for s in total["steps"]}["comments"] == 2
    listed = {f["slug"]: f["stats"] for f in client.get("/api/funnel/funnels",
                                                          headers=operator).json()}
    assert listed == {"asosiy": {"entries": 1, "pdf_sent": 1, "booked": 0},
                      "yozgi": {"entries": 1, "pdf_sent": 0, "booked": 1}}
    assert client.get(f"/api/funnel/stats?funnel_id={ANY_ID}", headers=operator).status_code == 404


# --------------------------------------------------------------------------- #
# qa-review regressions (§11)
# --------------------------------------------------------------------------- #
def test_rename_resyncs_the_funnels_sheet_rows(client, admin, database):
    """Item 6: the Sheet shows the funnel name — a rename marks its rows dirty
    without touching the entries' updated_at."""
    lager = create(client, admin)
    fid = uuid.UUID(lager["id"])
    db_add(database, FunnelEntry(funnel_id=fid, source="telegram_direct", start_token="tokREN0001",
                                 step="ask_name", sheet_dirty=False))
    (before,) = db_all(database, FunnelEntry)
    client.patch(f"/api/funnel/funnels/{lager['id']}", headers=admin, json={"keywords": "lager2"})
    assert db_all(database, FunnelEntry)[0].sheet_dirty is False        # not a rename
    client.patch(f"/api/funnel/funnels/{lager['id']}", headers=admin, json={"name": "Lager 2027"})
    (after,) = db_all(database, FunnelEntry)
    assert after.sheet_dirty is True and after.updated_at == before.updated_at


def test_copy_with_empty_text_drops_the_copied_override(client, admin):
    """Item 9: copy_from + "" for a key → that key falls back to the global text."""
    source = create(client, admin, name="Manba", keywords="manba",
                    texts={"FUNNEL_ASK_NAME": "Manba: ismingiz?", "FUNNEL_ASK_PHONE": "Raqam?"})
    copy = create(client, admin, name="Nusxa", keywords="nusxa", copy_from_id=source["id"],
                  texts={"FUNNEL_ASK_NAME": ""})
    assert copy["texts"] == {"FUNNEL_ASK_PHONE": "Raqam?"}


def test_delete_race_with_a_new_entry_is_409(client, admin, database, monkeypatch):
    """Item 10: an entry created between the check and the delete → 409, not 500."""
    import asyncio

    from app.api import funnels as funnels_api

    lager = create(client, admin)
    db_add(database, FunnelEntry(funnel_id=uuid.UUID(lager["id"]), source="telegram_direct",
                                 start_token="tokRACE00001", step="ask_name"))

    async def enforce_foreign_keys():                 # SQLite: behave like PostgreSQL
        from sqlalchemy import text

        async with database() as s:
            if s.bind.dialect.name == "sqlite":
                await s.execute(text("PRAGMA foreign_keys=ON"))
    asyncio.run(enforce_foreign_keys())

    async def no_entries_yet(db, funnel_id):          # the check ran before the insert
        return False

    monkeypatch.setattr(funnels_api, "_has_entries", no_entries_yet)
    r = client.delete(f"/api/funnel/funnels/{lager['id']}", headers=admin)
    assert r.status_code == 409 and "arxivlang" in r.json()["detail"]
    assert db_all(database, Funnel, Funnel.id == uuid.UUID(lager["id"]))


def test_funnel_writes_invalidate_the_routing_cache(client, admin, database):
    """Item 8: a funnel saved in the panel routes comments immediately."""
    import asyncio

    from app.funnel import funnels

    asyncio.run(funnels.load_all())                   # warm the cache
    create(client, admin, name="Lager", keywords="lager")
    assert {f.slug for f in asyncio.run(funnels.load_all())} == {"asosiy", "lager"}
