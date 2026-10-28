"""Executor tests: real asyncio subprocesses against fake_qloo.py. No Node, no network, no Qloo calls."""

import json
import logging
import os
import shutil
import sys
import time
from pathlib import Path

import pytest
from pydantic import SecretStr

from app.integrations.qloo.executor import (
    LOCAL_HARNESS_BIN,
    Envelope,
    QlooError,
    QlooFailure,
    SubprocessExecutor,
    build_request,
    resolve_qloo_command,
    validate_query,
)

FAKE_QLOO = Path(__file__).with_name("fake_qloo.py")
DUMMY_KEY = "dummy-qloo-key-7f3a9c"
NODE = shutil.which("node")


def make_executor(**overrides: object) -> SubprocessExecutor:
    options: dict[str, object] = {
        "api_key": SecretStr(DUMMY_KEY),
        "command": [sys.executable, str(FAKE_QLOO)],
        "timeout_seconds": 20,
        "backoff_seconds": 0,
    }
    options.update(overrides)
    return SubprocessExecutor(**options)  # type: ignore[arg-type]


async def failure_of(executor: SubprocessExecutor, query: str, workflow: str = "find_tags") -> QlooError:
    with pytest.raises(QlooFailure) as caught:
        await executor.run(workflow, {"query": query, "limit": 5})
    return caught.value.error


async def test_envelope_is_parsed_and_the_child_gets_a_minimal_environment(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("NEBIUS_API_KEY", "not-for-qloo")
    monkeypatch.setenv("DATABASE_URL", "postgresql://not-for-qloo")

    envelope = await make_executor().run("find_tags", {"query": "ok", "limit": 5})

    assert envelope.status == "ok"
    assert envelope.results == [{"id": "urn:tag:keyword:qloo:hiking", "name": "Hiking", "type": "urn:tag:keyword:qloo"}]
    seen = envelope.model_extra or {}
    assert {"QLOO_API_KEY", "QLOO_HOME", "PATH"} <= set(seen["seen_env"])
    assert not {"NEBIUS_API_KEY", "DATABASE_URL"} & set(seen["seen_env"])
    assert seen["argv"][:3] == ["exec", "find_tags", "--input-file"]
    assert DUMMY_KEY not in json.dumps(seen["argv"])
    assert os.path.normcase(seen["qloo_home"]).startswith(os.path.normcase(seen["cwd"]))  # per-run state
    assert not Path(seen["cwd"]).exists()  # isolated working directory removed afterwards


async def test_timeout_kills_the_process() -> None:
    started = time.monotonic()
    error = await failure_of(make_executor(timeout_seconds=0.5, deadline_seconds=0.6), "sleep")
    assert error.code == "QLOO_TIMEOUT"
    assert error.retryable
    assert time.monotonic() - started < 10


async def test_nonzero_exit_without_a_result_is_an_execution_failure() -> None:
    error = await failure_of(make_executor(), "crash")
    assert error.code == "QLOO_EXECUTION_FAILED"
    assert "exited with code 3" in error.message
    assert "boom" not in error.message  # stderr never reaches errors


@pytest.mark.parametrize("behavior", ["badjson", "big", "wrong operation", "old schema"])
async def test_malformed_or_oversized_output_is_an_invalid_response(behavior: str) -> None:
    error = await failure_of(make_executor(), behavior)
    assert error.code == "QLOO_INVALID_RESPONSE"
    assert not error.retryable


async def test_harness_failure_wrapper_keeps_its_code() -> None:
    error = await failure_of(make_executor(), "auth")
    assert (error.code, error.retryable) == ("QLOO_AUTH", False)
    assert "Test recovery text." in error.message


async def test_retryable_harness_errors_are_retried_within_bounds(caplog: pytest.LogCaptureFixture) -> None:
    caplog.set_level(logging.WARNING, logger="app.integrations.qloo")
    for behavior, code in (("ratelimit", "QLOO_RATE_LIMIT"), ("error envelope", "QLOO_UPSTREAM")):
        caplog.clear()
        error = await failure_of(make_executor(), behavior)
        assert (error.code, error.retryable) == (code, True)
        assert "attempt=3" in caplog.text
        assert "attempt=4" not in caplog.text


async def test_only_retryable_failures_are_retried(monkeypatch: pytest.MonkeyPatch) -> None:
    def fake_attempts(executor: SubprocessExecutor, outcomes: list[object]) -> list[float]:
        calls: list[float] = []

        async def attempt(workflow: str, payload: dict, timeout: float) -> object:
            calls.append(timeout)
            outcome = outcomes[min(len(calls), len(outcomes)) - 1]
            if isinstance(outcome, QlooFailure):
                raise outcome
            return outcome

        monkeypatch.setattr(executor, "_attempt", attempt)
        return calls

    transient = QlooFailure(QlooError(code="QLOO_UPSTREAM", message="x", retryable=True))
    permanent = QlooFailure(QlooError(code="QLOO_CONTRACT", message="x", retryable=False))
    ok = Envelope.model_validate({"schema_version": "1.0-preview.1", "operation": "find_tags", "status": "ok",
                                  "results": [], "execution": {"transport": "direct"}})

    executor = make_executor()
    calls = fake_attempts(executor, [transient, transient, ok])
    result = await executor.run("find_tags", {"query": "x"})
    assert (result.status, result.operation) == ("ok", "find_tags")
    assert len(calls) == 3

    executor = make_executor()
    calls = fake_attempts(executor, [permanent, ok])
    with pytest.raises(QlooFailure):
        await executor.run("find_tags", {"query": "x"})
    assert len(calls) == 1

    executor = make_executor()
    calls = fake_attempts(executor, [transient])
    with pytest.raises(QlooFailure):
        await executor.run("find_tags", {"query": "x"})
    assert len(calls) == 3  # one try plus two retries, never more


@pytest.mark.parametrize("workflow", ["rank", "describe", "where_popular", "find_tags; rm -rf /", "../find_tags", ""])
async def test_only_allowlisted_workflows_run(monkeypatch: pytest.MonkeyPatch, workflow: str) -> None:
    executor = make_executor()

    async def must_not_spawn(*args: object) -> None:
        raise AssertionError("a process was started")

    monkeypatch.setattr(executor, "_attempt", must_not_spawn)
    error = await failure_of(executor, "ok", workflow)
    assert error.code == "QLOO_WORKFLOW_UNAVAILABLE"


@pytest.mark.parametrize(
    "fields",
    [{"query": "x", "extra": 1}, {"query": "x", "limit": 50}, {"query": "x", "limit": 0}, {"query": ""}, {}],
)
async def test_invalid_requests_are_rejected_before_spawning(fields: dict) -> None:
    with pytest.raises(QlooFailure) as caught:
        await make_executor(command=["must-not-run"]).run("find_tags", fields)
    assert caught.value.error.code == "QLOO_INVALID_REQUEST"


@pytest.mark.parametrize(
    ("api_key", "command"),
    [(None, ["qloo"]), (SecretStr(""), ["qloo"]), (SecretStr("   "), ["qloo"]), (SecretStr("key"), None)],
)
async def test_unconfigured_executor_never_spawns(api_key: SecretStr | None, command: list[str] | None) -> None:
    executor = SubprocessExecutor(api_key=api_key, command=command, timeout_seconds=1)
    assert not executor.is_configured()
    error = await failure_of(executor, "ok")
    assert error.code == "QLOO_NOT_CONFIGURED"


async def test_the_credential_never_reaches_logs_errors_or_results(caplog: pytest.LogCaptureFixture) -> None:
    caplog.set_level(logging.DEBUG, logger="app.integrations.qloo")
    executor = make_executor()
    for behavior in ("ok", "crash", "auth", "leak"):
        try:
            text = (await executor.run("find_tags", {"query": behavior})).model_dump_json()
        except QlooFailure as failure:
            text = failure.error.model_dump_json()
            if behavior == "leak":
                assert failure.error.code == "QLOO_INVALID_RESPONSE"  # echoed credential is refused
        assert DUMMY_KEY not in text
    assert "[REDACTED]" in caplog.text  # the leaky stderr line was logged, redacted
    assert DUMMY_KEY not in caplog.text


def test_validate_query_normalizes_whitespace_and_width() -> None:
    assert validate_query("  outdoor\t exploration \n") == "outdoor exploration"
    assert validate_query("ｈｉｋｉｎｇ") == "hiking"


@pytest.mark.parametrize("value", ["Tokyo 2020", "jazz 1999-2005", "2026-10-25 launch", "C++ developers", "東京 ハイキング"])
def test_validate_query_accepts_ordinary_terms(value: str) -> None:
    assert validate_query(value) == value


@pytest.mark.parametrize(
    "value",
    [
        "",
        "   ",
        "x" * 101,
        "mail jane.doe@example.com",
        "call +1 (415) 555-0100",
        "ref 4155550100123",
        "bad\x00byte",
    ],
)
def test_validate_query_rejects_empty_long_control_and_personal_data(value: str) -> None:
    with pytest.raises(QlooFailure) as caught:
        validate_query(value)
    assert caught.value.error.code == "QLOO_INVALID_REQUEST"


def test_build_request_returns_the_canonical_request() -> None:
    assert build_request("find_tags", {"query": "hiking"}) == {"query": "hiking", "limit": 10}
    assert build_request("recommend", {"target_type": "brand", "signal_tags": ["urn:tag:x"], "signals": None}) == {
        "target_type": "brand",
        "signal_tags": ["urn:tag:x"],
        "limit": 10,
    }


def test_resolve_command_uses_a_configured_file() -> None:
    assert resolve_qloo_command(str(FAKE_QLOO)) == [str(FAKE_QLOO.resolve())]


def test_resolve_command_ignores_a_directory_named_like_the_binary(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    (tmp_path / "qloo").mkdir()  # backend/qloo is such a directory
    monkeypatch.chdir(tmp_path)
    command = resolve_qloo_command("qloo")
    if NODE and LOCAL_HARNESS_BIN.is_file():
        assert command == [NODE, str(LOCAL_HARNESS_BIN)]
    else:
        assert command is None or Path(command[0]).is_file()


@pytest.mark.skipif(NODE is None or not LOCAL_HARNESS_BIN.is_file(), reason="run `npm ci` in backend/qloo")
async def test_the_real_harness_failure_output_is_parsed(monkeypatch: pytest.MonkeyPatch) -> None:
    """The pinned harness with no credential in its environment answers QLOO_AUTH without
    contacting Qloo (verified in 0.1.26), exercising its real output format and exit code 4."""
    executor = make_executor(command=[NODE, str(LOCAL_HARNESS_BIN)], timeout_seconds=60)
    build_env = executor._env

    def env_without_credential(home: Path) -> dict[str, str]:
        env = build_env(home)
        del env["QLOO_API_KEY"]
        return env

    monkeypatch.setattr(executor, "_env", env_without_credential)
    error = await failure_of(executor, "hiking")
    assert (error.code, error.retryable) == ("QLOO_AUTH", False)
