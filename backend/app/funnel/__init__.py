"""Lead-magnet funnel (SPEC §10) — a deterministic scripted flow, not free-form AI.

    Instagram comment/DM "wunderkind" ─► follow gate ─► t.me deep link
    Telegram channel comment         ─► reply with deep link
    Bot /start ─► name ─► phone ─► grade ─► PDF ─► sales sequence ─► interview booking

Modules:
  keywords        — keyword matcher (Latin/Cyrillic tolerant)
  texts           — fixed Uzbek strings, template rendering, date/grade formatting
  slots           — interview slot generation (pure) + taken-slot counts (DB)
  repo            — entry lookups, lead upsert, Sheets dirty flag, bot deep links
  instagram_gate  — Instagram hook: keyword comments, follow gate, link
  bot             — Telegram hook: /start, collection steps, group comments
  booking         — interview booking callbacks (fb:*)
  delivery        — PDF + sales message sending
  sales           — per-minute scheduler: pending PDFs + sales sequence
  reminders       — booking-day reminder cron
  gsheet          — Google Sheets client + dirty outbox sync
  validation      — panel settings validation for FUNNEL_* / GSHEET_* keys

Existing modules only call in through small hooks (Instagram webhook, Telegram
`handle_update`, `main.py` scheduler). Single uvicorn worker → asyncio locks.
"""
