"""`alembic upgrade head` for a second brand's database (docker-compose.brand2.yml).

On a brand-new, empty database it also deletes the placeholder sales messages
that migration 74ce2ab64d21 seeds: they are written for Wunderkind and would show
up (inactive, but with its name) in the new brand's panel. On an existing database
it is exactly `alembic upgrade head`, so it is safe to run on every start.

Run from the backend directory:  python -m scripts.prepare_db
"""
from __future__ import annotations

import asyncio

from alembic import command
from alembic.config import Config
from loguru import logger
from sqlalchemy import inspect, text
from sqlalchemy.ext.asyncio import create_async_engine

from app.config import settings


async def _is_empty() -> bool:
    engine = create_async_engine(settings.DATABASE_URL)
    try:
        async with engine.connect() as conn:
            tables = await conn.run_sync(lambda c: inspect(c).get_table_names())
    finally:
        await engine.dispose()
    return "alembic_version" not in tables


async def _drop_seeded_sales_messages() -> int:
    engine = create_async_engine(settings.DATABASE_URL)
    try:
        async with engine.begin() as conn:
            # Right after the first upgrade the only rows are the seeded ones
            return (await conn.execute(text("DELETE FROM funnel_messages"))).rowcount
    finally:
        await engine.dispose()


def main() -> None:
    empty = asyncio.run(_is_empty())
    command.upgrade(Config("alembic.ini"), "head")
    if empty:
        removed = asyncio.run(_drop_seeded_sales_messages())
        logger.info("New database: {} placeholder sales message(s) removed", removed)


if __name__ == "__main__":
    main()
