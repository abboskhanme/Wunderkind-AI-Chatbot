"""Form field definitions and answer validation (SPEC §15.1, §15.3).

Field definitions come from the admin panel (cleaned by `clean_fields`); answers
come from the public page (checked by `validate_answers`). Error texts are Uzbek:
they are shown to the admin or to the person filling the form.
"""
from __future__ import annotations

import re
import secrets
from dataclasses import dataclass, field
from datetime import date
from typing import Any, Mapping, Optional, Sequence

from app.models.form import CHOICE_TYPES, FIELD_TYPES, LEAD_FIELDS, MAX_FIELDS, MAX_OPTIONS
from app.services.phone import extract_phone

TYPE_LABELS = {
    "short_text": "Qisqa javob", "long_text": "Uzun javob", "phone": "Telefon",
    "email": "Email", "number": "Raqam", "date": "Sana", "single_choice": "Bitta tanlov",
    "multiple_choice": "Bir nechta tanlov", "dropdown": "Ro'yxatdan tanlash",
}
MAX_LENGTH = {"short_text": 500, "long_text": 5000}
_ID_RE = re.compile(r"^[a-z0-9]{1,16}$")
_EMAIL_RE = re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]+$")
_NUMBER_RE = re.compile(r"^-?\d{1,15}([.,]\d{1,6})?$")


def new_field_id() -> str:
    return secrets.token_hex(4)


def default_fields() -> list[dict[str, Any]]:
    """A new form starts with the two questions every lead needs."""
    return [
        {"id": new_field_id(), "type": "short_text", "label": "Ism-familiya", "required": True,
         "placeholder": "", "help": "", "lead_field": "name"},
        {"id": new_field_id(), "type": "phone", "label": "Telefon raqam", "required": True,
         "placeholder": "+998 90 123 45 67", "help": "", "lead_field": "phone"},
    ]


def _text(value: Any, limit: int) -> str:
    return str(value or "").strip()[:limit]


def clean_fields(raw: Sequence[Mapping[str, Any]]) -> list[dict[str, Any]]:
    """Normalized field list; ValueError (Uzbek) when the definition is unusable."""
    if not raw:
        raise ValueError("Formada kamida bitta savol bo'lishi kerak")
    if len(raw) > MAX_FIELDS:
        raise ValueError(f"Savollar {MAX_FIELDS} tadan ko'p bo'lmasin")
    out: list[dict[str, Any]] = []
    ids: set[str] = set()
    lead_fields: set[str] = set()
    for n, item in enumerate(raw, start=1):
        field_id = str(item.get("id") or "").strip().lower() or new_field_id()
        if not _ID_RE.match(field_id) or field_id in ids:
            field_id = new_field_id()
        ids.add(field_id)
        kind = item.get("type")
        if kind not in FIELD_TYPES:
            raise ValueError(f"{n}-savol: turi noto'g'ri")
        label = _text(item.get("label"), 300)
        if not label:
            raise ValueError(f"{n}-savol: savol matnini yozing")
        clean: dict[str, Any] = {
            "id": field_id, "type": kind, "label": label,
            "required": bool(item.get("required")),
            "placeholder": _text(item.get("placeholder"), 120),
            "help": _text(item.get("help"), 500),
        }
        if kind in CHOICE_TYPES:
            options: list[str] = []
            for option in item.get("options") or []:
                option = _text(option, 200)
                if option and option not in options:
                    options.append(option)
            if not options:
                raise ValueError(f"{n}-savol («{label}»): kamida bitta variant kiriting")
            if len(options) > MAX_OPTIONS:
                raise ValueError(f"{n}-savol («{label}»): variantlar {MAX_OPTIONS} tadan "
                                 "ko'p bo'lmasin")
            clean["options"] = options
        lead_field = item.get("lead_field") or None
        if lead_field is not None:
            if lead_field not in LEAD_FIELDS:
                raise ValueError(f"{n}-savol: lead maydoni noto'g'ri")
            if lead_field in lead_fields:
                raise ValueError(f"{n}-savol («{label}»): bu lead maydoni boshqa savolga "
                                 "ham berilgan")
            if kind == "multiple_choice":
                raise ValueError(f"{n}-savol («{label}»): bir nechta tanlovli savolni lead "
                                 "maydoniga bog'lab bo'lmaydi")
            lead_fields.add(lead_field)
        clean["lead_field"] = lead_field
        out.append(clean)
    return out


@dataclass
class Checked:
    """Result of checking one submission."""

    # [{field_id, label, type, value}] — only answered fields
    answers: list[dict[str, Any]] = field(default_factory=list)
    # field id -> error text for the page
    errors: dict[str, str] = field(default_factory=dict)
    # field id -> what the person typed (re-render after an error)
    values: dict[str, Any] = field(default_factory=dict)
    # Lead columns from answers mapped with lead_field ("phone" → normalized)
    lead: dict[str, str] = field(default_factory=dict)


def _one(value: Any) -> str:
    if isinstance(value, (list, tuple)):
        value = value[0] if value else ""
    return str(value or "").strip()


def validate_answers(fields: Sequence[Mapping[str, Any]],
                     data: Mapping[str, Any]) -> Checked:
    """`data`: field id -> str (or list[str] for multiple_choice)."""
    result = Checked()
    for spec in fields:
        field_id, kind = spec["id"], spec["type"]
        raw = data.get(field_id)
        if kind == "multiple_choice":
            chosen = raw if isinstance(raw, (list, tuple)) else ([raw] if raw else [])
            picked = [o for o in spec.get("options", []) if o in {str(c) for c in chosen}]
            result.values[field_id] = picked
            if len({str(c) for c in chosen if c}) != len(picked):
                result.errors[field_id] = "Ro'yxatdagi variantlardan tanlang"
            elif not picked and spec.get("required"):
                result.errors[field_id] = "Kamida bittasini tanlang"
            elif picked:
                result.answers.append(_answer(spec, picked))
            continue

        text = _one(raw)
        result.values[field_id] = text
        if not text:
            if spec.get("required"):
                result.errors[field_id] = "Bu savolga javob bering"
            continue
        value: Optional[str] = text
        error: Optional[str] = None
        if kind in MAX_LENGTH and len(text) > MAX_LENGTH[kind]:
            error = f"Javob {MAX_LENGTH[kind]} belgidan oshmasin"
        elif kind == "phone":
            value = extract_phone(text)
            if not value:
                error = "Telefon raqamni to'liq kiriting, masalan +998 90 123 45 67"
        elif kind == "email":
            if len(text) > 254 or not _EMAIL_RE.match(text):
                error = "Email manzilni to'g'ri kiriting, masalan ism@gmail.com"
        elif kind == "number":
            if not _NUMBER_RE.match(text):
                error = "Faqat raqam kiriting"
        elif kind == "date":
            try:
                date.fromisoformat(text)
            except ValueError:
                error = "Sanani tanlang"
        elif kind in ("single_choice", "dropdown"):
            if text not in spec.get("options", []):
                error = "Ro'yxatdagi variantlardan tanlang"
        if error:
            result.errors[field_id] = error
            continue
        result.answers.append(_answer(spec, value))
        if spec.get("lead_field"):
            result.lead[spec["lead_field"]] = str(value)
    return result


def _answer(spec: Mapping[str, Any], value: Any) -> dict[str, Any]:
    return {"field_id": spec["id"], "label": spec["label"], "type": spec["type"],
            "value": value}


def display(value: Any) -> str:
    """An answer as one line of text."""
    if isinstance(value, (list, tuple)):
        return ", ".join(str(v) for v in value)
    return str(value if value is not None else "")
