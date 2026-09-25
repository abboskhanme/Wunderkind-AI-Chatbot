"""Funnel pure logic: keyword matcher, slot generation, template rendering."""
from __future__ import annotations

from collections import Counter
from datetime import date, datetime, time, timezone
from zoneinfo import ZoneInfo

import pytest

from app.funnel import keywords, slots, texts

TZ = ZoneInfo("Asia/Tashkent")
KEYS = ["wunderkind", "вундеркинд"]


# --------------------------------------------------------------------------- #
# Keyword matcher
# --------------------------------------------------------------------------- #
@pytest.mark.parametrize("text", [
    "wunderkind", "Wunderkind", "WUNDERKIND!!!", "  wunderkind 🔥", "#wunderkind",
    "Menga ham wunderkind yuboring", "вундеркинд", "Вундеркинд, пожалуйста",
    "Vunderkind", "wunderkindga qiziqaman", "Wünderkind",
])
def test_keyword_matches(text):
    assert keywords.matches(text, KEYS)


@pytest.mark.parametrize("text", [
    "", "salom", "wunder", "kind", "wunder kind", "narxi qancha?", "🔥🔥🔥",
    "superwunderkind",       # the keyword must start a word
])
def test_keyword_does_not_match(text):
    assert not keywords.matches(text, KEYS)


def test_keyword_setting_is_used_and_multiword(monkeypatch):
    from app.config import settings

    monkeypatch.setattr(settings, "FUNNEL_KEYWORDS", "lider farzand, kitob")
    assert keywords.matches("Menga LIDER farzand qo'llanmasi kerak")
    assert keywords.matches("kitob")
    assert not keywords.matches("wunderkind")          # not configured any more
    assert keywords.parse_keywords(" a, b ;a\nc ") == ["a", "b", "c"]


# --------------------------------------------------------------------------- #
# Slots
# --------------------------------------------------------------------------- #
MONDAY = date(2026, 9, 28)      # Monday


def cfg(**over) -> slots.SlotConfig:
    base = dict(tz=TZ, work_days=frozenset(range(1, 7)), holidays=frozenset(),
                day_start=time(9, 0), day_end=time(16, 0), slot_minutes=30, capacity=1,
                days_ahead=7)
    base.update(over)
    return slots.SlotConfig(**base)


def local(day: date, hh: int, mm: int = 0) -> datetime:
    return datetime.combine(day, time(hh, mm), TZ)


def test_day_slots_start_every_30_min_last_before_end():
    got = [s.strftime("%H:%M") for s in slots.day_slots(MONDAY, cfg())]
    assert got[0] == "09:00" and got[-1] == "15:30" and len(got) == 14


def test_work_days_and_holidays_have_no_slots():
    sunday = date(2026, 10, 4)
    assert slots.day_slots(sunday, cfg()) == []
    assert slots.day_slots(MONDAY, cfg(holidays=frozenset({MONDAY}))) == []
    assert slots.parse_work_days("1-3,5") == frozenset({1, 2, 3, 5})
    assert slots.parse_work_days("1,2,3") == frozenset({1, 2, 3})
    assert slots.parse_holidays("2026-10-01, 2026-12-08\n2026-02-31") == frozenset(
        {date(2026, 10, 1), date(2026, 12, 8)})


def test_today_needs_60_minutes_lead_time():
    now = local(MONDAY, 9, 40).astimezone(timezone.utc)
    free = slots.free_slots(MONDAY, cfg(), Counter(), now)
    assert free[0][0].strftime("%H:%M") == "11:00"          # 10:40 + rounding to slot
    assert slots.is_bookable(local(MONDAY, 11), cfg(), now)
    assert not slots.is_bookable(local(MONDAY, 10, 30), cfg(), now)
    assert not slots.is_bookable(local(MONDAY, 11, 15), cfg(), now)   # not a slot start


def test_capacity_counts_scheduled_bookings():
    now = local(MONDAY, 7).astimezone(timezone.utc)
    taken = Counter({local(MONDAY, 9).astimezone(timezone.utc): 1})
    assert local(MONDAY, 9) not in [s for s, _ in slots.free_slots(MONDAY, cfg(), taken, now)]
    free = dict(slots.free_slots(MONDAY, cfg(capacity=2), taken, now))
    assert free[local(MONDAY, 9)] == 1 and free[local(MONDAY, 9, 30)] == 2


def test_bookable_days_window_skips_sunday_holiday_and_full_days():
    now = local(MONDAY, 7).astimezone(timezone.utc)
    tuesday = date(2026, 9, 29)
    full = Counter({s.astimezone(timezone.utc): 1 for s in slots.day_slots(tuesday, cfg())})
    days = slots.bookable_days(now, cfg(holidays=frozenset({date(2026, 10, 1)})), full)
    assert days == [MONDAY, date(2026, 9, 30), date(2026, 10, 2), date(2026, 10, 3)]
    # 7 calendar days including today: Mon..Sun, Sunday is not a work day
    assert slots.booking_window(now, cfg())[-1] == date(2026, 10, 4)


def test_slot_keys_roundtrip():
    start = local(MONDAY, 15, 30)
    assert slots.slot_key(start) == "202609281530"
    assert slots.parse_slot_key("202609281530", cfg()) == start
    assert slots.parse_slot_key("garbage", cfg()) is None
    assert slots.parse_day_key("20260928") == MONDAY


# --------------------------------------------------------------------------- #
# Texts
# --------------------------------------------------------------------------- #
def test_render_fills_and_drops_empty_placeholder_lines():
    template = "Salom {name}!\n📍 Manzil: {address}\n{unknown} qoladi\nOxiri"
    assert texts.render(template, name="Malika", address="") == \
        "Salom Malika!\n{unknown} qoladi\nOxiri"


def test_booking_values_are_local_uzbek():
    start = datetime(2026, 9, 26, 5, 0, tzinfo=timezone.utc)     # 10:00 Tashkent
    values = texts.booking_values("Ali", start)
    assert values["date"] == "26-sentabr" and values["weekday"] == "shanba"
    assert values["time"] == "10:00" and values["name"] == "Ali"


@pytest.mark.parametrize("typed,stored", [
    ("5", "5"), ("5-sinf", "5"), ("5 sinf", "5"), ("05", "5"), ("bog'cha", "Bog'cha"),
    ("tayyorlov", "tayyorlov"), ("", None), ("x" * 30, None), ("!!!", None),
])
def test_parse_grade(typed, stored):
    assert texts.parse_grade(typed) == stored


def test_grade_display_and_name_validation():
    assert texts.grade_display("7") == "7-sinf"
    assert texts.grade_display("Bog'cha") == "Bog'cha"
    assert texts.valid_name("  Aliyeva   Malika ") == "Aliyeva Malika"
    for bad in ("A", "12345", "", "x" * 81, "Ismim nima?", "Bir ikki uch tort besh"):
        assert texts.valid_name(bad) is None
    assert texts.valid_name("Abdullayeva Malika Anvar qizi") == "Abdullayeva Malika Anvar qizi"


def test_lock_eviction_keeps_locks_someone_waits_for(monkeypatch):
    """Evicting a just-released lock that still has a queued waiter would let a
    second task take a fresh lock for the same person at the same time."""
    import asyncio

    from app.funnel import locks

    monkeypatch.setattr(locks, "_MAX_IDLE", 2)

    async def go():
        first = locks.lock("tg:1")
        await first.acquire()
        waiter = asyncio.create_task(first.acquire())
        await asyncio.sleep(0)
        first.release()                    # unlocked, but the waiter is still queued
        for key in ("tg:2", "tg:3", "tg:4"):
            locks.lock(key)                # triggers eviction
        assert locks.lock("tg:1") is first
        await waiter
        first.release()

    asyncio.run(go())
