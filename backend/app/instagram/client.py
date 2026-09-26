"""Instagram Graph API klienti — kommentga javob, private reply, DM.

**"Instagram API with Instagram Login"** ishlatiladi (graph.instagram.com), ya'ni
Facebook Page ulash SHART EMAS va o'z akkauntimiz uchun App Review kerak emas.

Endpointlar:
  • ochiq javob      -> POST /{comment-id}/replies
  • private reply/DM -> POST /me/messages
Ruxsatlar: instagram_business_basic, ..._manage_messages, ..._manage_comments.

Yuborishlar global throttle bilan cheklanadi (soniyasiga ~1 ta) — Instagram
rate limitiga urilmaslik va "spam" belgisidan qochish uchun.
"""
from __future__ import annotations

import asyncio
import time

import httpx
from loguru import logger

from app.config import settings

# Global throttle: ketma-ket ikki so'rov orasida kamida shuncha soniya
_MIN_INTERVAL = 1.0
_throttle_lock = asyncio.Lock()
_last_call = 0.0


async def _throttle() -> None:
    global _last_call
    async with _throttle_lock:
        wait = _MIN_INTERVAL - (time.monotonic() - _last_call)
        if wait > 0:
            await asyncio.sleep(wait)
        _last_call = time.monotonic()


# Instagram javob oynasi yopilganini bildiruvchi xatolar (Meta kodlari)
_WINDOW_ERROR_CODES = {10, 551, 200}
_WINDOW_HINTS = ("outside of allowed window", "outside the allowed window",
                 "24 hours", "messaging window")


def _error_text(data: dict) -> str:
    err = (data or {}).get("error") or {}
    msg = err.get("error_user_msg") or err.get("message") or str(data)[:200]
    return str(msg)


def _no_consent(resp: httpx.Response) -> bool:
    """IG error 230 "User consent is required" (profile of someone who has not
    messaged us yet). Instagram returns it as HTTP 500, but it is not transient."""
    try:
        return int((resp.json().get("error") or {}).get("code") or 0) == 230
    except (ValueError, AttributeError, TypeError):
        return False


def _is_window_error(data: dict) -> bool:
    err = (data or {}).get("error") or {}
    if err.get("code") in _WINDOW_ERROR_CODES:
        return True
    text = str(err.get("message") or "").lower()
    return any(h in text for h in _WINDOW_HINTS)


class InstagramClient:
    # Qiymatlarni HAR chaqiruvda settings'dan o'qiymiz — shunda remote config
    # (admin panel) token/versiya/ID ni yangilaganda darrov qo'llanadi (restartsiz).
    @property
    def _base(self) -> str:
        return f"{settings.IG_API_BASE.rstrip('/')}/{settings.GRAPH_API_VERSION}"

    async def _post(self, path: str, *, params=None, json=None) -> dict:
        params = {**(params or {}), "access_token": settings.IG_ACCESS_TOKEN}
        url = f"{self._base}/{path}"
        delay = 1.0
        for attempt in range(3):
            await _throttle()
            try:
                async with httpx.AsyncClient(timeout=15.0) as client:
                    resp = await client.post(url, params=params, json=json)
                if resp.status_code == 200:
                    return resp.json()
                # rate-limit / vaqtinchalik xatoliklar — backoff
                if resp.status_code in (429, 500, 503):
                    logger.warning(
                        "IG API {} ({}-urinish), backoff {}s: {}",
                        resp.status_code, attempt + 1, delay, resp.text[:200],
                    )
                    await asyncio.sleep(delay)
                    delay *= 2
                    continue
                logger.error("IG API xato {}: {}", resp.status_code, resp.text[:300])
                return {}
            except httpx.HTTPError as exc:
                logger.warning("IG API ulanish xatosi ({}): {}", attempt + 1, exc)
                await asyncio.sleep(delay)
                delay *= 2
        logger.error("IG API 3 urinishdan keyin ham muvaffaqiyatsiz: {}", path)
        return {}

    async def _get(self, path: str, *, params=None) -> dict:
        """GET so'rov (throttle + backoff bilan). Xatoda bo'sh dict."""
        params = {**(params or {}), "access_token": settings.IG_ACCESS_TOKEN}
        url = path if path.startswith("http") else f"{self._base}/{path}"
        delay = 1.0
        for attempt in range(3):
            await _throttle()
            try:
                async with httpx.AsyncClient(timeout=20.0) as client:
                    resp = await client.get(url, params=params)
                if resp.status_code == 200:
                    return resp.json()
                if _no_consent(resp):
                    # The person has not messaged us yet — retrying cannot help
                    logger.info("IG API GET: no user consent yet for {}", path)
                    return {}
                if resp.status_code in (429, 500, 503):
                    logger.warning(
                        "IG API GET {} ({}-urinish), backoff {}s: {}",
                        resp.status_code, attempt + 1, delay, resp.text[:200],
                    )
                    await asyncio.sleep(delay)
                    delay *= 2
                    continue
                logger.error("IG API GET xato {}: {}", resp.status_code, resp.text[:300])
                return {}
            except httpx.HTTPError as exc:
                logger.warning("IG API GET ulanish xatosi ({}): {}", attempt + 1, exc)
                await asyncio.sleep(delay)
                delay *= 2
        logger.error("IG API GET 3 urinishdan keyin ham muvaffaqiyatsiz: {}", path)
        return {}

    async def list_conversations(self, after: str | None = None) -> dict:
        """Suhbatlar ro'yxati (Requests papkasidagilar ham, 30 kun ichida faol).

        Nested `messages{...}` bilan bitta so'rovda xabar matnlarini ham
        olishga urinamiz — bo'lmasa importer har xabarni alohida so'raydi.
        """
        params: dict[str, str] = {
            "platform": "instagram",
            "fields": (
                "id,updated_time,participants,"
                "messages.limit(50){id,created_time,from,to,message}"
            ),
            "limit": "50",
        }
        if after:
            params["after"] = after
        return await self._get("me/conversations", params=params)

    async def get_message(self, message_id: str) -> dict:
        """Bitta xabar tafsiloti (nested so'rov ishlamasa zaxira yo'l)."""
        return await self._get(
            message_id, params={"fields": "id,created_time,from,to,message"}
        )

    async def reply_to_comment(self, comment_id: str, message: str) -> dict:
        """Ochiq kommentga ochiq javob yozadi."""
        return await self._post(f"{comment_id}/replies", params={"message": message})

    async def send_private_reply(self, comment_id: str, message: str) -> dict:
        """Kommentga shaxsiy (DM) javob — har komment uchun faqat BIR marta."""
        return await self._post(
            "me/messages",
            json={"recipient": {"comment_id": comment_id}, "message": {"text": message}},
        )

    async def send_dm(self, recipient_id: str, message: str) -> dict:
        """Foydalanuvchiga DM yuboradi (24 soatlik oyna qoidasi)."""
        return await self._post(
            "me/messages",
            json={"recipient": {"id": recipient_id}, "message": {"text": message}},
        )

    async def send_dm_result(
        self, recipient_id: str, message: str, *, human_agent: bool = False,
        allow_tag_fallback: bool = True,
    ) -> dict:
        """DM yuboradi va NATIJANI batafsil qaytaradi (admin panel "Suhbatlar" uchun).

        `send_dm` xatoni yutib yuboradi (bot uchun shu yetarli), bu yerda esa
        operatorga sababni ko'rsatishimiz kerak.

        human_agent=True — 24 soatlik oyna yopilgan, lekin 7 kun ichida:
        Meta'ning HUMAN_AGENT tegi bilan JONLI operator javob bera oladi
        (avtomatik xabarga bu teg TAQIQLANGAN — shuning uchun uni faqat
        odam yozgan xabarga qo'yamiz).
        """
        payload: dict = {
            "recipient": {"id": recipient_id},
            "message": {"text": message},
        }
        if human_agent:
            payload["messaging_type"] = "MESSAGE_TAG"
            payload["tag"] = "HUMAN_AGENT"

        status, data = await self._post_once("me/messages", payload)
        if status == 200:
            return {"sent": True, "tag": "HUMAN_AGENT" if human_agent else None}

        error = _error_text(data)
        # Oyna yopilgan bo'lsa — bir marta HUMAN_AGENT tegi bilan qayta urinamiz
        # Automated messages (follow-ups) must NEVER use this tag (Meta policy).
        if not human_agent and allow_tag_fallback and _is_window_error(data):
            payload["messaging_type"] = "MESSAGE_TAG"
            payload["tag"] = "HUMAN_AGENT"
            status2, data2 = await self._post_once("me/messages", payload)
            if status2 == 200:
                return {"sent": True, "tag": "HUMAN_AGENT"}
            error = _error_text(data2)

        logger.warning("DM yuborilmadi ({}): {}", status, error)
        return {"sent": False, "error": error}

    async def _post_once(self, path: str, json: dict) -> tuple[int, dict]:
        """Bitta POST — javob kodi va tanasi bilan (retry'siz, xato yutilmaydi)."""
        url = f"{self._base}/{path}"
        await _throttle()
        try:
            async with httpx.AsyncClient(timeout=20.0) as client:
                resp = await client.post(
                    url, params={"access_token": settings.IG_ACCESS_TOKEN}, json=json
                )
            try:
                body = resp.json()
            except ValueError:
                body = {"raw": resp.text[:300]}
            return resp.status_code, body
        except httpx.HTTPError as exc:
            return 0, {"error": {"message": f"Ulanish xatosi: {exc}"}}

    # --- Lead-magnet funnel (SPEC §10) -------------------------------------
    async def send_message_to(self, recipient: dict, message: dict) -> dict:
        """One Send API call, no retries. `recipient` = {"id": igsid} or
        {"comment_id": ...} (private reply). Result: {"sent": bool, "error"?}."""
        status, data = await self._post_once(
            "me/messages", {"recipient": recipient, "message": message})
        if status == 200:
            return {"sent": True, "message_id": str(data.get("message_id") or "")}
        error = _error_text(data)
        logger.warning("IG xabar yuborilmadi ({}): {}", status, error)
        return {"sent": False, "error": error}

    async def send_quick_replies(self, recipient: dict, text: str,
                                 quick_replies: list[dict]) -> dict:
        """Text with quick-reply buttons (tap = a DM with the button title)."""
        return await self.send_message_to(
            recipient, {"text": text, "quick_replies": quick_replies})

    async def send_button_template(self, recipient: dict, text: str,
                                   buttons: list[dict]) -> dict:
        """Button template (text ≤ 640 chars, ≤ 3 buttons, e.g. web_url)."""
        return await self.send_message_to(recipient, {"attachment": {
            "type": "template",
            "payload": {"template_type": "button", "text": text, "buttons": buttons},
        }})

    async def get_user_profile(self, igsid: str) -> dict | None:
        """{username, is_user_follow_business, ...} or None when unavailable
        (no consent yet, permission missing, API error)."""
        data = await self._get(igsid, params={"fields": "username,is_user_follow_business"})
        return data or None

    async def get_media(self, media_id: str) -> dict | None:
        """{shortcode, permalink} of a post — funnels may filter posts by link."""
        data = await self._get(media_id, params={"fields": "shortcode,permalink"})
        return data or None

    async def subscribe_webhooks(self) -> dict:
        """Akkauntni webhook maydonlariga obuna qiladi (/connect oqimida chaqiriladi).

        FAQAT `comments` va `messages`. Ilgari uchinchi bo'lib `message_echoes`
        ham yuborilardi — Instagram API'da bunday maydon YO'Q va u butun so'rovni
        rad etardi (400: "Param subscribed_fields[2] must be one of ..."), ya'ni
        akkaunt hech qaysi maydonga obuna bo'lmay qolardi va webhook umuman
        kelmasdi. Akkauntdan chiqqan xabarlar (echo) baribir `messages` orqali
        `is_echo` bayrog'i bilan keladi — alohida maydon shart emas.
        """
        return await self._post(
            "me/subscribed_apps",
            params={"subscribed_fields": "comments,messages"},
        )


instagram = InstagramClient()
