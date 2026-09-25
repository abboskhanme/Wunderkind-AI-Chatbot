"""Follow-up: one gentle reminder when a customer goes silent mid-conversation.

Runs on a scheduler. A lead qualifies when:
  * the last message in the chat is ours (assistant), i.e. we asked and wait;
  * the customer's last message is older than FOLLOWUP_AFTER_HOURS;
  * we have no phone number yet (after that staff take over by phone);
  * no follow-up was sent since the customer last wrote;
  * the channel still allows us to write (Instagram: 24h after the customer's
    last message; Telegram: 3 days, to stay polite);
  * the lead is open and the bot is not paused in that chat.
"""
from __future__ import annotations

from datetime import datetime, timedelta, timezone

from loguru import logger
from sqlalchemy import select, update

from app.config import settings
from app.db import session as db_session
from app.instagram.client import instagram
from app.instagram.models import IncomingEvent
from app.leads import client as leads_client
from app.models.lead import CLOSED_STATUSES, Lead, LeadMessage
from app.processing.pipeline import _agent, ai_enabled_for, conversation_lock
from app.state.store import store
from app.telegram_business.client import telegram

# Instagram: free-form messages only within 24h of the customer's last message
_WINDOW = {"instagram": timedelta(hours=23), "telegram": timedelta(days=3)}
_BATCH = 20


def _task(hours: float) -> str:
    return (
        f"Mijoz taxminan {int(hours)} soatdan beri javob bermadi. Suhbat davomida "
        "BITTA qisqa, iliq eslatma yoz: oxirgi savolingni yoki bepul sinov darsi "
        "taklifini eslat va javob berish oson bo'lgan savol bilan tugat."
    )


async def due_leads(now: datetime | None = None) -> list[Lead]:
    now = now or datetime.now(timezone.utc)
    after = timedelta(hours=max(1, int(settings.FOLLOWUP_AFTER_HOURS or 3)))
    oldest = now - max(_WINDOW.values())
    async with db_session.SessionLocal() as db:
        leads = (await db.execute(
            select(Lead).where(
                Lead.status.notin_(CLOSED_STATUSES),
                Lead.contact.is_(None),
                Lead.last_followup_at.is_(None),
                Lead.last_customer_at.is_not(None),
                Lead.last_customer_at <= now - after,
                Lead.last_customer_at >= oldest,
            ).order_by(Lead.last_customer_at.desc()).limit(_BATCH * 3)
        )).scalars().all()

        due: list[Lead] = []
        for lead in leads:
            last_customer = _aware(lead.last_customer_at)
            if now - last_customer > _WINDOW.get(lead.channel, _WINDOW["instagram"]):
                continue
            last = (await db.execute(
                select(LeadMessage.role, LeadMessage.kind)
                .where(LeadMessage.lead_id == lead.id, LeadMessage.kind.in_(("dm", "comment")))
                .order_by(LeadMessage.created_at.desc()).limit(1)
            )).first()
            # Only DM conversations where we spoke last
            if not last or last.role != "assistant" or last.kind != "dm":
                continue
            due.append(lead)
            if len(due) >= _BATCH:
                break
        return due


async def send_followup(lead: Lead) -> bool:
    event = IncomingEvent(kind="dm", text="", sender_id=lead.external_id,
                          channel=lead.channel, chat_id=lead.external_id,
                          username=lead.username)
    if await store.is_paused(event.store_key):
        return False
    ctx = await leads_client.fetch_context(lead.external_id, channel=lead.channel) or {}
    history = ctx.get("messages") or []
    # The customer may have written meanwhile — then the pipeline answers, not us
    if not history or history[-1].get("role") != "assistant":
        return False
    hours = (datetime.now(timezone.utc) - _aware(lead.last_customer_at)).total_seconds() / 3600
    try:
        out = await _agent.handle(
            "", is_comment=False, username=lead.username,
            history=history,
            known={k: ctx.get(k) for k in ("name", "contact", "course_interest",
                                           "student_age", "preferred_time", "summary")},
            channel=lead.channel, task=_task(hours),
        )
    except Exception as exc:  # noqa: BLE001
        logger.warning("Follow-up generation failed ({}): {}", lead.id, exc)
        return False

    text = out.reply.strip()
    if not text:
        return False
    await store.mark_sent(event.store_key, text)
    if lead.channel == "telegram":
        from app.telegram_business.webhook import connection_for_chat

        conn_id = await connection_for_chat(lead.external_id)
        sent = (await telegram.send_message(lead.external_id, text,
                                            business_connection_id=conn_id)).get("sent")
    else:
        sent = (await instagram.send_dm_result(
            lead.external_id, text, allow_tag_fallback=False)).get("sent")
    if not sent:
        logger.info("Follow-up not delivered: lead={}", lead.id)
        return False
    await leads_client.log_message(
        user_id=lead.external_id, username=lead.username, channel=lead.channel,
        text=text, role="assistant", kind="dm", meta={"followup": True},
    )
    return True


async def run_followups() -> int:
    """Scheduler entry point. Returns the number of follow-ups sent."""
    if not settings.FOLLOWUP_ENABLED:
        return 0
    sent = 0
    try:
        leads = await due_leads()
    except Exception as exc:  # noqa: BLE001
        logger.warning("Follow-up query failed: {}", exc)
        return 0
    for lead in leads:
        if not ai_enabled_for(lead.channel):
            continue
        # Mark first, atomically: only if nothing changed since due_leads() —
        # a crash mid-send or a new customer message must not cause a double.
        async with db_session.SessionLocal() as db:
            result = await db.execute(
                update(Lead)
                .where(Lead.id == lead.id, Lead.last_followup_at.is_(None),
                       Lead.last_customer_at == lead.last_customer_at)
                .values(last_followup_at=datetime.now(timezone.utc))
            )
            await db.commit()
            if result.rowcount != 1:
                continue
        async with conversation_lock(f"tg:{lead.external_id}" if lead.channel == "telegram"
                                     else lead.external_id):
            if await send_followup(lead):
                sent += 1
    if sent:
        logger.info("Follow-ups sent: {}", sent)
    return sent


def _aware(dt: datetime) -> datetime:
    return dt if dt.tzinfo else dt.replace(tzinfo=timezone.utc)
