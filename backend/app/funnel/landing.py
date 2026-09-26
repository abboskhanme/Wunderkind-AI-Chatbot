"""`/go/<token>` — the page the Instagram «Qo'llanmani olish» button opens.

Why not a plain t.me link: Instagram opens links in its in-app browser, and
that browser blocks the jump from t.me to the Telegram app (`tg://`), so the
page flashes and closes. Our own page offers every route that can escape it:
- a tapped `tg://resolve` link (a user gesture is allowed where an automatic
  redirect is not),
- on Android an `intent://` link aimed at the Telegram app, falling back to
  t.me in the system browser,
- on iOS an `x-safari-https://` link (opens Safari, iOS 17+),
- the plain t.me link, and a manual «/start <code>» the parent can send to the
  bot themselves (the bot treats it exactly like the deep link).
The page redirects automatically by device (phone → app, computer → Telegram
Web); the buttons are only a manual fallback.
"""
from __future__ import annotations

import json
import re
from html import escape
from urllib.parse import quote

from fastapi import APIRouter, Request
from loguru import logger
from fastapi.responses import HTMLResponse

from app.config import settings

router = APIRouter(tags=["Funnel landing"])

# Entry tokens (12 chars) and funnel payloads (tgc, f_<slug>) — nothing else
_TOKEN_RE = re.compile(r"[A-Za-z0-9_-]{2,40}")

_HEADERS = {
    "X-Content-Type-Options": "nosniff",
    "Referrer-Policy": "no-referrer",
    "Cache-Control": "no-store",
    "Content-Security-Policy": ("default-src 'none'; style-src 'unsafe-inline'; "
                                "script-src 'unsafe-inline'; base-uri 'none'; "
                                "form-action 'none'; frame-ancestors 'none'"),
}

_CSS = """
*{box-sizing:border-box}body{margin:0;font:17px/1.55 system-ui,-apple-system,"Segoe UI",Roboto,sans-serif;color:#1f2937;background:#f1f5f9}
main{max-width:460px;margin:0 auto;padding:28px 18px 40px}
.card{background:#fff;border-radius:16px;padding:24px 20px;box-shadow:0 1px 3px rgba(0,0,0,.08)}
h1{font-size:22px;line-height:1.3;margin:0 0 8px}p{margin:0 0 14px}
.btn{display:block;width:100%;text-align:center;padding:15px 16px;border-radius:12px;font-weight:600;text-decoration:none;margin:0 0 10px;border:0;font-size:17px;cursor:pointer}
.primary{background:#229ED9;color:#fff}.secondary{background:#e0f2fe;color:#0369a1}.ghost{background:#f1f5f9;color:#334155}
.hint{font-size:15px;color:#475569;background:#f8fafc;border:1px solid #e2e8f0;border-radius:12px;padding:12px 14px;margin:16px 0 0}
.code{display:flex;gap:8px;align-items:center;margin-top:8px}
.code code{flex:1;font:600 16px ui-monospace,Menlo,monospace;background:#fff;border:1px dashed #94a3b8;border-radius:8px;padding:10px;word-break:break-all}
.code button{padding:10px 14px;border:0;border-radius:8px;background:#334155;color:#fff;font:inherit;font-size:15px}
.hide{display:none}
"""


def _page(title: str, body: str, status: int = 200) -> HTMLResponse:
    html = (
        "<!doctype html><html lang=\"uz\"><head><meta charset=\"utf-8\">"
        "<meta name=\"viewport\" content=\"width=device-width,initial-scale=1\">"
        "<meta name=\"robots\" content=\"noindex\">"
        f"<title>{escape(title)}</title><style>{_CSS}</style></head>"
        f"<body><main>{body}</main></body></html>"
    )
    return HTMLResponse(html, status_code=status, headers=_HEADERS)


def render(bot: str, token: str) -> HTMLResponse:
    """The landing page for one deep-link payload (values already validated).

    It redirects by itself (nothing to tap): Android → the Telegram app via an
    intent (t.me if the app is missing); iPhone → the app via tg://, and from
    Instagram's in-app browser, if that is blocked, Safari (which then opens the
    app); computer → Telegram Web in the browser. The buttons stay as a manual
    fallback."""
    tme = f"https://t.me/{bot}?start={token}"
    tg = f"tg://resolve?domain={bot}&start={token}"
    intent = (f"intent://resolve?domain={bot}&start={token}#Intent;scheme=tg;"
              f"package=org.telegram.messenger;S.browser_fallback_url={quote(tme, safe='')};end")
    here = f"{settings.PUBLIC_URL.rstrip('/')}/go/{token}"
    safari = "x-safari-" + here if here.startswith("https://") else ""
    web = f"https://web.telegram.org/k/#?tgaddr={quote(tg, safe='')}"
    command = f"/start {token}"

    body = f"""
<div class="card">
  <h1>Telegram ochilmoqda…</h1>
  <p>Telegram ochilgach, pastdagi <b>«START»</b> tugmasini bosing — qo'llanma o'sha
  yerda. Ochilmasa, tugmalardan birini bosing:</p>
  <a id="open" class="btn primary" href="{escape(tg)}">Telegram'da ochish</a>
  <a id="safari" class="btn secondary hide" href="{escape(safari)}">Safari orqali ochish</a>
  <a id="web" class="btn secondary hide" href="{escape(web)}">Telegram Web'da ochish</a>
  <a class="btn ghost" href="{escape(tme)}">t.me orqali ochish</a>
  <div class="hint">
    Yoki Telegram'da <b>@{escape(bot)}</b> botini toping va shu xabarni yuboring:
    <div class="code"><code id="cmd">{escape(command)}</code>
    <button id="copy" type="button">Nusxa</button></div>
  </div>
</div>
<script>
(function(){{
  var ua = navigator.userAgent || "";
  var inApp = /Instagram|FBAN|FBAV|FB_IAB/i.test(ua);
  var android = /Android/i.test(ua);
  var ios = /iPhone|iPad|iPod/i.test(ua) ||
            (navigator.platform === "MacIntel" && navigator.maxTouchPoints > 1);
  var mobile = android || ios || /Mobile/i.test(ua);
  var TG = {json.dumps(tg)}, INTENT = {json.dumps(intent)},
      SAFARI = {json.dumps(safari)}, WEB = {json.dumps(web)};
  var open = document.getElementById("open");
  if (android) open.href = INTENT;
  if (ios && inApp && SAFARI) document.getElementById("safari").classList.remove("hide");
  if (!mobile) document.getElementById("web").classList.remove("hide");
  var copy = document.getElementById("copy");
  copy.onclick = function(){{
    var text = document.getElementById("cmd").textContent;
    if (navigator.clipboard) navigator.clipboard.writeText(text).then(function(){{
      copy.textContent = "✓";
    }});
  }};
  // Automatic: phone → the app first, computer → the browser (Telegram Web)
  if (android) {{
    location.href = INTENT;
  }} else if (ios) {{
    location.href = TG;
    // Instagram's browser may block tg:// — still here after a moment → Safari
    if (inApp && SAFARI) setTimeout(function(){{
      if (!document.hidden) location.href = SAFARI;
    }}, 1200);
  }} else if (!mobile) {{
    location.replace(WEB);
  }}
}})();
</script>"""
    return _page("Telegram ochilmoqda — qo'llanma", body)


@router.api_route("/go/{token}", methods=["GET", "HEAD"], include_in_schema=False)
async def landing(token: str, request: Request) -> HTMLResponse:
    from app.services.agent_status import telegram_bot_username

    # Which devices/browsers reach the page — the only way to see why Telegram
    # did not open for someone
    logger.info("Funnel landing /go/{} ua={}", token[:40],
                (request.headers.get("user-agent") or "")[:200])

    if not _TOKEN_RE.fullmatch(token):
        return _page("Havola noto'g'ri", "<div class=\"card\"><h1>Havola noto'g'ri</h1>"
                     "<p>Instagram'dagi xabarimizdagi tugmani qayta bosing.</p></div>", 404)
    bot = await telegram_bot_username()
    if not bot:
        return _page("Vaqtincha ishlamayapti", "<div class=\"card\"><h1>Vaqtincha "
                     "ishlamayapti</h1><p>Birozdan so'ng qayta urinib ko'ring.</p></div>", 503)
    return render(bot, token)
