"""Fixtures shared by the suites; imported by tests/integration/conftest.py and tests/security/conftest.py.

Names carry a `qa_` prefix (or are user labels) so they never shadow the shared fixtures in tests/conftest.py.
"""

import asyncio
import os
import shutil
import uuid
from collections.abc import AsyncIterator, Iterator
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

import asyncpg

import httpx
import pytest

from tests.integration._support import AppHandle, apply_env, auth, base_env, migrate, running_app


# QA_POSTGRES=1 with TEST_POSTGRES_URL runs these suites on a disposable PostgreSQL server instead of SQLite:
# one migrated template database per session, and a fresh copy (CREATE DATABASE ... TEMPLATE) per test.
QA_POSTGRES = os.environ.get("QA_POSTGRES") == "1" and bool(os.environ.get("TEST_POSTGRES_URL"))


def _in_thread(coroutine_factory):  # type: ignore[no-untyped-def]
    with ThreadPoolExecutor(max_workers=1) as pool:
        return pool.submit(lambda: asyncio.run(coroutine_factory())).result()


@pytest.fixture(scope="session")
def qa_db_template(tmp_path_factory: pytest.TempPathFactory) -> Path | str | None:
    """One migrated database per session (alembic upgrade head); each test gets a copy."""
    if QA_POSTGRES:
        from tests.postgres import _pg

        name, url = _in_thread(lambda: _pg.create_database("qa_tpl"))
        try:
            migrate(url)
        except Exception as exc:  # noqa: BLE001
            pytest.fail(f"QA harness: 'alembic upgrade head' failed on Postgres: {exc!r}", pytrace=False)
        yield name
        _in_thread(lambda: _pg.drop_database(name))
        return
    path = tmp_path_factory.mktemp("qa-db") / "template.db"
    try:
        migrate(f"sqlite+aiosqlite:///{path.as_posix()}")
    except Exception as exc:  # noqa: BLE001 - every API test needs the schema; say so once, loudly
        pytest.fail(f"QA harness: 'alembic upgrade head' failed, so the API cannot be tested: {exc!r}", pytrace=False)
    yield path


@pytest.fixture
def qa_env(monkeypatch: pytest.MonkeyPatch, tmp_path: Path, qa_db_template: Path | str | None) -> Iterator[dict[str, str]]:
    """Hermetic settings: APP_ENV=test, AUTH_MODE=dev, a migrated temp database, no provider credentials."""
    env = base_env(tmp_path)
    database = None
    if QA_POSTGRES and isinstance(qa_db_template, str):
        from tests.postgres import _pg

        database = f"qa_{uuid.uuid4().hex[:12]}"

        async def clone() -> None:
            admin = await asyncpg.connect(_pg.plain(_pg.ADMIN_URL))
            try:
                await admin.execute(f'CREATE DATABASE "{database}" TEMPLATE "{qa_db_template}"')
            finally:
                await admin.close()

        _in_thread(clone)
        env["DATABASE_URL"] = _pg.with_database(_pg.ADMIN_URL, database)
    elif isinstance(qa_db_template, Path):
        shutil.copyfile(qa_db_template, tmp_path / "nativeproof-test.db")
    apply_env(monkeypatch, env)
    yield env
    if database is not None:
        from tests.postgres import _pg

        _in_thread(lambda: _pg.drop_database(database))


@pytest.fixture
async def qa_app(qa_env: dict[str, str]) -> AsyncIterator[AppHandle]:
    async with running_app() as handle:
        yield handle


@pytest.fixture
def qa_client(qa_app: AppHandle) -> httpx.AsyncClient:
    return qa_app.client


@pytest.fixture
def qa_fake(monkeypatch: pytest.MonkeyPatch):  # type: ignore[no-untyped-def]
    """the test double for `app.workflows` (knobs: status, raise_in, block). For engine tests that must not depend on F."""
    import sys

    import app as app_package
    from tests.api import fake_workflows

    fake = fake_workflows.install(monkeypatch)
    # install() only replaces sys.modules; once the real package was imported, `import app.workflows as w`
    # resolves the parent's attribute first and would keep running the real workflows.
    monkeypatch.setattr(app_package, "workflows", sys.modules["app.workflows"], raising=False)
    return fake


@pytest.fixture
def alice() -> dict[str, str]:
    return auth("qa-alice")


@pytest.fixture
def bob() -> dict[str, str]:
    return auth("qa-bob")
