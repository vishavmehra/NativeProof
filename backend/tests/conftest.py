"""Shared fixtures: isolated settings, a fresh SQLite database per test, and an ASGI client.

Provider credentials are blanked so no test can reach a paid API, even when backend/.env
holds real keys (environment variables take precedence over the .env file).
"""

import asyncio
from collections.abc import AsyncIterator, Iterator
from typing import Any

import httpx
import pytest
from fastapi import FastAPI

from app.core.config import get_settings
from app.db.base import Base
from app.db.session import dispose_engine, get_engine
from app.main import create_app
from app.schemas.runs import TERMINAL_RUN_STATUSES

BLANKED = (
    "NEBIUS_API_KEY", "NEBIUS_DEFAULT_MODEL", "NEBIUS_FAST_MODEL", "NEBIUS_REASONING_MODEL", "OPENROUTER_API_KEY",
    "OPENROUTER_BASE_URL", "OPENROUTER_DEFAULT_MODEL", "QLOO_API_KEY", "SUPABASE_URL", "SUPABASE_JWT_SECRET",
    "SUPABASE_SECRET_KEY", "EMBEDDING_MODEL", "EMBEDDING_DIMENSIONS", "VISION_MODEL", "RERANK_MODEL", "RERANK_PROVIDER",
)


def pytest_configure(config: pytest.Config) -> None:
    config.addinivalue_line("markers", "postgres: opt-in checks against a real Postgres (NATIVEPROOF_TEST_POSTGRES_URL)")


def auth(label: str) -> dict[str, str]:
    """Headers for a dev-mode user; different labels are different users."""
    return {"Authorization": f"Bearer dev-{label}"}


ALICE, BOB = auth("alice"), auth("bob")


@pytest.fixture
def test_settings(monkeypatch: pytest.MonkeyPatch, tmp_path: Any) -> Iterator[None]:
    monkeypatch.setenv("APP_ENV", "test")
    monkeypatch.setenv("AUTH_MODE", "dev")
    monkeypatch.setenv("LOG_LEVEL", "WARNING")
    monkeypatch.setenv("DATABASE_URL", f"sqlite+aiosqlite:///{(tmp_path / 'test.db').as_posix()}")
    monkeypatch.setenv("ASSET_STORAGE_BACKEND", "database")  # tests never reach the real Storage bucket
    for name in BLANKED:
        monkeypatch.setenv(name, "")
    get_settings.cache_clear()
    yield
    get_settings.cache_clear()


@pytest.fixture
async def app(test_settings: None) -> AsyncIterator[FastAPI]:
    """The application with a migrated-equivalent schema, run through its lifespan like uvicorn does."""
    await dispose_engine()
    async with get_engine().begin() as connection:
        await connection.run_sync(Base.metadata.create_all)
    application = create_app()
    async with application.router.lifespan_context(application):
        yield application
    await dispose_engine()


@pytest.fixture
async def client(app: FastAPI) -> AsyncIterator[httpx.AsyncClient]:
    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://test", headers=ALICE) as c:
        yield c


async def wait_for_run(client: httpx.AsyncClient, run_id: str, timeout: float = 10.0, **kwargs: Any) -> dict[str, Any]:
    """Poll GET /runs/{id} until the run reaches a terminal status."""
    async with asyncio.timeout(timeout):
        while True:
            response = await client.get(f"/api/v1/runs/{run_id}", **kwargs)
            assert response.status_code == 200, response.text
            run = response.json()
            if run["status"] in TERMINAL_RUN_STATUSES:
                return run
            await asyncio.sleep(0.02)
