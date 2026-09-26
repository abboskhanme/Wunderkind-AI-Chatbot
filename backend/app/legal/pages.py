"""Public legal pages for Meta App Review (SPEC §12.1): /privacy, /terms,
/data-deletion. Server-rendered HTML — no JS, no auth, no template engine.

Every value that comes from settings goes through `_e()` (HTML escape). The text
describes what the system really does (SPEC §2, §10, §11); when the data flows
change, update the text AND `LAST_UPDATED`.
"""
from __future__ import annotations

import re
from datetime import date, datetime, timezone
from html import escape
from typing import Optional
from zoneinfo import ZoneInfo

from fastapi import APIRouter, Request
from fastapi.responses import HTMLResponse
from sqlalchemy import select

from app.config import settings
from app.db import session as db_session
from app.models.legal import CONFIRMATION_CODE_LENGTH, DataDeletionRequest

router = APIRouter(tags=["Legal pages"])

# The date the page TEXT last changed (not the deploy date)
LAST_UPDATED = date(2026, 9, 26)
RETENTION_MONTHS = 24
DELETION_DAYS = 30
_CODE_RE = re.compile(rf"[A-Za-z0-9]{{{CONFIRMATION_CODE_LENGTH}}}")

_HEADERS = {
    "X-Content-Type-Options": "nosniff",
    # The status URL carries the confirmation code — never leak it via Referer
    "Referrer-Policy": "no-referrer",
    "Content-Security-Policy": ("default-src 'none'; style-src 'unsafe-inline'; "
                                "form-action 'self'; base-uri 'none'; frame-ancestors 'none'"),
}

_CSS = """
*{box-sizing:border-box}body{margin:0;font:16px/1.65 system-ui,-apple-system,"Segoe UI",Roboto,sans-serif;color:#1f2937;background:#f8fafc}
header{background:#fff;border-bottom:1px solid #e5e7eb}
.wrap{max-width:820px;margin:0 auto;padding:0 20px}
nav{display:flex;flex-wrap:wrap;gap:6px 18px;padding:14px 0;font-size:14px}
nav b{flex:1 0 100%;color:#111827;font-size:16px}
a{color:#4f46e5}nav a{text-decoration:none}nav a[aria-current]{font-weight:600;text-decoration:underline}
main.wrap{padding-top:24px;padding-bottom:40px}
article{background:#fff;border:1px solid #e5e7eb;border-radius:12px;padding:24px 28px;margin-bottom:24px}
h1{font-size:26px;line-height:1.3;margin:0 0 4px}h2{font-size:18px;margin:28px 0 8px}
.meta{color:#6b7280;font-size:14px;margin:0 0 16px}.langs{font-size:14px;margin:0 0 16px}
ul{padding-left:22px}li{margin:4px 0}dl{margin:0}dt{font-weight:600}dd{margin:0 0 8px}
.box{border-radius:10px;padding:14px 18px;margin:0 0 24px;border:1px solid}
.ok{background:#ecfdf5;border-color:#a7f3d0}.wait{background:#fffbeb;border-color:#fde68a}.no{background:#fef2f2;border-color:#fecaca}
form{display:flex;flex-wrap:wrap;gap:8px;margin-top:8px}
input{flex:1 1 220px;padding:10px 12px;border:1px solid #d1d5db;border-radius:8px;font:inherit}
button{padding:10px 18px;border:0;border-radius:8px;background:#4f46e5;color:#fff;font:inherit;cursor:pointer}
footer{color:#6b7280;font-size:13px;padding:0 0 32px}
@media (max-width:560px){article{padding:18px 16px}h1{font-size:22px}}
"""


# ---------------------------------------------------------------------------
# Values from settings (escaped) with the SPEC §12.3 fallbacks
# ---------------------------------------------------------------------------
def _e(value: object) -> str:
    return escape(str(value or ""), quote=True)


def _company() -> str:
    return (settings.COMPANY_NAME or "").strip() or "Wunderkind"


def _entity() -> str:
    return (settings.LEGAL_ENTITY_NAME or "").strip() or _company()


def _phone() -> str:
    return (settings.LEGAL_CONTACT_PHONE or settings.FUNNEL_STAFF_PHONE or "").strip()


def _address() -> str:
    return (settings.LEGAL_ADDRESS or settings.FUNNEL_ADDRESS or "").strip()


def _email() -> str:
    return (settings.LEGAL_CONTACT_EMAIL or "").strip()


def _website() -> str:
    return (settings.PUBLIC_URL or "").strip().rstrip("/")


def _instagram() -> str:
    return (settings.IG_USERNAME or "").strip().lstrip("@")


def _who(lang: str) -> str:
    """«Wunderkind» private school (+ legal entity when it differs)."""
    company, entity = _e(_company()), _e(_entity())
    extra = f" ({entity})" if _entity() != _company() else ""
    if lang == "uz":
        return f"«{company}» xususiy maktabi{extra}"
    return f"{company} private school{extra}"


def _contact_list(lang: str) -> str:
    """Only the contact lines that have a value — no empty labels."""
    uz = lang == "uz"
    rows: list[tuple[str, str]] = [
        ("Tashkilot" if uz else "Organisation", _e(_entity())),
    ]
    if _email():
        rows.append(("E-mail", f'<a href="mailto:{_e(_email())}">{_e(_email())}</a>'))
    if _phone():
        tel = re.sub(r"[^\d+]", "", _phone())
        rows.append(("Telefon" if uz else "Phone", f'<a href="tel:{_e(tel)}">{_e(_phone())}</a>'))
    if _address():
        rows.append(("Manzil" if uz else "Address", _e(_address()).replace("\n", "<br>")))
    if _instagram():
        handle = _e(_instagram())
        rows.append(("Instagram", f'<a href="https://www.instagram.com/{handle}/">@{handle}</a>'))
    if _website():
        rows.append(("Veb-sayt" if uz else "Website", f'<a href="{_e(_website())}">{_e(_website())}</a>'))
    return "<dl>" + "".join(f"<dt>{k}</dt><dd>{v}</dd>" for k, v in rows) + "</dl>"


def _write_to_us(lang: str) -> str:
    """Inline "write to us at …" with whatever channels are configured."""
    uz = lang == "uz"
    parts = []
    if _email():
        parts.append(f'<a href="mailto:{_e(_email())}">{_e(_email())}</a>')
    if _phone():
        parts.append(_e(_phone()))
    if parts:
        return (" yoki ".join(parts)) if uz else (" or ".join(parts))
    return ("Instagram yoki Telegram orqali bizga yozing" if uz
            else "message us on Instagram or Telegram")


# ---------------------------------------------------------------------------
# Layout
# ---------------------------------------------------------------------------
_NAV = (
    ("/privacy", "Maxfiylik siyosati", "Privacy Policy"),
    ("/terms", "Foydalanish shartlari", "Terms of Service"),
    ("/data-deletion", "Ma'lumotlarni o'chirish", "Data Deletion"),
)


def _page(path: str, title_uz: str, title_en: str, body_uz: str, body_en: str, *,
          top: str = "", status_code: int = 200, cache: bool = True) -> HTMLResponse:
    links = "".join(
        f'<a href="{href}"{" aria-current=page" if href == path else ""}>{uz} / {en}</a>'
        for href, uz, en in _NAV
    )
    updated_uz = LAST_UPDATED.strftime("%d.%m.%Y")
    updated_en = f"{LAST_UPDATED:%B} {LAST_UPDATED.day}, {LAST_UPDATED.year}"
    html = f"""<!doctype html>
<html lang="uz">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>{_e(title_uz)} / {_e(title_en)} — {_e(_company())}</title>
<style>{_CSS}</style>
</head>
<body>
<header><div class="wrap"><nav><b>{_e(_company())}</b>{links}</nav></div></header>
<main class="wrap">
{top}
<p class="langs"><a href="#uz">O'zbekcha</a> · <a href="#en" hreflang="en">English</a></p>
<article id="uz" lang="uz">
<h1>{title_uz}</h1>
<p class="meta">Oxirgi yangilanish: {updated_uz}</p>
{body_uz}
</article>
<article id="en" lang="en">
<h1>{title_en}</h1>
<p class="meta">Last updated: {updated_en}</p>
{body_en}
</article>
</main>
<footer class="wrap">© {LAST_UPDATED.year} {_e(_entity())}</footer>
</body>
</html>"""
    headers = dict(_HEADERS)
    headers["Cache-Control"] = "public, max-age=300" if cache else "no-store"
    return HTMLResponse(html, status_code=status_code, headers=headers)


# ---------------------------------------------------------------------------
# Privacy Policy
# ---------------------------------------------------------------------------
def _privacy_uz() -> str:
    return f"""
<p>Ushbu siyosat {_who("uz")} («biz») Instagram va Telegram'dagi avtomatlashtirilgan
yordamchimiz (sun'iy intellekt asosidagi yordamchi) hamda qabul bo'limi xodimlari
orqali qanday shaxsiy ma'lumotlarni to'plashi, ulardan nima uchun foydalanishi va
kimga uzatishini tushuntiradi.</p>

<h2>1. Biz kimmiz</h2>
<p>Biz — {_who("uz")}. Shaxsiy ma'lumotlaringiz bo'yicha biz bilan bog'lanish:</p>
{_contact_list("uz")}

<h2>2. Qanday ma'lumotlarni to'playmiz</h2>
<p><b>Instagram orqali</b> (postimizga izoh qoldirsangiz yoki bizga Direct xabar yozsangiz):</p>
<ul>
<li>Instagram foydalanuvchi identifikatoringiz (Instagram bizning ilovamizga beradigan ID) va foydalanuvchi nomingiz (@username);</li>
<li>postlarimizga yozgan izohlaringiz va bizga yuborgan xabarlaringiz matni;</li>
<li>qo'llanma so'raganingizda — sahifamizga obuna bo'lganmisiz yoki yo'q (ha/yo'q).</li>
</ul>
<p><b>Telegram orqali</b> (botimizga yoki yordamchimiz ulangan maktab Telegram akkauntiga yozsangiz):</p>
<ul>
<li>Telegram foydalanuvchi ID'ingiz, foydalanuvchi nomingiz va chat ID;</li>
<li>bizga yuborgan xabarlaringiz, Telegram kanalimiz muhokama guruhida kalit so'z bilan yozgan izohlaringiz;</li>
<li>qo'llanma so'raganingizda — Telegram kanalimizga a'zomisiz yoki yo'q (ha/yo'q).</li>
</ul>
<p><b>O'zingiz bergan ma'lumotlar:</b> ism-familiyangiz, telefon raqamingiz (faqat o'zingiz
yuborganingizda), farzandingizning sinfi (yoki siz aytgan yoshi), qulay vaqt, qabul
suhbatiga yozilgan sana va vaqt.</p>
<p><b>Avtomatik yaratiladigan ma'lumotlar:</b> suhbatning qisqa mazmuni, murojaat bosqichi
va qiziqish darajasi (ball) — xodimlarimiz kimga birinchi qo'ng'iroq qilishni bilishi uchun.</p>
<p>Biz yuborgan rasm, ovozli xabar va fayllaringizni yuklab olmaymiz va saqlamaymiz —
faqat ular yuborilganini qayd etamiz. To'lov ma'lumotlari va parollarni to'plamaymiz.</p>

<h2>3. Ma'lumotlardan nima uchun foydalanamiz</h2>
<ul>
<li>savollaringizga javob berish (sun'iy intellekt yordamchisi va xodimlarimiz);</li>
<li>siz so'ragan bepul qo'llanmani (PDF) yuborish;</li>
<li>qabul haqida keyingi xabarlarni yuborish (qo'llanmadan keyingi ma'lumot xabarlari, javobsiz qolgan savolga bitta eslatma);</li>
<li>qabul suhbatiga yozish va suhbat kuni eslatma yuborish;</li>
<li>xodimlar siz bilan bog'lanishi uchun murojaatlar ro'yxatini yuritish.</li>
</ul>
<p>Ma'lumotlaringizni reklama nishonlash (targeting) uchun ishlatmaymiz va hech kimga
sotmaymiz.</p>

<h2>4. Sun'iy intellekt (AI)</h2>
<p>Javoblar avtomatik tarzda sun'iy intellekt yordamida yaratiladi — birinchi javobda buni
ochiq aytamiz. Javob tayyorlash uchun xabaringiz matni va suhbat tarixi AI
provayderiga (5-bo'lim) yuboriladi. AI xato qilishi mumkin: narx, sana va qabul
shartlarini xodimlarimiz tasdiqlaydi. Istalgan vaqtda xodim bilan gaplashishni
so'rashingiz mumkin. AI siz uchun huquqiy yoki shunga o'xshash jiddiy oqibatli qarorlar
qabul qilmaydi.</p>

<h2>5. Ma'lumotlar kimga uzatiladi</h2>
<p>Faqat xizmatni ko'rsatish uchun zarur bo'lgan quyidagi xizmat ko'rsatuvchilarga:</p>
<ul>
<li><b>Google</b> — Gemini API: AI javoblarini yaratish (xabar matni va suhbat tarixi);</li>
<li><b>Google</b> — Google Sheets: xodimlar uchun murojaatlar jadvali (ism, telefon, sinf, Telegram/Instagram foydalanuvchi nomi, suhbat sanasi);</li>
<li><b>Anthropic</b> — Claude API: faqat zaxira AI provayderi yoqilgan bo'lsa, xuddi shu maqsadda;</li>
<li><b>Meta Platforms</b> — Instagram API: Instagram'dagi xabar va izohlarni qabul qilish va javob yuborish;</li>
<li><b>Telegram</b> — bot xabarlarini qabul qilish va yuborish, xodimlarimizga bildirishnomalar;</li>
<li><b>DigitalOcean</b> — server va ma'lumotlar bazasi (Frankfurt, Germaniya);</li>
<li><b>Cloudflare</b> — saytimizga keladigan trafikni himoyalash va yetkazish.</li>
</ul>
<p>Shu sababli ma'lumotlaringiz O'zbekistondan tashqaridagi serverlarda (jumladan
Germaniya va AQSh) qayta ishlanishi mumkin. Qonun talab qilgan hollardan tashqari
ma'lumotlaringizni boshqa hech kimga bermaymiz.</p>

<h2>6. Qancha saqlaymiz</h2>
<p>Qabul bo'yicha muloqot uchun kerak bo'lgan muddat davomida, lekin oxirgi
murojaatingizdan keyin ko'pi bilan {RETENTION_MONTHS} oy, yoki siz o'chirishni
so'ragunga qadar.</p>

<h2>7. Sizning huquqlaringiz</h2>
<p>Siz ma'lumotlaringizni ko'rish, tuzatish yoki o'chirishni so'rashingiz, xabar olishdan
voz kechishingiz mumkin. Telegram botda <b>/stop</b> buyrug'i qo'llanmadan keyingi
xabarlarni to'xtatadi. O'chirish uchun {_write_to_us("uz")} yoki
<a href="/data-deletion">Ma'lumotlarni o'chirish</a> sahifasidagi ko'rsatmalardan
foydalaning. So'rovlar {DELETION_DAYS} kun ichida bajariladi.</p>

<h2>8. Bolalar</h2>
<p>Xizmatimiz ota-onalar va vasiylarga mo'ljallangan. Biz 13 yoshgacha bo'lgan bolalardan
bevosita ma'lumot to'plamaymiz (bila turib). Farzandning sinfi haqidagi ma'lumotni
ota-ona beradi. Agar bola bizga o'zi yozgan bo'lsa, bizga xabar bering — ma'lumotlarni
o'chiramiz.</p>

<h2>9. Xavfsizlik</h2>
<p>Ma'lumotlar shifrlangan (HTTPS) ulanish orqali uzatiladi. Boshqaruv paneliga faqat
shaxsiy login va rolga ega vakolatli xodimlar kira oladi; xizmat kalitlari bazada
shifrlangan, parollar xeshlangan holda saqlanadi. Hech bir usul 100% xavfsizlikni
kafolatlamaydi, lekin biz ma'lumotlaringizni himoya qilish uchun oqilona choralar ko'ramiz.</p>

<h2>10. O'zgarishlar</h2>
<p>Siyosat o'zgarsa, shu sahifani yangilaymiz va yuqoridagi «Oxirgi yangilanish» sanasini
o'zgartiramiz.</p>
"""


def _privacy_en() -> str:
    return f"""
<p>This policy explains what personal data {_who("en")} ("we", "us") collects through
our automated assistant (an AI-powered assistant) on Instagram and Telegram and through
our admissions staff, why we use it and with whom we share it.</p>

<h2>1. Who we are</h2>
<p>We are {_who("en")}. Contact us about your personal data:</p>
{_contact_list("en")}

<h2>2. Data we collect</h2>
<p><b>Through Instagram</b> (when you comment on our posts or send us a direct message):</p>
<ul>
<li>your Instagram-scoped user ID (the ID Instagram gives our app) and your username;</li>
<li>the text of the comments you post on our posts and of the messages you send us;</li>
<li>when you ask for our guide — whether you follow our account (yes/no).</li>
</ul>
<p><b>Through Telegram</b> (when you write to our bot or to the school's Telegram account connected to our assistant):</p>
<ul>
<li>your Telegram user ID, username and chat ID;</li>
<li>the messages you send us, and your comments containing our keyword in our Telegram channel's discussion group;</li>
<li>when you ask for our guide — whether you are a member of our Telegram channel (yes/no).</li>
</ul>
<p><b>Information you give us:</b> your name, your phone number (only when you share it),
your child's grade (or age, if you tell us), a convenient time, and the date and time
of the admission interview you book.</p>
<p><b>Generated automatically:</b> a short summary of the conversation, its stage and an
interest score, so that our staff know whom to call first.</p>
<p>We do not download or store photos, voice messages or files you send — we only note
that one was sent. We do not collect payment data or passwords.</p>

<h2>3. How we use it</h2>
<ul>
<li>to answer your questions (AI assistant and our staff);</li>
<li>to send you the free guide (PDF) you requested;</li>
<li>to send admission follow-up messages (information messages after the guide, one reminder if your question was left unanswered);</li>
<li>to book your admission interview and remind you on the day;</li>
<li>to keep a list of enquiries so our staff can contact you.</li>
</ul>
<p>We do not use your data for advertising targeting and we never sell it.</p>

<h2>4. Artificial intelligence</h2>
<p>Replies are generated automatically by artificial intelligence — we say so in our
first reply. To prepare a reply, the text of your message and the conversation history
are sent to an AI provider (section 5). AI can make mistakes: our staff confirm fees,
dates and admission terms. You can ask to talk to a staff member at any time. The AI
does not make decisions that have legal or similarly significant effects on you.</p>

<h2>5. Who we share it with</h2>
<p>Only with the service providers we need to run the service:</p>
<ul>
<li><b>Google</b> — Gemini API: generating AI replies (message text and conversation history);</li>
<li><b>Google</b> — Google Sheets: the enquiry list for our staff (name, phone, grade, Telegram/Instagram username, interview date);</li>
<li><b>Anthropic</b> — Claude API: only if our backup AI provider is enabled, for the same purpose;</li>
<li><b>Meta Platforms</b> — Instagram API: receiving and answering Instagram messages and comments;</li>
<li><b>Telegram</b> — receiving and sending bot messages, notifications to our staff;</li>
<li><b>DigitalOcean</b> — server and database hosting (Frankfurt, Germany);</li>
<li><b>Cloudflare</b> — protecting and delivering traffic to our website.</li>
</ul>
<p>Your data may therefore be processed on servers outside Uzbekistan (including
Germany and the USA). We do not share your data with anyone else unless the law
requires it.</p>

<h2>6. How long we keep it</h2>
<p>For as long as needed for admission communication, but no longer than
{RETENTION_MONTHS} months after your last contact with us, or until you ask us to
delete it.</p>

<h2>7. Your rights</h2>
<p>You can ask to see, correct or delete your data and opt out of messages. The
<b>/stop</b> command in our Telegram bot stops the messages sent after the guide. To
request deletion, write to {_write_to_us("en")} or follow the instructions on the
<a href="/data-deletion">Data Deletion</a> page. We complete requests within
{DELETION_DAYS} days.</p>

<h2>8. Children</h2>
<p>Our service is addressed to parents and guardians. We do not knowingly collect data
directly from children under 13. The child's grade is provided by the parent. If a
child has contacted us directly, tell us and we will delete the data.</p>

<h2>9. Security</h2>
<p>Data is transmitted over encrypted (HTTPS) connections. Only authorised staff with
personal accounts and roles can access the admin panel; service keys are stored
encrypted and passwords are hashed. No method is 100% secure, but we take reasonable
measures to protect your data.</p>

<h2>10. Changes</h2>
<p>If this policy changes, we will update this page and the "Last updated" date above.</p>
"""


# ---------------------------------------------------------------------------
# Terms of Service
# ---------------------------------------------------------------------------
def _terms_uz() -> str:
    ig = f" (@{_e(_instagram())})" if _instagram() else ""
    return f"""
<p>Ushbu shartlar {_who("uz")} Instagram{ig} va Telegram'dagi avtomatlashtirilgan
yordamchisidan («xizmat») foydalanish qoidalarini belgilaydi. Bizga yozish yoki
xizmatdan foydalanish orqali siz ushbu shartlarga rozilik bildirasiz.</p>

<h2>1. Xizmat</h2>
<p>Yordamchi maktab haqidagi savollarga javob beradi, bepul qo'llanmani yuboradi, qabul
haqida ma'lumot beradi va qabul suhbatiga yozadi. Xizmat bepul.</p>

<h2>2. Foydalanish qoidalari</h2>
<ul>
<li>noqonuniy, haqoratli yoki spam xabarlar yubormang;</li>
<li>boshqa shaxslarning ma'lumotlarini ularning roziligisiz yubormang;</li>
<li>o'zingizni boshqa shaxs deb tanishtirmang;</li>
<li>xizmat ishini buzishga, uni suiiste'mol qilishga yoki ichki ko'rsatmalarini olishga urinmang.</li>
</ul>

<h2>3. Sun'iy intellekt javoblari</h2>
<p>Javoblar sun'iy intellekt tomonidan avtomatik yaratiladi va noto'g'ri yoki to'liq
bo'lmasligi mumkin. Narxlar, jadval va qabul shartlari faqat xodimlarimiz tasdiqlagandan
keyin rasmiy hisoblanadi. Javoblar tibbiy, huquqiy yoki psixologik maslahat emas;
qo'llanma umumiy ma'rifiy material hisoblanadi.</p>

<h2>4. Qabul kafolatlanmaydi</h2>
<p>Qabul suhbatiga yozilish maktabga qabul qilinishni kafolatlamaydi. Qabul bo'yicha
qaror maktabning o'z qabul tartibiga ko'ra qabul qilinadi. Suhbat vaqtini o'zgartirish
yoki bekor qilish zarur bo'lsa, sizga xabar beramiz.</p>

<h2>5. Xabarlar</h2>
<p>Qo'llanmani so'raganingizdan keyin qabul haqida ma'lumot xabarlari olishingiz mumkin.
Telegram botda <b>/stop</b> buyrug'i ularni to'xtatadi.</p>

<h2>6. Uchinchi tomon platformalari</h2>
<p>Instagram va Telegram o'z shartlariga bo'ysunadi; ularning ishlashi uchun biz javob
bermaymiz.</p>

<h2>7. Intellektual mulk</h2>
<p>Qo'llanma va boshqa materiallar maktabga tegishli. Ulardan shaxsiy, notijorat
maqsadda foydalanishingiz mumkin.</p>

<h2>8. Javobgarlikni cheklash</h2>
<p>Xizmat «boricha» taqdim etiladi va uzluksiz ishlashi kafolatlanmaydi. O'zbekiston
Respublikasi qonunchiligida ruxsat etilgan darajada biz xizmatdan foydalanish yoki
foydalana olmaslik, shuningdek xodimlar tasdiqlamagan AI javobiga tayanish natijasidagi
bilvosita zararlar uchun javobgar emasmiz. Bu shartlar qonun bilan cheklab bo'lmaydigan
huquqlaringizni cheklamaydi.</p>

<h2>9. O'zgartirish va to'xtatish</h2>
<p>Biz xizmatni yoki ushbu shartlarni o'zgartirishimiz yoki xizmatni to'xtatishimiz,
qoidalarni buzgan foydalanuvchilarni bloklashimiz mumkin. O'zgarishlar shu sahifada
e'lon qilinadi.</p>

<h2>10. Amaldagi qonunchilik</h2>
<p>Ushbu shartlarga O'zbekiston Respublikasi qonunchiligi qo'llaniladi. Nizolar avval
muzokara yo'li bilan, kelishilmasa O'zbekiston Respublikasi sudlarida hal qilinadi.</p>

<h2>11. Maxfiylik va aloqa</h2>
<p>Ma'lumotlaringiz <a href="/privacy">Maxfiylik siyosati</a>ga muvofiq qayta ishlanadi.</p>
{_contact_list("uz")}
"""


def _terms_en() -> str:
    ig = f" (@{_e(_instagram())})" if _instagram() else ""
    return f"""
<p>These terms govern the use of the automated assistant of {_who("en")} on
Instagram{ig} and Telegram (the "service"). By writing to us or using the service you
agree to these terms.</p>

<h2>1. The service</h2>
<p>The assistant answers questions about the school, sends our free guide, informs you
about admission and books admission interviews. The service is free of charge.</p>

<h2>2. Acceptable use</h2>
<ul>
<li>do not send unlawful, abusive or spam messages;</li>
<li>do not send other people's personal data without their consent;</li>
<li>do not impersonate another person;</li>
<li>do not try to disrupt or abuse the service or to extract its internal instructions.</li>
</ul>

<h2>3. AI-generated replies</h2>
<p>Replies are generated automatically by artificial intelligence and may be inaccurate
or incomplete. Fees, schedules and admission terms are official only once confirmed by
our staff. Replies are not medical, legal or psychological advice; the guide is general
educational material.</p>

<h2>4. No guarantee of admission</h2>
<p>Booking an admission interview does not guarantee admission. Admission decisions are
made by the school under its own admission procedure. If an interview has to be moved
or cancelled, we will let you know.</p>

<h2>5. Messages</h2>
<p>After you request the guide you may receive admission information messages. The
<b>/stop</b> command in our Telegram bot stops them.</p>

<h2>6. Third-party platforms</h2>
<p>Instagram and Telegram are subject to their own terms; we are not responsible for
their availability.</p>

<h2>7. Intellectual property</h2>
<p>The guide and other materials belong to the school. You may use them for personal,
non-commercial purposes.</p>

<h2>8. Limitation of liability</h2>
<p>The service is provided "as is" and uninterrupted operation is not guaranteed. To the
extent permitted by the law of the Republic of Uzbekistan, we are not liable for
indirect losses arising from the use of, or inability to use, the service, or from
relying on AI replies not confirmed by our staff. Nothing in these terms limits rights
that cannot be limited by law.</p>

<h2>9. Changes and termination</h2>
<p>We may change the service or these terms, suspend the service, or block users who
break these rules. Changes are published on this page.</p>

<h2>10. Governing law</h2>
<p>These terms are governed by the law of the Republic of Uzbekistan. Disputes are first
settled by negotiation and, failing that, by the courts of the Republic of Uzbekistan.</p>

<h2>11. Privacy and contact</h2>
<p>We process your data according to our <a href="/privacy">Privacy Policy</a>.</p>
{_contact_list("en")}
"""


# ---------------------------------------------------------------------------
# Data deletion instructions + status lookup
# ---------------------------------------------------------------------------
def _local(dt: Optional[datetime]) -> str:
    if dt is None:
        return ""
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    try:
        zone = ZoneInfo(settings.TIMEZONE)
    except Exception:  # noqa: BLE001
        zone = ZoneInfo("UTC")
    return f"{dt.astimezone(zone):%d.%m.%Y %H:%M} ({_e(zone.key)})"


def _status_box(code: str, row: Optional[DataDeletionRequest]) -> str:
    code_html = f"<code>{_e(code)}</code>"
    if row is None:
        return (f'<div class="box no" role="status"><p><b>So\'rov topilmadi / Request not found</b></p>'
                f"<p>Kod {code_html} bo'yicha so'rov topilmadi. Kodni tekshiring.<br>"
                f"<span lang=\"en\">No request was found for code {code_html}. Please check the code.</span></p></div>")
    if row.status == "completed":
        return (f'<div class="box ok" role="status"><p><b>So\'rov bajarildi / Request completed</b></p>'
                f"<p>Tasdiqlash kodi / Confirmation code: {code_html}<br>"
                f"Qabul qilindi / Received: {_local(row.created_at)}<br>"
                f"Bajarildi / Completed: {_local(row.completed_at)}</p>"
                "<p>Ushbu Instagram akkauntiga tegishli suhbatlar, aloqa ma'lumotlari, voronka "
                "yozuvlari va suhbatga yozilishlar bazamizdan o'chirildi.<br>"
                "<span lang=\"en\">The conversations, contact details, funnel records and interview "
                "bookings linked to this Instagram account were deleted from our database.</span></p></div>")
    return (f'<div class="box wait" role="status"><p><b>So\'rov qabul qilindi / Request received</b></p>'
            f"<p>Tasdiqlash kodi / Confirmation code: {code_html}<br>"
            f"Qabul qilindi / Received: {_local(row.created_at)}</p>"
            f"<p>So'rov bajarilmoqda — {DELETION_DAYS} kun ichida yakunlanadi.<br>"
            f"<span lang=\"en\">Your request is being processed and will be completed within "
            f"{DELETION_DAYS} days.</span></p></div>")


def _lookup_form(lang: str, code: str = "") -> str:
    uz = lang == "uz"
    label = "Tasdiqlash kodi" if uz else "Confirmation code"
    button = "Tekshirish" if uz else "Check"
    ident = "code-uz" if uz else "code-en"
    return (f'<form method="get" action="/data-deletion"><label for="{ident}" hidden>{label}</label>'
            f'<input id="{ident}" name="code" value="{_e(code)}" maxlength="64" '
            f'placeholder="{label}" autocomplete="off" required>'
            f'<button type="submit">{button}</button></form>')


def _deletion_uz(code: str) -> str:
    return f"""
<p>Siz bizdagi shaxsiy ma'lumotlaringizni (suhbatlar, ism, telefon raqami, farzandingiz
sinfi, suhbatga yozilish) istalgan vaqtda o'chirishni so'rashingiz mumkin.</p>

<h2>Qanday so'rash mumkin</h2>
<ul>
<li><b>Yozing yoki qo'ng'iroq qiling:</b> {_write_to_us("uz")}. «Ma'lumotlarimni
o'chiring» deb yozing va sizni topishimiz uchun Instagram yoki Telegram foydalanuvchi
nomingizni ko'rsating.</li>
<li><b>Instagram yoki Telegram orqali:</b> bizga Direct'da yoki Telegram botimizga
«Ma'lumotlarimni o'chiring» deb yozing — xodimlarimiz suhbatlarni ko'rib chiqadi.</li>
<li><b>Instagram ilovasi orqali</b> (agar ilovamizga Instagram orqali kirgan bo'lsangiz):
Instagram → Sozlamalar va faoliyat → <i>Ilovalar va veb-saytlar</i> → ilovamizni tanlang
→ «Olib tashlash». Instagram bizga o'chirish so'rovini avtomatik yuboradi, biz shu
akkauntga tegishli ma'lumotlarni o'chiramiz va tasdiqlash kodini beramiz.</li>
</ul>
<p>Telegram botda <b>/stop</b> buyrug'i faqat xabarlarni to'xtatadi — ma'lumotlarni
o'chirmaydi.</p>

<h2>Nima o'chiriladi</h2>
<p>Suhbatlar, aloqa ma'lumotlari, voronka yozuvlari, qabul suhbatiga yozilishlar va
xodimlar jadvalidagi qator. So'rov bajarilganini isbotlash uchun faqat so'rovning o'zi
(tasdiqlash kodi, sana, holat va u tegishli Instagram ID) saqlanadi. So'rovlar
{DELETION_DAYS} kun ichida bajariladi (Instagram orqali kelganlari — darhol).</p>

<h2>So'rov holatini tekshirish</h2>
<p>Tasdiqlash kodingizni kiriting:</p>
{_lookup_form("uz", code)}
"""


def _deletion_en(code: str) -> str:
    return f"""
<p>You can ask us at any time to delete the personal data we hold about you
(conversations, name, phone number, your child's grade, interview bookings).</p>

<h2>How to request deletion</h2>
<ul>
<li><b>Write or call us:</b> {_write_to_us("en")}. Write "Please delete my data" and give
your Instagram or Telegram username so we can find your records.</li>
<li><b>On Instagram or Telegram:</b> send "Please delete my data" to our Instagram
account or to our Telegram bot — our staff review the conversations.</li>
<li><b>In the Instagram app</b> (if you logged in to our app with Instagram): Instagram →
Settings and activity → <i>Apps and websites</i> → select our app → Remove. Instagram then
sends us a deletion request automatically; we delete the data linked to that account
and issue a confirmation code.</li>
</ul>
<p>The <b>/stop</b> command in our Telegram bot only stops messages — it does not delete
data.</p>

<h2>What is deleted</h2>
<p>Conversations, contact details, funnel records, admission interview bookings and the
row in our staff spreadsheet. Only the request itself (confirmation code, dates, status
and the Instagram ID it concerns) is kept, as proof that it was carried out. Requests
are completed within {DELETION_DAYS} days (requests from Instagram immediately).</p>

<h2>Check the status of a request</h2>
<p>Enter your confirmation code:</p>
{_lookup_form("en", code)}
"""


# ---------------------------------------------------------------------------
# Routes
# ---------------------------------------------------------------------------
@router.api_route("/privacy", methods=["GET", "HEAD"], include_in_schema=False)
async def privacy_page():
    return _page("/privacy", "Maxfiylik siyosati", "Privacy Policy",
                 _privacy_uz(), _privacy_en())


@router.api_route("/terms", methods=["GET", "HEAD"], include_in_schema=False)
async def terms_page():
    return _page("/terms", "Foydalanish shartlari", "Terms of Service",
                 _terms_uz(), _terms_en())


@router.api_route("/data-deletion", methods=["GET", "HEAD"], include_in_schema=False)
async def data_deletion_page(request: Request):
    code = (request.query_params.get("code") or "").strip()[:64]
    top, status_code = "", 200
    if code:
        row = None
        if _CODE_RE.fullmatch(code):
            async with db_session.SessionLocal() as db:
                row = (await db.execute(select(DataDeletionRequest).where(
                    DataDeletionRequest.confirmation_code == code))).scalar_one_or_none()
        top = _status_box(code, row)
        status_code = 200 if row else 404
    return _page("/data-deletion", "Ma'lumotlarni o'chirish", "User Data Deletion",
                 _deletion_uz(code), _deletion_en(code), top=top,
                 status_code=status_code, cache=not code)
