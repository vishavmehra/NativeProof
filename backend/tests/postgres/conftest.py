"""Opt-in PostgreSQL 17 suite (G): migrations, existing-data safety, and RLS on a disposable local/CI server.

Set TEST_POSTGRES_URL=postgresql+asyncpg://postgres@127.0.0.1:55432/postgres (never a Supabase URL).
"""

from collections.abc import AsyncIterator

import pytest

from tests.postgres._pg import create_database, drop_database


@pytest.fixture
async def fresh_db() -> AsyncIterator[str]:
    """An empty database with the Supabase stub; dropped after the test."""
    name, url = await create_database()
    try:
        yield url
    finally:
        await drop_database(name)
