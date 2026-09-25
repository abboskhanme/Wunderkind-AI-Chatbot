# Wunderkind AI Agent

AI sales agent for the Wunderkind private school. Answers Instagram comments/DMs
and Telegram chats, drives each conversation to an admission interview booking
(name + phone), logs everything, and alerts staff in Telegram. Managed from one
admin panel. Ported from `NUR-Project/agent`; see `docs/SPEC.md`.

```
backend/   FastAPI: webhooks + agent pipeline + admin API (/api) + scheduler
frontend/  React admin panel (Uzbek UI), served by Caddy which also proxies the backend
docs/      SPEC.md, ASSUMPTIONS.md, QOLLANMA.md (user manual, Uzbek)
```

## Run (Docker)

```bash
cp .env.example .env        # set POSTGRES_PASSWORD, SECRET_KEY, ADMIN_PASSWORD
docker compose -p wkagent up -d --build
open http://localhost:8080  # login: ADMIN_USERNAME / ADMIN_PASSWORD
```

Migrations run automatically on backend start (`alembic upgrade head`).
The backend must run with **one** uvicorn worker (in-process scheduler).

## Production

Point a domain at the server, then in `.env`:

```
PUBLIC_URL=https://agent.example.uz
SITE_ADDRESS=agent.example.uz
WEB_HTTP_PORT=80
WEB_HTTPS_PORT=443
```

Caddy obtains the TLS certificate itself. Webhook URLs (shown in the panel):
`{PUBLIC_URL}/webhook/instagram`, `{PUBLIC_URL}/webhook/telegram`.
Instagram OAuth redirect URI to register in the Meta app: `{PUBLIC_URL}/connect/callback`.

## Configure (admin panel → Sozlamalar)

1. **AI** — Gemini API key (default provider). Claude is an optional fallback.
2. **Bilim bazasi** — courses, prices, schedule, trial lesson, promos, FAQ. The agent
   only states facts from here. Test answers in **Sinov**.
3. **Telegram** — sales bot token from @BotFather + webhook secret (webhook registers
   itself once `PUBLIC_URL` is set); alert chat IDs.
4. **Instagram** — Meta app (Instagram API with Instagram Login): App ID, App Secret,
   verify token; set the webhook in Meta (fields `comments`, `messages`); then press
   **Ulash**.

## Local development

```bash
cd backend
uv venv -p 3.12 .venv && uv pip install -p .venv/bin/python -r requirements-dev.txt
.venv/bin/pytest -q                       # SQLite + mock AI, no network
DATABASE_URL=postgresql+asyncpg://... .venv/bin/uvicorn app.main:app --reload
cd ../frontend && npm install && npm run dev   # http://localhost:5173, proxies to :8000
```

`AI_PROVIDER=mock` in `.env` runs the full flow without an AI key.
