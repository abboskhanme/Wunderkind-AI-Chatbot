"""Bot menyusi — mijoz bo'lim tanlasa AI'siz tayyor javob (matn + rasmlar).

Bo'limlar admin panelda («Bot menyusi» sahifasi) boshqariladi va bazadan
o'qiladi. Mijoz bo'limni uch yo'l bilan tanlaydi:

  • Botning o'z chatida — «Menu» tugmasidagi buyruq (`/narxlar`) yoki pastki
    klaviaturadagi tugma («💰 Narxlar»). Klaviatura `/start` da chiqadi.
  • Business ulanishida (siz nomingizdan yozishma) — pastki klaviatura
    Telegram tomonidan TAQIQLANGAN, shuning uchun salomlashish xabari ostida
    inline tugmalar chiqadi; buyruqni qo'lda yozish ham ishlaydi.
  • Havola: `t.me/<bot>?start=narxlar` — Instagram bio yoki reklamadan to'g'ri
    shu bo'limga olib keladi.

Boshqa har qanday matn avvalgidek AI'ga ketadi.

Olingan menyu umumiy holatga (Redis) versiyasi bilan yoziladi — bir nechta
worker bo'lsa ham har biri webhook kelganda versiyani solishtirib o'zini
yangilaydi.

Rasmlar Telegram'ga bir marta yuklanadi: javobdagi `file_id` rasm xeshi
bo'yicha keshlanadi va keyingi safar baytlar qayta yuborilmaydi. Kesh eskirgan
bo'lsa (bot tokeni almashgan) — rasmlar qaytadan yuklanadi.
"""
from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass, field
from typing import Optional

from loguru import logger

from app.config import settings
from app.instagram.models import IncomingEvent
from app.leads import client as leads_client
from app.state.store import store
from app.telegram_business.client import PhotoInput, telegram

DEFAULT_GREETING = (
    "Assalomu alaykum! 👋\n"
    "Quyidagi bo'limlardan birini tanlang yoki savolingizni yozing — darhol javob beramiz."
)
CAPTION_LIMIT = 1024          # Telegram rasm izohi chegarasi (UTF-16 birliklarida)
MAX_ALBUM = 10                # sendMediaGroup chegarasi
CALLBACK_PREFIX = "menu:"
FILE_KEY = "tgfile:{bot}:{sha}"
PAYLOAD_KEY = "tgmenu:payload"
REV_KEY = "tgmenu:rev"
# Telegram faqat mijoz bot chatiga birinchi kirganda /start yuboradi
_GREETING_COMMANDS = frozenset({"start", "menu"})
_GREETING_WORDS = frozenset({"menyu", "menu", "меню"})
# Mijoz rasm yuborgandagi o'rinbosar matn (models.message_text bilan bir xil).
# Business ulanishida botning o'z albomi ham echo bo'lib aynan shunday qaytadi.
_PHOTO_ECHO = "[Mijoz rasm yubordi]"


def tg_len(text: str) -> int:
    """Telegram matn uzunligini UTF-16 birliklarida sanaydi (emoji — 2 ta)."""
    return len(text.encode("utf-16-le")) // 2


# --------------------------------------------------------------------------- #
# Ma'lumot
# --------------------------------------------------------------------------- #
@dataclass(frozen=True)
class MenuImage:
    id: str
    sha256: str
    content_type: str = "image/jpeg"


@dataclass(frozen=True)
class MenuItem:
    id: str
    command: str
    title: str
    text: str = ""
    images: tuple[MenuImage, ...] = ()


@dataclass(frozen=True)
class Menu:
    greeting: str = ""
    items: tuple[MenuItem, ...] = ()

    @classmethod
    def from_payload(cls, data: dict) -> "Menu":
        items = []
        for raw in data.get("items") or []:
            command = str(raw.get("command") or "").strip().lower()
            title = str(raw.get("title") or "").strip()
            if not command or not title:
                continue
            items.append(MenuItem(
                id=str(raw.get("id") or ""),
                command=command,
                title=title,
                text=str(raw.get("text") or ""),
                images=tuple(
                    MenuImage(id=str(img["id"]), sha256=str(img.get("sha256") or ""),
                              content_type=str(img.get("content_type") or "image/jpeg"))
                    for img in (raw.get("images") or []) if img.get("id")
                ),
            ))
        return cls(greeting=str(data.get("greeting") or ""), items=tuple(items))

    @property
    def greeting_text(self) -> str:
        return self.greeting.strip() or DEFAULT_GREETING

    def by_command(self, command: str) -> Optional[MenuItem]:
        command = command.strip().lower()
        return next((i for i in self.items if i.command == command), None)

    def by_title(self, text: str) -> Optional[MenuItem]:
        needle = text.strip().casefold()
        return next((i for i in self.items if i.title.casefold() == needle), None)

    def commands(self) -> list[dict]:
        # Telegram: ko'pi bilan 100 ta buyruq, tavsif 1-256 belgi
        return [{"command": i.command, "description": i.title[:256]} for i in self.items[:100]]


@dataclass
class MenuAction:
    kind: str                         # "greeting" | "item"
    item: Optional[MenuItem] = None


@dataclass
class _State:
    menu: Menu = field(default_factory=Menu)
    rev: Optional[str] = None
    commands_fp: Optional[str] = None


_state = _State()


def current() -> Menu:
    return _state.menu


# --------------------------------------------------------------------------- #
# Load from DB, share across workers, sync Telegram commands
# --------------------------------------------------------------------------- #
async def _load_payload() -> dict:
    """Active menu items + greeting from the database (same shape as NUR's API)."""
    from sqlalchemy import select

    from app.db import session as db_session
    from app.models.bot_menu import BotMenuItem

    async with db_session.SessionLocal() as db:
        items = (await db.execute(
            select(BotMenuItem).where(BotMenuItem.is_active.is_(True))
            .order_by(BotMenuItem.sort_order, BotMenuItem.created_at)
        )).scalars().all()
        return {
            "greeting": settings.TG_MENU_GREETING or "",
            "items": [
                {
                    "id": str(i.id), "command": i.command, "title": i.title,
                    "text": i.text or "",
                    "images": [
                        {"id": str(img.id), "sha256": img.sha256,
                         "content_type": img.content_type}
                        for img in i.images
                    ],
                }
                for i in items
            ],
        }


def _parse(data: object) -> Optional[Menu]:
    try:
        return Menu.from_payload(data)  # type: ignore[arg-type]
    except (AttributeError, KeyError, TypeError, ValueError) as exc:
        logger.warning("Bot menyusi formati noto'g'ri (eski menyu qoladi): {}", exc)
        return None


def _apply(menu: Menu, rev: str) -> None:
    if menu != _state.menu:
        logger.info("Bot menyusi yangilandi: {} ta bo'lim", len(menu.items))
    _state.menu = menu
    _state.rev = rev


async def refresh() -> Menu:
    """Reload the menu from the database. On error the old menu stays.

    Commands are synced only after a SUCCESSFUL load — otherwise a DB hiccup
    would wipe the bot's command list.
    """
    try:
        data = await _load_payload()
    except Exception as exc:  # noqa: BLE001
        logger.warning("Bot menu load failed (keeping old menu): {}", exc)
        return _state.menu
    menu = _parse(data)
    if menu is None:
        return _state.menu

    raw = json.dumps(data, sort_keys=True, ensure_ascii=False)
    rev = hashlib.sha1(raw.encode()).hexdigest()
    _apply(menu, rev)
    try:
        await store.set_value(PAYLOAD_KEY, raw)
        await store.set_value(REV_KEY, rev)
    except Exception as exc:  # noqa: BLE001
        logger.warning("Menyuni umumiy holatga yozishda xato: {}", exc)
    await sync_commands()
    return _state.menu


async def ensure_fresh() -> Menu:
    """Boshqa worker yangi menyu olgan bo'lsa — shuni o'zimizga ham qo'llaymiz."""
    try:
        rev = await store.get_value(REV_KEY)
        if rev and rev != _state.rev:
            raw = await store.get_value(PAYLOAD_KEY)
            menu = _parse(json.loads(raw)) if raw else None
            if menu is not None:
                _apply(menu, rev)
    except Exception as exc:  # noqa: BLE001
        logger.warning("Umumiy menyuni o'qishda xato (joriy menyu qoladi): {}", exc)
    return _state.menu


async def sync_commands() -> None:
    """Sync the bot's «Menu» commands with the menu items (when changed)."""
    if not telegram.enabled:
        return
    commands = _state.menu.commands()
    fingerprint = f"{settings.TG_SALES_BOT_TOKEN[:12]}|{json.dumps(commands, ensure_ascii=False)}"
    if fingerprint == _state.commands_fp:
        return
    ok = await (telegram.set_my_commands(commands) if commands
                else telegram.delete_my_commands())
    if ok:
        _state.commands_fp = fingerprint


# --------------------------------------------------------------------------- #
# Tanlovni aniqlash
# --------------------------------------------------------------------------- #
def match(text: str, menu: Menu) -> Optional[MenuAction]:
    """Matn menyu tanlovimi? Bo'lim bo'lmasa har doim `None` — hammasi AI'ga ketadi."""
    if not menu.items or not text:
        return None
    raw = text.strip()
    if raw.startswith("/"):
        parts = raw[1:].split(maxsplit=1)
        command = parts[0].split("@", 1)[0].lower() if parts else ""
        argument = parts[1].strip() if len(parts) > 1 else ""
        if command == "start" and argument:          # t.me/<bot>?start=narxlar
            item = menu.by_command(argument)
            if item:
                return MenuAction("item", item)
        if command in _GREETING_COMMANDS:
            return MenuAction("greeting")
        item = menu.by_command(command)
        return MenuAction("item", item) if item else None
    if raw.casefold() in _GREETING_WORDS:
        return MenuAction("greeting")
    item = menu.by_title(raw)
    return MenuAction("item", item) if item else None


# --------------------------------------------------------------------------- #
# Klaviaturalar
# --------------------------------------------------------------------------- #
def _rows(buttons: list[dict], per_row: int = 2) -> list[list[dict]]:
    return [buttons[i:i + per_row] for i in range(0, len(buttons), per_row)]


def reply_keyboard(menu: Menu) -> dict:
    """Botning o'z chati uchun — doim ko'rinib turadigan pastki klaviatura."""
    return {
        "keyboard": _rows([{"text": i.title} for i in menu.items]),
        "resize_keyboard": True,
        "is_persistent": True,
        "input_field_placeholder": "Savolingizni yozing...",
    }


def inline_keyboard(menu: Menu) -> dict:
    """Business ulanishi uchun — pastki klaviatura u yerda ishlamaydi."""
    return {"inline_keyboard": _rows([
        {"text": i.title, "callback_data": f"{CALLBACK_PREFIX}{i.command}"}
        for i in menu.items
    ])}


# --------------------------------------------------------------------------- #
# Yuborish
# --------------------------------------------------------------------------- #
def _bot_id() -> str:
    return settings.TG_SALES_BOT_TOKEN.split(":", 1)[0]


def _disclosure(text: str) -> str:
    """Suhbatning birinchi xabarida AI ekanligini aytish (AI javobidagi bilan bir xil)."""
    from app.processing.pipeline import _with_disclosure

    return _with_disclosure(text).strip()


def _is_file_id_error(result: dict) -> bool:
    error = str(result.get("error") or "").lower()
    return "file identifier" in error or "file_id" in error


async def _download(image: MenuImage) -> Optional[tuple[bytes, str]]:
    import uuid

    from sqlalchemy import select

    from app.db import session as db_session
    from app.models.bot_menu import BotMenuImage

    try:
        async with db_session.SessionLocal() as db:
            data = (await db.execute(
                select(BotMenuImage.data).where(BotMenuImage.id == uuid.UUID(image.id))
            )).scalar_one_or_none()
        if data:
            return bytes(data), image.content_type
        logger.warning("Menu image not found: {}", image.id)
    except Exception as exc:  # noqa: BLE001
        logger.warning("Menu image load failed: {}", exc)
    return None


async def _photos(images: tuple[MenuImage, ...], *, use_cache: bool) -> tuple[list[PhotoInput], bool]:
    """Photos: cached `file_id` or bytes from the DB. Returns (list, any_cached)."""
    photos: list[PhotoInput] = []
    cached_any = False
    for image in images:
        if use_cache and image.sha256:
            file_id = await store.get_value(FILE_KEY.format(bot=_bot_id(), sha=image.sha256))
            if file_id:
                photos.append(file_id)
                cached_any = True
                continue
        data = await _download(image)
        if data:
            photos.append(data)
    return photos, cached_any


async def _send_photo_set(chat_id: str, photos: list[PhotoInput], caption: Optional[str],
                          conn_id: Optional[str], reply_markup: Optional[dict]) -> dict:
    if len(photos) == 1:
        return await telegram.send_photo(chat_id, photos[0], caption=caption,
                                         business_connection_id=conn_id,
                                         reply_markup=reply_markup)
    # Albomga klaviatura biriktirib bo'lmaydi (Bot API cheklovi)
    return await telegram.send_media_group(chat_id, photos, caption=caption,
                                           business_connection_id=conn_id)


async def _send_photos(chat_id: str, images: tuple[MenuImage, ...], caption: Optional[str],
                       conn_id: Optional[str], reply_markup: Optional[dict] = None) -> dict:
    photos, cached_any = await _photos(images, use_cache=True)
    if not photos:
        return {"sent": False, "error": "Rasm topilmadi"}
    result = await _send_photo_set(chat_id, photos, caption, conn_id, reply_markup)
    if not result.get("sent") and cached_any and _is_file_id_error(result):
        # Keshdagi file_id yaroqsiz (masalan bot tokeni almashgan) — qayta yuklaymiz
        logger.info("Keshdagi rasm ID'si ishlamadi — rasmlar qaytadan yuklanadi")
        photos, _ = await _photos(images, use_cache=False)
        if photos:
            result = await _send_photo_set(chat_id, photos, caption, conn_id, reply_markup)

    if result.get("sent"):
        # Faqat hammasi yetib borgan bo'lsa ID'lar tartibi rasmlarga mos keladi
        file_ids = result.get("file_ids") or []
        if len(file_ids) == len(images):
            for image, file_id in zip(images, file_ids):
                if file_id and image.sha256:
                    await store.set_value(
                        FILE_KEY.format(bot=_bot_id(), sha=image.sha256), file_id)
    return result


async def send_item(chat_id: str, item: MenuItem, *, conn_id: Optional[str], store_key: str,
                    keyboard: Optional[dict] = None, first_contact: bool = False) -> list[str]:
    """Bo'limni yuboradi. Qaytaradi: yuborilgan qismlar matni (jurnal uchun).

    Business ulanishida bot yuborgan har bir xabar echo bo'lib qaytadi. Echo
    `mark_sent` dan OLDIN yetib kelsa bot uni operator yozdi deb o'zini
    pauzaga qo'yardi — shuning uchun iz yuborishdan OLDIN qoldiriladi.
    `keyboard` — botning o'z chatida pastki klaviaturani yangilab qo'yish uchun.
    """
    text = item.text.strip()
    if first_contact:
        text = _disclosure(text)
    sent: list[str] = []
    images = item.images[:MAX_ALBUM]
    keyboard_used = False

    if images:
        caption = text if text and tg_len(text) <= CAPTION_LIMIT else None
        # Klaviaturani faqat keyin matn yuborilmaydigan bitta rasmga biriktiramiz
        photo_markup = keyboard if caption and len(images) == 1 else None
        await store.mark_sent(store_key, _PHOTO_ECHO)
        if caption:
            await store.mark_sent(store_key, caption)
        result = await _send_photos(chat_id, images, caption, conn_id, photo_markup)
        if not result.get("sent") and caption:
            # Izoh rad etildi (masalan uzunlik) — rasmlar izohsiz, matn alohida
            logger.info("Rasm izohi qabul qilinmadi ({}) — matn alohida yuboriladi",
                        result.get("error"))
            caption, photo_markup = None, None
            result = await _send_photos(chat_id, images, None, conn_id)
        if result.get("sent"):
            sent.append(f"[{len(images)} ta rasm]")
            if caption:
                sent.append(caption)
                text = ""
                keyboard_used = photo_markup is not None
        else:
            logger.warning("Menyu rasmlari yuborilmadi ({}): {}", item.command, result.get("error"))

    body = text or ("" if sent else item.title)
    if body:
        await store.mark_sent(store_key, body)
        result = await telegram.send_message(
            chat_id, body, business_connection_id=conn_id,
            reply_markup=None if keyboard_used else keyboard,
        )
        if result.get("sent"):
            sent.append(body)
    return sent


async def send_greeting(chat_id: str, menu: Menu, *, conn_id: Optional[str],
                        store_key: str, first_contact: bool = False) -> list[str]:
    markup = inline_keyboard(menu) if conn_id else reply_keyboard(menu)
    text = _disclosure(menu.greeting_text) if first_contact else menu.greeting_text
    await store.mark_sent(store_key, text)
    result = await telegram.send_message(chat_id, text, business_connection_id=conn_id,
                                         reply_markup=markup)
    return [text] if result.get("sent") else []


# --------------------------------------------------------------------------- #
# Webhook'dan chaqiriladi
# --------------------------------------------------------------------------- #
async def handle_action(event: IncomingEvent, action: MenuAction) -> None:
    """Mijoz xabari menyu tanlovi bo'lib chiqdi — AI'siz javob beramiz."""
    try:
        if await store.seen_once(event.dedup_key, settings.DEDUP_TTL):
            return
    except Exception as exc:  # noqa: BLE001
        logger.warning("Dedup xatosi (davom etamiz): {}", exc)

    chat_id = event.chat_id or event.sender_id
    await _respond(
        chat_id=chat_id, sender_id=event.sender_id, username=event.username,
        conn_id=event.business_connection_id, action=action,
        user_text=event.text, user_role="user", message_id=event.message_id,
    )


async def handle_callback(callback: dict) -> None:
    """Inline tugma bosildi (`menu:<buyruq>`)."""
    data = str(callback.get("data") or "")
    callback_id = str(callback.get("id") or "")
    if callback_id:
        await telegram.answer_callback_query(callback_id)
    if not data.startswith(CALLBACK_PREFIX):
        return

    message = callback.get("message") or {}
    chat = message.get("chat") or {}
    if chat.get("type") != "private":
        return

    try:
        if callback_id and await store.seen_once(f"tgcb:{callback_id}", settings.DEDUP_TTL):
            return
    except Exception as exc:  # noqa: BLE001
        logger.warning("Dedup xatosi (davom etamiz): {}", exc)

    menu = await ensure_fresh()
    item = menu.by_command(data[len(CALLBACK_PREFIX):])
    frm = callback.get("from") or {}
    chat_id = str(chat.get("id") or "")
    conn_id = message.get("business_connection_id")
    if not conn_id:
        from app.telegram_business.webhook import connection_for_chat
        conn_id = await connection_for_chat(chat_id)
    if not item and not menu.items:
        return
    # Business chatida tugmani akkaunt egasi (siz) ham bosishi mumkin — u mijoz emas
    by_owner = bool(frm.get("id")) and str(frm.get("id")) != chat_id
    await _respond(
        chat_id=chat_id, sender_id=chat_id,
        username=None if by_owner else (frm.get("username") or chat.get("username") or None),
        conn_id=conn_id,
        # Bo'lim o'chirilgan/nomi o'zgargan eski tugma — yangi menyuni ko'rsatamiz
        action=MenuAction("item", item) if item else MenuAction("greeting"),
        user_text=f"[Tugma: {item.title}]" if item else "[Eski menyu tugmasi]",
        user_role="operator" if by_owner else "user",
        message_id=None,
    )


async def _is_first_contact(sender_id: str, store_key: str) -> bool:
    """Bu mijoz bilan hali yozishma bo'lmaganmi (AI pipeline bilan bir xil mantiq)."""
    try:
        ctx = await leads_client.fetch_context(sender_id, channel="telegram")
        if ctx is not None:
            return not (ctx.get("messages") or [])
        return not await store.get_history(store_key)
    except Exception as exc:  # noqa: BLE001
        logger.warning("Suhbat tarixini tekshirishda xato: {}", exc)
        return False


async def _respond(*, chat_id: str, sender_id: str, username: Optional[str],
                   conn_id: Optional[str], action: MenuAction, user_text: str,
                   user_role: str, message_id: Optional[str]) -> None:
    store_key = f"{IncomingEvent.KEY_PREFIX['telegram']}{sender_id}"
    menu = _state.menu
    first_contact = user_role == "user" and await _is_first_contact(sender_id, store_key)
    if action.kind == "greeting":
        parts = await send_greeting(chat_id, menu, conn_id=conn_id, store_key=store_key,
                                    first_contact=first_contact)
    elif action.item:
        keyboard = reply_keyboard(menu) if not conn_id and menu.items else None
        parts = await send_item(chat_id, action.item, conn_id=conn_id, store_key=store_key,
                                keyboard=keyboard, first_contact=first_contact)
    else:
        return
    logger.info("Menyu javobi ({}): {}", action.item.command if action.item else "salom",
                "yuborildi" if parts else "YUBORILMADI")

    # Yozishma Leadlar bo'limida ham ko'rinsin va AI keyingi savollarda nima
    # yuborilganini bilsin (masalan «50 litrlisi qancha edi?»)
    reply = "\n".join(parts)
    try:
        await leads_client.log_message(
            user_id=sender_id, username=username, channel="telegram",
            text=user_text, role=user_role, kind="dm", ig_message_id=message_id,
        )
        if reply:
            await leads_client.log_message(
                user_id=sender_id, username=username, channel="telegram",
                text=reply, role="assistant", kind="dm",
            )
    except Exception as exc:  # noqa: BLE001
        logger.warning("Menyu yozishmasini jurnalga yozishda xato: {}", exc)
    try:
        await store.append_turn(store_key, user_role, user_text)
        if reply:
            await store.append_turn(store_key, "assistant", reply)
    except Exception as exc:  # noqa: BLE001
        logger.warning("Tarixni saqlashda xato: {}", exc)
