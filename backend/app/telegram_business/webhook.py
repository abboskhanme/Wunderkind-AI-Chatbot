"""Telegram webhook — shaxsiy chatlar (Business ulanishi yoki bot chati).

Telegram 60 soniya kutadi, lekin biz Instagram bilan bir xil qoidaga amal
qilamiz: og'ir ish (AI + javob + baza) fon vazifasiga topshiriladi va 200
DARHOL qaytariladi.

Business ulanishi qanday ishlaydi:
  1. Foydalanuvchi Telegram → Sozlamalar → Business → Chatbots'da botni ulaydi.
  2. Telegram `business_connection` update yuboradi — unda ulanish `id` va
     akkaunt egasining `user.id` bo'ladi. Shuni saqlab qo'yamiz:
       - `tgconn:<connection_id>` → egasining user id
       - `tgchat:<chat_id>`       → connection id (javob yuborishda kerak)
  3. Mijoz yozganda `business_message` keladi va javob AYNAN shu
     `business_connection_id` bilan yuboriladi — mijoz javobni akkaunt
     egasidan (sizdan) kelgan deb ko'radi.
"""
from __future__ import annotations

import hmac
import json
from typing import Optional

from fastapi import APIRouter, BackgroundTasks, Header, Request, Response
from loguru import logger

from app.config import settings
from app.funnel import bot as funnel_bot
from app.leads import profiles
from app.processing.pipeline import process_event
from app.state.store import store
from app.telegram_business import menu
from app.telegram_business.client import telegram
from app.telegram_business.models import parse_update

router = APIRouter(prefix="/webhook", tags=["Telegram webhook"])

CONN_KEY = "tgconn:{}"      # ulanish -> egasi
CHAT_KEY = "tgchat:{}"      # chat -> ulanish


async def remember_connection(conn: dict) -> None:
    """`business_connection` update'ini saqlaymiz (egasi va holati)."""
    conn_id = str(conn.get("id") or "")
    user = conn.get("user") or {}
    owner_id = str(user.get("id") or "")
    if not conn_id or not owner_id:
        return
    enabled = conn.get("is_enabled", True)
    await store.set_value(CONN_KEY.format(conn_id), owner_id if enabled else "")
    logger.info(
        "Telegram Business ulanishi {}: conn={} egasi={}",
        "yoqildi" if enabled else "o'chirildi", conn_id, owner_id,
    )


async def owner_of(conn_id: Optional[str]) -> Optional[int]:
    if not conn_id:
        return None
    raw = await store.get_value(CONN_KEY.format(conn_id))
    return int(raw) if raw and raw.isdigit() else None


async def connection_for_chat(chat_id: str) -> Optional[str]:
    """Shu chatga javob yozishda ishlatiladigan Business ulanishi."""
    return await store.get_value(CHAT_KEY.format(chat_id))


def _valid_secret(secret: Optional[str]) -> bool:
    return bool(secret and hmac.compare_digest(secret, settings.tg_webhook_secret))


@router.post("/telegram")
async def receive(
    request: Request,
    background: BackgroundTasks,
    x_telegram_bot_api_secret_token: Optional[str] = Header(default=None),
):
    if not _valid_secret(x_telegram_bot_api_secret_token):
        logger.warning("Telegram webhook maxfiy sarlavhasi noto'g'ri")
        return Response(content="forbidden", status_code=403)

    try:
        update = json.loads(await request.body())
    except json.JSONDecodeError:
        return Response(content="bad json", status_code=400)

    await handle_update(update, background)
    return Response(content="OK", media_type="text/plain")


async def handle_update(update: dict, background: BackgroundTasks) -> None:
    """One Telegram update -> side effects queued on `background`.

    Shared by the webhook and by local long polling (app.telegram_business.polling).
    """
    await _route_update(update, background)
    # Account profile (name, username, shared phone, ...) — after the reply
    person = profiles.telegram_person(update)
    if person is not None:
        background.add_task(profiles.capture_telegram, person)


async def _route_update(update: dict, background: BackgroundTasks) -> None:
    # 1) Ulanish o'zgarishi (ulandi/uzildi)
    conn = update.get("business_connection")
    if isinstance(conn, dict):
        await remember_connection(conn)

    # 1b) Lead-magnet funnel (SPEC §10): /start deep links, collection steps,
    #     booking buttons, keyword comments in the channel group — before menu/AI
    if await funnel_bot.claim_update(update, background):
        return

    # 2) Menyudagi inline tugma bosildi (Business chatidagi salomlashish ostida)
    callback = update.get("callback_query")
    if isinstance(callback, dict):
        background.add_task(menu.handle_callback, callback)
        return

    # 2b) "/id" — shows the chat ID to paste into «Bildirishnoma oluvchilar»
    plain = update.get("message") or {}
    if isinstance(plain, dict) and str(plain.get("text") or "").strip().split("@")[0] == "/id":
        chat_id = (plain.get("chat") or {}).get("id")
        if chat_id is not None:
            background.add_task(telegram.send_message, chat_id,
                                f"Chat ID: {chat_id}\nBuni admin panel → Sozlamalar → Telegram → "
                                "«Bildirishnoma oluvchilar» maydoniga kiriting.")
        return

    # 3) Xabarlar
    msg = update.get("business_message") or {}
    conn_id = msg.get("business_connection_id") if isinstance(msg, dict) else None
    owner_id = await owner_of(conn_id)

    events = parse_update(update, owner_id=owner_id)
    if events:
        # Boshqa worker menyuni yangilagan bo'lishi mumkin (prod'da bir nechta jarayon)
        await menu.ensure_fresh()
    for event in events:
        if event.business_connection_id and event.chat_id:
            # Javob yozishda kerak bo'ladi
            await store.set_value(
                CHAT_KEY.format(event.chat_id), event.business_connection_id
            )
        # Menyu tanlovi (`/narxlar`, «💰 Narxlar» tugmasi) — AI'siz tayyor javob
        if event.kind == "dm" and not event.has_attachment and settings.TG_SALES_ENABLED:
            action = menu.match(event.text, menu.current())
            if action:
                background.add_task(menu.handle_action, event, action)
                continue
        background.add_task(process_event, event)
