"""Lead-magnet funnel admin API (SPEC §10.4, §11.3) — page "Voronka".

A,O: stats, entries, bookings (list/patch), slots. A only: sales sequence,
lead-magnet PDF, Google Sheets, test message. Endpoints serving files accept
`?token=` (for <img>/<a href> where no header can be set).

Optional `funnel_id` (§11.3): absent → all funnels for stats/entries/bookings,
the default funnel for messages and the lead magnet. Funnel CRUD: app.api.funnels.
"""
from __future__ import annotations

import hashlib
import urllib.parse
import uuid
from datetime import date, datetime, time, timedelta, timezone
from typing import Optional

from fastapi import APIRouter, Depends, File, HTTPException, Query, Response, UploadFile
from sqlalchemy import case, delete, exists, func, or_, select
from sqlalchemy.orm import undefer

from app.config import settings
from app.core.deps import (
    DB, AdminUser, CurrentUser, get_current_user, get_user_header_or_query, require_admin,
)
from app.funnel import booking as funnel_booking
from app.funnel import delivery, funnels, gsheet, repo, slots, texts
from app.funnel.funnels import FunnelView
from app.models.bot_menu import ALLOWED_IMAGE_TYPES, MAX_IMAGE_BYTES
from app.models.funnel import (
    BOOKING_STATUSES, FUNNEL_SOURCES, FUNNEL_STEPS, LEAD_MAGNET_KEY, MAX_PDF_BYTES,
    FunnelDelivery, FunnelEntry, FunnelFile, FunnelMessage, InterviewBooking,
)
from app.models.lead import Lead
from app.models.user import User
from app.schemas.api import ReorderIn
from app.schemas.funnel import (
    BookingCounts, BookingOut, BookingStatus, BookingUpdate, DayStats, FunnelEntryList,
    FunnelEntryOut, FunnelMessageIn, FunnelMessageOut, FunnelMessagePatch, FunnelStats,
    LeadMagnetOut, ResyncOut, SentOut, SheetTestOut, SlotOut, SourceCount, StepCount,
    TestMessageIn,
)
from app.telegram_business.client import telegram

router = APIRouter(prefix="/funnel", tags=["Funnel"])
staff = [Depends(get_current_user)]
admin = [Depends(require_admin)]

_PDF_TYPES = frozenset({"application/pdf", "application/x-pdf", "application/octet-stream"})


def _local_midnight(day: date) -> datetime:
    return datetime.combine(day, time.min, texts.tz()).astimezone(timezone.utc)


def _booking_out(item: InterviewBooking, entry: FunnelEntry,
                 names: dict[uuid.UUID, str]) -> BookingOut:
    return BookingOut(
        id=item.id, entry_id=item.entry_id, funnel_id=entry.funnel_id,
        funnel_name=names.get(entry.funnel_id), lead_id=item.lead_id, full_name=entry.full_name,
        phone=entry.phone, grade=entry.grade, starts_at=item.starts_at, status=item.status,
        note=item.note, reminder_sent_at=item.reminder_sent_at, created_at=item.created_at)


async def _names(db) -> dict[uuid.UUID, str]:
    return {f.id: f.name for f in await funnels.load_all(db)}


async def _scope(db, funnel_id: Optional[uuid.UUID]) -> Optional[uuid.UUID]:
    """Filter for stats/entries/bookings: None = every funnel."""
    if funnel_id is not None and await funnels.get(db, funnel_id) is None:
        raise HTTPException(404, "Voronka topilmadi")
    return funnel_id


async def _funnel(db, funnel_id: Optional[uuid.UUID]) -> FunnelView:
    """Target for messages / lead magnet: the default funnel when not given."""
    if funnel_id is None:
        return await funnels.default(db)
    funnel = await funnels.get(db, funnel_id)
    if funnel is None:
        raise HTTPException(404, "Voronka topilmadi")
    return funnel


# --------------------------------------------------------------------------- #
# Stats (A,O)
# --------------------------------------------------------------------------- #
_STEP_LABELS = (
    ("comments", "Izoh / so'rov"),
    ("link_sent", "Havola olindi"),
    ("bot_started", "Botga kirdi"),
    ("contact_collected", "Raqam qoldirdi"),
    ("pdf_sent", "Qo'llanma oldi"),
    ("booked", "Suhbatga yozildi"),
    ("attended", "Suhbatga keldi"),
)


def _flag(condition) -> object:
    return func.coalesce(func.sum(case((condition, 1), else_=0)), 0)


def _in(scope: Optional[uuid.UUID]) -> tuple:
    return (FunnelEntry.funnel_id == scope,) if scope is not None else ()


def _booked_in(scope: Optional[uuid.UUID]) -> tuple:
    """Booking rows of one funnel (through their entry)."""
    if scope is None:
        return ()
    return (InterviewBooking.entry_id.in_(
        select(FunnelEntry.id).where(FunnelEntry.funnel_id == scope)),)


@router.get("/stats", response_model=FunnelStats, dependencies=staff)
async def stats(db: DB, days: int = Query(30, ge=1, le=365),
                funnel_id: Optional[uuid.UUID] = None):
    scope = await _scope(db, funnel_id)
    tz = texts.tz()
    today = datetime.now(tz).date()
    first_day = today - timedelta(days=days - 1)
    since = _local_midnight(first_day)
    entry = FunnelEntry
    any_booking = exists().where(InterviewBooking.entry_id == entry.id)
    attended = exists().where(InterviewBooking.entry_id == entry.id,
                              InterviewBooking.status == "attended")
    # Telegram-sourced entries got the deep link by definition (no IG link step)
    counts = (await db.execute(select(
        func.count(),
        _flag(or_(entry.link_sent_at.is_not(None), entry.source != "instagram")),
        _flag(entry.bot_started_at.is_not(None)),
        _flag(entry.phone.is_not(None)),
        _flag(entry.pdf_sent_at.is_not(None)),
        _flag(any_booking),
        _flag(attended),
    ).select_from(entry).where(entry.created_at >= since, *_in(scope)))).one()
    steps = [StepCount(key=key, label=label, count=int(n or 0))
             for (key, label), n in zip(_STEP_LABELS, counts)]

    per_source = dict((await db.execute(
        select(entry.source, func.count()).where(entry.created_at >= since, *_in(scope))
        .group_by(entry.source))).all())
    by_source = [SourceCount(source=s, count=int(per_source.get(s, 0))) for s in FUNNEL_SOURCES]

    # A reschedule cancels the old row: that is not a cancellation, don't count it
    real = InterviewBooking.rescheduled.is_(False)
    booked_in = _booked_in(scope)
    per_status = dict((await db.execute(
        select(InterviewBooking.status, func.count())
        .where(InterviewBooking.created_at >= since, real, *booked_in)
        .group_by(InterviewBooking.status))).all())
    today_count = (await db.execute(
        select(func.count()).select_from(InterviewBooking).where(
            *booked_in, InterviewBooking.status != "cancelled",
            InterviewBooking.starts_at >= _local_midnight(today),
            InterviewBooking.starts_at < _local_midnight(today + timedelta(days=1)))
    )).scalar() or 0
    bookings = BookingCounts(today=int(today_count),
                             **{s: int(per_status.get(s, 0)) for s in BOOKING_STATUSES})

    # Per-day series bucketed in Python (portable across DBs; timestamps only)
    series = {first_day + timedelta(days=i): [0, 0, 0] for i in range(days)}
    for column, index in ((entry.created_at, 0), (entry.pdf_sent_at, 1)):
        for (at,) in (await db.execute(
                select(column).where(column >= since, *_in(scope)))).all():
            day = texts.local(at).date()
            if day in series:
                series[day][index] += 1
    for (at,) in (await db.execute(
            select(InterviewBooking.created_at)
            .where(InterviewBooking.created_at >= since, real, *booked_in))).all():
        day = texts.local(at).date()
        if day in series:
            series[day][2] += 1
    by_day = [DayStats(date=d.isoformat(), entries=v[0], pdf=v[1], bookings=v[2])
              for d, v in series.items()]
    return FunnelStats(steps=steps, by_source=by_source, bookings=bookings, by_day=by_day)


# --------------------------------------------------------------------------- #
# Entries / bookings / slots (A,O)
# --------------------------------------------------------------------------- #
@router.get("/entries", response_model=FunnelEntryList, dependencies=staff)
async def list_entries(
    db: DB, source: Optional[str] = None, step: Optional[str] = None,
    search: Optional[str] = None, page: int = Query(1, ge=1),
    page_size: int = Query(50, ge=1, le=200), funnel_id: Optional[uuid.UUID] = None,
):
    q = select(FunnelEntry).where(*_in(await _scope(db, funnel_id)))
    if source in FUNNEL_SOURCES:
        q = q.where(FunnelEntry.source == source)
    if step in FUNNEL_STEPS:
        q = q.where(FunnelEntry.step == step)
    if search and search.strip():
        like = f"%{search.strip()}%"
        q = q.where(or_(FunnelEntry.full_name.ilike(like), FunnelEntry.phone.ilike(like),
                        FunnelEntry.ig_username.ilike(like), FunnelEntry.tg_username.ilike(like)))
    total = (await db.execute(select(func.count()).select_from(q.subquery()))).scalar() or 0
    entries = (await db.execute(
        q.order_by(FunnelEntry.created_at.desc()).offset((page - 1) * page_size).limit(page_size)
    )).scalars().all()
    ids = [e.id for e in entries]
    bookings = await repo.latest_bookings(db, ids)
    sent = dict((await db.execute(
        select(FunnelDelivery.entry_id, func.count()).where(FunnelDelivery.entry_id.in_(ids))
        .group_by(FunnelDelivery.entry_id))).all()) if ids else {}
    names = await _names(db)
    items = [FunnelEntryOut(
        id=e.id, funnel_id=e.funnel_id, funnel_name=names.get(e.funnel_id),
        source=e.source, step=e.step, full_name=e.full_name, phone=e.phone,
        grade=e.grade, ig_username=e.ig_username, tg_username=e.tg_username, lead_id=e.lead_id,
        pdf_sent_at=e.pdf_sent_at, opted_out=e.opted_out, created_at=e.created_at,
        booking=_booking_out(bookings[e.id], e, names) if e.id in bookings else None,
        messages_sent=int(sent.get(e.id, 0)),
    ) for e in entries]
    return FunnelEntryList(items=items, total=total)


@router.get("/bookings", response_model=list[BookingOut], dependencies=staff)
async def list_bookings(db: DB, date_from: Optional[date] = None, date_to: Optional[date] = None,
                        status: Optional[BookingStatus] = None,
                        funnel_id: Optional[uuid.UUID] = None):
    """date_from/date_to: local (TIMEZONE) dates, both inclusive."""
    q = select(InterviewBooking, FunnelEntry).join(
        FunnelEntry, FunnelEntry.id == InterviewBooking.entry_id
    ).where(*_in(await _scope(db, funnel_id)))
    if date_from:
        q = q.where(InterviewBooking.starts_at >= _local_midnight(date_from))
    if date_to:
        q = q.where(InterviewBooking.starts_at < _local_midnight(date_to + timedelta(days=1)))
    if status:
        q = q.where(InterviewBooking.status == status)
    rows = (await db.execute(q.order_by(InterviewBooking.starts_at))).all()
    names = await _names(db)
    return [_booking_out(item, entry, names) for item, entry in rows]


@router.patch("/bookings/{booking_id}", response_model=BookingOut)
async def update_booking(booking_id: uuid.UUID, payload: BookingUpdate, db: DB,
                         user: CurrentUser):
    """Status / note (A,O). Marks the entry for the Sheet; the lead status is left
    alone (`enrolled` is set by staff, not automatically)."""
    item = await db.get(InterviewBooking, booking_id)
    if item is None:
        raise HTTPException(404, "Suhbat topilmadi")
    entry = await db.get(FunnelEntry, item.entry_id)
    data = payload.model_dump(exclude_unset=True)
    if "note" in data:
        item.note = (data["note"] or "").strip() or None
    new_status = data.get("status")
    if new_status == "scheduled" and item.status != "scheduled":
        raise HTTPException(400, "Suhbatni qayta tiklab bo'lmaydi — mijoz botda yangi vaqt "
                                 "tanlaydi (yoki «Suhbatga yozilish» tugmasini bosadi)")
    if new_status and new_status != item.status:
        item.status = new_status
        lead = await db.get(Lead, item.lead_id) if item.lead_id else None
        if lead is not None:
            values = texts.booking_values(None, item.starts_at)
            repo.log_system(db, lead, f"🗓 Suhbat ({values['date']}, {values['time']}): "
                                      f"{texts.BOOKING_LABELS[new_status]}",
                            by_name=user.full_name or user.username, booking_status=new_status)
    if entry is not None:
        repo.touch(entry)
    await db.commit()
    return _booking_out(item, entry, await _names(db))


@router.get("/slots", response_model=list[SlotOut], dependencies=staff)
async def slots_for_day(db: DB, day: date = Query(alias="date")):
    cfg = slots.SlotConfig.from_settings()
    starts = slots.day_slots(day, cfg)
    if not starts:
        return []
    taken = await slots.taken_counts(db, starts[0], starts[-1] + timedelta(minutes=1))
    return [SlotOut(time=s.strftime("%H:%M"),
                    free=max(0, cfg.capacity - taken.get(s.astimezone(timezone.utc), 0)))
            for s in starts]


# --------------------------------------------------------------------------- #
# Sales sequence (A)
# --------------------------------------------------------------------------- #
async def _messages(db, funnel_id: uuid.UUID) -> list[FunnelMessage]:
    return list((await db.execute(
        select(FunnelMessage).where(FunnelMessage.funnel_id == funnel_id)
        .order_by(FunnelMessage.sort_order, FunnelMessage.created_at)
    )).scalars().all())


async def _message(db, message_id: uuid.UUID) -> FunnelMessage:
    item = await db.get(FunnelMessage, message_id)
    if item is None:
        raise HTTPException(404, "Xabar topilmadi")
    return item


@router.get("/messages", response_model=list[FunnelMessageOut], dependencies=admin)
async def list_messages(db: DB, funnel_id: Optional[uuid.UUID] = None):
    return await _messages(db, (await _funnel(db, funnel_id)).id)


@router.post("/messages", response_model=FunnelMessageOut, status_code=201, dependencies=admin)
async def create_message(payload: FunnelMessageIn, db: DB,
                         funnel_id: Optional[uuid.UUID] = None):
    funnel = await _funnel(db, funnel_id)
    max_order = (await db.execute(
        select(func.max(FunnelMessage.sort_order)).where(FunnelMessage.funnel_id == funnel.id)
    )).scalar() or 0
    item = FunnelMessage(funnel_id=funnel.id, text=payload.text.strip(),
                         delay_minutes=payload.delay_minutes, is_active=payload.is_active,
                         sort_order=max_order + 1)
    db.add(item)
    await db.commit()
    return item


@router.patch("/messages/{message_id}", response_model=FunnelMessageOut, dependencies=admin)
async def update_message(message_id: uuid.UUID, payload: FunnelMessagePatch, db: DB):
    item = await _message(db, message_id)
    for key, value in payload.model_dump(exclude_unset=True).items():
        if value is not None:
            setattr(item, key, value.strip() if isinstance(value, str) else value)
    await db.commit()
    return item


@router.delete("/messages/{message_id}", status_code=204, dependencies=admin)
async def delete_message(message_id: uuid.UUID, db: DB):
    item = await _message(db, message_id)
    # Explicit: SQLite (tests) does not enforce ON DELETE CASCADE
    await db.execute(delete(FunnelDelivery).where(FunnelDelivery.message_id == item.id))
    await db.delete(item)
    await db.commit()
    return Response(status_code=204)


@router.post("/messages/reorder", response_model=list[FunnelMessageOut], dependencies=admin)
async def reorder_messages(payload: ReorderIn, db: DB, funnel_id: Optional[uuid.UUID] = None):
    funnel = await _funnel(db, funnel_id)
    items = {m.id: m for m in await _messages(db, funnel.id)}
    for index, message_id in enumerate(payload.ids):
        if message_id in items:          # ids of other funnels are ignored
            items[message_id].sort_order = index
    await db.commit()
    return await _messages(db, funnel.id)


@router.put("/messages/{message_id}/image", response_model=FunnelMessageOut, dependencies=admin)
async def upload_message_image(message_id: uuid.UUID, db: DB, file: UploadFile = File(...)):
    item = await _message(db, message_id)
    if file.content_type not in ALLOWED_IMAGE_TYPES:
        raise HTTPException(400, "Faqat JPG, PNG yoki WEBP rasm")
    data = await file.read(MAX_IMAGE_BYTES + 1)
    if len(data) > MAX_IMAGE_BYTES:
        raise HTTPException(400, "Rasm 5 MB dan katta")
    if not data:
        raise HTTPException(400, "Bo'sh fayl")
    item.image = data
    item.image_content_type = file.content_type
    await db.commit()
    return item


@router.delete("/messages/{message_id}/image", status_code=204, dependencies=admin)
async def delete_message_image(message_id: uuid.UUID, db: DB):
    item = await _message(db, message_id)
    item.image = None
    item.image_content_type = None
    await db.commit()
    return Response(status_code=204)


@router.get("/messages/{message_id}/image")
async def get_message_image(message_id: uuid.UUID, db: DB,
                            user: User = Depends(get_user_header_or_query)):
    if user.role != "admin":
        raise HTTPException(403, "Faqat administrator uchun")
    row = (await db.execute(
        select(FunnelMessage.image, FunnelMessage.image_content_type)
        .where(FunnelMessage.id == message_id)
    )).first()
    if row is None or not row.image:
        raise HTTPException(404, "Rasm topilmadi")
    return Response(content=bytes(row.image), media_type=row.image_content_type or "image/jpeg",
                    headers={"Cache-Control": "private, max-age=3600"})


# --------------------------------------------------------------------------- #
# Lead-magnet PDF (A)
# --------------------------------------------------------------------------- #
@router.get("/lead-magnet", response_model=Optional[LeadMagnetOut], dependencies=admin)
async def get_lead_magnet(db: DB, funnel_id: Optional[uuid.UUID] = None):
    funnel = await _funnel(db, funnel_id)
    return await db.get(FunnelFile, (funnel.id, LEAD_MAGNET_KEY))


def _pdf_filename(name: Optional[str]) -> str:
    base = (name or "").replace("\\", "/").rsplit("/", 1)[-1].strip() or "qollanma.pdf"
    if not base.lower().endswith(".pdf"):
        base += ".pdf"
    return base[-200:]


@router.put("/lead-magnet", response_model=LeadMagnetOut, dependencies=admin)
async def upload_lead_magnet(db: DB, file: UploadFile = File(...),
                             funnel_id: Optional[uuid.UUID] = None):
    if file.content_type not in _PDF_TYPES:
        raise HTTPException(400, "Faqat PDF fayl yuklang")
    data = await file.read(MAX_PDF_BYTES + 1)
    if len(data) > MAX_PDF_BYTES:
        raise HTTPException(400, "Fayl 20 MB dan katta")
    if not data.startswith(b"%PDF"):
        raise HTTPException(400, "Bu PDF fayl emas")
    funnel = await _funnel(db, funnel_id)
    row = await db.get(FunnelFile, (funnel.id, LEAD_MAGNET_KEY))
    if row is None:
        row = FunnelFile(funnel_id=funnel.id, key=LEAD_MAGNET_KEY)
        db.add(row)
    row.filename = _pdf_filename(file.filename)
    row.content_type = "application/pdf"
    row.size_bytes = len(data)
    row.data = data
    row.sha256 = hashlib.sha256(data).hexdigest()
    row.tg_file_id = None          # new file -> upload to Telegram again
    row.updated_at = repo.now()
    await db.commit()
    return LeadMagnetOut(filename=row.filename, size_bytes=row.size_bytes,
                         updated_at=row.updated_at)


@router.get("/lead-magnet/download")
async def download_lead_magnet(db: DB, user: User = Depends(get_user_header_or_query),
                               funnel_id: Optional[uuid.UUID] = None):
    if user.role != "admin":
        raise HTTPException(403, "Faqat administrator uchun")
    funnel = await _funnel(db, funnel_id)
    row = (await db.execute(
        select(FunnelFile).options(undefer(FunnelFile.data))
        .where(FunnelFile.funnel_id == funnel.id, FunnelFile.key == LEAD_MAGNET_KEY)
    )).scalar_one_or_none()
    if row is None:
        raise HTTPException(404, "Qo'llanma hali yuklanmagan")
    quoted = urllib.parse.quote(row.filename)
    return Response(content=bytes(row.data), media_type="application/pdf", headers={
        "Content-Disposition": f"attachment; filename=\"qollanma.pdf\"; filename*=UTF-8''{quoted}",
    })


# --------------------------------------------------------------------------- #
# Google Sheets + test message (A)
# --------------------------------------------------------------------------- #
@router.post("/sheet/test", response_model=SheetTestOut, dependencies=admin)
async def sheet_test():
    return SheetTestOut(**await gsheet.test_connection())


@router.post("/sheet/resync", response_model=ResyncOut, dependencies=admin)
async def sheet_resync(db: DB):
    return ResyncOut(queued=await gsheet.mark_all_dirty(db))


@router.post("/test-message", response_model=SentOut)
async def test_message(payload: TestMessageIn, db: DB, user: AdminUser):
    """Preview a template in a real Telegram chat (nothing is stored)."""
    if not telegram.enabled:
        return SentOut(sent=False, error="Telegram bot sozlanmagan")
    chat_id = payload.tg_chat_id.strip()
    if payload.kind == "sales":
        if payload.message_id:
            message = await _message(db, payload.message_id)
        else:
            default = await funnels.default(db)
            message = next((m for m in await _messages(db, default.id) if m.is_active), None)
            if message is None:
                raise HTTPException(400, "Faol sotuv xabari yo'q")
        result = await delivery.send_sales_message(chat_id, message,
                                                   await funnels.get(db, message.funnel_id))
    else:
        cfg = slots.SlotConfig.from_settings()
        tomorrow = datetime.now(cfg.tz).date() + timedelta(days=1)
        sample = datetime.combine(tomorrow, cfg.day_start, cfg.tz)
        template = (settings.FUNNEL_CONFIRM_TEXT if payload.kind == "confirm"
                    else settings.FUNNEL_REMINDER_TEXT)
        result = await funnel_booking.send_booking_message(
            chat_id, template, user.full_name or user.username, sample)
    return SentOut(sent=bool(result.get("sent")), error=result.get("error"))
