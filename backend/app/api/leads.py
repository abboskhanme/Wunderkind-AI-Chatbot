"""Leads and conversations (admin + operator)."""
from __future__ import annotations

import csv
import io
import uuid
from datetime import datetime, timezone
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Query, Response
from sqlalchemy import and_, case, func, or_, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.deps import DB, CurrentUser, get_current_user, require_admin
from app.leads import profiles
from app.models.lead import CHANNELS, STATUS_LABELS, Lead, LeadMessage
from app.models.profile import CustomerProfile
from app.models.user import User
from app.schemas.api import (
    BotToggleIn, InboxItem, LeadDetail, LeadList, LeadOut, LeadUpdate, MessageOut,
    ProfileOut, ReplyOut, TextIn,
)
from app.services import channels

router = APIRouter(prefix="/leads", tags=["Leads"], dependencies=[Depends(get_current_user)])

_CHAT_KINDS = ("dm", "comment")


def _now() -> datetime:
    return datetime.now(timezone.utc)


async def _get(db: AsyncSession, lead_id: uuid.UUID) -> Lead:
    lead = await db.get(Lead, lead_id)
    if not lead:
        raise HTTPException(404, "Lead topilmadi")
    return lead


async def _names(db: AsyncSession, ids: list[Optional[uuid.UUID]]) -> dict[uuid.UUID, str]:
    ids = [i for i in ids if i]
    if not ids:
        return {}
    rows = (await db.execute(select(User.id, User.full_name, User.username)
                             .where(User.id.in_(ids)))).all()
    return {r.id: r.full_name or r.username for r in rows}


async def _counts(db: AsyncSession, ids: list[uuid.UUID]) -> dict[uuid.UUID, int]:
    if not ids:
        return {}
    rows = (await db.execute(
        select(LeadMessage.lead_id, func.count())
        .where(LeadMessage.lead_id.in_(ids), LeadMessage.kind.in_(_CHAT_KINDS))
        .group_by(LeadMessage.lead_id)
    )).all()
    return {r[0]: r[1] for r in rows}


def _out(lead: Lead, names: dict, counts: dict, accounts: Optional[dict] = None) -> LeadOut:
    out = LeadOut.model_validate(lead)
    out.assigned_to_name = names.get(lead.assigned_to_id)
    out.message_count = counts.get(lead.id, 0)
    out.profile_name = (accounts or {}).get((lead.channel, lead.external_id))
    return out


def _profile_match(like: str):
    """The lead's account profile matches the search (account name, shared phone)."""
    return select(CustomerProfile.id).where(
        CustomerProfile.channel == Lead.channel,
        CustomerProfile.external_id == Lead.external_id,
        or_(CustomerProfile.full_name.ilike(like), CustomerProfile.phone.ilike(like)),
    ).exists()


def _filtered(status: Optional[str], channel: Optional[str], search: Optional[str],
              min_score: Optional[int], has_contact: Optional[bool]):
    q = select(Lead)
    if status:
        q = q.where(Lead.status == status)
    if channel in CHANNELS:
        q = q.where(Lead.channel == channel)
    if search:
        like = f"%{search.strip()}%"
        q = q.where(or_(Lead.username.ilike(like), Lead.name.ilike(like),
                        Lead.contact.ilike(like), Lead.course_interest.ilike(like),
                        _profile_match(like)))
    if min_score is not None:
        q = q.where(Lead.lead_score >= min_score)
    if has_contact is True:
        q = q.where(Lead.contact.is_not(None))
    elif has_contact is False:
        q = q.where(Lead.contact.is_(None))
    return q


@router.get("", response_model=LeadList)
async def list_leads(
    db: DB,
    status: Optional[str] = None, channel: Optional[str] = None,
    search: Optional[str] = None, min_score: Optional[int] = Query(None, ge=0, le=100),
    has_contact: Optional[bool] = None,
    page: int = Query(1, ge=1), page_size: int = Query(50, ge=1, le=200),
):
    q = _filtered(status, channel, search, min_score, has_contact)
    total = (await db.execute(select(func.count()).select_from(q.subquery()))).scalar() or 0
    leads = (await db.execute(
        q.order_by(func.coalesce(Lead.last_message_at, Lead.created_at).desc())
        .offset((page - 1) * page_size).limit(page_size)
    )).scalars().all()
    names = await _names(db, [l.assigned_to_id for l in leads])
    counts = await _counts(db, [l.id for l in leads])
    accounts = await profiles.names(db, list(leads))
    return LeadList(items=[_out(l, names, counts, accounts) for l in leads], total=total)


@router.get("/export.csv")
async def export_csv(
    db: DB,
    status: Optional[str] = None, channel: Optional[str] = None,
    search: Optional[str] = None, min_score: Optional[int] = None,
    has_contact: Optional[bool] = None,
):
    leads = (await db.execute(
        _filtered(status, channel, search, min_score, has_contact)
        .order_by(Lead.created_at.desc()).limit(10000)
    )).scalars().all()
    accounts = await profiles.names(db, list(leads))
    buf = io.StringIO()
    writer = csv.writer(buf)
    writer.writerow(["Sana", "Kanal", "Username", "Ism", "Akkaunt nomi", "Telefon", "Qiziqish",
                     "Yosh/sinf", "Qulay vaqt", "Holat", "Ball", "Xulosa", "Izoh"])
    for l in leads:
        writer.writerow([_cell(v) for v in (
            _local(l.created_at), l.channel,
            l.username or "", l.name or "", accounts.get((l.channel, l.external_id), ""),
            l.contact or "", l.course_interest or "",
            l.student_age or "", l.preferred_time or "", STATUS_LABELS.get(l.status, l.status),
            l.lead_score, l.summary or "", l.note or "",
        )])
    # BOM so Excel opens UTF-8 (Cyrillic) correctly
    return Response(
        content="﻿" + buf.getvalue(), media_type="text/csv; charset=utf-8",
        headers={"Content-Disposition": 'attachment; filename="leads.csv"'},
    )


def _cell(value: object) -> object:
    """Customer-typed text (account names, messages) must not become an Excel
    formula: "=HYPERLINK(...)" is written as text. A phone's "+" is data."""
    if not isinstance(value, str) or not value:
        return value
    if value[0] in ("=", "-", "@", "\t", "\r") or (value[0] == "+" and not value[1:].isdigit()):
        return "'" + value
    return value


def _local(dt: Optional[datetime]) -> str:
    if not dt:
        return ""
    from zoneinfo import ZoneInfo

    from app.config import settings

    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    try:
        dt = dt.astimezone(ZoneInfo(settings.TIMEZONE))
    except Exception:  # noqa: BLE001
        pass
    return dt.strftime("%Y-%m-%d %H:%M")


@router.get("/assignees")
async def assignees(db: DB):
    rows = (await db.execute(
        select(User).where(User.is_active.is_(True)).order_by(User.full_name)
    )).scalars().all()
    return [{"id": u.id, "full_name": u.full_name or u.username} for u in rows]


@router.get("/inbox", response_model=list[InboxItem])
async def inbox(
    db: DB, search: Optional[str] = None, channel: Optional[str] = None,
    only_unread: bool = False,
):
    unread = func.count(case((and_(
        LeadMessage.role == "user",
        or_(Lead.last_read_at.is_(None), LeadMessage.created_at > Lead.last_read_at),
    ), 1)))
    agg = (
        select(LeadMessage.lead_id.label("lead_id"), unread.label("unread"))
        .join(Lead, Lead.id == LeadMessage.lead_id)
        .where(LeadMessage.kind.in_(_CHAT_KINDS))
        .group_by(LeadMessage.lead_id)
        .subquery()
    )
    q = select(Lead, agg.c.unread).join(agg, agg.c.lead_id == Lead.id)
    if channel in CHANNELS:
        q = q.where(Lead.channel == channel)
    if search:
        like = f"%{search.strip()}%"
        q = q.where(or_(Lead.username.ilike(like), Lead.name.ilike(like),
                        Lead.contact.ilike(like), _profile_match(like)))
    if only_unread:
        q = q.where(agg.c.unread > 0)
    rows = (await db.execute(
        q.order_by(Lead.last_message_at.desc().nulls_last()).limit(100)
    )).all()

    last: dict[uuid.UUID, LeadMessage] = {}
    ids = [r[0].id for r in rows]
    if ids:
        latest = (
            select(LeadMessage.lead_id, func.max(LeadMessage.created_at).label("at"))
            .where(LeadMessage.lead_id.in_(ids), LeadMessage.kind.in_(_CHAT_KINDS))
            .group_by(LeadMessage.lead_id).subquery()
        )
        msgs = (await db.execute(
            select(LeadMessage).join(latest, and_(
                LeadMessage.lead_id == latest.c.lead_id,
                LeadMessage.created_at == latest.c.at,
            ))
        )).scalars().all()
        for m in msgs:
            last.setdefault(m.lead_id, m)

    accounts = await profiles.names(db, [r[0] for r in rows])
    items = []
    for lead, unread_count in rows:
        m = last.get(lead.id)
        items.append(InboxItem(
            lead_id=lead.id, channel=lead.channel, username=lead.username,
            name=lead.name, profile_name=accounts.get((lead.channel, lead.external_id)),
            contact=lead.contact, status=lead.status,
            lead_score=lead.lead_score or 0, stage=lead.stage,
            last_message=m.text if m else None,
            last_message_role=m.role if m else None,
            last_message_at=lead.last_message_at,
            unread=int(unread_count or 0),
            window=channels.window(lead.channel, lead.last_customer_at),
        ))
    return items


@router.get("/{lead_id}", response_model=LeadDetail)
async def get_lead(lead_id: uuid.UUID, db: DB):
    lead = await _get(db, lead_id)
    msgs = (await db.execute(
        select(LeadMessage).where(LeadMessage.lead_id == lead.id)
        .order_by(LeadMessage.created_at)
    )).scalars().all()
    names = await _names(db, [lead.assigned_to_id])
    profile = await profiles.get(db, lead.channel, lead.external_id)
    out = _out(lead, names, {lead.id: sum(m.kind in _CHAT_KINDS for m in msgs)})
    out.profile_name = profile.full_name if profile else None
    detail = LeadDetail.model_validate({
        **out.model_dump(),
        "messages": [MessageOut.model_validate(m) for m in msgs],
        "profile": _profile_out(profile),
    })
    return detail


def _profile_out(profile: Optional[CustomerProfile]) -> Optional[ProfileOut]:
    if profile is None:
        return None
    out = ProfileOut.model_validate(profile)
    # The photo is served by /avatar; the CDN link itself expires anyway
    out.details = {k: v for k, v in (profile.details or {}).items() if k != "profile_pic"}
    return out


@router.post("/{lead_id}/profile/refresh", response_model=Optional[ProfileOut])
async def refresh_profile(lead_id: uuid.UUID, db: DB):
    """Re-read the account profile from Telegram / Instagram now."""
    lead = await _get(db, lead_id)
    return _profile_out(await profiles.refresh(lead.channel, lead.external_id))


@router.get("/{lead_id}/avatar")
async def avatar(lead_id: uuid.UUID, db: DB):
    lead = await _get(db, lead_id)
    image = await profiles.avatar(lead.channel, lead.external_id)
    if image is None:
        raise HTTPException(404, "Rasm yo'q")
    content, media_type = image
    return Response(content=content, media_type=media_type,
                    headers={"Cache-Control": "private, max-age=3600"})


@router.patch("/{lead_id}", response_model=LeadOut)
async def update_lead(lead_id: uuid.UUID, payload: LeadUpdate, db: DB, user: CurrentUser):
    lead = await _get(db, lead_id)
    data = payload.model_dump(exclude_unset=True)
    if "assigned_to_id" in data and data["assigned_to_id"] and not await db.get(
            User, data["assigned_to_id"]):
        raise HTTPException(400, "Mas'ul foydalanuvchi topilmadi")
    old_status = lead.status
    if "status" in data and data["status"] is None:
        del data["status"]  # status is NOT NULL
    for field, value in data.items():
        if isinstance(value, str):
            value = value.strip() or None
        setattr(lead, field, value)
    if payload.status and payload.status != old_status:
        db.add(LeadMessage(
            lead_id=lead.id, kind="status", role="system", created_at=_now(),
            text=f"Holat: {STATUS_LABELS.get(old_status, old_status)} → "
                 f"{STATUS_LABELS.get(payload.status, payload.status)}",
            meta={"by": str(user.id), "by_name": user.full_name or user.username,
                  "from": old_status, "to": payload.status},
        ))
    try:
        await db.commit()
    except IntegrityError:
        raise HTTPException(400, "Bu mijozning boshqa ochiq leadi bor — avval uni yoping") from None
    await db.refresh(lead)
    names = await _names(db, [lead.assigned_to_id])
    return _out(lead, names, await _counts(db, [lead.id]))


@router.delete("/{lead_id}", status_code=204, dependencies=[Depends(require_admin)])
async def delete_lead(lead_id: uuid.UUID, db: DB):
    await db.delete(await _get(db, lead_id))
    await db.commit()
    return Response(status_code=204)


@router.post("/{lead_id}/read", status_code=204)
async def mark_read(lead_id: uuid.UUID, db: DB):
    lead = await _get(db, lead_id)
    lead.last_read_at = _now()
    await db.commit()
    return Response(status_code=204)


@router.post("/{lead_id}/reply", response_model=ReplyOut)
async def reply(lead_id: uuid.UUID, payload: TextIn, db: DB, user: CurrentUser):
    lead = await _get(db, lead_id)
    text = payload.text.strip()
    result = await channels.send_reply(lead, text)
    if not result.get("sent"):
        return ReplyOut(sent=False, error=result.get("error") or "Yuborilmadi")
    now = _now()
    msg = LeadMessage(
        lead_id=lead.id, kind="dm", role="operator", text=text, created_at=now,
        meta={"by": str(user.id), "by_name": user.full_name or user.username,
              "tag": result.get("tag")},
    )
    db.add(msg)
    lead.last_read_at = now
    lead.last_message_at = now
    if lead.status == "new":
        lead.status = "contacted"
    await db.commit()
    await db.refresh(msg)
    return ReplyOut(sent=True, message=MessageOut.model_validate(msg))


@router.get("/{lead_id}/bot")
async def bot_state(lead_id: uuid.UUID, db: DB):
    return {"paused": await channels.is_paused(await _get(db, lead_id))}


@router.post("/{lead_id}/bot")
async def set_bot_state(lead_id: uuid.UUID, payload: BotToggleIn, db: DB):
    return {"paused": await channels.set_ai(await _get(db, lead_id), payload.enabled)}


@router.post("/{lead_id}/notes", response_model=MessageOut, status_code=201)
async def add_note(lead_id: uuid.UUID, payload: TextIn, db: DB, user: CurrentUser):
    lead = await _get(db, lead_id)
    msg = LeadMessage(lead_id=lead.id, kind="note", role="system", text=payload.text.strip(),
                      created_at=_now(),
                      meta={"by": str(user.id), "by_name": user.full_name or user.username})
    db.add(msg)
    await db.commit()
    await db.refresh(msg)
    return msg
