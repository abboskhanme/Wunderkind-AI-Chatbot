"""Instagram akkauntni ULASH (Business Login) — "bir marta bosib" ulanadi.

Nima uchun kerak: token'ni qo'lda Graph API Explorer'dan olish uzoq va xatoga
moyil. Bu modul rasmiy OAuth oqimini o'zi bajaradi:

  1. POST /api/settings/instagram/connect-url -> imzolangan state bilan login URL
  2. GET  /connect/callback  -> code ni tokenga almashtiradi (qisqa muddatli)
                                -> uzoq muddatli tokenga (60 kun) almashtiradi
                                -> IG_USER_ID ni oladi
                                -> webhook'larga obuna qiladi
                                -> hammasini sozlamalar jadvaliga yozadi

Shundan keyin token 60 kunlik bo'ladi va `refresh_token_if_due()` uni har kuni
tekshirib, muddati yaqinlashsa avtomatik yangilaydi (restart shart emas).

Hujjat: Instagram API with Instagram Login > Business Login.
"""
from __future__ import annotations

import html
from datetime import datetime, timedelta, timezone
from urllib.parse import urlencode

import httpx
from fastapi import APIRouter, Request
from fastapi.responses import HTMLResponse
from loguru import logger

from app.config import settings
from app.instagram.client import instagram

router = APIRouter(tags=["Instagram ulash"])

AUTHORIZE_URL = "https://www.instagram.com/oauth/authorize"
TOKEN_URL = "https://api.instagram.com/oauth/access_token"
SCOPES = (
    "instagram_business_basic,"
    "instagram_business_manage_messages,"
    "instagram_business_manage_comments"
)
# 60 kunlik tokenni shuncha kundan keyin yangilaymiz (zaxira bilan)
_REFRESH_AFTER_DAYS = 45


def _redirect_uri() -> str:
    return f"{settings.PUBLIC_URL.rstrip('/')}/connect/callback"


def _page(title: str, body: str, ok: bool = True) -> HTMLResponse:
    color = "#16a34a" if ok else "#dc2626"
    return HTMLResponse(
        f"""<!doctype html><meta charset="utf-8">
<title>{title}</title>
<body style="font-family:system-ui,sans-serif;max-width:640px;margin:60px auto;padding:0 20px;line-height:1.6">
<h2 style="color:{color}">{title}</h2>{body}
<p><a href="/settings" style="display:inline-block;margin-top:12px;padding:10px 16px;background:#4f46e5;color:#fff;border-radius:8px;text-decoration:none">← Admin panelga qaytish</a></p></body>""",
        status_code=200 if ok else 400,
    )


# ===========================================================================
# 1-qadam — Instagram login oynasi manzili (admin panel so'raydi)
# ===========================================================================
def missing_config() -> list[str]:
    return [
        name
        for name, val in (
            ("IG_APP_ID", settings.IG_APP_ID),
            ("IG_APP_SECRET", settings.IG_APP_SECRET),
            ("PUBLIC_URL", settings.PUBLIC_URL),
        )
        if not val
    ]


def build_authorize_url(state: str) -> str:
    """Instagram OAuth URL. `state` is a short-lived signed token from the panel:
    without it anyone could open /connect and attach THEIR account to our agent."""
    query = urlencode(
        {
            "client_id": settings.IG_APP_ID,
            "redirect_uri": _redirect_uri(),
            "response_type": "code",
            "scope": SCOPES,
            "state": state,
        }
    )
    return f"{AUTHORIZE_URL}?{query}"


# ===========================================================================
# 2-qadam — Instagram qaytargan `code` ni tokenga almashtirish
# ===========================================================================
@router.get("/connect/callback")
async def connect_callback(request: Request):
    params = request.query_params
    if params.get("error"):
        return _page(
            "Ruxsat berilmadi",
            f"<p>Instagram javobi: <code>{html.escape(params.get('error_description') or params['error'])}</code></p>"
            "<p>Admin paneldan «Ulash» tugmasini qaytadan bosing.</p>",
            ok=False,
        )
    from app.core.security import decode_token

    if not decode_token(params.get("state") or "", purpose="ig_connect"):
        return _page(
            "Havola eskirgan",
            "<p>Ulash havolasi noto'g'ri yoki muddati o'tgan. Admin paneldan "
            "<b>Sozlamalar → Instagram → «Ulash»</b> tugmasini qaytadan bosing.</p>",
            ok=False,
        )
    code = params.get("code")
    if not code:
        return _page("Xato", "<p><code>code</code> kelmadi.</p>", ok=False)

    try:
        token, user_id = await _exchange_code(code)
        long_token = await _to_long_lived(token)
        # Akkauntning BARCHA identifikatorlarini olamiz — webhook'da o'z
        # izohimizni tanish uchun ularning hammasi kerak
        me = await _fetch_me(long_token)
        user_id = user_id or me.get("user_id") or me.get("id")
    except Exception as exc:  # noqa: BLE001
        logger.exception("Instagram ulashda xato: {}", exc)
        return _page("Ulashda xato", f"<p><code>{html.escape(str(exc))}</code></p>", ok=False)

    # Ishlab turgan holatda qo'llaymiz (restartsiz)
    settings.IG_ACCESS_TOKEN = long_token
    settings.IG_USER_ID = str(user_id or "")
    settings.IG_ACCOUNT_ID = str(me.get("id") or "")
    settings.IG_USERNAME = str(me.get("username") or "")
    settings.IG_TOKEN_ISSUED_AT = datetime.now(timezone.utc).isoformat()

    # Webhook maydonlariga obuna (comments + messages)
    sub = await instagram.subscribe_webhooks()
    subscribed = bool(sub.get("success", True)) and sub != {}

    # Persist — survives container restarts
    from app.runtime_config import push_config

    saved = await push_config(
        {
            "IG_ACCESS_TOKEN": long_token,
            "IG_USER_ID": settings.IG_USER_ID,
            "IG_ACCOUNT_ID": settings.IG_ACCOUNT_ID,
            "IG_USERNAME": settings.IG_USERNAME,
            "IG_TOKEN_ISSUED_AT": settings.IG_TOKEN_ISSUED_AT,
        }
    )

    logger.info(
        "Instagram connected: user_id={} account_id={} username={} subscribed={} saved={}",
        settings.IG_USER_ID, settings.IG_ACCOUNT_ID, settings.IG_USERNAME,
        subscribed, saved,
    )
    sub_txt = "ha" if subscribed else "tekshiring"
    saved_txt = "ha" if saved else "YO'Q — qaytadan ulang"
    return _page(
        "Instagram ulandi ✅",
        f"<p>Akkaunt ID: <code>{user_id}</code></p>"
        f"<p>Webhook obunasi: <b>{sub_txt}</b></p>"
        f"<p>Sozlamalarga saqlandi: <b>{saved_txt}</b></p>"
        "<p>Endi postingizga izoh yozib yoki DM yuborib sinab ko'ring. "
        "Bu oynani yopib, admin panelga qaytishingiz mumkin.</p>",
        ok=True,
    )


# ===========================================================================
# Token almashish yordamchilari
# ===========================================================================
async def _exchange_code(code: str) -> tuple[str, str | None]:
    """`code` -> qisqa muddatli (1 soat) token."""
    async with httpx.AsyncClient(timeout=20.0) as client:
        resp = await client.post(
            TOKEN_URL,
            data={
                "client_id": settings.IG_APP_ID,
                "client_secret": settings.IG_APP_SECRET,
                "grant_type": "authorization_code",
                "redirect_uri": _redirect_uri(),
                "code": code,
            },
        )
    if resp.status_code != 200:
        raise RuntimeError(f"token almashtirish {resp.status_code}: {resp.text[:200]}")
    data = resp.json()
    return data["access_token"], (str(data["user_id"]) if data.get("user_id") else None)


async def _to_long_lived(short_token: str) -> str:
    """Qisqa muddatli -> uzoq muddatli (60 kun) token."""
    async with httpx.AsyncClient(timeout=20.0) as client:
        resp = await client.get(
            f"{settings.IG_API_BASE.rstrip('/')}/access_token",
            params={
                "grant_type": "ig_exchange_token",
                "client_secret": settings.IG_APP_SECRET,
                "access_token": short_token,
            },
        )
    if resp.status_code != 200:
        raise RuntimeError(f"uzoq token {resp.status_code}: {resp.text[:200]}")
    return resp.json()["access_token"]


async def ensure_identity() -> bool:
    """Akkauntimiz ID va username'ini bilishimizga KAFOLAT beradi.

    Nima uchun kerak: webhook'da o'z izohimizni aynan shu ID/username bo'yicha
    ajratamiz. Bilmasak — bot o'z javobini begona izoh deb hisoblab, o'ziga
    javob yozadi va cheksiz halqa boshlanadi.

    Ilgari bu qiymatlar faqat «Ulash» tugmasi bosilganda saqlanardi, ya'ni eski
    ulanishlarda ular bo'sh qolib ketardi. Endi agent ishga tushganda tokendan
    foydalanib o'zi aniqlaydi va bazaga yozib qo'yadi — qo'lda qayta ulash
    talab qilinmaydi.
    """
    if not settings.IG_ACCESS_TOKEN:
        return False
    if settings.IG_ACCOUNT_ID and settings.IG_USERNAME:
        return True  # allaqachon ma'lum

    me = await _fetch_me(settings.IG_ACCESS_TOKEN)
    if not me:
        logger.error(
            "Akkaunt ID sini aniqlab bo'lmadi — bot o'z izohini tanimasligi va "
            "halqaga tushishi mumkin. Tokenni tekshiring."
        )
        return False

    settings.IG_ACCOUNT_ID = str(me.get("id") or "")
    settings.IG_USERNAME = str(me.get("username") or "")
    if not settings.IG_USER_ID:
        settings.IG_USER_ID = str(me.get("user_id") or "")

    from app.runtime_config import push_config

    await push_config({
        "IG_USER_ID": settings.IG_USER_ID,
        "IG_ACCOUNT_ID": settings.IG_ACCOUNT_ID,
        "IG_USERNAME": settings.IG_USERNAME,
    })
    logger.info(
        "Akkaunt aniqlandi: account_id={} user_id={} username={}",
        settings.IG_ACCOUNT_ID, settings.IG_USER_ID, settings.IG_USERNAME,
    )
    return True


async def _fetch_me(token: str) -> dict:
    """Akkaunt haqidagi barcha identifikatorlar: `id`, `user_id`, `username`.

    Uchalasi ham kerak: webhook'da `from.id` ba'zan akkauntning o'z `id` si,
    ba'zan app-scoped `user_id` bo'lib keladi. Bittasiga tayanib qolsak, bot
    o'z izohini begona deb hisoblab, cheksiz javob halqasiga tushadi.
    """
    async with httpx.AsyncClient(timeout=20.0) as client:
        resp = await client.get(
            f"{settings.IG_API_BASE.rstrip('/')}/{settings.GRAPH_API_VERSION}/me",
            params={"fields": "id,user_id,username", "access_token": token},
        )
    if resp.status_code != 200:
        logger.warning("me?fields=id,user_id {}: {}", resp.status_code, resp.text[:200])
        return {}
    return resp.json() or {}


# ===========================================================================
# Token yangilash — scheduler har kuni chaqiradi
# ===========================================================================
async def refresh_token_if_due() -> bool:
    """Uzoq muddatli tokenni muddati yaqinlashganda yangilaydi (60 -> yana 60 kun)."""
    if not settings.IG_ACCESS_TOKEN:
        return False

    issued = settings.IG_TOKEN_ISSUED_AT
    if issued:
        try:
            when = datetime.fromisoformat(issued)
            if when.tzinfo is None:
                when = when.replace(tzinfo=timezone.utc)
            if datetime.now(timezone.utc) - when < timedelta(days=_REFRESH_AFTER_DAYS):
                return False  # hali erta
        except ValueError:
            logger.warning("IG_TOKEN_ISSUED_AT o'qib bo'lmadi: {}", issued)

    try:
        async with httpx.AsyncClient(timeout=20.0) as client:
            resp = await client.get(
                f"{settings.IG_API_BASE.rstrip('/')}/refresh_access_token",
                params={
                    "grant_type": "ig_refresh_token",
                    "access_token": settings.IG_ACCESS_TOKEN,
                },
            )
        if resp.status_code != 200:
            logger.error("Token yangilash {}: {}", resp.status_code, resp.text[:200])
            from app.telegram.notifier import notify_token_problem

            await notify_token_problem(resp.text[:200])
            return False
        new_token = resp.json()["access_token"]
    except httpx.HTTPError as exc:
        logger.warning("Token yangilashda ulanish xatosi: {}", exc)
        return False

    settings.IG_ACCESS_TOKEN = new_token
    settings.IG_TOKEN_ISSUED_AT = datetime.now(timezone.utc).isoformat()

    from app.runtime_config import push_config

    await push_config(
        {
            "IG_ACCESS_TOKEN": new_token,
            "IG_TOKEN_ISSUED_AT": settings.IG_TOKEN_ISSUED_AT,
        }
    )
    logger.info("Instagram tokeni yangilandi (yana 60 kun)")
    return True
