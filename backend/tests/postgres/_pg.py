"""Helpers for the opt-in PostgreSQL suite (marker `postgres`, needs TEST_POSTGRES_URL).

TEST_POSTGRES_URL points at a disposable server's admin database, e.g.
postgresql+asyncpg://postgres@127.0.0.1:55432/postgres. Every test works in its own throwaway database with the
Supabase stub applied (tests/postgres/supabase_stub.sql) and drops it afterwards. Never point this at Supabase.
"""

from __future__ import annotations

import os
import uuid
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from urllib.parse import urlsplit, urlunsplit

import asyncpg

BACKEND_DIR = Path(__file__).resolve().parents[2]
STUB = Path(__file__).with_name("supabase_stub.sql")
ADMIN_URL = os.environ.get("TEST_POSTGRES_URL", "")


def plain(url: str) -> str:
    """asyncpg DSN from a SQLAlchemy URL."""
    return url.replace("postgresql+asyncpg://", "postgresql://", 1)


def with_database(url: str, name: str) -> str:
    parts = urlsplit(url)
    return urlunsplit(parts._replace(path=f"/{name}"))


async def create_database(prefix: str = "qa") -> tuple[str, str]:
    """Create an empty database with the Supabase stub; return (name, SQLAlchemy URL)."""
    name = f"{prefix}_{uuid.uuid4().hex[:12]}"
    admin = await asyncpg.connect(plain(ADMIN_URL))
    try:
        await admin.execute(f'CREATE DATABASE "{name}"')
    finally:
        await admin.close()
    url = with_database(ADMIN_URL, name)
    connection = await asyncpg.connect(plain(url))
    try:
        await connection.execute(STUB.read_text(encoding="utf-8"))
    finally:
        await connection.close()
    return name, url


async def drop_database(name: str) -> None:
    admin = await asyncpg.connect(plain(ADMIN_URL))
    try:
        await admin.execute(f'DROP DATABASE IF EXISTS "{name}" WITH (FORCE)')
    finally:
        await admin.close()


def alembic(url: str, action: str, revision: str | None) -> None:
    """`alembic upgrade|downgrade <revision>` (or `check`) against url, in a worker thread: env.py uses asyncio.run."""

    def run() -> None:
        from alembic import command
        from alembic.config import Config

        config = Config(str(BACKEND_DIR / "alembic.ini"))
        config.set_main_option("script_location", str(BACKEND_DIR / "migrations").replace("%", "%%"))
        config.set_main_option("sqlalchemy.url", url.replace("%", "%%"))
        config.attributes["configure_logging"] = False
        operation = getattr(command, action)
        operation(config) if revision is None else operation(config, revision)

    with ThreadPoolExecutor(max_workers=1) as pool:
        pool.submit(run).result()


def head_and_previous() -> tuple[str, str]:
    from alembic.config import Config
    from alembic.script import ScriptDirectory

    config = Config(str(BACKEND_DIR / "alembic.ini"))
    config.set_main_option("script_location", str(BACKEND_DIR / "migrations"))
    script = ScriptDirectory.from_config(config)
    head = script.get_current_head()
    assert head is not None
    previous = script.get_revision(head).down_revision
    assert isinstance(previous, str), "expected a linear migration history"
    return head, previous
