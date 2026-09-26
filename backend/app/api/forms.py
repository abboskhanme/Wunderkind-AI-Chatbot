"""Forms admin API (SPEC §15.4) — page «Formalar».

A,O: read forms and their submissions (+ CSV). A: create, edit, delete.
The public page and the submission → lead logic live in app.forms.
"""
from __future__ import annotations

import csv
import io
import uuid
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Query, Response
from sqlalchemy import func, select, update

from app.api.leads import _local
from app.core.deps import DB, get_current_user, get_user_header_or_query, require_admin
from app.forms import fields as form_fields
from app.forms import service
from app.models.form import Form, FormSubmission
from app.models.lead import Lead
from app.models.user import User
from app.schemas.forms import (
    FormField, FormIn, FormOut, FormPatch, SubmissionList, SubmissionOut,
)

router = APIRouter(prefix="/forms", tags=["Forms"])
staff = [Depends(get_current_user)]
admin = [Depends(require_admin)]

_HAS_SUBMISSIONS = "Formada javoblar bor — o'chirib bo'lmaydi. Uni nofaol qiling."


async def _row(db, form_id: uuid.UUID) -> Form:
    form = await db.get(Form, form_id)
    if form is None:
        raise HTTPException(404, "Forma topilmadi")
    return form


def _clean(items: Optional[list[FormField]]) -> list[dict]:
    try:
        return form_fields.clean_fields([i.model_dump() for i in items or []])
    except ValueError as exc:
        raise HTTPException(400, str(exc)) from None


async def _check_slug(db, slug: str, exclude: Optional[uuid.UUID] = None) -> None:
    q = select(Form.id).where(Form.slug == slug)
    if exclude is not None:
        q = q.where(Form.id != exclude)
    if (await db.execute(q.limit(1))).first() is not None:
        raise HTTPException(400, "Bu havola band — boshqasini yozing")


async def _outputs(db, forms: list[Form]) -> list[FormOut]:
    ids = [f.id for f in forms]
    stats: dict[uuid.UUID, tuple[int, object]] = {}
    if ids:
        stats = {row[0]: (row[1], row[2]) for row in (await db.execute(
            select(FormSubmission.form_id, func.count(), func.max(FormSubmission.created_at))
            .where(FormSubmission.form_id.in_(ids)).group_by(FormSubmission.form_id)
        )).all()}
    out = []
    for f in forms:
        count, last = stats.get(f.id, (0, None))
        out.append(FormOut(
            id=f.id, title=f.title, slug=f.slug, description=f.description or "",
            fields=[FormField(**field) for field in f.fields or []],
            submit_label=f.submit_label, success_message=f.success_message or "",
            is_active=f.is_active, notify=f.notify, sort_order=f.sort_order,
            url=service.public_url(f.slug), submissions=int(count), last_submission_at=last,
            created_at=f.created_at, updated_at=f.updated_at))
    return out


@router.get("", response_model=list[FormOut], dependencies=staff)
async def list_forms(db: DB):
    rows = (await db.execute(
        select(Form).order_by(Form.sort_order, Form.created_at.desc()))).scalars().all()
    return await _outputs(db, list(rows))


@router.post("", response_model=FormOut, status_code=201, dependencies=admin)
async def create_form(payload: FormIn, db: DB):
    slug = payload.slug or await service.unique_slug(db, service.slug_base(payload.title))
    await _check_slug(db, slug)
    form = Form(title=payload.title.strip(), slug=slug, description=payload.description.strip(),
                fields=_clean(payload.fields) if payload.fields else form_fields.default_fields(),
                submit_label=payload.submit_label.strip(),
                success_message=payload.success_message.strip(),
                is_active=payload.is_active, notify=payload.notify, sort_order=0)
    db.add(form)
    await db.commit()
    return (await _outputs(db, [form]))[0]


@router.get("/{form_id}", response_model=FormOut, dependencies=staff)
async def get_form(form_id: uuid.UUID, db: DB):
    return (await _outputs(db, [await _row(db, form_id)]))[0]


@router.patch("/{form_id}", response_model=FormOut, dependencies=admin)
async def update_form(form_id: uuid.UUID, payload: FormPatch, db: DB):
    form = await _row(db, form_id)
    data = payload.model_dump(exclude_unset=True)
    if data.get("slug") is not None and data["slug"] != form.slug:
        await _check_slug(db, data["slug"], exclude=form.id)
        form.slug = data["slug"]
    if payload.fields is not None:
        form.fields = _clean(payload.fields)
    for key in ("title", "description", "submit_label", "success_message"):
        if data.get(key) is not None:
            setattr(form, key, data[key].strip())
    for key in ("is_active", "notify"):
        if data.get(key) is not None:
            setattr(form, key, data[key])
    await db.commit()
    return (await _outputs(db, [form]))[0]


@router.delete("/{form_id}", status_code=204, dependencies=admin)
async def delete_form(form_id: uuid.UUID, db: DB):
    form = await _row(db, form_id)
    has = (await db.execute(select(FormSubmission.id)
                            .where(FormSubmission.form_id == form.id).limit(1))).first()
    if has is not None:
        raise HTTPException(409, _HAS_SUBMISSIONS)
    # Explicit SET NULL: SQLite (tests) does not enforce the FK
    await db.execute(update(Lead).where(Lead.form_id == form.id).values(form_id=None))
    await db.delete(form)
    await db.commit()
    return Response(status_code=204)


async def _submissions(db, form_id: uuid.UUID, offset: int, limit: int):
    return (await db.execute(
        select(FormSubmission, Lead.name, Lead.contact)
        .outerjoin(Lead, Lead.id == FormSubmission.lead_id)
        .where(FormSubmission.form_id == form_id)
        .order_by(FormSubmission.created_at.desc()).offset(offset).limit(limit)
    )).all()


@router.get("/{form_id}/submissions", response_model=SubmissionList, dependencies=staff)
async def list_submissions(form_id: uuid.UUID, db: DB, page: int = Query(1, ge=1),
                           page_size: int = Query(50, ge=1, le=200)):
    form = await _row(db, form_id)
    total = (await db.execute(select(func.count()).select_from(FormSubmission)
                              .where(FormSubmission.form_id == form.id))).scalar() or 0
    rows = await _submissions(db, form.id, (page - 1) * page_size, page_size)
    return SubmissionList(total=total, items=[
        SubmissionOut(id=s.id, created_at=s.created_at, lead_id=s.lead_id, lead_name=name,
                      lead_contact=contact, answers=s.answers or [], utm=s.utm or {})
        for s, name, contact in rows])


@router.delete("/{form_id}/submissions/{submission_id}", status_code=204,
               dependencies=admin)
async def delete_submission(form_id: uuid.UUID, submission_id: uuid.UUID, db: DB):
    """Delete one answer (a person's data-deletion request); the lead stays."""
    row = await db.get(FormSubmission, submission_id)
    if row is None or row.form_id != form_id:
        raise HTTPException(404, "Javob topilmadi")
    await db.delete(row)
    await db.commit()
    return Response(status_code=204)


def _cell(value: str) -> str:
    """Spreadsheet formula injection guard (answers are typed by anyone)."""
    return "'" + value if value[:1] in ("=", "+", "-", "@") else value


@router.get("/{form_id}/submissions.csv")
async def export_submissions(form_id: uuid.UUID, db: DB,
                             user: User = Depends(get_user_header_or_query)):
    form = await _row(db, form_id)
    current = form.fields or []
    rows = await _submissions(db, form.id, 0, 20000)
    buf = io.StringIO()
    writer = csv.writer(buf)
    writer.writerow(["Sana", *[_cell(f["label"]) for f in current], "Manba (UTM)"])
    for s, _name, _contact in rows:
        by_id = {a.get("field_id"): form_fields.display(a.get("value")) for a in s.answers or []}
        created = _local(s.created_at)
        utm = "; ".join(f"{k}={v}" for k, v in (s.utm or {}).items())
        writer.writerow([created, *[_cell(by_id.get(f["id"], "")) for f in current], _cell(utm)])
    name = f"{form.slug}-javoblar.csv"
    return Response(content="﻿" + buf.getvalue(), media_type="text/csv; charset=utf-8",
                    headers={"Content-Disposition": f'attachment; filename="{name}"'})
