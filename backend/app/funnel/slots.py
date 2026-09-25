"""Interview slots (SPEC §10.1 "Booking").

Pure functions over a `SlotConfig` snapshot of the settings, plus one DB query
for how many `scheduled` bookings each slot already has. All slot times are
timezone-aware in TIMEZONE; `taken` maps UTC slot starts to booking counts.
"""
from __future__ import annotations

import re
from collections import Counter
from dataclasses import dataclass
from datetime import date, datetime, time, timedelta, timezone
from zoneinfo import ZoneInfo

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import settings
from app.funnel import texts
from app.models.funnel import InterviewBooking

LEAD_TIME = timedelta(minutes=60)   # today's slots need at least this much notice


def parse_hhmm(value: str, default: time) -> time:
    match = re.fullmatch(r"\s*(\d{1,2}):(\d{2})\s*", value or "")
    if not match or int(match[1]) > 23 or int(match[2]) > 59:
        return default
    return time(int(match[1]), int(match[2]))


def parse_work_days(value: str) -> frozenset[int]:
    """"1-6" / "1,2,3" / "1-3,5" -> ISO weekdays (1 = Monday … 7 = Sunday)."""
    days: set[int] = set()
    for part in (value or "").split(","):
        bounds = [int(x) for x in re.findall(r"[1-7]", part)]
        if len(bounds) == 1:
            days.add(bounds[0])
        elif len(bounds) >= 2:
            low, high = sorted(bounds[:2])
            days.update(range(low, high + 1))
    return frozenset(days)


def parse_holidays(value: str) -> frozenset[date]:
    out: set[date] = set()
    for raw in re.findall(r"\d{4}-\d{2}-\d{2}", value or ""):
        try:
            out.add(date.fromisoformat(raw))
        except ValueError:
            continue
    return frozenset(out)


@dataclass(frozen=True)
class SlotConfig:
    tz: ZoneInfo
    work_days: frozenset[int]
    holidays: frozenset[date]
    day_start: time
    day_end: time
    slot_minutes: int
    capacity: int
    days_ahead: int

    @classmethod
    def from_settings(cls) -> "SlotConfig":
        return cls(
            tz=texts.tz(),
            work_days=parse_work_days(settings.FUNNEL_WORK_DAYS) or frozenset(range(1, 7)),
            holidays=parse_holidays(settings.FUNNEL_HOLIDAYS),
            day_start=parse_hhmm(settings.FUNNEL_DAY_START, time(9, 0)),
            day_end=parse_hhmm(settings.FUNNEL_DAY_END, time(16, 0)),
            slot_minutes=max(5, int(settings.FUNNEL_SLOT_MINUTES or 30)),
            capacity=max(1, int(settings.FUNNEL_SLOT_CAPACITY or 1)),
            days_ahead=max(1, int(settings.FUNNEL_BOOK_DAYS_AHEAD or 7)),
        )


def is_work_day(day: date, cfg: SlotConfig) -> bool:
    return day.isoweekday() in cfg.work_days and day not in cfg.holidays


def day_slots(day: date, cfg: SlotConfig) -> list[datetime]:
    """Every slot start of a working day: day_start, +slot, … while start < day_end."""
    if not is_work_day(day, cfg):
        return []
    step = timedelta(minutes=cfg.slot_minutes)
    current = datetime.combine(day, cfg.day_start, cfg.tz)
    end = datetime.combine(day, cfg.day_end, cfg.tz)
    out: list[datetime] = []
    while current < end:
        out.append(current)
        current += step
    return out


def _key(at: datetime) -> datetime:
    return at.astimezone(timezone.utc)


def free_slots(day: date, cfg: SlotConfig, taken: Counter, now: datetime) -> list[tuple[datetime, int]]:
    """Bookable slots of `day` with their free capacity (>0), respecting lead time."""
    earliest = now + LEAD_TIME
    out = []
    for start in day_slots(day, cfg):
        if start < earliest:
            continue
        free = cfg.capacity - taken.get(_key(start), 0)
        if free > 0:
            out.append((start, free))
    return out


def booking_window(now: datetime, cfg: SlotConfig) -> list[date]:
    """Calendar days a person may pick: today + the next days_ahead-1 days."""
    today = now.astimezone(cfg.tz).date()
    return [today + timedelta(days=i) for i in range(cfg.days_ahead)]


def bookable_days(now: datetime, cfg: SlotConfig, taken: Counter) -> list[date]:
    """Working, non-holiday days in the window that still have a free slot."""
    return [d for d in booking_window(now, cfg) if free_slots(d, cfg, taken, now)]


def is_bookable(start: datetime, cfg: SlotConfig, now: datetime) -> bool:
    """Is `start` a real slot inside the window (capacity is checked separately)?"""
    day = start.astimezone(cfg.tz).date()
    if day not in booking_window(now, cfg) or start < now + LEAD_TIME:
        return False
    return any(s == start for s in day_slots(day, cfg))


def window_bounds(now: datetime, cfg: SlotConfig) -> tuple[datetime, datetime]:
    days = booking_window(now, cfg)
    start = datetime.combine(days[0], time.min, cfg.tz)
    end = datetime.combine(days[-1] + timedelta(days=1), time.min, cfg.tz)
    return start, end


async def taken_counts(db: AsyncSession, start: datetime, end: datetime) -> Counter:
    """Scheduled bookings per slot start (UTC keys) in [start, end)."""
    rows = (await db.execute(
        select(InterviewBooking.starts_at, func.count())
        .where(InterviewBooking.status == "scheduled",
               InterviewBooking.starts_at >= start.astimezone(timezone.utc),
               InterviewBooking.starts_at < end.astimezone(timezone.utc))
        .group_by(InterviewBooking.starts_at)
    )).all()
    counts: Counter = Counter()
    for at, n in rows:
        if at.tzinfo is None:
            at = at.replace(tzinfo=timezone.utc)
        counts[_key(at)] += int(n)
    return counts


def slot_key(start: datetime) -> str:
    """Callback/lock form of a slot: local YYYYMMDDHHMM."""
    return start.strftime("%Y%m%d%H%M")


def parse_slot_key(value: str, cfg: SlotConfig) -> datetime | None:
    try:
        return datetime.strptime(value, "%Y%m%d%H%M").replace(tzinfo=cfg.tz)
    except ValueError:
        return None


def parse_day_key(value: str) -> date | None:
    try:
        return datetime.strptime(value, "%Y%m%d").date()
    except ValueError:
        return None
