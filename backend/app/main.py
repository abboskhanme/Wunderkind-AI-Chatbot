"""Wunderkind AI Agent — FastAPI app: channel webhooks + admin API + scheduler.

Run locally:  uvicorn app.main:app --reload --port 8000
Must run with ONE worker: the scheduler (daily report, token refresh,
follow-ups) lives in-process and would otherwise fire once per worker.
"""
from __future__ import annotations

import asyncio

import sys
from contextlib import asynccontextmanager
from zoneinfo import ZoneInfo

from apscheduler.schedulers.asyncio import AsyncIOScheduler
from apscheduler.triggers.cron import CronTrigger
from apscheduler.triggers.interval import IntervalTrigger
from fastapi import APIRouter, FastAPI
from fastapi.middleware.cors import CORSMiddleware
from loguru import logger
from sqlalchemy import func, select

from app import runtime_config
from app.agent import knowledge
from app.api import auth, bot_menu, dashboard, funnel, funnels, leads, playground, users
from app.api import settings as settings_api
from app.config import settings
from app.core.security import hash_password
from app.db import session as db_session
from app.funnel import funnels as funnel_registry
from app.funnel import gsheet as funnel_gsheet
from app.funnel import reminders as funnel_reminders
from app.funnel import sales as funnel_sales
from app.legal.pages import router as legal_pages_router
from app.funnel.landing import router as funnel_landing_router
from app.instagram.oauth import ensure_identity, refresh_token_if_due
from app.instagram.meta_callbacks import router as meta_callbacks_router
from app.instagram.oauth import router as oauth_router
from app.instagram.webhook import router as ig_webhook_router
from app.models.user import User
from app.processing.followup import run_followups
from app.telegram.notifier import send_daily_report
from app.telegram_business import menu as tg_menu
from app.telegram_business.client import telegram
from app.telegram_business.webhook import router as tg_webhook_router

logger.remove()
# diagnose=False: tracebacks must not print local variables (tokens)
logger.add(sys.stderr, level=settings.LOG_LEVEL, diagnose=False, backtrace=False)

_scheduler: AsyncIOScheduler | None = None
_tg_webhook_state: dict[str, str] = {}
_startup_jobs: set[asyncio.Task] = set()    # keep references to fire-and-forget tasks


async def bootstrap_admin() -> None:
    """Create the first admin from ADMIN_USERNAME/ADMIN_PASSWORD if no users exist."""
    async with db_session.SessionLocal() as db:
        count = (await db.execute(select(func.count()).select_from(User))).scalar() or 0
        if count:
            return
        if not settings.ADMIN_PASSWORD:
            logger.warning("No users and ADMIN_PASSWORD is empty — cannot create admin")
            return
        db.add(User(username=settings.ADMIN_USERNAME, full_name="Administrator",
                    password_hash=hash_password(settings.ADMIN_PASSWORD), role="admin",
                    is_active=True))
        await db.commit()
        logger.info("Admin user created: {}", settings.ADMIN_USERNAME)


async def setup_telegram_webhook() -> None:
    """Register the sales bot webhook (again whenever token/URL/secret change)."""
    if not telegram.enabled or not settings.PUBLIC_URL:
        return
    url = f"{settings.PUBLIC_URL.rstrip('/')}/webhook/telegram"
    secret = settings.tg_webhook_secret
    fingerprint = f"{settings.TG_SALES_BOT_TOKEN[:12]}|{url}|{secret[:8]}"
    if _tg_webhook_state.get("fp") == fingerprint:
        return
    if await telegram.set_webhook(url, secret):
        _tg_webhook_state["fp"] = fingerprint


def _timezone() -> str:
    try:
        ZoneInfo(settings.TIMEZONE)
        return settings.TIMEZONE
    except Exception:  # noqa: BLE001
        logger.warning("Invalid TIMEZONE {!r} — using Asia/Tashkent", settings.TIMEZONE)
        return "Asia/Tashkent"


def _schedule_daily_report() -> None:
    if not _scheduler:
        return
    try:
        hour, minute = (int(x) for x in settings.DAILY_REPORT_TIME.split(":"))
        trigger = CronTrigger(hour=hour, minute=minute, timezone=_timezone())
        _scheduler.add_job(send_daily_report, trigger,
                           id="daily_report", replace_existing=True)
    except Exception as exc:  # noqa: BLE001
        logger.warning("Daily report not scheduled (DAILY_REPORT_TIME?): {}", exc)


def _schedule_funnel_reminders() -> None:
    """Booking-day reminders at FUNNEL_REMINDER_TIME (TIMEZONE); re-run on change."""
    if not _scheduler:
        return
    try:
        hour, minute = (int(x) for x in settings.FUNNEL_REMINDER_TIME.split(":"))
        trigger = CronTrigger(hour=hour, minute=minute, timezone=_timezone())
        _scheduler.add_job(funnel_reminders.run_reminders, trigger, id="funnel_reminders",
                           replace_existing=True, misfire_grace_time=3600, coalesce=True)
    except Exception as exc:  # noqa: BLE001
        logger.warning("Funnel reminders not scheduled (FUNNEL_REMINDER_TIME?): {}", exc)


async def after_settings_change(changed: list[str]) -> None:
    """Apply side effects of a settings save (called by the settings API)."""
    keys = set(changed)
    if keys & {"TG_SALES_BOT_TOKEN", "TG_WEBHOOK_SECRET", "TG_SALES_ENABLED"}:
        _tg_webhook_state.clear()
        await setup_telegram_webhook()
        await tg_menu.refresh()
    if keys & {"DAILY_REPORT_TIME", "TIMEZONE"}:
        _schedule_daily_report()
    if keys & {"FUNNEL_REMINDER_TIME", "TIMEZONE"}:
        _schedule_funnel_reminders()
    if keys & {"GSHEET_SPREADSHEET_ID", "GSHEET_WORKSHEET"}:
        await funnel_gsheet.reset_target()
    if "IG_ACCESS_TOKEN" in keys:
        try:
            await ensure_identity()
        except Exception as exc:  # noqa: BLE001
            logger.warning("Instagram identity check failed: {}", exc)


async def _startup_tasks() -> None:
    try:
        await runtime_config.reload()
        await bootstrap_admin()
        await funnel_registry.ensure_default()    # the migration creates it; safety net
    except Exception as exc:  # noqa: BLE001
        logger.error("Database not ready at startup: {}", exc)
    knowledge.get_knowledge()
    for step in (ensure_identity, setup_telegram_webhook, tg_menu.refresh):
        try:
            await step()
        except Exception as exc:  # noqa: BLE001
            logger.warning("Startup step {} failed: {}", step.__name__, exc)
    # Down at FUNNEL_REMINDER_TIME? Send today's reminders late (mornings only)
    task = asyncio.create_task(funnel_reminders.catch_up())
    _startup_jobs.add(task)
    task.add_done_callback(_startup_jobs.discard)


@asynccontextmanager
async def lifespan(app: FastAPI):
    global _scheduler
    if (not settings.SECRET_KEY or settings.SECRET_KEY.startswith("change-me")
            or len(settings.SECRET_KEY) < 32):
        raise RuntimeError("SECRET_KEY is weak or unset — set a random 32+ char value in .env")
    await _startup_tasks()
    logger.info("Wunderkind AI Agent started (provider={})", settings.AI_PROVIDER)

    _scheduler = AsyncIOScheduler(timezone=_timezone())
    _schedule_daily_report()
    _scheduler.add_job(refresh_token_if_due, IntervalTrigger(hours=24), id="ig_token_refresh")
    _scheduler.add_job(run_followups, IntervalTrigger(minutes=15), id="followups")
    # Lead-magnet funnel: pending PDFs + sales sequence, Sheets outbox, reminders
    _scheduler.add_job(funnel_sales.run_minutely, IntervalTrigger(minutes=1), id="funnel_sales")
    _scheduler.add_job(funnel_gsheet.sync_dirty, IntervalTrigger(minutes=1),
                       id="funnel_sheet_sync")
    _schedule_funnel_reminders()
    _scheduler.start()
    from app.telegram_business.polling import run_polling

    poller = asyncio.create_task(run_polling())
    yield
    poller.cancel()
    _scheduler.shutdown(wait=False)


app = FastAPI(title="Wunderkind AI Agent", version="1.0.0", lifespan=lifespan)

if settings.CORS_ORIGINS:
    app.add_middleware(
        CORSMiddleware,
        allow_origins=[o.strip() for o in settings.CORS_ORIGINS.split(",") if o.strip()],
        allow_credentials=True, allow_methods=["*"], allow_headers=["*"],
    )

api = APIRouter(prefix="/api")
for module in (auth, users, settings_api, dashboard, leads, bot_menu, playground, funnel,
               funnels):
    api.include_router(module.router)
app.include_router(api)
app.include_router(ig_webhook_router)
app.include_router(tg_webhook_router)
app.include_router(oauth_router)
app.include_router(meta_callbacks_router)
app.include_router(legal_pages_router)
app.include_router(funnel_landing_router)


@app.get("/health")
async def health():
    return {"status": "ok"}
