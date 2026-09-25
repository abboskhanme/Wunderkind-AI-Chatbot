"""Import existing Instagram conversations into the local conversation log.

Nima uchun kerak:
  • Webhook obunasi ishlamagan davrda (yoki "Requests" papkasida turgan)
    yozishmalar bizning tizimga umuman tushmagan.
  • Instagram Conversations API 30 kun ichida faol bo'lgan suhbatlarni
    (Requests papkasidagilarni ham) qaytaradi — shu oyna yopilgunicha
    hammasini bazaga ko'chirib olamiz.

Import qilingan suhbatlarga AI JAVOB YOZMAYDI: Instagram'da javob oynasi
mijozning oxirgi xabaridan 24 soat, eski suhbatlar bu oynadan chiqib ketgan.
Ular Leadlar bo'limida `source="instagram_import"` bilan turadi va xodim
qo'lda bog'lanadi.
"""
from __future__ import annotations

import asyncio

from loguru import logger

from app.config import settings
from app.instagram.client import instagram
from app.leads import client as leads_client

_SOURCE = "instagram_import"
_MAX_PAGES = 20          # zaxira cheklov (50 suhbat × 20 sahifa = 1000)
_MAX_MESSAGES = 50       # bitta suhbatdan olinadigan xabarlar


def _self_ids() -> set[str]:
    return {str(i) for i in (settings.IG_USER_ID, settings.IG_ACCOUNT_ID) if i}


def _other_participant(conv: dict) -> tuple[str | None, str | None]:
    """Suhbatdagi MIJOZ (biz emas) ishtirokchisining id va username'i."""
    ids = _self_ids()
    me = (settings.IG_USERNAME or "").strip().lower()
    for part in ((conv.get("participants") or {}).get("data") or []):
        pid = str(part.get("id") or "")
        uname = (part.get("username") or "").strip()
        if pid in ids or (me and uname.lower() == me):
            continue
        return pid or None, uname or None
    return None, None


async def _messages_of(conv: dict) -> list[dict]:
    """Suhbat xabarlari — nested javobdan yoki har birini alohida so'rab."""
    nested = ((conv.get("messages") or {}).get("data")) or []
    if nested and any("message" in m for m in nested):
        return nested[:_MAX_MESSAGES]

    out: list[dict] = []
    for item in nested[:_MAX_MESSAGES]:
        mid = item.get("id")
        if not mid:
            continue
        detail = await instagram.get_message(str(mid))
        if detail:
            out.append(detail)
    return out


async def import_conversations() -> dict:
    """Barcha mavjud suhbatlarni suhbat jurnaliga ko'chiradi.

    Qaytaradi: {"conversations": N, "messages": M, "skipped": K}
    """
    if not settings.IG_ACCESS_TOKEN:
        logger.error("Import: Instagram tokeni yo'q")
        return {"error": "instagram_not_connected"}

    ids = _self_ids()
    stats = {"conversations": 0, "messages": 0, "skipped": 0}
    after: str | None = None

    for page in range(_MAX_PAGES):
        data = await instagram.list_conversations(after)
        convs = data.get("data") or []
        if not convs:
            break

        for conv in convs:
            user_id, username = _other_participant(conv)
            if not user_id:
                stats["skipped"] += 1
                continue

            messages = await _messages_of(conv)
            # Instagram eng yangisidan beradi — tarix to'g'ri tartibda yozilsin
            messages = sorted(messages, key=lambda m: m.get("created_time") or "")

            wrote = 0
            for msg in messages:
                text = (msg.get("message") or "").strip()
                if not text:
                    continue
                sender = str(((msg.get("from") or {}).get("id")) or "")
                role = "operator" if sender in ids else "user"
                ok = await leads_client.log_message(
                    user_id=user_id,
                    username=username,
                    channel="instagram",
                    text=text,
                    role=role,
                    kind="dm",
                    ig_message_id=str(msg.get("id") or "") or None,
                    sent_at=msg.get("created_time"),
                    source=_SOURCE,
                )
                if ok:
                    wrote += 1

            if wrote:
                stats["conversations"] += 1
                stats["messages"] += wrote
            else:
                stats["skipped"] += 1

        after = (((data.get("paging") or {}).get("cursors") or {}).get("after"))
        if not after or not (data.get("paging") or {}).get("next"):
            break
        await asyncio.sleep(0.5)

    logger.info(
        "Instagram import tugadi: {} suhbat, {} xabar ({} o'tkazib yuborildi)",
        stats["conversations"], stats["messages"], stats["skipped"],
    )
    return stats


async def import_and_notify() -> None:
    """Fon rejimida import + Telegram'ga natija (uzoq davom etishi mumkin)."""
    try:
        stats = await import_conversations()
    except Exception as exc:  # noqa: BLE001
        logger.exception("Import xatosi: {}", exc)
        stats = {"error": str(exc)}

    try:
        from app.telegram.notifier import _send as send_text

        if stats.get("error"):
            await send_text(f"❌ Instagram import xatosi: {stats['error']}")
        else:
            await send_text(
                "✅ Instagram suhbatlari import qilindi\n"
                f"Suhbatlar: {stats['conversations']}\n"
                f"Xabarlar: {stats['messages']}\n"
                "Suhbatlar bo'limida «instagram_import» manbasi bilan ko'rinadi."
            )
    except Exception as exc:  # noqa: BLE001
        logger.warning("Import natijasini yuborib bo'lmadi: {}", exc)
