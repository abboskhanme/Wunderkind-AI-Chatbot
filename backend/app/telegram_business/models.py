"""Telegram update'ini bitta `IncomingEvent` ga aylantirish.

Instagram bilan bir xil `IncomingEvent` ishlatiladi — shunda pipeline (dedup,
xotira, AI, lead, operator pauzasi) ikkala kanal uchun BITTA bo'lib qoladi.
"""
from __future__ import annotations

from typing import Any, Optional

from app.instagram.models import IncomingEvent

# Matnsiz xabarlar — mazmunini o'qiy olmaymiz, lekin tarixda ko'rinishi kerak
_ATTACHMENT_LABELS: tuple[tuple[str, str], ...] = (
    ("photo", "rasm"),
    ("video", "video"),
    ("video_note", "video xabar"),
    ("voice", "ovozli xabar"),
    ("audio", "audio"),
    ("document", "fayl"),
    ("sticker", "stiker"),
    ("location", "lokatsiya"),
    ("contact", "kontakt"),
)


def message_text(msg: dict[str, Any]) -> tuple[str, bool]:
    """Xabar matni va matnsiz (media) ekanligi.

    Matn yoki caption bo'lsa — o'sha; aks holda "[Mijoz rasm yubordi]" kabi
    o'rinbosar matn (Instagramdagi bilan bir xil uslub).
    """
    text = (msg.get("text") or msg.get("caption") or "").strip()
    if text:
        return text, bool(msg.get("caption"))

    names: list[str] = []
    for key, label in _ATTACHMENT_LABELS:
        if msg.get(key) and label not in names:
            names.append(label)
    if not names:
        return "", False
    return f"[Mijoz {', '.join(names)} yubordi]", True


def event_from_message(
    msg: dict[str, Any], *, owner_id: Optional[int] = None
) -> Optional[IncomingEvent]:
    """Telegram xabaridan hodisa yasaydi.

    `owner_id` — Business ulanishidagi akkaunt egasi (ya'ni SIZ). Xabar undan
    chiqqan bo'lsa, bu operator qo'lda yozgani hisoblanadi → `echo`.
    """
    chat = msg.get("chat") or {}
    frm = msg.get("from") or {}
    if chat.get("type") != "private":
        return None                      # guruh/kanal — bu bot vazifasi emas
    if frm.get("is_bot"):
        return None

    text, has_attachment = message_text(msg)
    if not text:
        return None

    chat_id = str(chat.get("id") or "")
    from_id = str(frm.get("id") or "")
    conn_id = msg.get("business_connection_id")

    # Akkaunt egasi yozgan bo'lsa — operator aralashdi (mijoz emas).
    # Business chatida chat.id doim MIJOZ: undan boshqa har qanday yuboruvchi
    # (egasi yoki uning nomidan yozgan bot) — biz tomon. Faqat saqlangan
    # `owner_id` ga tayanish xavfli: u yo'qolsa bot o'z javobiga javob berib
    # cheksiz halqaga tushardi.
    is_owner = bool(
        (owner_id and str(owner_id) == from_id)
        or (conn_id and (msg.get("sender_business_bot") or (from_id and from_id != chat_id)))
    )
    kind = "echo" if is_owner else "dm"
    # echo'да "suhbatdosh" — mijoz, ya'ni chat egasi
    sender_id = chat_id if is_owner else from_id

    username = (frm.get("username") or "").strip() or None
    if is_owner:
        username = (chat.get("username") or "").strip() or None

    return IncomingEvent(
        kind=kind,
        text=text,
        sender_id=sender_id,
        channel="telegram",
        chat_id=chat_id,
        business_connection_id=conn_id,
        username=username,
        message_id=str(msg.get("message_id") or "") or None,
        has_attachment=has_attachment and not (msg.get("text") or msg.get("caption")),
    )


def parse_update(
    update: dict[str, Any], *, owner_id: Optional[int] = None
) -> list[IncomingEvent]:
    """Update ichidagi xabar(lar)ni hodisaga aylantiradi."""
    events: list[IncomingEvent] = []
    for key in ("business_message", "message"):
        msg = update.get(key)
        if not isinstance(msg, dict):
            continue
        ev = event_from_message(msg, owner_id=owner_id)
        if ev:
            events.append(ev)
    return events
