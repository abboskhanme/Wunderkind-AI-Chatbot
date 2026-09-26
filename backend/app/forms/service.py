"""A form submission → a lead (SPEC §15.2).

Every submission is stored with its answers; its lead is the person's open lead
of the SAME form with the same phone (filling a form twice updates, not
duplicates), or a new lead with channel "form" and this form as its source.
"""
from __future__ import annotations

import html
import re
import uuid
from datetime import datetime, timezone
from typing import Any, Optional

from loguru import logger
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import settings
from app.db import session as db_session
from app.forms.fields import Checked, display
from app.funnel import funnels
from app.models.form import Form, FormSubmission
from app.models.lead import CLOSED_STATUSES, Lead, LeadMessage
from app.telegram import notifier

FORM_CHANNEL = "form"
FORM_SOURCE = "form"
LEAD_SCORE = 50
SLUG_RE = re.compile(r"^[a-z0-9][a-z0-9-]{0,39}$")
DEFAULT_SUCCESS = "Rahmat! Javobingiz qabul qilindi. Tez orada siz bilan bog'lanamiz."
_ALERT_LIMIT = 3500
# Lead column per lead_field, with its length
_LEAD_COLUMNS = {"name": ("name", 255), "phone": ("contact", 64),
                 "student_age": ("student_age", 64), "course_interest": ("course_interest", 255),
                 "preferred_time": ("preferred_time", 255)}


def now() -> datetime:
    return datetime.now(timezone.utc)


def public_url(slug: str) -> str:
    base = settings.PUBLIC_URL.rstrip("/") if settings.PUBLIC_URL else ""
    return f"{base}/f/{slug}"


def slug_base(title: str) -> str:
    """"Yozgi lager 2026" -> "yozgi-lager-2026" (same transliteration as funnels)."""
    base = funnels.slugify(title).replace("_", "-")[:36].strip("-")
    if base == "voronka" and "voronka" not in (title or "").lower():
        base = "forma"        # funnels.slugify's fallback for titles with no letters
    return base or "forma"


async def unique_slug(db: AsyncSession, base: str) -> str:
    taken = set((await db.execute(
        select(Form.slug).where(Form.slug.like(f"{base}%")))).scalars().all())
    if base not in taken:
        return base
    for n in range(2, 1000):
        candidate = f"{base[:36]}-{n}"
        if candidate not in taken:
            return candidate
    return f"{base[:30]}-{uuid.uuid4().hex[:8]}"


def log_text(form: Form, answers: list[dict[str, Any]]) -> str:
    lines = [f"📝 Forma to'ldirildi: «{form.title}»"]
    lines += [f"{a['label']}: {display(a['value'])}" for a in answers]
    return "\n".join(lines)


async def _lead_for(db: AsyncSession, form: Form, phone: Optional[str],
                    submission_id: uuid.UUID) -> tuple[Lead, bool]:
    """(lead, existed): the open lead of this form with this phone, or a new one."""
    if phone:
        lead = (await db.execute(
            select(Lead).where(Lead.channel == FORM_CHANNEL, Lead.form_id == form.id,
                               Lead.contact == phone, Lead.status.notin_(CLOSED_STATUSES))
            .order_by(Lead.created_at.desc()).limit(1)
        )).scalar_one_or_none()
        if lead is not None:
            return lead, True
    lead = Lead(channel=FORM_CHANNEL, external_id=submission_id.hex, source=FORM_SOURCE,
                form_id=form.id, status="new", lead_score=0, extra={})
    db.add(lead)
    return lead, False


async def submit(form_id: uuid.UUID, checked: Checked, utm: dict[str, str], *,
                 alert: bool = True) -> Optional[FormSubmission]:
    """Store the submission, create/update its lead, alert staff (unless `alert`
    is False — throttled). None when the form disappeared meanwhile."""
    async with db_session.SessionLocal() as db:
        form = await db.get(Form, form_id)
        if form is None:
            return None
        submission_id = uuid.uuid4()
        at = now()
        lead, existed = await _lead_for(db, form, checked.lead.get("phone"), submission_id)
        for key, value in checked.lead.items():
            column, limit = _LEAD_COLUMNS[key]
            # Someone who knows the phone must not overwrite what staff corrected;
            # the new answers are in the submission and the log line anyway
            if not existed or not getattr(lead, column):
                setattr(lead, column, value[:limit])
        lead.lead_score = max(lead.lead_score or 0, LEAD_SCORE)
        lead.last_message_at = at
        await db.flush()
        submission = FormSubmission(id=submission_id, form_id=form.id, lead_id=lead.id,
                                    answers=checked.answers, utm=utm, created_at=at)
        db.add(submission)
        db.add(LeadMessage(lead_id=lead.id, kind="status", role="system", created_at=at,
                           text=log_text(form, checked.answers),
                           meta={"form_id": str(form.id), "submission_id": str(submission_id)}))
        await db.commit()
        title, notify, lead_id = form.title, form.notify, lead.id
    logger.info("Form {} submitted → lead {}", form_id, lead_id)
    if notify and alert:
        await _alert(title, checked.answers, lead_id, utm)
    return submission


def _short(text: str, limit: int = 300) -> str:
    return text if len(text) <= limit else text[:limit] + "…"


async def _alert(title: str, answers: list[dict[str, Any]], lead_id: uuid.UUID,
                 utm: dict[str, str]) -> None:
    lines = [f"📝 <b>Yangi forma javobi</b> — «{html.escape(title)}»"]
    size = len(lines[0])
    for a in answers:
        # Cut the plain values, never the HTML (a cut tag breaks Telegram's parser)
        line = (f"<b>{html.escape(a['label'][:100])}:</b> "
                f"{html.escape(_short(display(a['value'])))}")
        if size + len(line) > _ALERT_LIMIT:
            lines.append("…")
            break
        lines.append(line)
        size += len(line) + 1
    if utm:
        lines.append("Manba: " + html.escape(_short(", ".join(f"{k}={v}" for k, v in utm.items()))))
    text = "\n".join(lines)
    if settings.PUBLIC_URL:
        text += f"\n{settings.PUBLIC_URL.rstrip('/')}/leads?lead={lead_id}"
    try:
        await notifier.send_text(text)
    except Exception as exc:  # noqa: BLE001 — the submission is already saved
        logger.warning("Form alert failed: {}", exc)
