"""Fixed Uzbek strings of the funnel + template rendering and formatting helpers.

Editable texts (welcome, questions, captions, confirmation, reminder, ...) are
panel settings (`FUNNEL_*` in app.config); the short service strings below are
not worth a setting each.
"""
from __future__ import annotations

import re
from datetime import date, datetime
from zoneinfo import ZoneInfo

from app.config import settings

# --- Buttons ---------------------------------------------------------------------
FOLLOW_QUICK_REPLY = {"content_type": "text", "title": "✅ Obuna bo'ldim",
                      "payload": "FUNNEL_FOLLOW_CHECK"}
LINK_BUTTON = "📘 Qo'llanmani olish"            # Instagram button title: max 20 chars
SHARE_PHONE_BUTTON = "📱 Raqamni yuborish"
CHANNEL_BUTTON = "📢 Kanalga o'tish"
CHECK_BUTTON = "✅ Tekshirish"
RESCHEDULE_BUTTON = "🔁 Vaqtni o'zgartirish"
CANCEL_BUTTON = "❌ Bekor qilish"
BACK_BUTTON = "⬅️ Orqaga"

# --- Instagram -------------------------------------------------------------------
IG_TRY_LATER = ("Hozir obunani tekshira olmadim 🙏 Iltimos, birozdan so'ng «tayyor» deb "
                "yozing.")
IG_LINK_UNAVAILABLE = ("Kechirasiz, havolani hozir yubora olmadim 🙏 Iltimos, birozdan so'ng "
                       "«tayyor» deb yozing.")

# --- Telegram bot ----------------------------------------------------------------
NAME_INVALID = ("Iltimos, ism-familiyangizni harflar bilan yozing (masalan: Aliyeva Malika) "
                "✍️")
PHONE_INVALID = ("Raqam noto'g'ri ko'rinadi 🤔 Iltimos, +998 90 123 45 67 ko'rinishida yozing "
                 "yoki «📱 Raqamni yuborish» tugmasini bosing.")
PHONE_ACCEPTED = "Rahmat! ✅"
GRADE_INVALID = "Iltimos, pastdagi tugmalardan birini tanlang 👇"
PDF_PENDING = ("Qo'llanma tayyorlanmoqda — tez orada shu yerga yuboramiz 🙏 "
               "Savollaringiz bo'lsa, bemalol yozing.")
CHANNEL_GATE = ("Qo'llanmani olish uchun avval Telegram kanalimizga obuna bo'ling 👇\n"
                "So'ng «✅ Tekshirish» tugmasini bosing.")
CHANNEL_NOT_MEMBER = "Hali obuna bo'lmagansiz 🙏 Avval kanalga obuna bo'ling."
STOPPED = ("Xabarlar to'xtatildi. Qayta boshlash uchun /start ni bosing. Savollaringiz "
           "bo'lsa, bemalol yozing 😊")
START_FIRST = "Iltimos, avval /start ni bosing 🙂"

# --- Booking ---------------------------------------------------------------------
PICK_DATE = "Suhbat uchun qulay kunni tanlang 📅"
PICK_TIME = "{date} ({weekday}) — qulay vaqtni tanlang 🕐"
NO_FREE_DAYS = ("Afsuski, yaqin kunlarda bo'sh vaqt qolmadi 😔 Administratorimiz tez orada "
                "Siz bilan bog'lanadi.")
DAY_FULL = "Afsuski, bu kunda bo'sh vaqt qolmadi 😔 Boshqa kunni tanlang:"
SLOT_TAKEN = "Afsuski, bu vaqt band bo'ldi 😔 Boshqa vaqtni tanlang:"
SLOT_CHOSEN = "✅ Tanlandi: {date} ({weekday}), soat {time}"
ALREADY_BOOKED = ("Siz {date} ({weekday}) soat {time} ga suhbatga yozilgansiz ✅\n"
                  "Vaqtni o'zgartirish yoki bekor qilish mumkin 👇")
CANCELLED = ("Suhbat bekor qilindi. Boshqa vaqtga yozilmoqchi bo'lsangiz, pastdagi tugmani "
             "bosing 👇")
NOTHING_TO_CANCEL = "Sizda faol suhbat yo'q. Yozilish uchun pastdagi tugmani bosing 👇"

SOURCE_LABELS = {"instagram": "Instagram", "telegram_channel": "Telegram kanal",
                 "telegram_direct": "Telegram bot"}
BOOKING_LABELS = {"scheduled": "Rejalashtirilgan", "cancelled": "Bekor qilingan",
                  "attended": "Keldi", "no_show": "Kelmadi"}

_MONTHS = ("yanvar", "fevral", "mart", "aprel", "may", "iyun", "iyul", "avgust",
           "sentabr", "oktabr", "noyabr", "dekabr")
_WEEKDAYS = ("dushanba", "seshanba", "chorshanba", "payshanba", "juma", "shanba",
             "yakshanba")
_PLACEHOLDER = re.compile(r"\{(\w+)\}")


def render(template: str, **values: object) -> str:
    """Fill `{placeholders}`. Unknown ones stay as typed; a line whose placeholders
    are ALL empty is dropped (e.g. "📍 Manzil: {address}" before an address is set)."""
    lines: list[str] = []
    for line in (template or "").split("\n"):
        keys = [k for k in _PLACEHOLDER.findall(line) if k in values]
        if keys and all(not str(values[k] or "").strip() for k in keys):
            continue
        lines.append(_PLACEHOLDER.sub(
            lambda m: str(values[m[1]] or "") if m[1] in values else m[0], line))
    return "\n".join(lines).strip()


def tz() -> ZoneInfo:
    try:
        return ZoneInfo(settings.TIMEZONE or "Asia/Tashkent")
    except Exception:  # noqa: BLE001
        return ZoneInfo("Asia/Tashkent")


def local(dt: datetime) -> datetime:
    """Aware local time (SQLite returns naive UTC datetimes)."""
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=ZoneInfo("UTC"))
    return dt.astimezone(tz())


def day_label(day: date) -> str:
    """date(2026, 9, 26) -> "26-sentabr"."""
    return f"{day.day}-{_MONTHS[day.month - 1]}"


def weekday_label(day: date) -> str:
    return _WEEKDAYS[day.weekday()]


def booking_values(name: str | None, starts_at: datetime) -> dict[str, str]:
    """Placeholder values for FUNNEL_CONFIRM_TEXT / FUNNEL_REMINDER_TEXT."""
    at = local(starts_at)
    return {
        "name": (name or "").strip(),
        "date": day_label(at.date()),
        "weekday": weekday_label(at.date()),
        "time": at.strftime("%H:%M"),
        "staff_name": settings.FUNNEL_STAFF_NAME.strip(),
        "staff_phone": settings.FUNNEL_STAFF_PHONE.strip(),
        "address": settings.FUNNEL_ADDRESS.strip(),
    }


def grade_options() -> list[str]:
    return [g.strip() for g in (settings.FUNNEL_GRADES or "").split(",") if g.strip()]


def grade_display(grade: str | None) -> str:
    """"5" -> "5-sinf"; "Bog'cha" stays as is."""
    grade = (grade or "").strip()
    return f"{grade}-sinf" if grade.isdigit() else grade


def parse_grade(text: str) -> str | None:
    """Typed grade -> stored value: a listed option ("5-sinf" -> "5") or short free text."""
    raw = " ".join((text or "").split())
    if not raw or len(raw) > 20:
        return None
    options = grade_options()
    for option in options:
        if raw.casefold() in (option.casefold(), grade_display(option).casefold()):
            return option
    number = re.fullmatch(r"(\d{1,2})\s*[-–]?\s*(sinf|синф)?", raw, flags=re.IGNORECASE)
    if number and number[1].lstrip("0") in [o.lstrip("0") for o in options if o.isdigit()]:
        return str(int(number[1]))
    return raw if any(ch.isalnum() for ch in raw) else None


MAX_NAME_WORDS = 4


def valid_name(text: str) -> str | None:
    """2–80 characters, at least one letter, at most 4 words, no "?" — a question
    or a sentence is not a name. Whitespace collapsed."""
    name = " ".join((text or "").split())
    if (2 <= len(name) <= 80 and any(ch.isalpha() for ch in name) and "?" not in name
            and len(name.split()) <= MAX_NAME_WORDS):
        return name
    return None
