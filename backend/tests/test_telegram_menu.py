"""Telegram bot menyusi — tanlovni aniqlash, yuborish, webhook yo'naltirish."""
from __future__ import annotations

import asyncio

import pytest
from fastapi.testclient import TestClient

from app.config import settings
from app.instagram.models import IncomingEvent
from app.state.store import store
from app.telegram_business import menu as tg_menu
from app.telegram_business.client import telegram
from app.telegram_business.menu import Menu, MenuAction, MenuImage, MenuItem

PRICES = MenuItem(
    id="i1", command="narxlar", title="💰 Narxlar", text="Kotyol 50L — 1 200 000 so'm",
    images=(MenuImage("a", "sha-a", "image/png"), MenuImage("b", "sha-b", "image/jpeg")),
)
ADDRESS = MenuItem(id="i2", command="manzil", title="📍 Manzil", text="Toshkent, Chilonzor")
MENU = Menu(greeting="Xush kelibsiz!", items=(PRICES, ADDRESS))


@pytest.fixture(autouse=True)
def _menu_state(monkeypatch):
    monkeypatch.setattr(tg_menu, "_state", tg_menu._State(menu=MENU))
    monkeypatch.setattr(settings, "TG_SALES_BOT_TOKEN", "4242:secret")


@pytest.fixture
def fake_tg(monkeypatch):
    """Telegram va ERP chaqiruvlarini yozib boradi (tarmoqqa chiqmaydi)."""
    calls: dict[str, list] = {"message": [], "photo": [], "album": [], "download": [],
                              "log": [], "answer": []}

    async def send_message(chat_id, text, *, business_connection_id=None, reply_markup=None):
        calls["message"].append({"chat_id": chat_id, "text": text,
                                 "conn": business_connection_id, "markup": reply_markup})
        return {"sent": True}

    async def send_photo(chat_id, photo, *, caption=None, business_connection_id=None,
                         reply_markup=None):
        calls["photo"].append({"photo": photo, "caption": caption, "markup": reply_markup})
        return {"sent": True, "file_ids": ["fid-single"]}

    async def send_media_group(chat_id, photos, *, caption=None, business_connection_id=None):
        calls["album"].append({"photos": photos, "caption": caption,
                               "conn": business_connection_id})
        return {"sent": True, "file_ids": [f"fid-{i}" for i in range(len(photos))]}

    async def download(image):
        calls["download"].append(image.id)
        return (b"bytes-" + image.id.encode(), image.content_type)

    async def log_message(**kwargs):
        calls["log"].append(kwargs)
        return True

    async def answer(callback_id):
        calls["answer"].append(callback_id)
        return True

    async def fetch_context(user_id, limit=40, *, channel="instagram"):
        # Sukut bo'yicha — eski mijoz (oshkorlik qo'shilmaydi)
        return {"messages": calls["history"]}

    calls["history"] = [{"role": "user", "content": "salom"}]

    monkeypatch.setattr(telegram, "send_message", send_message)
    monkeypatch.setattr(telegram, "send_photo", send_photo)
    monkeypatch.setattr(telegram, "send_media_group", send_media_group)
    monkeypatch.setattr(telegram, "answer_callback_query", answer)
    monkeypatch.setattr(tg_menu, "_download", download)
    monkeypatch.setattr(tg_menu.leads_client, "log_message", log_message)
    monkeypatch.setattr(tg_menu.leads_client, "fetch_context", fetch_context)
    return calls


def _clear_file_cache():
    async def run():
        for sha in ("sha-a", "sha-b"):
            await store.set_value(tg_menu.FILE_KEY.format(bot="4242", sha=sha), "", ttl=0)
    asyncio.run(run())


# --------------------------------------------------------------------------- #
# Tanlovni aniqlash
# --------------------------------------------------------------------------- #
@pytest.mark.parametrize("text,kind,command", [
    ("/narxlar", "item", "narxlar"),
    ("/Narxlar@nur_sotuv_bot", "item", "narxlar"),
    ("💰 Narxlar", "item", "narxlar"),              # pastki klaviatura tugmasi
    ("  📍 manzil ", "item", "manzil"),
    ("/start", "greeting", None),
    ("/menu", "greeting", None),
    ("Menyu", "greeting", None),
    ("/start manzil", "item", "manzil"),           # t.me/<bot>?start=manzil
    ("/start noma_lum", "greeting", None),
])
def test_match_menu_choices(text, kind, command):
    action = tg_menu.match(text, MENU)
    assert action is not None and action.kind == kind
    assert (action.item.command if action.item else None) == command


@pytest.mark.parametrize("text", [
    "Narxlar qancha?", "narxlar", "/boshqa", "Salom", "",
])
def test_free_text_goes_to_ai(text):
    assert tg_menu.match(text, MENU) is None


def test_empty_menu_never_intercepts():
    """Bo'lim yo'q bo'lsa /start ham avvalgidek AI'ga ketadi."""
    assert tg_menu.match("/start", Menu()) is None


def test_menu_from_payload_skips_broken_items():
    menu = Menu.from_payload({"greeting": None, "items": [
        {"id": "1", "command": "Narxlar", "title": "Narxlar",
         "images": [{"id": "img1", "sha256": "x"}, {"sha256": "no-id"}]},
        {"id": "2", "command": "", "title": "Buyruqsiz"},
    ]})
    assert [i.command for i in menu.items] == ["narxlar"]
    assert [img.id for img in menu.items[0].images] == ["img1"]
    assert menu.greeting_text == tg_menu.DEFAULT_GREETING
    assert menu.commands() == [{"command": "narxlar", "description": "Narxlar"}]


def test_keyboards():
    reply = tg_menu.reply_keyboard(MENU)
    assert reply["keyboard"] == [[{"text": "💰 Narxlar"}, {"text": "📍 Manzil"}]]
    assert reply["is_persistent"] is True
    inline = tg_menu.inline_keyboard(MENU)
    assert inline["inline_keyboard"][0][0]["callback_data"] == "menu:narxlar"
    # Telegram chegarasi: callback_data 1-64 bayt
    assert all(len(b["callback_data"].encode()) <= 64 for b in inline["inline_keyboard"][0])


# --------------------------------------------------------------------------- #
# Yuborish
# --------------------------------------------------------------------------- #
def test_send_item_album_with_caption_then_uses_file_id_cache(fake_tg):
    _clear_file_cache()
    parts = asyncio.run(tg_menu.send_item("77", PRICES, conn_id=None, store_key="tg:77"))

    assert len(fake_tg["album"]) == 1
    album = fake_tg["album"][0]
    assert album["caption"] == PRICES.text
    assert album["photos"][0] == (b"bytes-a", "image/png")
    assert fake_tg["message"] == [], "qisqa matn izohga sig'adi — alohida xabar kerak emas"
    assert parts == ["[2 ta rasm]", PRICES.text]

    # Ikkinchi marta — rasmlar ERP'dan qayta yuklanmaydi, file_id ishlatiladi
    asyncio.run(tg_menu.send_item("77", PRICES, conn_id=None, store_key="tg:77"))
    assert fake_tg["download"] == ["a", "b"]
    assert fake_tg["album"][1]["photos"] == ["fid-0", "fid-1"]


def test_long_text_sent_separately(fake_tg):
    _clear_file_cache()
    long_item = MenuItem(id="i3", command="katalog", title="Katalog", text="x" * 1500,
                         images=(MenuImage("a", "sha-a"),))
    asyncio.run(tg_menu.send_item("77", long_item, conn_id="conn_1", store_key="tg:77"))
    assert fake_tg["photo"][0]["caption"] is None
    assert fake_tg["message"][0]["text"] == "x" * 1500
    assert fake_tg["message"][0]["conn"] == "conn_1"


def test_text_only_item(fake_tg):
    parts = asyncio.run(tg_menu.send_item("77", ADDRESS, conn_id=None, store_key="tg:77"))
    assert fake_tg["album"] == [] and fake_tg["photo"] == []
    assert fake_tg["message"][0]["text"] == "Toshkent, Chilonzor"
    assert parts == ["Toshkent, Chilonzor"]


def test_stale_file_id_falls_back_to_upload(fake_tg, monkeypatch):
    """Keshdagi file_id ishlamasa (bot tokeni almashgan) — rasmlar qayta yuklanadi."""
    async def seed():
        await store.set_value(tg_menu.FILE_KEY.format(bot="4242", sha="sha-a"), "old-a")
        await store.set_value(tg_menu.FILE_KEY.format(bot="4242", sha="sha-b"), "old-b")
    asyncio.run(seed())

    attempts: list = []

    async def flaky_album(chat_id, photos, *, caption=None, business_connection_id=None):
        attempts.append(photos)
        if photos[0] == "old-a":
            return {"sent": False, "error": "wrong file identifier"}
        return {"sent": True, "file_ids": ["new-a", "new-b"]}

    monkeypatch.setattr(telegram, "send_media_group", flaky_album)
    asyncio.run(tg_menu.send_item("77", PRICES, conn_id=None, store_key="tg:77"))

    assert attempts[0] == ["old-a", "old-b"]
    assert attempts[1][0] == (b"bytes-a", "image/png")

    async def check():
        assert await store.get_value(tg_menu.FILE_KEY.format(bot="4242", sha="sha-a")) == "new-a"
    asyncio.run(check())


def test_menu_reply_does_not_pause_bot_on_business_echo(fake_tg):
    """Business ulanishida bot yuborgan albom echo bo'lib qaytadi — bu operator emas."""
    from app.processing import pipeline

    _clear_file_cache()
    asyncio.run(tg_menu.send_item("6060", PRICES, conn_id="conn_1", store_key="tg:6060"))

    for text in (PRICES.text, "[Mijoz rasm yubordi]"):
        echo = IncomingEvent(kind="echo", text=text, sender_id="6060",
                             channel="telegram", chat_id="6060")
        asyncio.run(pipeline.process_event(echo))

    async def check():
        assert await store.is_paused("tg:6060") is False
    asyncio.run(check())


def test_greeting_keyboard_depends_on_chat_type(fake_tg):
    asyncio.run(tg_menu.send_greeting("1", MENU, conn_id=None, store_key="tg:1"))
    asyncio.run(tg_menu.send_greeting("2", MENU, conn_id="conn_1", store_key="tg:2"))
    bot_chat, business = fake_tg["message"]
    assert bot_chat["text"] == "Xush kelibsiz!" and "keyboard" in bot_chat["markup"]
    # Business'da pastki klaviatura taqiqlangan — faqat inline tugmalar
    assert "inline_keyboard" in business["markup"] and business["conn"] == "conn_1"


def test_handle_action_logs_conversation_and_dedups(fake_tg):
    event = IncomingEvent(kind="dm", text="/manzil", sender_id="8080", channel="telegram",
                          chat_id="8080", message_id="501", username="mijoz")
    action = MenuAction("item", ADDRESS)
    asyncio.run(tg_menu.handle_action(event, action))
    asyncio.run(tg_menu.handle_action(event, action))     # Telegram qayta yubordi

    assert len(fake_tg["message"]) == 1
    assert [(l["role"], l["text"]) for l in fake_tg["log"]] == [
        ("user", "/manzil"), ("assistant", "Toshkent, Chilonzor"),
    ]
    assert all(l["channel"] == "telegram" for l in fake_tg["log"])


def test_handle_callback_sends_item_to_business_chat(fake_tg):
    callback = {
        "id": "cb-1", "data": "menu:manzil", "from": {"id": 9090, "username": "ali"},
        "message": {"message_id": 3, "business_connection_id": "conn_7",
                    "chat": {"id": 9090, "type": "private"}},
    }
    asyncio.run(tg_menu.handle_callback(callback))
    asyncio.run(tg_menu.handle_callback(callback))

    assert fake_tg["answer"] == ["cb-1", "cb-1"], "spinner har doim o'chirilsin"
    assert len(fake_tg["message"]) == 1
    assert fake_tg["message"][0]["conn"] == "conn_7"
    assert fake_tg["log"][0]["text"] == "[Tugma: 📍 Manzil]"


# --------------------------------------------------------------------------- #
# Klient: albom multipart ko'rinishi
# --------------------------------------------------------------------------- #
def test_client_album_builds_attach_references(monkeypatch):
    captured: dict = {}

    async def fake_call(method, payload, *, files=None):
        captured.update(method=method, payload=payload, files=files)
        return True, [{"photo": [{"file_id": "s"}, {"file_id": "big-0"}]},
                      {"photo": [{"file_id": "big-1"}]}]

    monkeypatch.setattr(telegram, "_call", fake_call)
    result = asyncio.run(telegram.send_media_group(
        "5", ["cached-id", (b"raw", "image/png")], caption="Narxlar",
        business_connection_id="conn_1"))

    media = captured["payload"]["media"]
    assert media[0] == {"type": "photo", "media": "cached-id", "caption": "Narxlar"}
    assert media[1] == {"type": "photo", "media": "attach://photo1"}
    assert captured["files"]["photo1"] == ("photo1.png", b"raw", "image/png")
    assert captured["payload"]["business_connection_id"] == "conn_1"
    assert result == {"sent": True, "file_ids": ["big-0", "big-1"]}


# --------------------------------------------------------------------------- #
# Webhook yo'naltirish
# --------------------------------------------------------------------------- #
def test_webhook_routes_menu_and_free_text(monkeypatch):
    from app.telegram_business import webhook

    routed: list[tuple[str, str]] = []

    async def fake_action(event, action):
        routed.append(("menu", event.text))

    async def fake_process(event, **kwargs):
        routed.append(("ai", event.text))

    async def fake_callback(callback):
        routed.append(("callback", callback["data"]))

    async def no_refresh():
        return tg_menu.current()

    monkeypatch.setattr(webhook.menu, "handle_action", fake_action)
    monkeypatch.setattr(webhook.menu, "handle_callback", fake_callback)
    monkeypatch.setattr(webhook, "process_event", fake_process)
    monkeypatch.setattr(tg_menu, "refresh", no_refresh)
    monkeypatch.setattr(settings, "TG_SALES_ENABLED", True)
    monkeypatch.setattr(settings, "TG_WEBHOOK_SECRET", "s3cret")
    from app.main import app

    hdr = {"X-Telegram-Bot-Api-Secret-Token": "s3cret"}
    with TestClient(app) as c:
        for i, text in enumerate(["/narxlar", "Narxi qancha?"]):
            c.post("/webhook/telegram", headers=hdr, json={"update_id": i, "message": {
                "message_id": 100 + i, "text": text,
                "from": {"id": 31, "is_bot": False}, "chat": {"id": 31, "type": "private"}}})
        c.post("/webhook/telegram", headers=hdr, json={"update_id": 9, "callback_query": {
            "id": "q", "data": "menu:manzil", "from": {"id": 31},
            "message": {"message_id": 1, "chat": {"id": 31, "type": "private"}}}})


    assert routed == [("menu", "/narxlar"), ("ai", "Narxi qancha?"), ("callback", "menu:manzil")]


# --------------------------------------------------------------------------- #
# Review'dan keyingi holatlar
# --------------------------------------------------------------------------- #
def test_other_worker_picks_up_menu_from_shared_state(monkeypatch):
    """ERP «yangila» xabari bitta workerga tushadi — qolganlari umumiy holatdan oladi."""
    import json

    payload = {"greeting": "", "items": [{"id": "9", "command": "aksiya", "title": "🎁 Aksiya"}]}

    async def seed():
        await store.set_value(tg_menu.PAYLOAD_KEY, json.dumps(payload))
        await store.set_value(tg_menu.REV_KEY, "rev-42")
    asyncio.run(seed())
    try:
        menu = asyncio.run(tg_menu.ensure_fresh())
        assert [i.command for i in menu.items] == ["aksiya"]
        assert tg_menu._state.rev == "rev-42"
    finally:
        async def clear():
            await store.set_value(tg_menu.REV_KEY, "", ttl=0)
        asyncio.run(clear())


def test_caption_limit_counts_utf16_like_telegram(fake_tg):
    """Emoji Telegram'da 2 birlik — 1000 belgili emoji'li matn izohga sig'maydi."""
    _clear_file_cache()
    text = "💰" * 30 + "x" * 970           # 1000 kod nuqtasi, 1030 UTF-16 birligi
    assert tg_menu.tg_len(text) == 1030
    item = MenuItem(id="e", command="emoji", title="Emoji", text=text,
                    images=(MenuImage("a", "sha-a"),))
    asyncio.run(tg_menu.send_item("77", item, conn_id=None, store_key="tg:77"))
    assert fake_tg["photo"][0]["caption"] is None
    assert fake_tg["message"][0]["text"] == text


def test_rejected_caption_still_delivers_images(fake_tg, monkeypatch):
    _clear_file_cache()
    attempts: list = []

    async def picky_album(chat_id, photos, *, caption=None, business_connection_id=None):
        attempts.append(caption)
        if caption:
            return {"sent": False, "error": "Bad Request: message caption is too long"}
        return {"sent": True, "file_ids": ["n1", "n2"]}

    monkeypatch.setattr(telegram, "send_media_group", picky_album)
    parts = asyncio.run(tg_menu.send_item("77", PRICES, conn_id=None, store_key="tg:77"))
    assert attempts == [PRICES.text, None]
    assert fake_tg["message"][0]["text"] == PRICES.text
    assert parts == ["[2 ta rasm]", PRICES.text]


def test_marks_sent_before_sending_to_avoid_echo_race(fake_tg, monkeypatch):
    """Echo mark_sent'dan oldin kelsa bot o'zini pauzaga qo'yardi."""
    seen: list[bool] = []

    async def checking_send(chat_id, text, *, business_connection_id=None, reply_markup=None):
        seen.append(await store.was_sent_by_bot("tg:5151", text))
        return {"sent": True}

    monkeypatch.setattr(telegram, "send_message", checking_send)
    asyncio.run(tg_menu.send_item("5151", ADDRESS, conn_id="c", store_key="tg:5151"))
    asyncio.run(tg_menu.send_greeting("5151", MENU, conn_id="c", store_key="tg:5151"))
    assert seen == [True, True]


def test_bot_chat_item_refreshes_reply_keyboard(fake_tg):
    event = IncomingEvent(kind="dm", text="/start manzil", sender_id="3131", channel="telegram",
                          chat_id="3131", message_id="1")
    asyncio.run(tg_menu.handle_action(event, MenuAction("item", ADDRESS)))
    assert "keyboard" in fake_tg["message"][0]["markup"], "deep link orqali kelgan ham tugmalarni ko'rsin"


def test_first_contact_gets_ai_disclosure(fake_tg):
    fake_tg["history"].clear()                       # yangi mijoz
    event = IncomingEvent(kind="dm", text="/start", sender_id="4141", channel="telegram",
                          chat_id="4141", message_id="1")
    asyncio.run(tg_menu.handle_action(event, MenuAction("greeting")))
    assert "AI yordamchisi" in fake_tg["message"][0]["text"]
    assert fake_tg["message"][0]["text"].startswith("Xush kelibsiz!")


def test_stale_callback_shows_fresh_menu(fake_tg):
    callback = {"id": "cb-old", "data": "menu:ochirilgan", "from": {"id": 7070},
                "message": {"message_id": 1, "chat": {"id": 7070, "type": "private"}}}
    asyncio.run(tg_menu.handle_callback(callback))
    assert fake_tg["message"][0]["text"] == "Xush kelibsiz!"
    assert "keyboard" in fake_tg["message"][0]["markup"]


def test_owner_button_press_logged_as_operator(fake_tg):
    callback = {"id": "cb-owner", "data": "menu:manzil", "from": {"id": 555001},
                "message": {"message_id": 1, "business_connection_id": "conn_1",
                            "chat": {"id": 8181, "type": "private"}}}
    asyncio.run(tg_menu.handle_callback(callback))
    assert fake_tg["log"][0]["role"] == "operator"
    assert fake_tg["message"][0]["conn"] == "conn_1"


def test_upload_not_retried_after_read_timeout(monkeypatch):
    """Rasm yuklashda javob kelmasa qayta yubormaymiz — mijoz albomni ikki marta olmasin."""
    import httpx

    posts: list[int] = []

    class FakeClient:
        def __init__(self, *a, **k):
            pass

        async def __aenter__(self):
            return self

        async def __aexit__(self, *a):
            return False

        async def post(self, url, **kwargs):
            posts.append(1)
            raise httpx.ReadTimeout("slow")

    monkeypatch.setattr(httpx, "AsyncClient", FakeClient)
    result = asyncio.run(telegram.send_photo("5", (b"raw", "image/png")))
    assert result["sent"] is False and len(posts) == 1


def test_menu_load_error_keeps_old_menu(monkeypatch):
    async def broken():
        raise RuntimeError("db down")

    monkeypatch.setattr(tg_menu, "_load_payload", broken)
    assert asyncio.run(tg_menu.refresh()) == MENU
