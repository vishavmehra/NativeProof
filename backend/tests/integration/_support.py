"""QA harness for black-box API tests.

Runs the real ASGI app in-process the way uvicorn would: settings come from environment
variables (backend/.env is never read, so tests are hermetic and no real key is loaded),
the ASGI lifespan protocol runs startup/shutdown, and requests go through
httpx.AsyncClient(transport=ASGITransport(...)).

Import from test modules as `from tests.integration._support import ...` (absolute imports only,
so the module is loaded once).
"""

from __future__ import annotations

import asyncio
import contextlib
import importlib
import json
import logging
import threading
from collections.abc import AsyncIterator, Iterable, Mapping
from concurrent.futures import ThreadPoolExecutor
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from dataclasses import dataclass
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any, TypeVar
from uuid import NAMESPACE_URL, UUID, uuid5

import httpx
import pytest
from pydantic import BaseModel

from app.core.config import Settings, get_settings
from app.schemas.common import ErrorResponse
from app.schemas.runs import Run, RunAccepted

API = "/api/v1"
BACKEND_DIR = Path(__file__).resolve().parents[2]
TERMINAL_STATUSES = frozenset({"completed", "partial", "failed", "cancelled"})
RUN_TIMEOUT_SECONDS = 30.0
POLL_INTERVAL_SECONDS = 0.05

ModelT = TypeVar("ModelT", bound=BaseModel)


# --------------------------------------------------------------------------- markers


def awaiting(owner: str, what: str) -> pytest.MarkDecorator:
    """xfail (non-strict) for behaviour another agent has not delivered yet. Remove when it lands."""
    return pytest.mark.xfail(strict=False, reason=f"awaiting {owner}: {what}")


# --------------------------------------------------------------------------- auth


def auth(label: str = "qa-alice") -> dict[str, str]:
    """Dev-mode bearer header (contracts/README.md §4). Different labels are different users."""
    return {"Authorization": f"Bearer dev-{label}"}


def dev_user_id(label: str) -> UUID:
    return uuid5(NAMESPACE_URL, f"nativeproof-dev:{label}")


# --------------------------------------------------------------------------- environment


def base_env(tmp_path: Path) -> dict[str, str]:
    """Hermetic test settings. Provider hosts use the reserved `.invalid` TLD so nothing can reach the network."""
    database = (tmp_path / "nativeproof-test.db").as_posix()
    return {
        "APP_ENV": "test",
        "AUTH_MODE": "dev",
        "LOG_LEVEL": "INFO",
        "FRONTEND_ORIGINS": "http://localhost:3000",
        "DATABASE_URL": f"sqlite+aiosqlite:///{database}",
        "LLM_PRIMARY_PROVIDER": "nebius",
        "NEBIUS_BASE_URL": "https://nebius.invalid/v1/",
        "OPENROUTER_BASE_URL": "https://openrouter.invalid/api/v1/",
        "LLM_FALLBACK_ENABLED": "false",
        "LLM_REQUEST_TIMEOUT_SECONDS": "5",
        "LLM_MAX_RETRIES": "0",
        "QLOO_BIN": str(tmp_path / "qloo-not-installed"),
        "QLOO_TIMEOUT_SECONDS": "5",
        "MAX_ACTIVE_RUNS_PER_USER": "2",
        "ASSET_STORAGE_DIR": str(tmp_path / "storage"),
    }


def migrate(database_url: str) -> None:
    """`alembic upgrade head` against `database_url`, as the deploy runbook does before starting the app.

    Runs in a worker thread because migrations/env.py calls asyncio.run().
    """

    def upgrade() -> None:
        from alembic import command
        from alembic.config import Config

        config = Config(str(BACKEND_DIR / "alembic.ini"))
        config.set_main_option("script_location", str(BACKEND_DIR / "migrations").replace("%", "%%"))
        config.set_main_option("sqlalchemy.url", database_url.replace("%", "%%"))
        config.attributes["configure_logging"] = False
        command.upgrade(config, "head")

    with ThreadPoolExecutor(max_workers=1) as pool:
        pool.submit(upgrade).result()


# Provider credentials are absent (None) by default because .env is not read.
PROVIDER_SECRET_VARS = ("NEBIUS_API_KEY", "OPENROUTER_API_KEY", "QLOO_API_KEY", "SUPABASE_JWT_SECRET")


def apply_env(monkeypatch: pytest.MonkeyPatch, env: Mapping[str, str]) -> None:
    for name in PROVIDER_SECRET_VARS:
        monkeypatch.delenv(name, raising=False)
    for name, value in env.items():
        monkeypatch.setenv(name, value)
    # Never read backend/.env during tests: it holds a real key, and blank values there would
    # mask "not configured". Runtime override only; no application code changes.
    monkeypatch.setitem(Settings.model_config, "env_file", None)
    get_settings.cache_clear()


# --------------------------------------------------------------------------- fake provider


class FakeProvider:
    """OpenAI-compatible stand-in on 127.0.0.1 answering every request with one canned response.

    The openai SDK does not send through httpx (F: it uses httpx2), so respx cannot intercept it; a local
    server works for any client library. Point NEBIUS_BASE_URL at `base_url`.
    """

    def __init__(self, status: int, body: dict[str, Any]) -> None:
        self.status, self.payload = status, json.dumps(body).encode()
        self.requests: list[str] = []
        self.bodies: list[bytes] = []
        provider = self

        class Handler(BaseHTTPRequestHandler):
            def _answer(self) -> None:
                length = int(self.headers.get("Content-Length") or 0)
                provider.bodies.append(self.rfile.read(length) if length else b"")
                provider.requests.append(f"{self.command} {self.path}")
                self.send_response(provider.status)
                self.send_header("Content-Type", "application/json")
                self.send_header("Content-Length", str(len(provider.payload)))
                self.end_headers()
                self.wfile.write(provider.payload)

            do_GET = do_POST = _answer

            def log_message(self, *args: Any) -> None:  # keep test output quiet
                pass

        self.server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
        self.base_url = f"http://127.0.0.1:{self.server.server_address[1]}/v1/"

    def __enter__(self) -> FakeProvider:
        threading.Thread(target=self.server.serve_forever, daemon=True).start()
        return self

    def __exit__(self, *exc_info: object) -> None:
        self.server.shutdown()
        self.server.server_close()


# --------------------------------------------------------------------------- ASGI lifespan


class LifespanManager:
    """Run the ASGI lifespan protocol like uvicorn: startup on enter, shutdown on exit.

    httpx.ASGITransport does not send lifespan events, so without this the app's startup work
    (DB init, RUN_INTERRUPTED sweep, logging) would never run in tests.
    """

    def __init__(self, app: Any, timeout: float = 30.0) -> None:
        self.app = app
        self.timeout = timeout
        self.state: dict[str, Any] = {}
        self._receive: asyncio.Queue[dict[str, Any]] = asyncio.Queue()
        self._startup = asyncio.get_running_loop().create_future()
        self._shutdown = asyncio.get_running_loop().create_future()
        self._task: asyncio.Task[None] | None = None
        self.supported = True

    async def _send(self, message: dict[str, Any]) -> None:
        kind = message["type"]
        if kind == "lifespan.startup.complete" and not self._startup.done():
            self._startup.set_result(None)
        elif kind == "lifespan.startup.failed" and not self._startup.done():
            self._startup.set_exception(RuntimeError(f"app startup failed: {message.get('message', '')}"))
        elif kind == "lifespan.shutdown.complete" and not self._shutdown.done():
            self._shutdown.set_result(None)
        elif kind == "lifespan.shutdown.failed" and not self._shutdown.done():
            self._shutdown.set_exception(RuntimeError(f"app shutdown failed: {message.get('message', '')}"))

    async def _run(self) -> None:
        scope = {"type": "lifespan", "asgi": {"version": "3.0", "spec_version": "2.0"}, "state": self.state}
        try:
            await self.app(scope, self._receive.get, self._send)
        except BaseException as exc:  # startup raised before replying, or lifespan unsupported
            for future in (self._startup, self._shutdown):
                if not future.done():
                    future.set_exception(exc)
            raise

    async def __aenter__(self) -> LifespanManager:
        self._task = asyncio.create_task(self._run(), name="qa-lifespan")
        await self._receive.put({"type": "lifespan.startup"})
        await asyncio.wait_for(asyncio.shield(self._startup), self.timeout)
        return self

    async def __aexit__(self, *exc_info: object) -> None:
        if self._task is None or self._task.done():
            return
        await self._receive.put({"type": "lifespan.shutdown"})
        try:
            await asyncio.wait_for(asyncio.shield(self._shutdown), self.timeout)
        finally:
            with contextlib.suppress(BaseException):
                await asyncio.wait_for(self._task, self.timeout)


def with_lifespan_state(app: Any, state: dict[str, Any]) -> Any:
    """Copy lifespan state into each request scope, as uvicorn does (`request.state` support)."""

    async def wrapped(scope: dict[str, Any], receive: Any, send: Any) -> None:
        if scope["type"] in ("http", "websocket"):
            scope = {**scope, "state": dict(state)}
        await app(scope, receive, send)

    return wrapped


# --------------------------------------------------------------------------- app handle


@dataclass
class AppHandle:
    app: Any
    client: httpx.AsyncClient
    lifespan: LifespanManager


async def dispose_engine_if_present() -> None:
    """the session module keeps a process-global engine; dispose it so the next app sees a fresh DATABASE_URL."""
    try:
        module = importlib.import_module("app.db.session")
    except ImportError:
        return
    dispose = getattr(module, "dispose_engine", None)
    if dispose is not None:
        await dispose()


@contextlib.asynccontextmanager
async def running_app(*, raise_app_exceptions: bool = True, customize: Any = None) -> AsyncIterator[AppHandle]:
    """Create the app from the current environment, run its lifespan, and yield a client.

    `customize(app)` runs before startup (e.g. to add a test-only route).
    """
    from app.main import create_app

    get_settings.cache_clear()
    await dispose_engine_if_present()
    app = create_app()
    if customize is not None:
        customize(app)
    try:
        async with LifespanManager(app) as lifespan:
            transport = httpx.ASGITransport(
                app=with_lifespan_state(app, lifespan.state), raise_app_exceptions=raise_app_exceptions
            )
            async with httpx.AsyncClient(transport=transport, base_url="http://testserver") as client:
                yield AppHandle(app=app, client=client, lifespan=lifespan)
                await drain_background_tasks()
    finally:
        await dispose_engine_if_present()
        get_settings.cache_clear()
        # The app's JSON log handler is bound to this test's captured stdout; drop it so later tests that
        # log before creating an app do not write to a closed stream ("--- Logging error ---").
        root = logging.getLogger()
        for handler in [h for h in root.handlers if getattr(h, "_nativeproof", False)]:
            root.removeHandler(handler)


async def drain_background_tasks(timeout: float = 2.0) -> None:
    """Give in-process run tasks a moment to finish so the event loop closes cleanly."""
    current = asyncio.current_task()
    pending = [t for t in asyncio.all_tasks() if t is not current and not t.done() and t.get_name() != "qa-lifespan"]
    if pending:
        await asyncio.wait(pending, timeout=timeout)


# --------------------------------------------------------------------------- response helpers


def describe(response: httpx.Response, limit: int = 600) -> str:
    """Short response description for failure messages (tests never load real secrets)."""
    body = response.text
    if len(body) > limit:
        body = body[:limit] + "...<truncated>"
    return f"{response.request.method} {response.request.url.path} -> {response.status_code}: {body}"


def expect_status(response: httpx.Response, status: int) -> None:
    if response.status_code != status:
        pytest.fail(f"expected HTTP {status}, got {describe(response)}", pytrace=False)


def parse(model: type[ModelT], response: httpx.Response, status: int = 200) -> ModelT:
    """Assert the status, validate the body against its contract model, and check timestamps are UTC."""
    expect_status(response, status)
    parsed = model.model_validate_json(response.content)
    assert_utc_datetimes(parsed)
    assert response.headers.get("x-request-id"), f"missing X-Request-ID on {describe(response)}"
    return parsed


def expect_error(response: httpx.Response, status: int, code: str) -> ErrorResponse:
    """Assert a contract error envelope (contracts/README.md §3)."""
    expect_status(response, status)
    try:
        envelope = ErrorResponse.model_validate_json(response.content)
    except Exception as exc:  # noqa: BLE001 - report the contract violation clearly
        pytest.fail(f"error body is not an ErrorResponse envelope ({exc}): {describe(response)}", pytrace=False)
    if envelope.error.code != code:
        pytest.fail(f"expected error code {code}, got {envelope.error.code}: {describe(response)}", pytrace=False)
    assert envelope.error.request_id, f"empty request_id: {describe(response)}"
    header = response.headers.get("x-request-id")
    assert header == envelope.error.request_id, (
        f"X-Request-ID header {header!r} != error.request_id {envelope.error.request_id!r}"
    )
    return envelope


def detail_fields(envelope: ErrorResponse) -> list[str | None]:
    return [detail.field for detail in envelope.error.details]


def assert_utc_datetimes(value: Any, path: str = "$") -> None:
    """Every datetime in a contract response is timezone-aware UTC (contracts/README.md §3)."""
    if isinstance(value, datetime):
        assert value.tzinfo is not None and value.utcoffset() == timedelta(0), f"{path}: timestamp {value} is not UTC"
    elif isinstance(value, BaseModel):
        for name in type(value).model_fields:
            assert_utc_datetimes(getattr(value, name), f"{path}.{name}")
    elif isinstance(value, (list, tuple)):
        for index, item in enumerate(value):
            assert_utc_datetimes(item, f"{path}[{index}]")
    elif isinstance(value, dict):
        for key, item in value.items():
            assert_utc_datetimes(item, f"{path}.{key}")


# --------------------------------------------------------------------------- runs


async def start_run(
    client: httpx.AsyncClient, headers: Mapping[str, str], path: str, body: Mapping[str, Any], run_type: str
) -> RunAccepted:
    accepted = parse(RunAccepted, await client.post(path, json=dict(body), headers=dict(headers)), 202)
    assert accepted.run_type == run_type, f"RunAccepted.run_type {accepted.run_type} != {run_type}"
    assert accepted.status_url == f"{API}/runs/{accepted.run_id}", f"unexpected status_url {accepted.status_url}"
    return accepted


async def wait_for_run(
    client: httpx.AsyncClient, run_id: UUID | str, headers: Mapping[str, str], timeout: float = RUN_TIMEOUT_SECONDS
) -> Run:
    """Poll GET /runs/{id} until a terminal status (contracts/README.md §6)."""
    loop = asyncio.get_running_loop()
    deadline = loop.time() + timeout
    while True:
        run = parse(Run, await client.get(f"{API}/runs/{run_id}", headers=dict(headers)))
        if run.status in TERMINAL_STATUSES:
            return run
        if loop.time() > deadline:
            pytest.fail(f"run {run_id} still {run.status} after {timeout}s (stage {run.progress})", pytrace=False)
        await asyncio.sleep(POLL_INTERVAL_SECONDS)


async def fetch_all(
    client: httpx.AsyncClient, path: str, headers: Mapping[str, str], page_model: type[ModelT], **params: Any
) -> list[Any]:
    """Follow limit/offset pagination to collect every item."""
    items: list[Any] = []
    offset = 0
    while True:
        page = parse(
            page_model, await client.get(path, params={**params, "limit": 100, "offset": offset}, headers=dict(headers))
        )
        items.extend(page.items)  # type: ignore[attr-defined]
        offset += 100
        if offset >= page.total or not page.items:  # type: ignore[attr-defined]
            return items


def ids_of(items: Iterable[Any]) -> list[UUID]:
    return [item.id for item in items]
