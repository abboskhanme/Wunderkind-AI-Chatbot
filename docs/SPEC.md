# Wunderkind AI Agent — SPEC

AI sales agent for the Wunderkind private school (changed from "learning center" 2026-09-25). It answers Instagram
comments/DMs and Telegram chats, drives every conversation toward a sale
(free trial lesson / placement test booking → enrollment), stores every
conversation and lead, and is managed from one admin panel.

Ported from `NUR-Project/agent` (read-only source). The NUR agent talked to the
NUR ERP over HTTP for settings, memory, leads and bot menu; here all of that
lives in this project's own database, so those HTTP calls become direct DB calls.

## 1. Architecture

```
Instagram webhook ─┐                         ┌─► Instagram Graph API (reply/DM)
Telegram webhook ──┼─► FastAPI (backend) ────┼─► Telegram Bot API (reply, alerts)
Admin panel (SPA) ─┘   ├─ agent pipeline     └─► Claude / Gemini
                       ├─ admin API (/api)
                       ├─ PostgreSQL (settings, leads, messages, bot menu, users)
                       └─ Redis (dedup, pause, rate limits, TG connection map)
```

- **One backend process** (`uvicorn --workers 1`): APScheduler jobs (daily report,
  IG token refresh, follow-ups) must not run twice. Load is low; all I/O is async.
- Caddy serves the SPA and proxies `/api`, `/webhook`, `/connect` to the backend.
- `PUBLIC_URL` = the public HTTPS origin. Webhooks:
  `{PUBLIC_URL}/webhook/instagram`, `{PUBLIC_URL}/webhook/telegram`.

Stack: FastAPI, SQLAlchemy 2 async + asyncpg, Alembic, Pydantic v2, Redis,
React 18 + Vite + TS + Tailwind, Docker Compose + Caddy.

## 2. Channels

| Channel | In | Out |
|---|---|---|
| Instagram comment | webhook `comments` | public reply + optional private reply (move to DM) |
| Instagram DM | webhook `messages` (+ `is_echo` = operator typed in the app → pause bot) | `me/messages` (24h window; operator may use HUMAN_AGENT tag up to 7 days) |
| Telegram | bot webhook: bot's own chat **and** Telegram Business connection (bot answers in the owner's name) | `sendMessage` (+ menu: text/photos) |
| Telegram alerts | — | hot lead / escalation / daily report / token problems to `TELEGRAM_CHAT_ID` list |

WhatsApp from NUR is **not** ported (not requested).

Telegram alerts use `TELEGRAM_BOT_TOKEN`; if empty, the sales bot token is used
(sending does not conflict with the webhook).

## 3. Sales logic (the point of the product)

Goal per conversation: **name + phone + course (+ age/level, preferred time/branch)
→ trial lesson booked → staff calls → enrolled.**

- System prompt: learning-center sales consultant persona, answers only from the
  knowledge base, same language/script as the client, short, every reply ends
  with one question or call to action, objection handling (price → value/
  discounts/installments only if in KB), never invents prices/schedules,
  escalates to a human when unsure or asked.
- Structured output (`AgentOutput`): reply, language, intent, lead_score,
  is_hot_lead, move_to_dm, escalate_to_human, `stage`, lead{name, contact,
  course_interest, student_age, preferred_time, summary}.
- `stage` (AI's view of funnel): `greeting | discovery | offer | objection |
  closing | booked | support`.
- Phone numbers are also extracted from the raw text server-side (no AI needed).
- **Follow-up**: if the bot asked something and the client went silent,
  one follow-up message is sent after `FOLLOWUP_AFTER_HOURS` (default 3), only
  inside the channel's allowed window (IG 24h), only if no contact was
  collected yet, max once per lead per silence. Toggle `FOLLOWUP_ENABLED`.
- First message to a new person carries the AI disclosure line.
- Operator intervention (reply from panel, or typing in IG/TG app) is logged but
  does NOT pause the bot (changed 2026-09-25 at the client's request;
  `BOT_PAUSE_HOURS` is hidden/unused). The panel's per-chat AI toggle still
  silences a conversation until switched back on.

## 4. Data model

`users` — id (uuid), username (unique), full_name, password_hash, role
(`admin` | `operator`), is_active, created_at, updated_at.

`settings` — key (pk, str), value (text; secret values Fernet-encrypted with a
key derived from `SECRET_KEY`), updated_at.

`leads` — id uuid, channel (`instagram|telegram`), external_id (channel user id),
username, source (`instagram|telegram|instagram_import`), name, contact,
course_interest, student_age, preferred_time, language, intent, stage,
lead_score int, summary, status (`new|contacted|trial|enrolled|lost`),
note, assigned_to_id → users, last_read_at, last_customer_at,
last_followup_at, extra jsonb, created_at, updated_at.
Index (channel, external_id). One **open** lead per (channel, external_id)
(open = status not in enrolled/lost).

`lead_messages` — id uuid, lead_id → leads cascade, kind (`dm|comment|note|status`),
role (`user|assistant|operator|system`), text, external_message_id,
comment_id, media_id, meta jsonb, created_at. Index (lead_id, created_at).

`bot_menu_items` / `bot_menu_images` — same as NUR (command, title, text,
sort_order, is_active; images bytea + sha256, ≤10 per item, ≤5 MB,
jpeg/png/webp). Greeting in `settings.TG_MENU_GREETING`.

## 5. Settings catalog (editable in panel, applied live without restart)

Groups and keys (secret = masked in API, write-only):
- **ai**: AI_PROVIDER(claude|gemini), ANTHROPIC_API_KEY*, CLAUDE_MODEL,
  GEMINI_API_KEY*, GEMINI_MODEL, AI_MAX_TOKENS, AI_EFFORT(low|medium|high)
- **knowledge**: KB_COMPANY, KB_COURSES, KB_SCHEDULE, KB_PROMO, KB_FAQ, KB_RULES
  (textareas; shown on the separate "Bilim bazasi" page)
- **instagram**: IG_APP_ID, IG_APP_SECRET*, IG_VERIFY_TOKEN*,
  hidden: IG_ACCESS_TOKEN*, IG_USER_ID, IG_ACCOUNT_ID, IG_USERNAME,
  IG_TOKEN_ISSUED_AT, GRAPH_API_VERSION
- **telegram**: TG_SALES_BOT_TOKEN*, TG_SALES_ENABLED(ha|yo'q),
  TG_WEBHOOK_SECRET*, TELEGRAM_BOT_TOKEN*, TELEGRAM_CHAT_ID, DAILY_REPORT_TIME
- **sales**: FOLLOWUP_ENABLED(ha|yo'q), FOLLOWUP_AFTER_HOURS, BOT_PAUSE_HOURS,
  CMT_LIMIT_PER_POST, CMT_LIMIT_TOTAL, IG_AI_ENABLED(ha|yo'q)
- **general**: COMPANY_NAME, TIMEZONE

Infra keys stay in `.env` only: DATABASE_URL, REDIS_URL, SECRET_KEY,
PUBLIC_URL, ADMIN_USERNAME/ADMIN_PASSWORD (first-run bootstrap), CORS_ORIGINS.
Value resolution: DB value → `.env` value → default.

## 6. API contract

All admin endpoints under `/api`, JSON, `Authorization: Bearer <jwt>`.
Errors: `{"detail": "<uzbek message>"}`. Roles: **A** = admin, **O** = operator.

### Auth
- `POST /api/auth/login` `{username, password}` → `{access_token, token_type:"bearer", user}` (public)
- `GET /api/auth/me` → `User` (A,O)
- `User` = `{id, username, full_name, role, is_active, created_at}`

### Users (A)
- `GET /api/users` → `User[]`
- `POST /api/users` `{username, full_name, password, role}` → `User`
- `PATCH /api/users/{id}` `{full_name?, password?, role?, is_active?}` → `User`
- `DELETE /api/users/{id}` → 204 (cannot delete self)

### Settings (A)
- `GET /api/settings` →
  `{groups: [{id, title, items: [{key, label, type, secret, options, placeholder, help, value, masked, is_set, from_env}]}], status: AgentStatus}`
  (knowledge group included; secrets return `value:""` + `masked:"••••abcd"`)
- `PUT /api/settings` `{values: {KEY: "value" | "" | null}}` → same as GET.
  Empty/null deletes the DB row (env fallback). Unknown key → 400. Applies live
  (reloads runtime config, re-registers Telegram webhook/commands).
- `AgentStatus` = `{ai_provider, ai_ready, instagram_connected, instagram_username,
  instagram_token_issued_at, telegram_connected, telegram_bot_username,
  notifications_ready, public_url, webhooks: {instagram, telegram}}`
- `GET /api/settings/status` → `AgentStatus` (A,O)
- `POST /api/settings/instagram/connect-url` → `{url}` — Instagram OAuth URL with a
  signed short-lived `state` (callback rejects missing/invalid state).
- `POST /api/settings/instagram/import` → `{started: true}` (background import of
  last-30-day IG conversations as `instagram_import` leads, no AI replies)
- `POST /api/settings/telegram/test` → `{sent: bool, error?}` (test alert to TELEGRAM_CHAT_ID)

### Dashboard (A,O)
- `GET /api/dashboard?days=7` →
  `{totals: {conversations, messages_in, ai_replies, leads_with_contact, hot, trial, enrolled},
    today: {conversations, messages_in, new_leads, hot},
    by_channel: [{channel, conversations}],
    by_status: [{status, count}],
    by_day: [{date, conversations, leads}],
    top_courses: [{course, count}],
    status: AgentStatus}`

### Leads / conversations (A,O)
- `GET /api/leads?status=&channel=&search=&min_score=&has_contact=&page=1&page_size=50`
  → `{items: LeadOut[], total}`
- `GET /api/leads/inbox?search=&channel=&only_unread=` → `InboxItem[]` (sorted by last message desc, max 100)
- `GET /api/leads/{id}` → `LeadDetail` (= LeadOut + `messages: Message[]`)
- `PATCH /api/leads/{id}` `{status?, name?, contact?, course_interest?, student_age?, preferred_time?, note?, assigned_to_id?}` → `LeadOut`
  (status change is also written as a `status` message)
- `DELETE /api/leads/{id}` → 204 (A only)
- `POST /api/leads/{id}/read` → 204
- `POST /api/leads/{id}/reply` `{text}` → `{sent, error?, message?: Message}`
  (sends via channel, pauses AI in that chat, `new`→`contacted`)
- `GET /api/leads/{id}/bot` → `{paused}`; `POST /api/leads/{id}/bot` `{enabled}` → `{paused}`
- `POST /api/leads/{id}/notes` `{text}` → `Message`
- `GET /api/leads/export.csv` (same filters as list) → CSV
- `GET /api/leads/assignees` → `[{id, full_name}]`
- `LeadOut` = `{id, channel, external_id, username, source, name, contact,
  course_interest, student_age, preferred_time, language, intent, stage,
  lead_score, summary, status, note, assigned_to_id, assigned_to_name,
  message_count, last_customer_at, created_at, updated_at}`
- `InboxItem` = `{lead_id, channel, username, name, contact, status, lead_score,
  stage, last_message, last_message_role, last_message_at, unread, window}`
  (`window`: `open | human_agent | closed`; telegram always `open`)
- `Message` = `{id, kind, role, text, meta, created_at}`

### Bot menu (A)
- `GET /api/bot-menu` → `{greeting, items: [{id, command, title, text, sort_order, is_active, images: [{id, content_type, size_bytes, sort_order}]}]}`
- `PUT /api/bot-menu/greeting` `{greeting}` → `{greeting}`
- `POST /api/bot-menu/items` `{command, title, text, is_active}` → item
- `PATCH /api/bot-menu/items/{id}` (same fields, optional) → item
- `DELETE /api/bot-menu/items/{id}` → 204
- `POST /api/bot-menu/items/reorder` `{ids: [..]}` → items
- `POST /api/bot-menu/items/{id}/images` multipart `files[]` → item
- `DELETE /api/bot-menu/images/{image_id}` → 204
- `GET /api/bot-menu/images/{image_id}` → image bytes (auth via `?token=` too, for `<img>`)

### Playground (A)
- `POST /api/playground` `{messages: [{role:"user"|"assistant", content}], channel:"instagram"|"telegram", is_comment: bool}`
  → `AgentOutput` (real AI + current KB; nothing is sent or stored)

### Channel endpoints (no JWT)
- `GET/POST /webhook/instagram` (verify token / HMAC `X-Hub-Signature-256`)
- `POST /webhook/telegram` (`X-Telegram-Bot-Api-Secret-Token`; derived from SECRET_KEY if TG_WEBHOOK_SECRET is empty)
- `GET /connect/callback?code&state` — IG OAuth callback, HTML result page
- `GET /health`

## 7. Admin panel (Uzbek UI)

Sidebar: Bosh sahifa · Suhbatlar · Leadlar · Bilim bazasi · Bot menyusi ·
Sinov (playground) · Sozlamalar · Foydalanuvchilar. Operators see only
Bosh sahifa, Suhbatlar, Leadlar.

- **Bosh sahifa**: KPI tiles, funnel by status, conversations by day, channel split,
  top courses, agent status card (what is connected / what is missing, with links).
- **Suhbatlar**: left list (channel icon, name/@username, last message, unread badge,
  window badge), right chat thread (user/assistant/operator bubbles, notes), reply
  box (disabled when window closed), AI on/off toggle, lead side card (status,
  fields, note) editable inline. Polls every 5 s.
- **Leadlar**: filterable table, status pills, score, contact, course; row → drawer
  with details + conversation; CSV export.
- **Bilim bazasi**: 6 large textareas with help/placeholders tailored to a learning
  center; save.
- **Bot menyusi**: greeting + items CRUD, drag/arrow reorder, image upload/preview.
- **Sinov**: chat box that calls `/api/playground`, shows reply + stage/score/intent
  JSON badges; channel & comment toggles; reset.
- **Sozlamalar**: grouped forms (AI, Instagram, Telegram, Sotuv, Umumiy); secrets as
  password inputs showing mask; Instagram "Ulash"/"Qayta ulash" button, webhook URLs
  with copy buttons, "Eski suhbatlarni import qilish"; Telegram "Test xabar".
- **Foydalanuvchilar**: CRUD.

## 8. Non-functional
- Webhooks return 200 immediately; processing in background tasks.
- IG self-comment loop protection (ID set + username) and per-post/global comment
  rate limits (from NUR, kept as is).
- Secrets encrypted at rest; never logged; masked in API.
- Tests: pytest with SQLite (aiosqlite) for API/RBAC + ported pipeline tests with mock AI.

## 9. Out of scope (now)
WhatsApp, pushing leads into Edutizim/LMS CRM, multi-tenant, voice transcription.

## 10. Lead-magnet funnel (added 2026-09-25)

Client brief (Uzbek TZ, 2026-09-25): attract new **school** pupils. A video on
Instagram / the Telegram channel announces a lead magnet — the PDF
"Lider farzand tarbiyalash uchun 8ta maslahat". People who comment the keyword
**"Wunderkind"** get the PDF through the Telegram bot, then receive sales
messages and book an admission interview. Data goes to Google Sheets until the
CRM exists.

This is a **deterministic scripted funnel** (templates edited in the panel), not
free-form AI: every step has fixed text and buttons. The existing AI agent keeps
answering everything that is *not* a funnel step (free questions in IG DMs and in
the bot). New code lives in `backend/app/funnel/` (+ `app/api/funnel.py`,
`app/models/funnel.py`); existing modules only get small hook calls.

### 10.1 Flow

```
IG comment "wunderkind" ─► public reply + private reply (DM #1: greeting,
   "follow us", quick reply «✅ Obuna bo'ldim»)
IG DM (button tap / any text while waiting) ─► follow check
   ├ follows / check impossible ─► DM with t.me deep link (start=<token>)
   └ not following ─► "still not following" + quick reply again
TG channel comment "wunderkind" (discussion group) ─► bot replies under the
   comment with URL button → t.me/<bot>?start=tgc
Bot /start [payload] ─► (tg source: channel membership check) ─►
   ask full name ─► ask phone (request_contact button or typed) ─►
   ask grade (inline buttons) ─► send PDF ─► Google Sheet row
Sales sequence: N messages at configured delays after the PDF, each with
   «📝 Suhbatga ro'yxatdan o'tish» button; stops once booked
Button ─► pick date (next working days Mon–Sat) ─► pick time slot ─►
   confirmation (date, time, staff name+phone, address) + sendLocation ─►
   staff alert + Sheet update. Buttons: «Vaqtni o'zgartirish», «Bekor qilish»
Booking day at 07:00 ─► reminder message
```

Details:
- **Keyword match**: case-insensitive, Latin/Cyrillic tolerant ("wunderkind",
  "вундеркинд"), whole text or word inside text. Keywords in `FUNNEL_KEYWORDS`
  (comma separated). A funnel comment does NOT go to the AI pipeline.
- **IG comment** (`app/instagram` hook, before `process_event`): public reply
  `FUNNEL_IG_COMMENT_REPLY` (skipped if empty); private reply
  `FUNNEL_IG_DM_WELCOME` with quick reply `{"content_type":"text","title":"✅ Obuna bo'ldim",
  "payload":"FUNNEL_FOLLOW_CHECK"}`. If the API rejects quick replies, resend as
  plain text (the welcome text itself asks to write "tayyor"). Before the private
  reply try the follow check; if it returns `true` the private reply already
  contains the link (`FUNNEL_IG_LINK_MESSAGE`). Same person commenting again on
  another post → a new private reply is allowed (one per comment), reuse the entry.
- **IG DM from a person whose entry is `ig_waiting_follow`**: any text / the
  quick-reply payload triggers the follow check. A DM containing the keyword from
  someone with no entry starts the flow directly in DM (no comment needed).
  Otherwise DMs go to the existing AI pipeline unchanged.
- **Follow check**: `GET /{igsid}?fields=username,is_user_follow_business`.
  `true` → link; `false` → `FUNNEL_IG_NOT_FOLLOWING` + quick reply (max 5 checks,
  then link anyway — no dead end); error/field missing → link if
  `FUNNEL_IG_FOLLOW_FAIL_OPEN=ha` (default) else "try later" text.
  `FUNNEL_IG_REQUIRE_FOLLOW=yo'q` skips the gate.
- **Link**: `https://t.me/<bot_username>?start=<token>`; token = 12 random
  url-safe chars stored on the entry. Sent as a button template (web_url) with a
  plain-text fallback.
- **TG channel comments**: updates from supergroup/group chats whose id equals
  `FUNNEL_TG_DISCUSSION_CHAT_ID` (or any group if empty) and whose text matches
  a keyword → `sendMessage(reply_to_message_id=…)` with `FUNNEL_TG_COMMENT_REPLY`
  and an inline URL button to `?start=tgc`. Rate: one reply per user per 10 min.
  Bot must be admin of the discussion group (or privacy mode off) — documented in
  QOLLANMA. `parse_update` still ignores groups for the AI.
- **Bot `/start`**: payload `<token>` binds the IG entry to this Telegram user;
  `tgc` = source `telegram_channel`; none = `telegram_direct` (still gets the
  funnel if `FUNNEL_BOT_START_FUNNEL=ha`, default). If the user already has an
  entry with `pdf_sent`, resend the PDF instead of re-asking.
  Channel gate (`FUNNEL_TG_CHANNEL` set and `FUNNEL_TG_REQUIRE_CHANNEL=ha`; applies
  to `telegram_channel`/`telegram_direct` sources): `getChatMember`; not a member →
  text + URL button to the channel + «✅ Tekshirish» callback; API error → pass.
- **Collection** (state machine on the entry `step`): name (2–80 chars, at least
  one letter) → phone (contact button `request_contact`, or typed; normalized with
  `app/services/phone.py`; invalid → re-ask) → grade (inline buttons from
  `FUNNEL_GRADES`, e.g. "Bog'cha,0,1,…,11"; typed value also accepted). Reply
  keyboard is removed after the phone. While a collection step is active, text is
  handled by the funnel, NOT by the AI. After `pdf_sent` all free text goes to the
  AI pipeline as before; menu commands keep working.
- **PDF**: `sendDocument` with caption `FUNNEL_PDF_CAPTION`; after the first
  upload the returned `file_id` is cached on the file row (cleared on re-upload).
  No PDF uploaded → text "tez orada yuboramiz", staff alert, entry stays
  `pdf_pending` and is delivered by the scheduler once a PDF exists.
- **Lead**: on reaching `pdf_sent` upsert the open Telegram lead (existing
  `leads` table): name, contact, `student_age` = "<grade>-sinf" (grade display),
  source = `lead_magnet_instagram | lead_magnet_telegram`, stage `offer`,
  lead_score 60; funnel steps are logged as `system` messages so the inbox shows
  them. Booking → lead status `trial`, stage `booked`, score 90.
- **Sales sequence** (`funnel_messages`): ordered active messages, each with
  `delay_minutes` after `pdf_sent_at` (defaults seeded: 10 min, 1 day, 2 days —
  content placeholders the client replaces), optional image, always with the
  booking button (`callback_data="fb:start"`). Scheduler (every minute) sends the
  first undelivered due message per entry, only between 09:00–21:00 local, stops
  when the entry has an active booking or `opted_out`. Each delivery recorded in
  `funnel_deliveries` (unique entry+message) → never twice. Telegram "bot
  blocked" error → `opted_out=true`. `/stop` → opted_out.
- **Booking**: `fb:start` → dates: next `FUNNEL_BOOK_DAYS_AHEAD` (7) days whose
  weekday is in `FUNNEL_WORK_DAYS` (default `1-6` = Mon–Sat), not in
  `FUNNEL_HOLIDAYS` (`YYYY-MM-DD` list), with ≥1 free slot. Slots: from
  `FUNNEL_DAY_START` (09:00) every `FUNNEL_SLOT_MINUTES` (30) while
  `start < FUNNEL_DAY_END` (16:00) → last slot 15:30; capacity
  `FUNNEL_SLOT_CAPACITY` (1) scheduled bookings per slot; today's slots need
  ≥60 min lead time. Callbacks `fb:d:<YYYYMMDD>`, `fb:t:<YYYYMMDDHHMM>`,
  `fb:back`, `fb:cancel`, `fb:resched`. Taking a slot re-checks capacity under a
  per-slot asyncio lock (single worker) — full → "bu vaqt band bo'ldi" + fresh
  slots. One `scheduled` booking per entry (reschedule = cancel old + create new).
- **Confirmation**: `FUNNEL_CONFIRM_TEXT` with placeholders `{name} {date} {time}
  {weekday} {staff_name} {staff_phone} {address}` + `sendLocation(FUNNEL_LOCATION_LAT,
  FUNNEL_LOCATION_LON)` when both set. Staff alert to `TELEGRAM_CHAT_ID`
  (name, phone, grade, date/time, source).
- **Reminder**: cron at `FUNNEL_REMINDER_TIME` (07:00, TIMEZONE): today's
  `scheduled` bookings with `reminder_sent_at IS NULL` created before the
  reminder time → `FUNNEL_REMINDER_TEXT` (same placeholders) + location. Also
  rescheduled when settings change.
- **Google Sheets**: service account JSON (`GSHEET_SERVICE_ACCOUNT_JSON`, secret)
  + `GSHEET_SPREADSHEET_ID` + `GSHEET_WORKSHEET` (default "Leadlar"). Sheets REST
  API v4 via httpx, OAuth token from a JWT signed with the service-account key
  (pyjwt + cryptography, already dependencies). One row per entry, header row
  created if the sheet is empty: `Sana | Manba | Ism-familiya | Telefon | Sinf |
  Telegram | Telegram ID | Instagram | Qo'llanma | Suhbat sanasi | Suhbat vaqti |
  Suhbat holati | Yangilangan`. Entry keeps `sheet_row`; first write = append
  (row parsed from `updates.updatedRange`), later = update that row. Outbox:
  every change sets `sheet_dirty=true`; a job every minute syncs dirty entries
  (so Google outages never lose data). Not configured → silently skipped.

### 10.2 Data model (new tables, one migration)

`funnel_entries` — id uuid, source (`instagram|telegram_channel|telegram_direct`),
start_token str(24) unique, ig_user_id str(64) index, ig_username, ig_comment_id,
follow_checks int 0, tg_user_id str(32) **unique nullable**, tg_chat_id, tg_username,
lead_id → leads SET NULL, step (`ig_waiting_follow|ig_link_sent|tg_channel_gate|
ask_name|ask_phone|ask_grade|pdf_pending|pdf_sent`), full_name, phone, grade,
followed_at, link_sent_at, bot_started_at, pdf_sent_at, opted_out bool,
sheet_row int null, sheet_dirty bool, created_at, updated_at.
If a Telegram user who already has an entry opens an IG token link, the IG data is
copied onto the existing TG entry and the IG-only entry is deleted.

`funnel_messages` — id uuid, sort_order int, text, delay_minutes int,
is_active bool, image bytea null, image_content_type, created_at, updated_at.

`funnel_deliveries` — id uuid, entry_id → cascade, message_id → cascade,
sent_at; unique (entry_id, message_id).

`funnel_files` — key str pk (`lead_magnet`), filename, content_type, size_bytes,
data bytea, sha256, tg_file_id null, updated_at. PDF only, ≤ 20 MB.

`interview_bookings` — id uuid, entry_id → cascade, lead_id → leads SET NULL,
starts_at timestamptz index, status (`scheduled|cancelled|attended|no_show`),
reminder_sent_at, note, created_at, updated_at. Partial unique index: one
`scheduled` per entry.

### 10.3 Settings (new catalog group `funnel` "Lead-magnet voronkasi", plus `gsheet` "Google Sheets")

`FUNNEL_ENABLED`(ha|yo'q, default ha), `FUNNEL_KEYWORDS` ("wunderkind, вундеркинд"),
`FUNNEL_IG_REQUIRE_FOLLOW`, `FUNNEL_IG_FOLLOW_FAIL_OPEN`, `FUNNEL_IG_COMMENT_REPLY`,
`FUNNEL_IG_DM_WELCOME`, `FUNNEL_IG_NOT_FOLLOWING`, `FUNNEL_IG_LINK_MESSAGE`,
`FUNNEL_TG_CHANNEL` (@username or -100…), `FUNNEL_TG_REQUIRE_CHANNEL`,
`FUNNEL_TG_DISCUSSION_CHAT_ID`, `FUNNEL_TG_COMMENT_REPLY`, `FUNNEL_BOT_START_FUNNEL`,
`FUNNEL_BOT_WELCOME`, `FUNNEL_ASK_NAME`, `FUNNEL_ASK_PHONE`, `FUNNEL_ASK_GRADE`,
`FUNNEL_GRADES`, `FUNNEL_PDF_CAPTION`, `FUNNEL_BOOK_BUTTON`, `FUNNEL_WORK_DAYS`,
`FUNNEL_DAY_START`, `FUNNEL_DAY_END`, `FUNNEL_SLOT_MINUTES`, `FUNNEL_SLOT_CAPACITY`,
`FUNNEL_BOOK_DAYS_AHEAD`, `FUNNEL_HOLIDAYS`, `FUNNEL_STAFF_NAME`, `FUNNEL_STAFF_PHONE`,
`FUNNEL_ADDRESS`, `FUNNEL_LOCATION_LAT`, `FUNNEL_LOCATION_LON`, `FUNNEL_CONFIRM_TEXT`,
`FUNNEL_REMINDER_TIME`, `FUNNEL_REMINDER_TEXT`; `GSHEET_SERVICE_ACCOUNT_JSON`*,
`GSHEET_SPREADSHEET_ID`, `GSHEET_WORKSHEET`.
Every text has a good Uzbek default in `config.py` so the funnel works out of the
box. Validation: times `HH:MM`, work days `1-6` / `1,2,3`, lat/lon floats, holidays
dates, service-account JSON parses and has `client_email` + `private_key`.
The funnel group is shown on the Funnel page, not in Sozlamalar.

### 10.4 API (all under `/api/funnel`, JWT; A = admin, O = operator)

- `GET /stats?days=30` (A,O) → `{steps: [{key, label, count}], by_source: [{source, count}],
  bookings: {scheduled, attended, no_show, cancelled, today}, by_day: [{date, entries, pdf, bookings}]}`
  Steps: comments(entries created), link_sent, bot_started, contact_collected
  (phone set), pdf_sent, booked (entries with any booking), attended.
- `GET /entries?source=&step=&search=&page=1&page_size=50` (A,O) →
  `{items: FunnelEntryOut[], total}`; `FunnelEntryOut` = `{id, source, step, full_name,
  phone, grade, ig_username, tg_username, lead_id, pdf_sent_at, opted_out,
  booking: BookingOut|null, messages_sent, created_at}`
- `GET /bookings?date_from=&date_to=&status=` (A,O) → `BookingOut[]` sorted by
  starts_at; `BookingOut` = `{id, entry_id, lead_id, full_name, phone, grade,
  starts_at, status, note, reminder_sent_at, created_at}`
- `PATCH /bookings/{id}` `{status?, note?}` (A,O) → `BookingOut` (sheet dirty; lead
  status `enrolled` is NOT set automatically)
- `GET /slots?date=YYYY-MM-DD` (A,O) → `[{time:"09:00", free:int}]`
- `GET /messages` (A) → `FunnelMessageOut[]` = `{id, sort_order, text, delay_minutes,
  is_active, has_image, image_content_type}`; `POST /messages` `{text, delay_minutes,
  is_active}`; `PATCH /messages/{id}`; `DELETE /messages/{id}` 204;
  `POST /messages/reorder` `{ids}`; `PUT /messages/{id}/image` multipart `file`
  (jpeg/png/webp ≤5 MB); `DELETE /messages/{id}/image`; `GET /messages/{id}/image`
  (auth via `?token=` too)
- `GET /lead-magnet` (A) → `{filename, size_bytes, updated_at} | null`;
  `PUT /lead-magnet` multipart `file` (application/pdf, ≤20 MB, `%PDF` magic);
  `GET /lead-magnet/download` (A, `?token=` allowed)
- `POST /sheet/test` (A) → `{ok, error?, title?}`; `POST /sheet/resync` (A) →
  `{queued:int}` (marks all entries dirty)
- `POST /test-message` (A) `{tg_chat_id, kind: "reminder"|"confirm"|"sales", message_id?}` →
  `{sent, error?}` — preview of a template in a real chat.

### 10.5 Admin panel — new page "Voronka" (sidebar after Leadlar; A,O)

Tabs: **Statistika** (step funnel bars + conversion %, by source, bookings today),
**Suhbatlar** (bookings: date range filter default today+7, status select inline,
note; operators can use), **Ro'yxat** (entries table, search/filter, link to lead),
**Xabarlar** (A: sales sequence CRUD — text, delay in minutes/hours/days picker,
active toggle, image, reorder), **Sozlamalar** (A: PDF upload/replace/download,
funnel + gsheet settings via existing settings API rendered with `SettingField`,
"Google Sheets'ni tekshirish" button, test message). Operators see only the first
three tabs.

### 10.6 Tests
Keyword matcher; slot generation (work days, holidays, lead time, capacity);
state machine name→phone→grade→pdf with a fake Telegram client; IG follow gate
true/false/error; token binding and merge; sales scheduler (delay, quiet hours,
stop on booking, no double send); reminder selection; Sheets row mapping +
dirty outbox with a fake HTTP transport; API RBAC (operator 403 on admin
endpoints, 401 without token).

### 10.7 Changes after qa-review (2026-09-25)
API contract (10.4) unchanged. Behaviour and data model:
- **Leaving the questions**: `/stop` mid-collection pauses it (entry `opted_out`, step
  kept; free text goes to the AI; `/start` or an inline button resumes). A text with
  "?" or the 2nd invalid answer in a row goes to the AI, step kept. Names: max 4
  words, no "?". Menu reply keyboard is restored after the phone and after `/stop`.
- **PDF send failure** → `pdf_pending` + "tez orada" text once + hourly-limited staff
  alert; retried with backoff 1→60 min (`funnel_entries.pdf_attempts`, `pdf_retry_at`).
- **Sales sequence**: seeded messages are inactive; texts containing `[raqam…]` /
  `[imtiyoz…]` are never sent.
- **Instagram DMs**: from someone without an entry the funnel starts only for a
  (nearly) bare keyword (no "?", ≤ 2 extra words); comments stay broad. Chats paused by
  an operator are left to the AI pipeline. DMs the funnel takes are logged to the IG lead.
- **Funnel log lines** on leads are `kind=status` (not part of the AI history).
- **Google Sheets**: header gets a 14th column `ID` (entry id); every batch reads it to
  find each entry's row (sorting the sheet is safe). 401/403/429/5xx/network stop the
  batch; other 4xx skip only that entry. Changing spreadsheet/worksheet re-exports all.
  A merged Instagram entry's row is taken over, or marked "Birlashtirildi"
  (`funnel_entries.sheet_merged_id`).
- **Bookings**: a reschedule marks the old row `rescheduled=true` (still `cancelled`);
  stats ignore it. PATCH to `scheduled` → 400. Group keyword replies skip TELEGRAM_CHAT_ID
  chats. Missed 07:00 reminders are sent at startup until 12:00.
- Migration `087311873265` (additive columns) follows `74ce2ab64d21`.

## 11. Multiple funnels (added 2026-09-25)

Client: "several funnels, each built separately" (Salebot-constructor-like later).
Phase 1 (this section): N funnels sharing the SAME step template (§10.1).
Phase 2 (later, separate spec): visual block constructor.

Shared by all funnels (stay global settings): booking schedule
(`FUNNEL_WORK_DAYS … FUNNEL_BOOK_DAYS_AHEAD`, `FUNNEL_HOLIDAYS`), staff/address/
location, confirm + reminder texts and time, Telegram channel gate settings
(`FUNNEL_TG_CHANNEL`, `FUNNEL_TG_REQUIRE_CHANNEL`, `FUNNEL_TG_DISCUSSION_CHAT_ID`),
IG follow flags, Google Sheets, `FUNNEL_ENABLED` (master switch).

Per funnel: name, active flag, keywords, optional Instagram post filter, lead
magnet PDF, sales messages, and text overrides.

### 11.1 Data model (one additive migration)
`funnels` — id uuid, name str(120), slug str(32) unique (a-z0-9_, used in deep
links), is_active bool, is_default bool (exactly one), keywords text (comma
separated; empty on the default funnel = use `FUNNEL_KEYWORDS`),
ig_media_ids text (comma separated Instagram media ids/permalinks shortcodes;
empty = any post), texts jsonb (per-funnel overrides of the whitelisted text keys
below; missing/empty key → global setting), sort_order, created_at, updated_at.
Whitelisted per-funnel text keys: FUNNEL_IG_COMMENT_REPLY, FUNNEL_IG_DM_WELCOME,
FUNNEL_IG_NOT_FOLLOWING, FUNNEL_IG_LINK_MESSAGE, FUNNEL_TG_COMMENT_REPLY,
FUNNEL_BOT_WELCOME, FUNNEL_ASK_NAME, FUNNEL_ASK_PHONE, FUNNEL_ASK_GRADE,
FUNNEL_GRADES, FUNNEL_PDF_CAPTION, FUNNEL_BOOK_BUTTON.

Migration: create `funnels`, insert the default funnel ("Asosiy voronka", slug
`asosiy`, is_default, empty overrides → behaves exactly like today); add
`funnel_id` (FK funnels, NOT NULL after backfill to the default) to
`funnel_entries` and `funnel_messages`; `funnel_files` gets `funnel_id`
(backfill default; the lead magnet becomes one PDF per funnel).
`funnel_entries.tg_user_id` uniqueness becomes (funnel_id, tg_user_id): one
person may go through several funnels. Downgrade must work (drop added
columns/table; before that delete non-default funnels' rows).

### 11.2 Routing
- Keyword match: iterate active funnels by sort_order; a funnel matches when a
  keyword matches AND (ig_media_ids empty OR the comment's media id is listed).
  Funnels with a media filter are checked before funnels without one. The default
  funnel's empty keywords mean `FUNNEL_KEYWORDS`. Saving a funnel whose keyword
  collides with another active funnel with the same media scope → 400
  (Uzbek message).
- Deep links: IG token links unchanged (token belongs to an entry → funnel).
  Telegram channel link `?start=tgc` → default funnel; `?start=tgc_<slug>` →
  that funnel; `?start=f_<slug>` → that funnel with source `telegram_direct`
  (for ads/bio links). Bare `/start` → default funnel (if
  FUNNEL_BOT_START_FUNNEL=ha).
- Bot state: a Telegram user's *current* entry = the most recently touched entry
  in a collection step; callbacks (`fb:*`) carry no funnel id — they act on the
  entry of the active booking flow (latest pdf_sent entry). Bookings stay one
  `scheduled` per person across funnels (a person books one interview, whichever
  funnel sent the button): taking a new slot from another funnel reschedules.
- Sales scheduler: per entry, its own funnel's messages. If the same person is
  in two funnels, both sequences run but stop on booking (existing rule).
- Inactive funnel: no new entries; in-flight entries finish.
- Deleting a funnel: only if it has no entries (else 409 "arxivlang" → set
  inactive); default funnel cannot be deleted or deactivated.

### 11.3 API changes (all `/api/funnel`)
- `GET /funnels` (A,O) → `FunnelOut[]` = `{id, name, slug, is_active, is_default,
  keywords, ig_media_ids, texts, sort_order, links: {telegram_channel, telegram_direct},
  stats: {entries, pdf_sent, booked}, has_pdf, created_at}`
- `POST /funnels` (A) `{name, slug?, keywords, ig_media_ids?, is_active?, texts?}`
  → FunnelOut (slug auto from name if absent; copy_from_id? optional: duplicates
  texts, messages and PDF of another funnel)
- `PATCH /funnels/{id}` (A), `DELETE /funnels/{id}` (A) 204/409,
  `POST /funnels/reorder` (A) `{ids}`
- Existing endpoints get an optional `funnel_id` query param (absent → all funnels
  for stats/entries/bookings; → default funnel for messages / lead-magnet):
  `GET /stats`, `GET /entries`, `GET /bookings`, `GET|POST /messages`,
  `POST /messages/reorder`, `GET|PUT /lead-magnet`, `GET /lead-magnet/download`.
  `FunnelEntryOut` and `BookingOut` gain `funnel_id, funnel_name`.
  `FunnelMessageOut` gains `funnel_id`.
- `GET /settings` unchanged; the per-funnel text keys stay in the global
  catalog as defaults.

- Backend clarifications (2026-09-25, no contract change): `POST /funnels` — `keywords`
  may be "" on a non-default funnel (deep-link-only funnel); `ig_media_ids` accepts
  media ids, post/reel links or shortcodes and is stored normalized ("id…, shortcode…").
  `PATCH /funnels/{id}` `texts` is MERGED: a key with text sets it, ""/null removes it
  (→ global), absent keys stay. `DELETE` of the default funnel → 400 (with entries → 409).
  Unknown `funnel_id` on any endpoint → 404. `copy_from_id` copies texts (payload texts
  win), sales messages with images and the PDF (keywords/post filter are not copied).
  Routing without a post (Instagram DM, Telegram group comment): unfiltered funnels
  first, then post-filtered ones by sort_order. Instagram DMs keep the strict rule
  (§10.7: nearly bare keyword). After qa-review: bare `/start` resumes the person's own
  latest entry (default funnel only for people with no entry); unknown `tgc_<slug>` →
  default funnel as `telegram_channel`; with the master switch off / an archived funnel a
  link only resumes unfinished questions; Sheet column O is written only if empty or
  "Voronka" (otherwise A:N + staff alert).

### 11.4 Google Sheets
New column "Voronka" (funnel name) inserted before "ID"… to avoid shifting the
existing layout it is APPENDED as column O after "ID"; header row updated on
next sync.

### 11.5 Admin panel
Voronka page:
- Top: funnel switcher (list/cards: name, active badge, keywords, entries/PDF/
  booked counts) + "Yangi voronka" (A) with optional "copy from".
- Selected funnel tabs: Statistika, Ro'yxat (scoped), Xabarlar (A), Sozlamalar
  (A: name, slug, active, keywords, IG post filter, PDF, text overrides — each
  override field shows the global default as placeholder with "umumiy matn"
  hint; empty = use global; deep links with copy buttons).
- "Hammasi" pseudo-funnel in the switcher for all-funnel Statistika/Ro'yxat.
- Suhbatlar tab (bookings) stays global with a funnel filter + column.
- Separate tab "Umumiy sozlamalar" (A): the shared settings (schedule, staff,
  address, confirm/reminder, TG channel, IG follow flags, master switch,
  Google Sheets + check/resync, test message). Remove from it the per-funnel
  keys (they live in each funnel's overrides; the global value is the default).

### 11.6 Tests
Migration backfill (existing entries/messages/PDF land in the default funnel,
behaviour unchanged — all existing funnel tests must pass untouched except for
new fields); routing by keyword and media filter; keyword collision 400;
`tgc_<slug>`/`f_<slug>` deep links; person in two funnels; per-funnel texts
override + fallback; per-funnel PDF; delete/deactivate rules; RBAC on new
endpoints.

## 12. Meta App Review readiness — legal pages & callbacks (added 2026-09-26)

Meta requires public URLs before an app can go Live / pass App Review:
Privacy Policy, Terms of Service, User Data Deletion (instructions URL or
callback), and (Instagram Login) a Deauthorize callback.

### 12.1 Public pages (server-rendered HTML, no JS, no auth)
`GET /privacy`, `GET /terms`, `GET /data-deletion` (optional `?code=<confirmation>`
shows that request's status). Rendered by the backend (Jinja-free: plain
f-strings/`string.Template`, HTML-escaped values), bilingual: Uzbek (Latin) first,
English below (reviewers read English), same simple styled layout, `lang` attrs,
mobile friendly, links between the three pages. Caddy routes these three paths
to the backend (add to the `@backend` matcher).

Content must describe the ACTUAL system (see §2, §10, §11):
- Who: `LEGAL_ENTITY_NAME` (fallback COMPANY_NAME), private school, contact
  `LEGAL_CONTACT_EMAIL`, `LEGAL_CONTACT_PHONE`, `LEGAL_ADDRESS`, website
  `PUBLIC_URL`; "last updated" date = the date the page text last changed
  (constant in code).
- Data collected: Instagram-scoped user id & username, comments/DMs sent to our
  account, Telegram user id/username/messages sent to our bot, name, phone number
  (only when the user shares it), child's grade, interview booking date/time,
  Instagram follow status (yes/no) of the user who contacted us, Telegram channel
  membership (yes/no).
- Purpose: answering questions, sending the requested guide (PDF), admission
  follow-up messages, booking/reminding the admission interview. No ads
  targeting, no sale of data.
- Processors: Google (Gemini API — generating replies; Google Sheets — staff
  lead list), Meta (Instagram API), Telegram, hosting provider (DigitalOcean,
  Frankfurt). AI disclosure.
- Retention: while needed for admission communication, max 24 months after last
  contact, or until a deletion request.
- Rights & deletion: how to request (email/phone, or the data-deletion page;
  `/stop` in the Telegram bot stops messages); deletion within 30 days.
- Children: the service is addressed to parents/guardians; we don't knowingly
  collect data directly from children under 13; the child's grade is provided by
  the parent.
- Terms: service description, acceptable use, no guarantee of admission,
  AI-generated replies may contain mistakes (staff confirm details), liability
  limitation, governing law Republic of Uzbekistan, contact.
- Data deletion page: instructions (write to email/phone or send "/delete"-style
  request; for Instagram users: remove the app in Instagram → Settings → Apps and
  websites), and the status lookup by confirmation code.

### 12.2 Meta callbacks (`/connect/*`, public, signature-verified)
- `POST /connect/data-deletion` — form field `signed_request`
  (`base64url(sig).base64url(payload)`, HMAC-SHA256 with `IG_APP_SECRET`; reject
  bad/missing signature with 400). Payload `user_id` = the Instagram-scoped id of
  the app user. Action: record a `data_deletion_requests` row
  (id, confirmation_code 16 url-safe chars unique, source "meta_callback",
  external_user_id, status `received|completed`, created_at, completed_at);
  delete leads (+ messages cascade) and funnel entries whose Instagram id equals
  that user id; if the user id equals our connected IG account (IG_USER_ID /
  IG_ACCOUNT_ID) → clear IG access token/identity settings (disconnect); mark
  completed; staff alert. Respond JSON
  `{"url": "{PUBLIC_URL}/data-deletion?code=<code>", "confirmation_code": "<code>"}`.
- `POST /connect/deauthorize` — same signature check; if it is our connected
  account → clear IG token/identity (disconnect) + staff alert; always 200.
- Idempotent on repeated requests for the same user (new code each time is fine).

### 12.3 Settings (new catalog group `legal` "Yuridik ma'lumotlar", shown in Sozlamalar)
`LEGAL_ENTITY_NAME`, `LEGAL_CONTACT_EMAIL` (validated email), `LEGAL_CONTACT_PHONE`,
`LEGAL_ADDRESS`. Empty → pages still render (fallbacks: COMPANY_NAME;
FUNNEL_STAFF_PHONE; FUNNEL_ADDRESS) and show no empty labels.

### 12.4 Panel
Sozlamalar → Instagram status card: add copyable URLs "Privacy Policy URL",
"Terms of Service URL", "User data deletion (callback URL)", "Deauthorize callback
URL" (from `AgentStatus.webhooks` / a new `legal_urls` object in AgentStatus:
`{privacy, terms, data_deletion_page, data_deletion_callback, deauthorize}`),
with a short hint where each goes in the Meta dashboard. Sozlamalar shows the new
`legal` group automatically.

### 12.5 Docs
`docs/META_APP_REVIEW.md` (English, for the client to paste): app description,
per-permission justification for `instagram_business_basic`,
`instagram_business_manage_messages`, `instagram_business_manage_comments`
(what we do, why needed, how a user benefits), step-by-step screencast script for
each, reviewer test instructions (panel login = a dedicated operator account the
client creates; test Instagram account), and the checklist of dashboard fields
(URLs above, icon, category Education, contact email, Business Verification).
Uzbek short summary in QOLLANMA (new section).

### 12.6 Tests
Signature verification (valid/invalid/missing), deletion removes the right lead,
messages, funnel entries and keeps others, own-account deletion disconnects
Instagram, confirmation status page shows the code, pages return 200 text/html
without auth and HTML-escape settings values, new settings validation.

## 13. Customer account profiles (added 2026-09-26)

Staff want the most the channels tell about each customer's account.

### 13.1 What is collected
| Channel | Source | Data |
|---|---|---|
| Telegram | every private update (`from` / `chat`) | first+last name, username, language_code, is_premium |
| Telegram | shared contact (`contact.user_id` = sender) | phone (verified) |
| Telegram | `getChat`, max once per 24 h per person | bio, birthdate, personal channel |
| Telegram | `getUserProfilePhotos` on demand | profile photo (proxied, not stored) |
| Instagram | comment webhook | username |
| Instagram | User Profile API — DMs only, max once per 6 h per person, 1 try / 5 s timeout, retried once without `is_verified_user` | name, username, profile_pic (link, expires), follower_count, is_verified_user, is_user_follow_business, is_business_follow_user |

Instagram never exposes phone numbers; the profile API works only after the
person messaged us (error 230 otherwise). A shared Telegram contact is also
logged as `[Mijoz kontakt yubordi: <name>, +<phone>]`, so the lead's phone fills
through the existing extraction and the AI sees it.

### 13.2 Storage
Table `customer_profiles` (channel, external_id unique; username, full_name,
phone, details JSON, fetched_at) — per person, not per lead, filled even before a
lead exists. Leads get `username` (Instagram DMs carry none) and an empty open
lead's `contact` from the profile; new leads start with both. `Lead.name` is NOT
filled from the account name — the AI treats `name` as known and would stop
asking for the real name. Meta data deletion also deletes the profiles.

### 13.3 Capture
TG `handle_update` and the IG webhook queue `profiles.capture_*` AFTER all reply
tasks of the update/batch (the IG client's 1 req/s throttle is shared with
replies; commenters never get an API read — no consent). Best effort, never
raises, logs no personal data. A fresh API read replaces the API-owned keys (a
hidden bio/birthdate disappears); other sources only add. A staff-sent contact
card in a Business chat is logged as `[Xodim kontakt yubordi: ...]`.

### 13.4 API (login required, admin + operator)
- `GET /api/leads/{id}` → `profile_name`, `profile` (details without the CDN link)
- `GET /api/leads`, `/api/leads/inbox` → `profile_name`; search also matches the
  account name and the shared phone; CSV gets «Akkaunt nomi».
- `POST /api/leads/{id}/profile/refresh` → re-read now; `null` when the channel
  gave nothing.
- `GET /api/leads/{id}/avatar` → image bytes (Telegram via bot API server-side;
  Instagram from Meta CDN hosts only, expired link renewed once), 404 if none.
