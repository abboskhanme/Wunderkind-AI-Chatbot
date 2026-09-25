"""Instagram webhook payloadini normalizatsiya qilish.

Meta payloadi murakkab va o'zgaruvchan — uni bitta sodda `IncomingEvent` ga
aylantiramiz, pipeline faqat shu bilan ishlaydi.
"""
from __future__ import annotations

import hashlib
from dataclasses import dataclass
from typing import Any

# Matnsiz xabarlar (ovoz, rasm, ...) endi tashlab yuborilmaydi — ular ham
# suhbat tarixiga tushadi, aks holda mijoz raqamini ovozda yuborsa yo'qolardi.
_ATTACHMENT_LABELS = {
    "image": "rasm",
    "video": "video",
    "audio": "ovozli xabar",
    "file": "fayl",
    "share": "post/reels",
    "story_mention": "story eslatmasi",
    "ig_reel": "reels",
    "location": "manzil",
}


def _attachment_text(attachments: list[dict]) -> str:
    """Matnsiz xabarni tarixda ko'rinadigan qisqa matnga aylantiradi."""
    names = []
    for att in attachments:
        label = _ATTACHMENT_LABELS.get(str(att.get("type") or "").lower(), "fayl")
        if label not in names:
            names.append(label)
    if not names:
        return ""
    return f"[Mijoz {', '.join(names)} yubordi]"


@dataclass
class IncomingEvent:
    kind: str  # "comment" | "dm" | "echo"
    text: str
    sender_id: str  # kanaldagi foydalanuvchi id (izoh/DM egasi; echo'da — mijoz)
    # Kanal: "instagram" | "telegram" | "whatsapp". Pipeline bitta — faqat
    # yuborish va jurnalga yozish kanalga qarab farq qiladi.
    channel: str = "instagram"
    # Telegram: qaysi chatga yozamiz va Business ulanishi identifikatori
    chat_id: str | None = None
    business_connection_id: str | None = None
    username: str | None = None
    comment_id: str | None = None
    media_id: str | None = None
    media_caption: str | None = None
    # Instagram xabar ID (mid) — dedup va suhbat jurnalidagi takrorni oldini oladi
    message_id: str | None = None
    # Matnsiz xabar (ovoz/rasm/...) — AI javobida hisobga olinadi
    has_attachment: bool = False

    # Kanal -> holat kaliti prefiksi (Instagram tarixiy sabablarga ko'ra prefikssiz)
    KEY_PREFIX = {"telegram": "tg:"}

    @property
    def store_key(self) -> str:
        """Redis holatidagi kalit — kanallar ID'lari to'qnashmasligi uchun."""
        return f"{self.KEY_PREFIX.get(self.channel, '')}{self.sender_id}"

    @property
    def dedup_key(self) -> str:
        prefix = self.KEY_PREFIX.get(self.channel, "")
        if prefix and self.message_id:
            return f"{prefix}{self.sender_id}:{self.message_id}"
        if self.comment_id:
            return f"comment:{self.comment_id}"
        if self.message_id:
            return f"msg:{self.message_id}"
        # hash() jarayonlar orasida turlicha bo'ladi — barqaror sha1 ishlatamiz
        digest = hashlib.sha1(self.text.encode()).hexdigest()[:16]
        return f"{self.kind}:{self.sender_id}:{digest}"


def parse_webhook(
    payload: dict[str, Any],
    self_ig_ids: set[str] | str,
    self_username: str = "",
) -> list[IncomingEvent]:
    """Meta 'instagram' webhook payloadidan hodisalarni ajratadi.

    `self_ig_ids` — BIZNING barcha ma'lum identifikatorlarimiz. Ataylab to'plam:
    Instagram bir joyda app-scoped `user_id`, boshqa joyda akkauntning o'z `id`
    sini beradi va webhook'da qaysi biri kelishiga ishonib bo'lmaydi. Bitta ID
    bilan solishtirish xavfli — mos kelmasa bot O'Z izohiga javob berib,
    cheksiz halqaga tushadi.

    `self_username` — o'sha zaxira tekshiruv: username Instagram'da yagona,
    shuning uchun ID formatlari qanday bo'lishidan qat'i nazar ishlaydi.
    """
    ids = {self_ig_ids} if isinstance(self_ig_ids, str) else set(self_ig_ids)
    ids = {str(i) for i in ids if i}
    me = (self_username or "").strip().lower()

    def _is_self(frm: dict) -> bool:
        if str(frm.get("id") or "") in ids:
            return True
        uname = (frm.get("username") or "").strip().lower()
        return bool(me and uname == me)

    events: list[IncomingEvent] = []
    for entry in payload.get("entry", []):
        # --- Izohlar (changes[].field == "comments") ---
        for change in entry.get("changes", []):
            if change.get("field") != "comments":
                continue
            value = change.get("value", {}) or {}
            frm = value.get("from", {}) or {}
            if _is_self(frm):
                continue  # o'z izohimiz — javob bermaymiz (halqadan saqlanish)
            text = (value.get("text") or "").strip()
            if not text:
                continue
            media = value.get("media", {}) or {}
            events.append(
                IncomingEvent(
                    kind="comment",
                    text=text,
                    sender_id=str(frm.get("id", "")),
                    username=frm.get("username"),
                    comment_id=str(value.get("id")) if value.get("id") else None,
                    media_id=str(media.get("id")) if media.get("id") else None,
                    media_caption=media.get("caption"),
                )
            )

        # --- DM'lar (messaging[]) ---
        for msg in entry.get("messaging", []):
            sender = str((msg.get("sender", {}) or {}).get("id") or "")
            recipient = str((msg.get("recipient", {}) or {}).get("id") or "")
            message = msg.get("message", {}) or {}
            text = (message.get("text") or "").strip()
            attachments = message.get("attachments") or []
            has_attachment = bool(attachments)
            if not text and has_attachment:
                text = _attachment_text(attachments)
            if not text:
                continue
            mid = str(message.get("mid") or "") or None

            # Echo — akkauntimizdan CHIQQAN xabar. Ikki manba bo'lishi mumkin:
            # botning o'zi yoki operator (telefondagi Instagram ilovasi).
            # Ikkinchisi bo'lsa botni o'sha suhbatda pauza qilamiz (pipeline hal qiladi).
            if message.get("is_echo") or (sender and sender in ids):
                events.append(
                    IncomingEvent(kind="echo", text=text, sender_id=recipient,
                                  message_id=mid)
                )
                continue

            events.append(IncomingEvent(
                kind="dm", text=text, sender_id=sender, message_id=mid,
                has_attachment=has_attachment,
            ))
    return events
