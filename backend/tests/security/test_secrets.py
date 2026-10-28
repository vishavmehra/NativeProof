"""No configured secret reaches an API response, an error body, or a log line (NFR-001/006).

Dummy secrets are injected through the environment. The real backend/.env values are also loaded
into memory and scanned for, in case any code path reads .env directly. Failure messages name the
variable and the location only; secret values are never printed.
"""

import logging
import sys
import traceback
from collections.abc import Iterator
from pathlib import Path

import httpx
import pytest
import respx
from dotenv import dotenv_values

from tests.integration._support import API, FakeProvider, auth, running_app, start_run, wait_for_run
from tests.integration.journey import (
    JAPAN,
    RESOLVABLE_TERMS,
    STUDY_REQUEST,
    create_live_campaign,
    create_live_project,
    full_journey,
)

DUMMY_SECRETS = {
    "NEBIUS_API_KEY": "sk-qa-DUMMY-nebius-7f3a9c1e5b2d4f60",
    "OPENROUTER_API_KEY": "sk-or-qa-DUMMY-2b8d4f6a0c1e3a59",
    "QLOO_API_KEY": "qloo-qa-DUMMY-9e1c3a5b7d0f2468",
    "SUPABASE_JWT_SECRET": "jwt-qa-DUMMY-secret-4c6e8a0b2d1f3e57",
}
SECRET_NAMES = tuple(DUMMY_SECRETS)
PROVIDER_ECHO = "qa simulated provider detail"
_STANDARD_RECORD_ATTRS = set(vars(logging.LogRecord("", 0, "", 0, "", None, None))) | {"message", "asctime", "taskName"}


def real_env_secrets() -> dict[str, str]:
    env_file = Path(__file__).resolve().parents[2] / ".env"
    if not env_file.exists():
        return {}
    values = dotenv_values(env_file)
    return {f"real .env {name}": value for name in SECRET_NAMES if (value := values.get(name)) and len(value) >= 8}


def all_secrets() -> dict[str, str]:
    return {**DUMMY_SECRETS, **real_env_secrets()}


def scan(text: str, where: str, secrets: dict[str, str]) -> None:
    for name, value in secrets.items():
        if value in text:
            pytest.fail(f"{name} value leaked in {where}", pytrace=False)


def record_texts(records: list[logging.LogRecord]) -> Iterator[tuple[str, str]]:
    for record in records:
        yield f"log record {record.name}:{record.levelname}", record.getMessage()
        if record.exc_info:
            yield f"log traceback {record.name}", "".join(traceback.format_exception(*record.exc_info))
        if record.exc_text:
            yield f"log exc_text {record.name}", record.exc_text
        extras = {k: v for k, v in vars(record).items() if k not in _STANDARD_RECORD_ATTRS}
        if extras:
            yield f"log extras {record.name}", repr(extras)


class Recorder:
    """httpx response hook that keeps every status line, header block, and body seen by the client."""

    def __init__(self) -> None:
        self.seen: list[tuple[str, str]] = []

    async def __call__(self, response: httpx.Response) -> None:
        await response.aread()
        where = f"{response.request.method} {response.request.url.path} -> {response.status_code}"
        self.seen.append((f"{where} headers", "\n".join(f"{k}: {v}" for k, v in response.headers.items())))
        self.seen.append((f"{where} body", response.text))

    def scan(self, secrets: dict[str, str]) -> None:
        assert self.seen, "no responses were recorded"
        for where, text in self.seen:
            scan(text, where, secrets)


def qloo_marker(tmp_path: Path) -> Path:
    return tmp_path / "qloo-invoked.marker"


def fake_qloo(tmp_path: Path) -> Path:
    """Fails and prints the key it was given, like a careless harness error; leaves a marker when invoked."""
    key, marker = DUMMY_SECRETS["QLOO_API_KEY"], qloo_marker(tmp_path)
    if sys.platform == "win32":
        path = tmp_path / "fake_qloo.cmd"
        script = f'@echo off\r\necho invoked> "{marker}"\r\necho auth failed for key {key} 1>&2\r\nexit /b 1\r\n'
    else:
        path = tmp_path / "fake_qloo"
        script = f"#!/bin/sh\necho invoked > '{marker}'\necho 'auth failed for key {key}' >&2\nexit 1\n"
    path.write_text(script, encoding="utf-8")
    if sys.platform != "win32":
        path.chmod(0o755)
    return path


@pytest.fixture
def dummy_secrets(qa_env: dict[str, str], monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> dict[str, str]:
    for name, value in DUMMY_SECRETS.items():
        monkeypatch.setenv(name, value)
    for name in ("NEBIUS_DEFAULT_MODEL", "NEBIUS_FAST_MODEL", "NEBIUS_REASONING_MODEL"):
        monkeypatch.setenv(name, "qa-test-model")
    monkeypatch.setenv("QLOO_BIN", str(fake_qloo(tmp_path)))
    return all_secrets()


ECHO = f"Incorrect API key provided: {DUMMY_SECRETS['NEBIUS_API_KEY']} ({PROVIDER_ECHO})"


async def test_no_secret_in_basic_and_error_responses(
    dummy_secrets: dict[str, str], caplog: pytest.LogCaptureFixture, capsys: pytest.CaptureFixture[str]
) -> None:
    caplog.set_level(logging.DEBUG)
    recorder = Recorder()
    async with running_app() as app:
        app.client.event_hooks["response"].append(recorder)
        await app.client.get("/health")
        await app.client.get("/ready")
        await app.client.get(f"{API}/projects")  # 401
        await app.client.get(f"{API}/projects", headers={"Authorization": f"Bearer {DUMMY_SECRETS['SUPABASE_JWT_SECRET']}"})
        await app.client.get(f"{API}/projects/not-a-uuid", headers=auth("qa-sec"))  # 422
        await app.client.post(f"{API}/projects", json={"name": "x"}, headers=auth("qa-sec"))  # 422
        await app.client.get(f"{API}/does-not-exist", headers=auth("qa-sec"))  # 404
    recorder.scan(dummy_secrets)
    for where, text in record_texts(caplog.records):
        scan(text, where, dummy_secrets)
    captured = capsys.readouterr()
    scan(captured.out + captured.err, "emitted log output", dummy_secrets)


async def test_no_secret_or_provider_detail_in_failed_live_runs(
    dummy_secrets: dict[str, str],
    caplog: pytest.LogCaptureFixture,
    capsys: pytest.CaptureFixture[str],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Providers that echo credentials or internal details must not reach clients (README §3)."""
    caplog.set_level(logging.DEBUG)
    recorder = Recorder()
    alice = auth("qa-sec")
    with FakeProvider(401, {"error": {"message": ECHO}}) as provider:  # Nebius answers 401 and echoes the key
        monkeypatch.setenv("NEBIUS_BASE_URL", provider.base_url)
        async with running_app() as app:
            app.client.event_hooks["response"].append(recorder)
            project = await create_live_project(app.client, alice)
            campaign = await create_live_campaign(app.client, alice, project.id)
            discovery = await start_run(
                app.client,
                alice,
                f"{API}/projects/{project.id}/discoveries",
                {"product_category": "apparel", "market": JAPAN, "research_question": "What matters here?"},
                "market_discovery",
            )
            study = await app.client.post(
                f"{API}/projects/{project.id}/studies", json={**STUDY_REQUEST, "campaign_id": str(campaign.id)}, headers=alice
            )
            rehearsal = await start_run(
                app.client, alice, f"{API}/studies/{study.json()['id']}/rehearsals", {}, "campaign_rehearsal"
            )
            for accepted in (discovery, rehearsal):
                run = await wait_for_run(app.client, accepted.run_id, alice)
                assert run.status == "failed", f"{run.run_type} ended {run.status}"
                assert run.error is not None and run.error.code != "INTERNAL_ERROR", "failure must come from the provider path"
                assert PROVIDER_ECHO not in (run.error.message if run.error else ""), "raw provider detail in Run.error"
            await app.client.get(f"{API}/projects/{project.id}/runs", headers=alice)
            await app.client.get(f"{API}/projects/{project.id}/evidence", headers=alice)
    recorder.scan(dummy_secrets)
    for where, text in recorder.seen:
        if PROVIDER_ECHO in text:
            pytest.fail(f"raw provider error text reached a client in {where}", pytrace=False)
    captured = capsys.readouterr()
    scan(captured.out + captured.err, "emitted log output", dummy_secrets)


async def test_no_secret_in_demo_journey_responses_or_logs(
    dummy_secrets: dict[str, str],
    caplog: pytest.LogCaptureFixture,
    capsys: pytest.CaptureFixture[str],
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Normal flows never even put a secret into a log record (stricter than formatter redaction).

    Live credentials are configured on purpose: a demo project must still never call Qloo or an LLM (README §5).
    """
    caplog.set_level(logging.DEBUG)
    recorder = Recorder()
    with FakeProvider(500, {"error": {"message": "demo must not call out"}}) as provider, respx.mock(assert_all_called=False) as network:
        monkeypatch.setenv("NEBIUS_BASE_URL", provider.base_url)
        network.route().mock(side_effect=httpx.ConnectError("qa: demo runs must not call out"))
        async with running_app() as app:
            app.client.event_hooks["response"].append(recorder)
            journey = await full_journey(app.client, auth("qa-sec"), check=False, terms=RESOLVABLE_TERMS)
            await app.client.get(f"{API}/reports/{journey.report.id}/export", params={"format": "markdown"}, headers=journey.headers)  # type: ignore[union-attr]
        assert not network.calls, f"demo journey made {len(network.calls)} outbound HTTP call(s); demo must never call out"
        assert not provider.requests, f"demo journey called the LLM provider: {provider.requests}"
    assert not qloo_marker(tmp_path).exists(), "a demo run invoked the qloo CLI; demo must use the fixture adapter"
    recorder.scan(dummy_secrets)
    for where, text in record_texts(caplog.records):
        scan(text, where, dummy_secrets)
    captured = capsys.readouterr()
    scan(captured.out + captured.err, "emitted log output", dummy_secrets)
