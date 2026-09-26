"""`/f/<slug>` — the public form page (SPEC §15.3).

Server-rendered HTML with inline CSS and no scripts: opens fast on any phone,
works inside Instagram/Telegram in-app browsers and without JavaScript.
GET shows the form; POST validates, stores (→ lead) and redirects to `?sent=1`.

Anti-spam without third parties: a hidden honeypot field, a signed render token
(too fast or too old → send again) and a per-IP rate limit. The IP is only used
for the rate limit key and never stored.
"""
from __future__ import annotations

import hashlib
import hmac
import ipaddress
import re
import time
from html import escape
from typing import Any, Mapping, Optional
from urllib.parse import parse_qs

from fastapi import APIRouter, Request
from fastapi.responses import HTMLResponse, RedirectResponse, Response
from loguru import logger
from sqlalchemy import select

from app.config import settings
from app.db import session as db_session
from app.forms import service
from app.forms.fields import Checked, validate_answers
from app.models.form import Form
from app.state.store import store

router = APIRouter(tags=["Forms (public)"])

MAX_BODY = 256 * 1024
MAX_FIELDS_IN_BODY = 2000
ALERTS_PER_MINUTE = 10
_TOKEN_RE = re.compile(r"(\d{1,12})\.([0-9a-f]{24})", re.ASCII)
_CONTROL = re.compile(r"[\x00-\x08\x0b\x0c\x0e-\x1f\x7f]")
MIN_FILL_SECONDS = 2
TOKEN_TTL = 24 * 3600
RATE_WINDOW = 600
RATE_LIMIT = 5
UTM_KEYS = ("utm_source", "utm_medium", "utm_campaign", "utm_content", "utm_term", "ref")
HONEYPOT = "website"

_HEADERS = {
    "X-Content-Type-Options": "nosniff",
    "Referrer-Policy": "strict-origin-when-cross-origin",
    "Cache-Control": "no-store",
    "Content-Security-Policy": ("default-src 'none'; style-src 'unsafe-inline'; "
                                "img-src 'self' data:; form-action 'self'; base-uri 'none'; "
                                "frame-ancestors 'none'"),
}

_CSS = """
*{box-sizing:border-box}
body{margin:0;font:16px/1.5 system-ui,-apple-system,"Segoe UI",Roboto,sans-serif;color:#1f2937;background:#eef2ff}
main{max-width:640px;margin:0 auto;padding:20px 14px 40px}
.card{background:#fff;border-radius:14px;padding:20px 18px;margin:0 0 12px;box-shadow:0 1px 2px rgba(0,0,0,.06);border:1px solid #e5e7eb}
.head{border-top:8px solid #4f46e5}
h1{font-size:24px;line-height:1.3;margin:0 0 8px}
.desc{margin:0 0 10px;white-space:pre-line;color:#374151}
.note{margin:0;font-size:13px;color:#b91c1c}
.q.err{border-color:#f87171}
.label{display:block;font-weight:600;margin:0 0 4px}
.req{color:#dc2626}
.help{font-size:14px;color:#6b7280;margin:0 0 8px;white-space:pre-line}
input[type=text],input[type=tel],input[type=email],input[type=date],textarea,select{
  width:100%;font:inherit;padding:11px 12px;border:1px solid #d1d5db;border-radius:10px;background:#fff;color:inherit}
textarea{min-height:110px;resize:vertical}
input:focus,textarea:focus,select:focus{outline:2px solid #6366f1;outline-offset:0;border-color:#6366f1}
.opt{display:flex;gap:10px;align-items:flex-start;padding:9px 4px;cursor:pointer}
.opt input{width:20px;height:20px;margin:2px 0 0;flex:none;accent-color:#4f46e5}
.error{color:#dc2626;font-size:14px;margin:8px 0 0}
.banner{background:#fef2f2;border:1px solid #fecaca;color:#991b1b;border-radius:12px;padding:12px 14px;margin:0 0 12px}
button{display:block;width:100%;padding:14px 16px;border:0;border-radius:12px;background:#4f46e5;color:#fff;font:600 17px/1.2 inherit;cursor:pointer}
button:hover{background:#4338ca}
.hp{position:absolute;left:-10000px;top:auto;width:1px;height:1px;overflow:hidden}
.foot{font-size:13px;color:#6b7280;text-align:center;margin:16px 0 0}
.foot a{color:#4f46e5}
.done{text-align:center;padding:32px 20px}
.done .ok{font-size:44px;line-height:1;margin:0 0 10px}
.again{display:inline-block;margin-top:14px;color:#4f46e5}
"""


# --------------------------------------------------------------------------- #
# Token, IP, rate limit
# --------------------------------------------------------------------------- #
def _key() -> bytes:
    return hmac.new(settings.SECRET_KEY.encode(), b"public-form-token", hashlib.sha256).digest()


async def _read_limited(request: Request) -> Optional[bytes]:
    """The body, or None when it is larger than MAX_BODY — stops reading at the
    limit (a huge POST must not be buffered into the single worker's memory)."""
    try:
        if int(request.headers.get("content-length") or 0) > MAX_BODY:
            return None
    except ValueError:
        return None
    chunks, size = [], 0
    async for chunk in request.stream():
        size += len(chunk)
        if size > MAX_BODY:
            return None
        chunks.append(chunk)
    return b"".join(chunks)


def clean_text(value: str) -> str:
    """No control characters (NUL breaks Postgres text/jsonb) from the public page."""
    return _CONTROL.sub("", value)


def make_token(form_id: str, issued: Optional[int] = None) -> str:
    issued = int(time.time()) if issued is None else issued
    mac = hmac.new(_key(), f"{form_id}:{issued}".encode(), hashlib.sha256).hexdigest()[:24]
    return f"{issued}.{mac}"


def token_problem(form_id: str, token: str, now: Optional[float] = None) -> Optional[str]:
    """None = fine; otherwise why the submission must be sent again."""
    now = time.time() if now is None else now
    match = _TOKEN_RE.fullmatch(token or "")
    if match is None:
        return "bad"
    issued_raw, mac = match.groups()
    expected = make_token(form_id, int(issued_raw)).partition(".")[2]
    if not hmac.compare_digest(mac, expected):
        return "bad"
    age = now - int(issued_raw)
    if age < MIN_FILL_SECONDS:
        return "fast"
    if age > TOKEN_TTL:
        return "old"
    return None


def client_ip(request: Request) -> str:
    ip = (request.headers.get("cf-connecting-ip")
          or (request.headers.get("x-forwarded-for") or "").split(",")[0]
          or (request.client.host if request.client else ""))
    return ip.strip() or "unknown"


def _bucket(ip: str) -> str:
    """IPv6: the /64 (one home or one VPS owns a whole /64); IPv4: the address."""
    try:
        addr = ipaddress.ip_address(ip)
    except ValueError:
        return ip
    if addr.version == 6:
        return str(ipaddress.ip_network(f"{addr}/64", strict=False))
    return str(addr)


async def _token_used(token: str) -> bool:
    """A render token submits once (a replayed POST reuses the same token)."""
    try:
        return await store.bump_rate(f"form:tok:{token}", TOKEN_TTL) > 1
    except Exception as exc:  # noqa: BLE001
        logger.warning("Form token store unavailable: {}", exc)
        return False


async def alert_allowed(form_id: str) -> bool:
    """At most ALERTS_PER_MINUTE staff alerts per form (a flood must not bury
    the other alerts; the submissions are still stored)."""
    try:
        return await store.bump_rate(f"form:alerts:{form_id}", 60) <= ALERTS_PER_MINUTE
    except Exception as exc:  # noqa: BLE001
        logger.warning("Form alert throttle unavailable: {}", exc)
        return True


async def _rate_exceeded(form_id: str, ip: str) -> bool:
    digest = hashlib.sha256(f"{settings.SECRET_KEY}:{_bucket(ip)}".encode()).hexdigest()[:24]
    try:
        return await store.bump_rate(f"form:rate:{form_id}:{digest}", RATE_WINDOW) > RATE_LIMIT
    except Exception as exc:  # noqa: BLE001 — never lose a real submission over the store
        logger.warning("Form rate limit unavailable: {}", exc)
        return False


# --------------------------------------------------------------------------- #
# Rendering
# --------------------------------------------------------------------------- #
def _page(title: str, body: str, *, description: str = "", status: int = 200) -> HTMLResponse:
    og = escape((description or "").strip().replace("\n", " ")[:200])
    doc = (
        "<!doctype html><html lang=\"uz\"><head><meta charset=\"utf-8\">"
        "<meta name=\"viewport\" content=\"width=device-width,initial-scale=1\">"
        "<meta name=\"robots\" content=\"noindex\">"
        f"<meta property=\"og:title\" content=\"{escape(title)}\">"
        + (f"<meta property=\"og:description\" content=\"{og}\">" if og else "")
        + f"<title>{escape(title)}</title><style>{_CSS}</style></head>"
        f"<body><main>{body}<p class=\"foot\">Ma'lumotlaringiz "
        "<a href=\"/privacy\">maxfiylik siyosati</a>ga muvofiq saqlanadi.</p></main></body></html>"
    )
    return HTMLResponse(doc, status_code=status, headers=_HEADERS)


def not_found() -> HTMLResponse:
    return _page("Forma topilmadi", "<div class=\"card done\"><h1>Forma topilmadi yoki "
                 "yopilgan</h1><p>Havolani tekshiring yoki biz bilan bog'laning.</p></div>",
                 status=404)


def _input(spec: Mapping[str, Any], value: Any) -> str:
    name = f"q_{spec['id']}"
    kind = spec["type"]
    required = " required" if spec.get("required") and kind != "multiple_choice" else ""
    placeholder = escape(spec.get("placeholder") or "")
    attrs = f'id="{name}" name="{name}"{required}'
    if placeholder:
        attrs += f' placeholder="{placeholder}"'
    text = escape(value if isinstance(value, str) else "")
    if kind == "long_text":
        return f'<textarea {attrs} maxlength="5000">{text}</textarea>'
    if kind in ("single_choice", "multiple_choice"):
        chosen = set(value) if isinstance(value, list) else {value}
        box = "radio" if kind == "single_choice" else "checkbox"
        rows = []
        for i, option in enumerate(spec.get("options") or []):
            checked = " checked" if option in chosen else ""
            rows.append(f'<label class="opt"><input type="{box}" name="{name}" '
                        f'value="{escape(option)}"{checked}{required if i == 0 else ""}>'
                        f"<span>{escape(option)}</span></label>")
        return "".join(rows)
    if kind == "dropdown":
        options = ['<option value="">Tanlang</option>'] + [
            f'<option value="{escape(o)}"{" selected" if o == value else ""}>{escape(o)}</option>'
            for o in spec.get("options") or []]
        return f"<select {attrs}>{''.join(options)}</select>"
    extra = {
        "short_text": ' type="text" maxlength="500"',
        "phone": ' type="tel" inputmode="tel" autocomplete="tel" maxlength="40"',
        "email": ' type="email" inputmode="email" autocomplete="email" maxlength="254"',
        "number": ' type="text" inputmode="decimal" maxlength="30"',
        "date": ' type="date"',
    }[kind]
    if spec.get("lead_field") == "name" and kind == "short_text":
        extra += ' autocomplete="name"'
    return f'<input{extra} {attrs} value="{text}">'


def render_form(form: Form, *, values: Optional[dict[str, Any]] = None,
                errors: Optional[dict[str, str]] = None, banner: str = "",
                utm: Optional[dict[str, str]] = None, status: int = 200) -> HTMLResponse:
    values, errors = values or {}, errors or {}
    fields = form.fields or []
    head = [f"<h1>{escape(form.title)}</h1>"]
    if form.description:
        head.append(f'<p class="desc">{escape(form.description)}</p>')
    if any(f.get("required") for f in fields):
        head.append('<p class="note">* — majburiy savol</p>')
    parts = [f'<div class="card head">{"".join(head)}</div>']
    if banner:
        parts.append(f'<div class="banner">{escape(banner)}</div>')
    hidden = [f'<input type="hidden" name="_t" value="{make_token(str(form.id))}">']
    hidden += [f'<input type="hidden" name="{k}" value="{escape(v)}">'
               for k, v in (utm or {}).items()]
    hidden.append(f'<div class="hp" aria-hidden="true"><label>Veb-sayt <input type="text" '
                  f'name="{HONEYPOT}" tabindex="-1" autocomplete="off"></label></div>')
    questions = []
    for spec in fields:
        field_id = spec["id"]
        error = errors.get(field_id)
        star = ' <span class="req">*</span>' if spec.get("required") else ""
        label_for = "" if spec["type"] in ("single_choice", "multiple_choice") \
            else f' for="q_{field_id}"'
        help_text = f'<p class="help">{escape(spec["help"])}</p>' if spec.get("help") else ""
        error_html = f'<p class="error">{escape(error)}</p>' if error else ""
        questions.append(
            f'<div class="card q{" err" if error else ""}">'
            f'<label class="label"{label_for}>{escape(spec["label"])}{star}</label>{help_text}'
            f'{_input(spec, values.get(field_id, ""))}{error_html}</div>')
    parts.append(f'<form method="post" action="/f/{escape(form.slug)}">{"".join(hidden)}'
                 f'{"".join(questions)}<button type="submit">'
                 f'{escape(form.submit_label or "Yuborish")}</button></form>')
    return _page(form.title, "".join(parts), description=form.description, status=status)


def render_done(form: Form) -> HTMLResponse:
    message = form.success_message.strip() or service.DEFAULT_SUCCESS
    body = (f'<div class="card head done"><p class="ok">✅</p><h1>{escape(form.title)}</h1>'
            f'<p class="desc">{escape(message)}</p>'
            f'<a class="again" href="/f/{escape(form.slug)}">Yana javob yuborish</a></div>')
    return _page(form.title, body, description=form.description)


# --------------------------------------------------------------------------- #
# Routes
# --------------------------------------------------------------------------- #
async def _active_form(slug: str) -> Optional[Form]:
    if not service.SLUG_RE.match(slug):
        return None
    async with db_session.SessionLocal() as db:
        form = (await db.execute(select(Form).where(Form.slug == slug))).scalar_one_or_none()
    return form if form is not None and form.is_active else None


def _utm(source: Mapping[str, Any]) -> dict[str, str]:
    out = {}
    for key in UTM_KEYS:
        value = source.get(key)
        if isinstance(value, list):
            value = value[0] if value else ""
        value = clean_text(str(value or "")).strip()[:200]
        if value:
            out[key] = value
    return out


@router.api_route("/f/{slug}", methods=["GET", "HEAD"], include_in_schema=False)
async def form_page(slug: str, request: Request) -> Response:
    form = await _active_form(slug)
    if form is None:
        return not_found()
    if request.query_params.get("sent") == "1":
        return render_done(form)
    return render_form(form, utm=_utm(request.query_params))


@router.post("/f/{slug}", include_in_schema=False)
async def form_submit(slug: str, request: Request) -> Response:
    form = await _active_form(slug)
    if form is None:
        return not_found()
    body = await _read_limited(request)
    if body is None:
        return _page("Juda katta", "<div class=\"card\"><h1>Javob juda katta</h1></div>",
                     status=413)
    try:
        data = parse_qs(body.decode("utf-8", "replace"), keep_blank_values=True,
                        max_num_fields=MAX_FIELDS_IN_BODY)
    except ValueError:
        return _page("Noto'g'ri so'rov", "<div class=\"card\"><h1>Noto'g'ri so'rov</h1></div>",
                     status=400)
    done = RedirectResponse(f"/f/{form.slug}?sent=1", status_code=303)
    if any(v.strip() for v in data.get(HONEYPOT, [])):
        logger.info("Form {}: honeypot filled — ignored", form.slug)
        return done
    utm = _utm(data)
    answers = {key[2:]: ([clean_text(v) for v in vals] if len(vals) > 1
                         else clean_text(vals[0]))
               for key, vals in data.items() if key.startswith("q_")}
    checked: Checked = validate_answers(form.fields or [], answers)
    token = (data.get("_t") or [""])[0]
    problem = token_problem(str(form.id), token)
    if problem:
        banner = ("Iltimos, formani to'ldirib qayta yuboring." if problem == "fast"
                  else "Sahifa eskirgan — javoblaringizni tekshirib, qayta yuboring.")
        return render_form(form, values=checked.values, errors=checked.errors, banner=banner,
                           utm=utm, status=400)
    if checked.errors:
        return render_form(form, values=checked.values, errors=checked.errors, utm=utm,
                           banner="Ba'zi javoblarni to'g'rilang.", status=400)
    if await _token_used(token):
        return render_form(form, values=checked.values, utm=utm, status=400,
                           banner="Sahifa eskirgan — javoblaringizni tekshirib, qayta yuboring.")
    if await _rate_exceeded(str(form.id), client_ip(request)):
        return _page("Juda ko'p urinish", "<div class=\"card done\"><h1>Juda ko'p urinish</h1>"
                     "<p>Birozdan so'ng qayta urinib ko'ring.</p></div>", status=429)
    if await service.submit(form.id, checked, utm,
                            alert=await alert_allowed(str(form.id))) is None:
        return not_found()
    return done

