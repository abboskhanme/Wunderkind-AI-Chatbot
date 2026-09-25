"""Admission-interview booking in the bot (SPEC §10.1 "Booking", "Confirmation").

Callbacks: fb:start (from the PDF / sales messages), fb:d:<YYYYMMDD>,
fb:t:<YYYYMMDDHHMM>, fb:back, fb:cancel, fb:resched. Dates and times are local
(TIMEZONE). Taking a slot re-checks capacity under a per-slot asyncio lock.
"""
from __future__ import annotations

import html
from datetime import date, datetime, timezone
from typing import Optional

from loguru import logger
from sqlalchemy import func, select

from app.config import settings
from app.db import session as db_session
from app.funnel import delivery, locks, repo, slots, texts
from app.models.funnel import FunnelEntry, InterviewBooking
from app.telegram import notifier
from app.telegram_business.client import telegram


def manage_keyboard() -> dict:
    return {"inline_keyboard": [
        [{"text": texts.RESCHEDULE_BUTTON, "callback_data": "fb:resched"}],
        [{"text": texts.CANCEL_BUTTON, "callback_data": "fb:cancel"}],
    ]}


def location() -> Optional[tuple[float, float]]:
    try:
        lat = float(settings.FUNNEL_LOCATION_LAT)
        lon = float(settings.FUNNEL_LOCATION_LON)
    except (TypeError, ValueError):
        return None
    return lat, lon


async def send_booking_message(chat_id: str, template: str, name: Optional[str],
                               starts_at: datetime) -> dict:
    """Confirmation / reminder text with manage buttons, then the location pin."""
    text = texts.render(template, **texts.booking_values(name, starts_at))
    result = await telegram.send_message(chat_id, text, reply_markup=manage_keyboard())
    point = location()
    if result.get("sent") and point:
        await telegram.send_location(chat_id, point[0], point[1])
    return result


def _day_button(day: date, today: date) -> str:
    if day == today:
        prefix = "Bugun"
    elif (day - today).days == 1:
        prefix = "Ertaga"
    else:
        prefix = texts.weekday_label(day).capitalize()
    return f"{prefix}, {texts.day_label(day)}"


def dates_keyboard(days: list[date], today: date) -> dict:
    buttons = [{"text": _day_button(d, today), "callback_data": f"fb:d:{d:%Y%m%d}"} for d in days]
    return {"inline_keyboard": [buttons[i:i + 2] for i in range(0, len(buttons), 2)]}


def times_keyboard(free: list[tuple[datetime, int]]) -> dict:
    buttons = [{"text": start.strftime("%H:%M"),
                "callback_data": f"fb:t:{slots.slot_key(start)}"} for start, _ in free]
    rows = [buttons[i:i + 4] for i in range(0, len(buttons), 4)]
    rows.append([{"text": texts.BACK_BUTTON, "callback_data": "fb:back"}])
    return {"inline_keyboard": rows}


async def _show(chat_id: str, message_id: object, text: str, markup: Optional[dict]) -> None:
    """Edit the picker message in place; send a new one if that is impossible."""
    if message_id:
        result = await telegram.edit_message_text(chat_id, message_id, text, reply_markup=markup)
        if result.get("sent") or "not modified" in str(result.get("error") or ""):
            return
    await telegram.send_message(chat_id, text, reply_markup=markup)


async def _taken(cfg: slots.SlotConfig, now: datetime):
    start, end = slots.window_bounds(now, cfg)
    async with db_session.SessionLocal() as db:
        return await slots.taken_counts(db, start, end)


# --------------------------------------------------------------------------- #
# Callback router (caller holds the person's lock and answered nothing yet)
# --------------------------------------------------------------------------- #
async def handle(user_id: str, chat_id: str, message_id: object, data: str) -> None:
    async with db_session.SessionLocal() as db:
        entry = await repo.entry_by_tg(db, user_id)
        current = await repo.active_booking(db, entry.id) if entry else None
    if entry is None:
        await telegram.send_message(chat_id, texts.START_FIRST)
        return
    if not entry.full_name or not entry.phone:
        from app.funnel.bot import ask_next   # finish the questions first

        await ask_next(entry.id)
        return

    cfg = slots.SlotConfig.from_settings()
    now = repo.now()
    if data == "fb:start" and current is not None:
        await telegram.send_message(
            chat_id, texts.render(texts.ALREADY_BOOKED,
                                  **texts.booking_values(entry.full_name, current.starts_at)),
            reply_markup=manage_keyboard())
    elif data in ("fb:start", "fb:resched"):
        await show_dates(chat_id, None, cfg, now)
    elif data == "fb:back":
        await show_dates(chat_id, message_id, cfg, now)
    elif data.startswith("fb:d:"):
        day = slots.parse_day_key(data[len("fb:d:"):])
        if day is None:
            return
        await show_times(chat_id, message_id, day, cfg, now)
    elif data.startswith("fb:t:"):
        start = slots.parse_slot_key(data[len("fb:t:"):], cfg)
        if start is None:
            return
        await take_slot(entry, chat_id, message_id, start, cfg, now)
    elif data == "fb:cancel":
        await cancel(entry, chat_id)


async def show_dates(chat_id: str, message_id: object, cfg: slots.SlotConfig,
                     now: datetime) -> None:
    days = slots.bookable_days(now, cfg, await _taken(cfg, now))
    if not days:
        await _show(chat_id, message_id, texts.NO_FREE_DAYS, None)
        return
    await _show(chat_id, message_id, texts.PICK_DATE,
                dates_keyboard(days, now.astimezone(cfg.tz).date()))


async def show_times(chat_id: str, message_id: object, day: date, cfg: slots.SlotConfig,
                     now: datetime, *, notice: Optional[str] = None) -> None:
    taken = await _taken(cfg, now)
    free = slots.free_slots(day, cfg, taken, now) if day in slots.booking_window(now, cfg) else []
    if not free:
        days = slots.bookable_days(now, cfg, taken)
        if not days:
            await _show(chat_id, message_id, texts.NO_FREE_DAYS, None)
        else:
            await _show(chat_id, message_id, texts.DAY_FULL,
                        dates_keyboard(days, now.astimezone(cfg.tz).date()))
        return
    title = texts.render(texts.PICK_TIME, date=texts.day_label(day), weekday=texts.weekday_label(day))
    await _show(chat_id, message_id, f"{notice}\n\n{title}" if notice else title,
                times_keyboard(free))


async def take_slot(entry: FunnelEntry, chat_id: str, message_id: object, start: datetime,
                    cfg: slots.SlotConfig, now: datetime) -> None:
    day = start.astimezone(cfg.tz).date()
    if not slots.is_bookable(start, cfg, now):
        await show_times(chat_id, message_id, day, cfg, now, notice=texts.SLOT_TAKEN)
        return
    start_utc = start.astimezone(timezone.utc)
    async with locks.lock(f"slot:{slots.slot_key(start)}"):
        async with db_session.SessionLocal() as db:
            fresh = await db.get(FunnelEntry, entry.id)
            if fresh is None:
                return
            outcome, previous = await _book(db, fresh, start_utc, cfg.capacity)
            if outcome == "booked":
                await db.commit()
            else:
                await db.rollback()
    if outcome == "full":
        await show_times(chat_id, message_id, day, cfg, now, notice=texts.SLOT_TAKEN)
        return
    values = texts.booking_values(entry.full_name, start_utc)
    await _show(chat_id, message_id, texts.render(texts.SLOT_CHOSEN, **values), None)
    if outcome == "booked":      # "already": double tap — the confirmation is above
        await send_booking_message(chat_id, settings.FUNNEL_CONFIRM_TEXT, entry.full_name,
                                   start_utc)
        title = "🔁 <b>Suhbat vaqti o'zgardi</b>" if previous else "📅 <b>Suhbatga yozilish</b>"
        await _alert(title, entry, start_utc, previous=previous)
        logger.info("Funnel booking: tg={} at {}", entry.tg_user_id, start_utc.isoformat())


async def _book(db, entry: FunnelEntry, start_utc: datetime,
                capacity: int) -> tuple[str, Optional[datetime]]:
    """Inside the slot lock. Returns ("booked" | "already" | "full", previous start)."""
    current = await repo.active_booking(db, entry.id)
    if current is not None and _same(current.starts_at, start_utc):
        return "already", None
    taken = (await db.execute(
        select(func.count()).select_from(InterviewBooking)
        .where(InterviewBooking.status == "scheduled", InterviewBooking.starts_at == start_utc)
    )).scalar() or 0
    if taken >= capacity:
        return "full", None
    previous = None
    if current is not None:          # reschedule = cancel old + create new
        previous = current.starts_at
        current.status = "cancelled"
        current.rescheduled = True   # not a real cancellation (stats)
        await db.flush()             # free the one-scheduled-per-entry index first
    booking = InterviewBooking(entry_id=entry.id, starts_at=start_utc, status="scheduled")
    db.add(booking)
    lead = await repo.ensure_lead(db, entry)
    booking.lead_id = lead.id
    if lead.status in ("new", "contacted"):
        repo.log_status(db, lead, "trial")
    lead.stage = "booked"
    lead.lead_score = max(lead.lead_score or 0, repo.LEAD_SCORE_BOOKED)
    values = texts.booking_values(entry.full_name, start_utc)
    repo.log_system(db, lead, f"📅 Suhbatga yozildi: {values['date']} ({values['weekday']}), "
                              f"{values['time']}", step="booked")
    repo.touch(entry)
    return "booked", previous


async def cancel(entry: FunnelEntry, chat_id: str) -> None:
    cancelled_at: Optional[datetime] = None
    async with db_session.SessionLocal() as db:
        fresh = await db.get(FunnelEntry, entry.id)
        current = await repo.active_booking(db, entry.id) if fresh else None
        if fresh is not None and current is not None:
            current.status = "cancelled"
            cancelled_at = current.starts_at
            lead = await repo.ensure_lead(db, fresh)
            values = texts.booking_values(fresh.full_name, current.starts_at)
            repo.log_system(db, lead, f"❌ Suhbat bekor qilindi (mijoz): {values['date']}, "
                                      f"{values['time']}", step="cancelled")
            repo.touch(fresh)
            await db.commit()
    if cancelled_at is None:
        await telegram.send_message(chat_id, texts.NOTHING_TO_CANCEL,
                                    reply_markup=delivery.book_keyboard())
        return
    await telegram.send_message(chat_id, texts.CANCELLED, reply_markup=delivery.book_keyboard())
    await _alert("❌ <b>Suhbat bekor qilindi</b>", entry, cancelled_at)


def _same(a: datetime, b: datetime) -> bool:
    if a.tzinfo is None:
        a = a.replace(tzinfo=timezone.utc)
    return a == b


async def _alert(title: str, entry: FunnelEntry, starts_at: datetime, *,
                 previous: Optional[datetime] = None) -> None:
    """Staff alert to TELEGRAM_CHAT_ID (name, phone, grade, date/time, source)."""
    def when(at: datetime) -> str:
        v = texts.booking_values(None, at)
        return f"{v['date']} ({v['weekday']}), {v['time']}"

    source = texts.SOURCE_LABELS.get(entry.source, entry.source)
    if entry.ig_username:
        source += f" · @{entry.ig_username}"
    lines = [
        title,
        f"👤 {html.escape(entry.full_name or '—')}",
        f"📞 {html.escape(entry.phone or '—')}",
        f"🎒 {html.escape(texts.grade_display(entry.grade) or '—')}",
        f"🗓 {when(starts_at)}" + (f" (avval: {when(previous)})" if previous else ""),
        f"Manba: {html.escape(source)}",
    ]
    if entry.tg_username:
        lines.append(f"Telegram: @{html.escape(entry.tg_username)}")
    try:
        await notifier.send_text("\n".join(lines))
    except Exception as exc:  # noqa: BLE001
        logger.warning("Booking alert failed: {}", exc)
