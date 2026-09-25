"""Telegram Bot API klienti — shaxsiy chatlarga AI javob berish uchun.

Instagram klientidan farqi: bu yerda javob oynasi cheklovi YO'Q, ya'ni
istalgan vaqtda yozish mumkin. Business ulanishida xabar
`business_connection_id` bilan yuboriladi — shunda mijoz javobni "bot"dan
emas, AKKAUNT EGASIDAN (sizdan) kelgan deb ko'radi.
"""
from __future__ import annotations

import asyncio
import json
from typing import Union

import httpx
from loguru import logger

from app.config import settings

_TIMEOUT = 20.0
# Rasm yuklash sekinroq bo'lishi mumkin (albomda 10 tagacha rasm)
_UPLOAD_TIMEOUT = 60.0

# Rasm: Telegram'dagi `file_id` (qayta yuklamasdan) yoki (baytlar, MIME turi)
PhotoInput = Union[str, tuple[bytes, str]]
# File: cached `file_id` or (bytes, filename, MIME type)
DocumentInput = Union[str, tuple[bytes, str, str]]

_EXT = {"image/png": "png", "image/webp": "webp"}


def _as_upload(name: str, photo: tuple[bytes, str]) -> tuple[str, bytes, str]:
    data, content_type = photo
    return (f"{name}.{_EXT.get(content_type, 'jpg')}", data, content_type)


def _largest_file_id(message: dict) -> str:
    sizes = message.get("photo") or []
    return str(sizes[-1].get("file_id") or "") if sizes else ""


class TelegramClient:
    @property
    def _base(self) -> str:
        # Qiymatlar har chaqiruvda o'qiladi — admin panelda sozlama o'zgarsa
        # agent restartsiz yangi tokenga o'tadi.
        base = settings.TG_API_BASE.rstrip("/")
        return f"{base}/bot{settings.TG_SALES_BOT_TOKEN}"

    @property
    def enabled(self) -> bool:
        return bool(settings.TG_SALES_BOT_TOKEN)

    async def _call(
        self, method: str, payload: dict, *, files: dict | None = None
    ) -> tuple[bool, dict]:
        """Bitta so'rov: (muvaffaqiyat, javob/xato).

        `files` berilsa so'rov multipart bo'ladi (rasm yuklash) — murakkab
        maydonlar (klaviatura, albom ro'yxati) JSON satr sifatida ketadi.
        """
        if not settings.TG_SALES_BOT_TOKEN:
            return False, {"description": "TG_SALES_BOT_TOKEN sozlanmagan"}
        url = f"{self._base}/{method}"
        delay = 1.0
        for attempt in range(3):
            try:
                if files:
                    form = {k: v if isinstance(v, str) else json.dumps(v)
                            for k, v in payload.items() if v is not None}
                    async with httpx.AsyncClient(timeout=_UPLOAD_TIMEOUT) as client:
                        resp = await client.post(url, data=form, files=files)
                else:
                    async with httpx.AsyncClient(timeout=_TIMEOUT) as client:
                        resp = await client.post(url, json=payload)
                data = resp.json() if resp.content else {}
                if resp.status_code == 200 and data.get("ok"):
                    result = data.get("result")
                    return True, result if result is not None else {}
                # 429 / 5xx — kutib qayta urinamiz
                if resp.status_code in (429, 500, 502, 503):
                    wait = float(
                        (data.get("parameters") or {}).get("retry_after") or delay
                    )
                    logger.warning("TG {} {} ({}-urinish), {}s kutamiz: {}",
                                   method, resp.status_code, attempt + 1, wait,
                                   str(data)[:200])
                    await asyncio.sleep(wait)
                    delay *= 2
                    continue
                return False, data
            except httpx.HTTPError as exc:
                # Rasm yuklashda javob kutish vaqti tugasa Telegram rasmni
                # allaqachon yuborgan bo'lishi mumkin — qayta urinsak mijoz
                # albomni ikki marta oladi. Faqat so'rov umuman yetib bormagan
                # (ulanish xatosi) holatda qayta urinamiz.
                if files and not isinstance(exc, (httpx.ConnectError, httpx.ConnectTimeout)):
                    logger.warning("TG {} javobi kelmadi, qayta yuborilmaydi: {}", method, exc)
                    return False, {"description": f"Telegram javob bermadi: {exc}"}
                logger.warning("TG {} ulanish xatosi ({}): {}", method, attempt + 1, exc)
                await asyncio.sleep(delay)
                delay *= 2
        return False, {"description": "Telegram javob bermadi (3 urinish)"}

    async def send_message(
        self, chat_id: str | int, text: str, *, business_connection_id: str | None = None,
        reply_markup: dict | None = None, reply_to_message_id: str | int | None = None,
    ) -> dict:
        """Xabar yuboradi. Natija: {"sent": bool, "error": str|None}.

        `reply_to_message_id` — answer under a message (group comments); still sent
        if that message was deleted meanwhile.
        """
        payload: dict = {"chat_id": chat_id, "text": text}
        if business_connection_id:
            payload["business_connection_id"] = business_connection_id
        if reply_markup:
            payload["reply_markup"] = reply_markup
        if reply_to_message_id:
            payload["reply_parameters"] = {"message_id": int(reply_to_message_id),
                                           "allow_sending_without_reply": True}
        ok, data = await self._call("sendMessage", payload)
        if ok:
            return {"sent": True, "message_id": str(data.get("message_id") or "")}
        error = data.get("description") or "Yuborilmadi"
        logger.warning("Telegram xabar yuborilmadi: {}", error)
        return {"sent": False, "error": error}

    async def send_photo(
        self, chat_id: str | int, photo: PhotoInput, *, caption: str | None = None,
        business_connection_id: str | None = None, reply_markup: dict | None = None,
    ) -> dict:
        """Bitta rasm. Natija: {"sent": bool, "file_ids": [..], "error": str|None}."""
        payload: dict = {"chat_id": chat_id}
        if caption:
            payload["caption"] = caption
        if business_connection_id:
            payload["business_connection_id"] = business_connection_id
        if reply_markup:
            payload["reply_markup"] = reply_markup
        files = None
        if isinstance(photo, str):
            payload["photo"] = photo
        else:
            files = {"photo": _as_upload("photo", photo)}
        ok, data = await self._call("sendPhoto", payload, files=files)
        if ok:
            return {"sent": True, "file_ids": [_largest_file_id(data)]}
        error = data.get("description") or "Rasm yuborilmadi"
        logger.warning("Telegram rasm yuborilmadi: {}", error)
        return {"sent": False, "error": error}

    async def send_media_group(
        self, chat_id: str | int, photos: list[PhotoInput], *, caption: str | None = None,
        business_connection_id: str | None = None,
    ) -> dict:
        """Albom (2-10 rasm). Izoh birinchi rasmga qo'yiladi — albom ostida ko'rinadi."""
        media: list[dict] = []
        files: dict = {}
        for index, photo in enumerate(photos):
            entry: dict = {"type": "photo"}
            if isinstance(photo, str):
                entry["media"] = photo
            else:
                name = f"photo{index}"
                entry["media"] = f"attach://{name}"
                files[name] = _as_upload(name, photo)
            if index == 0 and caption:
                entry["caption"] = caption
            media.append(entry)
        payload: dict = {"chat_id": chat_id, "media": media}
        if business_connection_id:
            payload["business_connection_id"] = business_connection_id
        ok, data = await self._call("sendMediaGroup", payload, files=files or None)
        if ok and isinstance(data, list):
            return {"sent": True, "file_ids": [_largest_file_id(m) for m in data]}
        error = (data.get("description") if isinstance(data, dict) else None) or "Albom yuborilmadi"
        logger.warning("Telegram albom yuborilmadi: {}", error)
        return {"sent": False, "error": error}

    async def set_my_commands(self, commands: list[dict]) -> bool:
        """Botning «Menu» tugmasidagi buyruqlar ro'yxati (shaxsiy chatlar uchun)."""
        ok, data = await self._call("setMyCommands", {
            "commands": commands, "scope": {"type": "all_private_chats"},
        })
        if not ok:
            logger.warning("Bot buyruqlari o'rnatilmadi: {}", data.get("description"))
        return ok

    async def delete_my_commands(self) -> bool:
        ok, _ = await self._call("deleteMyCommands", {"scope": {"type": "all_private_chats"}})
        return ok

    async def answer_callback_query(self, callback_query_id: str, text: str | None = None,
                                    *, show_alert: bool = False) -> bool:
        """Tugma bosilgach Telegram'dagi «yuklanmoqda» belgisini o'chiradi.

        `text` — optional short notice shown to the user (toast, or a popup with
        `show_alert`).
        """
        payload: dict = {"callback_query_id": callback_query_id}
        if text:
            payload["text"] = text[:200]
            payload["show_alert"] = show_alert
        ok, _ = await self._call("answerCallbackQuery", payload)
        return ok

    # --- Lead-magnet funnel (SPEC §10) -------------------------------------
    async def send_document(
        self, chat_id: str | int, document: DocumentInput, *, caption: str | None = None,
        reply_markup: dict | None = None,
    ) -> dict:
        """One file. `document` — cached `file_id` or (bytes, filename, MIME type).

        Result: {"sent": bool, "file_id": str, "error": str|None}.
        """
        payload: dict = {"chat_id": chat_id}
        if caption:
            payload["caption"] = caption
        if reply_markup:
            payload["reply_markup"] = reply_markup
        files = None
        if isinstance(document, str):
            payload["document"] = document
        else:
            data, filename, content_type = document
            files = {"document": (filename, data, content_type)}
        ok, data = await self._call("sendDocument", payload, files=files)
        if ok:
            return {"sent": True,
                    "file_id": str((data.get("document") or {}).get("file_id") or "")}
        error = data.get("description") or "Fayl yuborilmadi"
        logger.warning("Telegram fayl yuborilmadi: {}", error)
        return {"sent": False, "error": error}

    async def send_location(self, chat_id: str | int, latitude: float, longitude: float,
                            *, reply_markup: dict | None = None) -> dict:
        payload: dict = {"chat_id": chat_id, "latitude": latitude, "longitude": longitude}
        if reply_markup:
            payload["reply_markup"] = reply_markup
        ok, data = await self._call("sendLocation", payload)
        if ok:
            return {"sent": True}
        return {"sent": False, "error": data.get("description") or "Lokatsiya yuborilmadi"}

    async def edit_message_text(self, chat_id: str | int, message_id: str | int, text: str,
                                *, reply_markup: dict | None = None) -> dict:
        """Replace a sent message (e.g. date picker -> time picker). No markup = no buttons."""
        payload: dict = {"chat_id": chat_id, "message_id": int(message_id), "text": text}
        if reply_markup:
            payload["reply_markup"] = reply_markup
        ok, data = await self._call("editMessageText", payload)
        if ok:
            return {"sent": True}
        return {"sent": False, "error": data.get("description") or "Xabar tahrirlanmadi"}

    async def get_chat_member(self, chat_id: str | int, user_id: str | int) -> dict | None:
        """ChatMember object (`status`: creator|administrator|member|restricted|left|kicked),
        or None when Telegram refused (bot not admin, bad chat id, ...)."""
        ok, data = await self._call("getChatMember", {"chat_id": chat_id, "user_id": int(user_id)})
        if not ok:
            logger.warning("getChatMember {} failed: {}", chat_id, data.get("description"))
            return None
        return data

    async def get_chat(self, chat_id: str | int) -> dict | None:
        ok, data = await self._call("getChat", {"chat_id": chat_id})
        return data if ok else None

    async def get_me(self) -> dict:
        ok, data = await self._call("getMe", {})
        return data if ok else {}

    async def get_webhook_info(self) -> dict:
        ok, data = await self._call("getWebhookInfo", {})
        return data if ok else {}

    async def set_webhook(self, url: str, secret: str) -> bool:
        """Webhook o'rnatadi (Business va oddiy chat xabarlari uchun)."""
        ok, data = await self._call("setWebhook", {
            "url": url,
            "secret_token": secret,
            "allowed_updates": [
                "message", "edited_message", "callback_query",
                "business_connection", "business_message", "edited_business_message",
            ],
            "drop_pending_updates": False,
        })
        if ok:
            logger.info("Telegram webhook o'rnatildi: {}", url)
            return True
        logger.error("Telegram webhook o'rnatilmadi: {}", data.get("description"))
        return False


telegram = TelegramClient()
