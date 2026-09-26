"""Forms («Formalar», SPEC §15): admin API, the public page (validation,
anti-spam, utm), submission → lead mapping and the Leadlar source filter."""
from __future__ import annotations

import re
import time
import uuid

import pytest

from app.forms import public
from app.models.form import Form, FormSubmission
from app.models.lead import Lead, LeadMessage
from tests.conftest import auth_headers, make_user
from tests.funnel_fakes import db_all


@pytest.fixture
def admin(client, database):
    make_user(database, "admin", "admin")
    return auth_headers(client, "admin")


@pytest.fixture
def operator(client, database):
    make_user(database, "opa", "operator")
    return auth_headers(client, "opa")


@pytest.fixture
def alerts(monkeypatch):
    from app.telegram import notifier

    sent: list[str] = []

    async def send_text(text):
        sent.append(text)
        return {"sent": True}

    monkeypatch.setattr(notifier, "send_text", send_text)
    return sent


FIELDS = [
    {"id": "name", "type": "short_text", "label": "Ism-familiya", "required": True,
     "lead_field": "name"},
    {"id": "tel", "type": "phone", "label": "Telefon", "required": True, "lead_field": "phone"},
    {"id": "grade", "type": "dropdown", "label": "Sinf", "options": ["1-sinf", "2-sinf"],
     "lead_field": "student_age"},
    {"id": "days", "type": "multiple_choice", "label": "Qaysi kunlar",
     "options": ["Dushanba", "Chorshanba"]},
    {"id": "note", "type": "long_text", "label": "Izoh"},
]


def create(client, admin, **body) -> dict:
    r = client.post("/api/forms", json={"title": "Yozgi lager 2026", "fields": FIELDS, **body},
                    headers=admin)
    assert r.status_code == 201, r.text
    return r.json()


_ages = iter(range(10, 10**6))


def token(form: dict, age: int | None = None) -> str:
    """A fresh render token (each one submits once)."""
    return public.make_token(form["id"], int(time.time()) - (age or next(_ages) % 3000 + 10))


def fill(client, form: dict, *, age: int | None = None, **answers) -> object:
    data = {"_t": token(form, age), "q_name": "Ali Valiyev", "q_tel": "90 123 45 67",
            "q_grade": "2-sinf", "q_days": ["Dushanba", "Chorshanba"], "q_note": "=cmd",
            **answers}
    return client.post(f"/f/{form['slug']}", data=data, follow_redirects=False)


# --------------------------------------------------------------------------- #
# Admin API
# --------------------------------------------------------------------------- #
def test_rbac(client, admin, operator):
    form = create(client, admin)
    assert client.get("/api/forms").status_code == 401
    assert client.get("/api/forms", headers=operator).status_code == 200
    assert client.get(f"/api/forms/{form['id']}/submissions", headers=operator).status_code == 200
    assert client.post("/api/forms", json={"title": "x"}, headers=operator).status_code == 403
    assert client.patch(f"/api/forms/{form['id']}", json={"title": "y"},
                        headers=operator).status_code == 403
    assert client.delete(f"/api/forms/{form['id']}", headers=operator).status_code == 403
    assert client.get("/api/leads/sources").status_code == 401


def test_create_defaults_slug_and_field_rules(client, admin):
    plain = client.post("/api/forms", json={"title": "Qabul 2027"}, headers=admin).json()
    assert plain["slug"] == "qabul-2027" and plain["url"] == "/f/qabul-2027"
    assert [(f["label"], f["lead_field"]) for f in plain["fields"]] == [
        ("Ism-familiya", "name"), ("Telefon raqam", "phone")]
    again = client.post("/api/forms", json={"title": "Qabul 2027"}, headers=admin).json()
    assert again["slug"] == "qabul-2027-2"
    taken = client.post("/api/forms", json={"title": "x", "slug": "qabul-2027"}, headers=admin)
    assert taken.status_code == 400 and "band" in taken.json()["detail"]
    assert client.post("/api/forms", json={"title": "x", "slug": "Bad Slug"},
                       headers=admin).status_code == 422

    def bad(fields):
        r = client.patch(f"/api/forms/{plain['id']}", json={"fields": fields}, headers=admin)
        assert r.status_code == 400, r.text
        return r.json()["detail"]

    assert "variant" in bad([{"type": "dropdown", "label": "Sinf"}])
    assert "boshqa savolga" in bad([{"type": "short_text", "label": "A", "lead_field": "name"},
                                    {"type": "short_text", "label": "B", "lead_field": "name"}])
    assert "turi" in bad([{"type": "video", "label": "A"}])
    assert "savol matnini" in bad([{"type": "short_text", "label": " "}])
    assert "kamida bitta savol" in bad([])


# --------------------------------------------------------------------------- #
# Public page
# --------------------------------------------------------------------------- #
def test_page_renders_and_hides_inactive(client, admin):
    form = create(client, admin, description="Bepul dars")
    page = client.get(f"/f/{form['slug']}?utm_source=instagram&x=1")
    assert page.status_code == 200
    html = page.text
    assert "Yozgi lager 2026" in html and "Bepul dars" in html
    assert 'name="q_tel"' in html and 'type="tel"' in html
    assert 'name="utm_source" value="instagram"' in html and 'name="x"' not in html
    assert 'name="_t"' in html and 'name="website"' in html
    assert "<script" not in html and "/privacy" in html
    assert client.get("/f/yoq-forma").status_code == 404
    client.patch(f"/api/forms/{form['id']}", json={"is_active": False}, headers=admin)
    assert client.get(f"/f/{form['slug']}").status_code == 404


def test_submission_creates_lead_log_and_alert(client, admin, database, alerts):
    form = create(client, admin)
    page = client.get(f"/f/{form['slug']}?utm_campaign=yoz")
    utm = re.search(r'name="utm_campaign" value="([^"]+)"', page.text).group(1)
    r = fill(client, form, utm_campaign=utm)
    assert r.status_code == 303 and r.headers["location"] == f"/f/{form['slug']}?sent=1"
    assert "qabul qilindi" in client.get(r.headers["location"]).text

    (lead,) = db_all(database, Lead)
    assert (lead.channel, lead.source, str(lead.form_id)) == ("form", "form", form["id"])
    assert (lead.name, lead.contact, lead.student_age) == ("Ali Valiyev", "+998901234567",
                                                           "2-sinf")
    (sub,) = db_all(database, FormSubmission)
    assert sub.lead_id == lead.id and sub.utm == {"utm_campaign": "yoz"}
    assert {a["field_id"]: a["value"] for a in sub.answers}["days"] == ["Dushanba", "Chorshanba"]
    (log,) = db_all(database, LeadMessage)
    assert log.kind == "status" and "Forma to'ldirildi: «Yozgi lager 2026»" in log.text
    assert "Qaysi kunlar: Dushanba, Chorshanba" in log.text
    assert len(alerts) == 1 and "Ali Valiyev" in alerts[0] and "utm_campaign=yoz" in alerts[0]


def test_validation_errors_rerender_with_values(client, admin, database):
    form = create(client, admin)
    r = fill(client, form, q_name="", q_tel="123", q_grade="9-sinf", q_note="x" * 5001)
    assert r.status_code == 400
    assert "Bu savolga javob bering" in r.text and "Telefon raqamni to" in r.text
    assert "Ro&#x27;yxatdagi variantlardan" in r.text and "5000 belgidan" in r.text
    assert 'value="123"' in r.text                    # what they typed is kept
    assert db_all(database, Lead) == [] and db_all(database, FormSubmission) == []


def test_same_form_same_phone_updates_other_form_creates(client, admin, database):
    first = create(client, admin)
    second = create(client, admin, title="Qabul")
    assert fill(client, first, q_grade="").status_code == 303
    assert fill(client, first, q_name="Boshqa odam", q_tel="+998 90 123-45-67").status_code == 303
    assert len(db_all(database, Lead)) == 1 and len(db_all(database, FormSubmission)) == 2
    lead = db_all(database, Lead)[0]
    # Knowing the phone is not enough to rename someone's lead; empty columns fill
    assert (lead.name, lead.student_age) == ("Ali Valiyev", "2-sinf")
    assert fill(client, second).status_code == 303
    leads = db_all(database, Lead)
    assert len(leads) == 2 and {str(l.form_id) for l in leads} == {first["id"], second["id"]}


def test_honeypot_token_and_rate_limit(client, admin, database, alerts):
    form = create(client, admin)
    r = fill(client, form, website="http://spam")
    assert r.status_code == 303 and db_all(database, FormSubmission) == []
    fast = fill(client, form, age=-1)
    assert fast.status_code == 400 and "qayta yuboring" in fast.text
    forged = fill(client, form, _t="99.abc")
    assert forged.status_code == 400
    old = fill(client, form, age=2 * 24 * 3600)
    assert old.status_code == 400 and "eskirgan" in old.text
    assert db_all(database, FormSubmission) == []
    for _ in range(public.RATE_LIMIT):
        assert fill(client, form).status_code == 303
    assert fill(client, form).status_code == 429
    assert len(db_all(database, FormSubmission)) == public.RATE_LIMIT


# --------------------------------------------------------------------------- #
# Submissions, leads filter, delete
# --------------------------------------------------------------------------- #
def test_submissions_csv_leads_filter_and_reply(client, admin, operator, alerts):
    form = create(client, admin)
    other = create(client, admin, title="Boshqa")
    fill(client, form)
    fill(client, other, q_tel="+998 91 000 00 00")

    subs = client.get(f"/api/forms/{form['id']}/submissions", headers=operator).json()
    assert subs["total"] == 1 and subs["items"][0]["lead_name"] == "Ali Valiyev"
    csv_text = client.get(f"/api/forms/{form['id']}/submissions.csv", headers=admin).text
    header, row = csv_text.lstrip("﻿").strip().splitlines()
    assert header.startswith("Sana,Ism-familiya,Telefon,Sinf,Qaysi kunlar,Izoh")
    assert "'=cmd" in row and "+998901234567" in row

    listed = client.get(f"/api/leads?source=form:{form['id']}", headers=operator).json()
    assert listed["total"] == 1 and listed["items"][0]["form_name"] == "Yozgi lager 2026"
    assert client.get("/api/leads?channel=form", headers=operator).json()["total"] == 2
    assert client.get("/api/leads?source=form:nonsense", headers=operator).status_code == 400
    sources = client.get("/api/leads/sources", headers=operator).json()
    assert {"value": f"form:{form['id']}", "label": "Forma: Yozgi lager 2026", "count": 1} \
        in sources
    lead_id = listed["items"][0]["id"]
    detail = client.get(f"/api/leads/{lead_id}", headers=operator).json()
    assert detail["form_name"] == "Yozgi lager 2026"
    reply = client.post(f"/api/leads/{lead_id}/reply", json={"text": "Salom"},
                        headers=operator).json()
    assert reply["sent"] is False and "telefon" in reply["error"]
    export = client.get(f"/api/leads/export.csv?source=form:{form['id']}", headers=admin).text
    assert "Forma: Yozgi lager 2026" in export and "+998910000000" not in export


def test_delete_rules(client, admin, database, alerts):
    empty = create(client, admin, title="Bo'sh")
    used = create(client, admin, title="Ishlatilgan")
    fill(client, used)
    assert client.delete(f"/api/forms/{used['id']}", headers=admin).status_code == 409
    assert client.delete(f"/api/forms/{empty['id']}", headers=admin).status_code == 204
    assert client.get(f"/api/forms/{empty['id']}", headers=admin).status_code == 404
    assert [f.title for f in db_all(database, Form)] == ["Ishlatilgan"]
    assert client.get(f"/api/forms/{uuid.uuid4()}", headers=admin).status_code == 404


def test_token_is_single_use_and_ipv6_shares_a_bucket(client, admin, database, alerts):
    form = create(client, admin)
    one = token(form)
    assert fill(client, form, _t=one).status_code == 303
    replay = fill(client, form, _t=one)
    assert replay.status_code == 400 and "eskirgan" in replay.text
    assert len(db_all(database, FormSubmission)) == 1
    codes = [client.post(f"/f/{form['slug']}", follow_redirects=False,
                         headers={"CF-Connecting-IP": f"2001:db8:1:2::{n + 1}"},
                         data={"_t": token(form), "q_name": "Ali", "q_tel": f"90 000 00 0{n}"}
                         ).status_code
             for n in range(public.RATE_LIMIT + 1)]
    # Different addresses of one IPv6 /64 share one bucket
    assert codes == [303] * public.RATE_LIMIT + [429]


def test_control_characters_and_huge_bodies(client, admin, database, alerts):
    form = create(client, admin)
    assert fill(client, form, q_note="a\x00b", utm_source="ig\x00").status_code == 303
    (sub,) = db_all(database, FormSubmission)
    assert {a["field_id"]: a["value"] for a in sub.answers}["note"] == "ab"
    assert sub.utm == {"utm_source": "ig"}
    big = client.post(f"/f/{form['slug']}", content=b"q_note=" + b"x" * (public.MAX_BODY + 1),
                      headers={"Content-Type": "application/x-www-form-urlencoded"},
                      follow_redirects=False)
    assert big.status_code == 413
    many = "&".join(f"f{i}=1" for i in range(public.MAX_FIELDS_IN_BODY + 5))
    assert client.post(f"/f/{form['slug']}", content=many.encode(), follow_redirects=False,
                       headers={"Content-Type": "application/x-www-form-urlencoded"}
                       ).status_code == 400
    assert fill(client, form, _t="\u00b2.x").status_code == 400
    assert fill(client, form, _t="9" * 5000 + ".abc").status_code == 400


def test_alerts_are_throttled_per_form(client, admin, database, alerts, monkeypatch):
    monkeypatch.setattr(public, "ALERTS_PER_MINUTE", 2)
    monkeypatch.setattr(public, "RATE_LIMIT", 100)
    form = create(client, admin)
    for n in range(4):
        assert fill(client, form, q_tel=f"90 000 00 0{n}").status_code == 303
    assert len(db_all(database, FormSubmission)) == 4 and len(alerts) == 2


def test_deleting_lead_or_answer_removes_the_personal_data(client, admin, database, alerts):
    form = create(client, admin)
    fill(client, form)
    fill(client, form, q_tel="90 555 55 55")
    first, second = sorted(db_all(database, FormSubmission), key=lambda s: s.created_at)
    assert client.delete(f"/api/leads/{first.lead_id}", headers=admin).status_code == 204
    assert [s.id for s in db_all(database, FormSubmission)] == [second.id]
    url = f"/api/forms/{form['id']}/submissions/{second.id}"
    assert client.delete(url, headers=admin).status_code == 204
    assert db_all(database, FormSubmission) == []
    assert client.delete(url, headers=admin).status_code == 404
