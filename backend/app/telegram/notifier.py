"""Telegram staff alerts — hot lead, escalation, daily report, problems.

Sent with TELEGRAM_BOT_TOKEN, or the sales bot token when that is empty
(plain sendMessage does not conflict with the sales bot's webhook).
The daily report is computed from the database, so restarts lose nothing.
"""
from __future__ import annotations

import html
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo

import httpx
from loguru import logger
from sqlalchemy import func, select

from app.config import settings
from app.models_ai import AgentOutput, LeadPayload

_CHANNEL_ICONS = {"instagram": "📸 Instagram", "telegram": "✈️ Telegram"}


def chat_ids(value: str) -> list[str]:
    """"123, 456; -100789" -> ["123", "456", "-100789"]."""
    parts = (value or "").replace(";", ",").replace("\n", ",").split(",")
    out: list[str] = []
    for part in parts:
        part = part.strip()
        if part and part not in out:
            out.append(part)
    return out


def _esc(value: object) -> str:
    return html.escape(str(value))


async def send_text(text: str) -> dict:
    """Send to every recipient. Returns {"sent": bool, "error": str|None}."""
    token = settings.alert_bot_token
    targets = chat_ids(settings.TELEGRAM_CHAT_ID)
    if not token or not targets:
        logger.debug("Telegram alerts not configured — skipped")
        return {"sent": False, "error": "Bot tokeni yoki chat ID sozlanmagan"}
    url = f"{settings.TG_API_BASE.rstrip('/')}/bot{token}/sendMessage"
    errors: list[str] = []
    async with httpx.AsyncClient(timeout=10.0) as client:
        for chat_id in targets:
            try:
                resp = await client.post(url, json={
                    "chat_id": chat_id, "text": text, "parse_mode": "HTML",
                    "disable_web_page_preview": True,
                })
                if resp.status_code != 200:
                    desc = (resp.json() or {}).get("description", resp.text[:120])
                    errors.append(f"{chat_id}: {desc}")
                    logger.warning("Telegram alert {} (chat {}): {}",
                                   resp.status_code, chat_id, resp.text[:200])
            except (httpx.HTTPError, ValueError) as exc:
                errors.append(f"{chat_id}: {exc}")
                logger.warning("Telegram alert failed (chat {}): {}", chat_id, exc)
    if len(errors) == len(targets):
        return {"sent": False, "error": "; ".join(errors)}
    return {"sent": True, "error": "; ".join(errors) or None}


# Backwards-compatible alias used by the ported importer
_send = send_text


async def notify_hot_lead(username: str | None, out: AgentOutput, *,
                          channel: str = "instagram", known: dict | None = None) -> None:
    known = known or {}
    who = f"@{username}" if username else "mijoz"
    title = "⚠️ <b>Administrator kerak</b>" if out.escalate_to_human and not out.is_hot_lead \
        else "🔥 <b>Qaynoq lead!</b>"
    lines = [
        title,
        f"{_CHANNEL_ICONS.get(channel, channel)} · {_esc(who)}",
        f"Ball: {out.lead_score}/100 · bosqich: {_esc(out.stage)}",
    ]
    fields = (
        ("Ism", out.lead.name or known.get("name")),
        ("Telefon", out.lead.contact or known.get("contact")),
        ("Kurs", out.lead.course_interest or known.get("course_interest")),
        ("Yosh/daraja", out.lead.student_age or known.get("student_age")),
        ("Qulay vaqt", out.lead.preferred_time or known.get("preferred_time")),
        ("Xulosa", out.lead.summary),
    )
    lines += [f"{label}: {_esc(value)}" for label, value in fields if value]
    if out.escalate_to_human:
        lines.append("👉 Suhbatlar bo'limida javob bering")
    if settings.PUBLIC_URL:
        lines.append(f"{settings.PUBLIC_URL.rstrip('/')}/inbox")
    await send_text("\n".join(lines))


async def notify_ingest_failed(payload: LeadPayload) -> None:
    await send_text(
        "❌ <b>Leadni bazaga yozib bo'lmadi</b> (qo'lda kiriting)\n"
        f"Kimdan: {_esc(payload.username or payload.user_id)}\n"
        f"Telefon: {_esc(payload.contact or '-')}\n"
        f"Kurs: {_esc(payload.course_interest or '-')}"
    )


async def notify_comments_throttled(media: str, count: int, minutes: int) -> None:
    where = "bitta post ostida" if media != "all" else "umuman akkauntda"
    await send_text(
        f"⏳ <b>Izohlar ko'p</b>\n{where} {minutes} daqiqada {count} ta izoh keldi.\n"
        "Javoblar navbatga qo'yildi — oyna bo'shagach avtomatik yuboriladi."
    )


async def notify_token_problem(detail: str) -> None:
    await send_text(
        "⚠️ <b>Instagram tokenini yangilab bo'lmadi</b>\n"
        "Akkauntni qayta ulang: Admin panel → Sozlamalar → Instagram → «Qayta ulash».\n"
        f"Tafsilot: <code>{_esc(detail)}</code>"
    )


async def daily_stats(since: datetime) -> dict[str, int]:
    from app.db import session as db_session
    from app.models.lead import Lead, LeadMessage

    async with db_session.SessionLocal() as db:
        conversations = (await db.execute(
            select(func.count(func.distinct(LeadMessage.lead_id)))
            .where(LeadMessage.created_at >= since, LeadMessage.role == "user")
        )).scalar() or 0
        ai_replies = (await db.execute(
            select(func.count()).select_from(LeadMessage)
            .where(LeadMessage.created_at >= since, LeadMessage.role == "assistant")
        )).scalar() or 0
        new_leads = (await db.execute(
            select(func.count()).select_from(Lead).where(Lead.created_at >= since)
        )).scalar() or 0
        with_contact = (await db.execute(
            select(func.count()).select_from(Lead)
            .where(Lead.updated_at >= since, Lead.contact.is_not(None))
        )).scalar() or 0
        hot = (await db.execute(
            select(func.count()).select_from(Lead)
            .where(Lead.updated_at >= since, Lead.lead_score >= 85)
        )).scalar() or 0
    return {"conversations": conversations, "ai_replies": ai_replies,
            "new_leads": new_leads, "with_contact": with_contact, "hot": hot}


async def send_daily_report() -> None:
    tz = ZoneInfo(settings.TIMEZONE or "Asia/Tashkent")
    now = datetime.now(tz)
    since = (now - timedelta(hours=24)).astimezone(ZoneInfo("UTC"))
    try:
        s = await daily_stats(since)
    except Exception as exc:  # noqa: BLE001
        logger.warning("Daily report failed: {}", exc)
        return
    await send_text(
        f"📊 <b>AI agent — kunlik hisobot</b> ({now:%d.%m.%Y})\n"
        f"💬 Suhbatlar: {s['conversations']}\n"
        f"🤖 AI javoblari: {s['ai_replies']}\n"
        f"🆕 Yangi leadlar: {s['new_leads']}\n"
        f"📞 Telefon qoldirganlar: {s['with_contact']}\n"
        f"🔥 Qaynoq leadlar: {s['hot']}"
    )
