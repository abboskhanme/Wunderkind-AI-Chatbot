"""Test setup: SQLite database per test, mock AI, no network."""
from __future__ import annotations

import asyncio
import os

os.environ.setdefault("DATABASE_URL", "sqlite+aiosqlite:///:memory:")
os.environ["AI_PROVIDER"] = "mock"
os.environ["TG_POLLING"] = "false"  # no getUpdates calls from tests
os.environ["SECRET_KEY"] = "test-secret-key-that-is-long-enough-1234567890"
os.environ["PUBLIC_URL"] = ""
os.environ["REDIS_URL"] = ""
os.environ["ADMIN_PASSWORD"] = ""

import pytest
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine
from sqlalchemy.pool import StaticPool

from app.db import session as db_session
from app.db.base import Base
import app.models  # noqa: F401


@pytest.fixture(autouse=True)
def database(monkeypatch):
    engine = create_async_engine("sqlite+aiosqlite:///:memory:",
                                 connect_args={"check_same_thread": False},
                                 poolclass=StaticPool)

    async def _create():
        async with engine.begin() as conn:
            await conn.run_sync(Base.metadata.create_all)

    asyncio.run(_create())
    factory = async_sessionmaker(engine, expire_on_commit=False)
    monkeypatch.setattr(db_session, "SessionLocal", factory)

    async def _default_funnel():
        # Same state as after the migrations: the default funnel exists (SPEC §11.1)
        from app.funnel.funnels import ensure_default, invalidate

        invalidate()                  # the funnel cache belongs to the previous test's DB
        async with factory() as session:
            await ensure_default(session)

    asyncio.run(_default_funnel())
    yield factory
    asyncio.run(engine.dispose())


@pytest.fixture(autouse=True)
def fresh_state(monkeypatch):
    """Isolated in-memory store and default runtime settings per test."""
    from app import runtime_config
    from app.config import settings
    from app.state import store as store_mod

    import app.main as main_mod

    # Reset the shared singleton in place (tests import it by reference)
    store_mod.store.__init__()

    async def _no_startup():
        return None

    monkeypatch.setattr(main_mod, "_startup_tasks", _no_startup)
    for key, value in runtime_config.BASELINE.items():
        monkeypatch.setattr(settings, key, value)
    monkeypatch.setattr(settings, "AI_PROVIDER", "mock")
    yield store_mod.store


@pytest.fixture(autouse=True)
def no_profile_network(monkeypatch):
    """Account profile reads (SPEC §13) run after every update — never over the
    network in tests. Tests that need data patch these again."""
    from app.instagram.client import instagram
    from app.telegram_business.client import telegram

    async def _none(*_args, **_kwargs):
        return None

    monkeypatch.setattr(telegram, "get_chat", _none)
    monkeypatch.setattr(telegram, "get_user_profile_photos", _none)
    monkeypatch.setattr(telegram, "download_file", _none)
    monkeypatch.setattr(instagram, "get_full_profile", _none)


@pytest.fixture
def client(database):
    from fastapi.testclient import TestClient

    from app.db.session import get_db
    from app.main import app

    async def _get_db():
        async with database() as s:
            yield s

    app.dependency_overrides[get_db] = _get_db
    # Skip lifespan (network/scheduler); tests create users themselves
    c = TestClient(app)
    yield c
    app.dependency_overrides.clear()


def make_user(database, username="admin", role="admin", password="secret123"):
    from app.core.security import hash_password
    from app.models.user import User

    async def _mk():
        async with database() as s:
            u = User(username=username, full_name=username.title(),
                     password_hash=hash_password(password), role=role, is_active=True)
            s.add(u)
            await s.commit()
            return u

    return asyncio.run(_mk())


def auth_headers(client, username="admin", password="secret123") -> dict:
    r = client.post("/api/auth/login", json={"username": username, "password": password})
    assert r.status_code == 200, r.text
    return {"Authorization": f"Bearer {r.json()['access_token']}"}
