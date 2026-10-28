"""Bounded, allowlisted execution of `qloo exec` (D-024).

Runs `qloo exec <workflow> --input-file request.json` from the pinned @qloo/qloo-harness
(backend/qloo). Verified against harness 0.1.26 on 2026-10-25, from its source and from
runs without a credential:

- exit 0 prints one result envelope (schema "1.0-preview.1") as a JSON line on stdout;
- a failure prints {"error": {code, layer, retryable, recovery}, "operation", "correlation_id"}
  on stdout and exits 1 (execution), 2 (input), 4 (missing credential), or 130 (cancelled);
- usage errors print only to stderr and exit 2.

The credential reaches the child only through its environment, never through arguments,
logs, or errors.
"""

import asyncio
import contextlib
import json
import logging
import os
import random
import re
import shutil
import tempfile
import time
import unicodedata
from pathlib import Path
from typing import Annotated, Any, Literal

from pydantic import BaseModel, ConfigDict, Field, SecretStr, ValidationError

log = logging.getLogger(__name__)

RESULT_SCHEMA_VERSION = "1.0-preview.1"
LOCAL_HARNESS_BIN = (
    Path(__file__).resolve().parents[3] / "qloo" / "node_modules" / "@qloo" / "qloo-harness" / "dist" / "bin.js"
)
MAX_STDOUT_BYTES = 2 * 1024 * 1024
MAX_STDERR_BYTES = 16 * 1024
MAX_ATTEMPTS = 3  # one try plus at most two retries
MIN_RETRY_BUDGET_SECONDS = 1.0
# PATH and the OS basics Node needs. Nothing else from the backend environment is passed
# (no database URL, no model-provider keys).
_INHERITED_ENV = ("PATH", "SYSTEMROOT", "TEMP", "TMP", "HOME", "USERPROFILE")
_ERROR_CODE = re.compile(r"^[A-Z][A-Z0-9_]{0,63}$")
_EMAIL = re.compile(r"[^\s@]+@[^\s@]+\.[^\s@]+")
_PHONE = re.compile(r"\+?\d[\d\s().-]{5,}\d")
_HARNESS_MESSAGES = {
    "QLOO_AUTH": "Qloo rejected the request: the API credential is missing or invalid.",
    "QLOO_RATE_LIMIT": "Qloo's rate limit was reached.",
    "QLOO_TIMEOUT": "The Qloo request timed out.",
    "QLOO_UPSTREAM": "Qloo returned a server error.",
    "QLOO_CONTRACT": "Qloo rejected the request or returned an unexpected response.",
    "QLOO_DNS": "Qloo could not be reached (DNS).",
    "QLOO_CONNECT": "Qloo could not be reached (connection).",
    "QLOO_TLS": "Qloo could not be reached (TLS).",
    "TOOL_INPUT": "The Qloo harness rejected the workflow input.",
    "CANCELLED": "The Qloo request was cancelled.",
}


class QlooError(BaseModel):
    """A safe, presentable failure. Never contains credentials or raw provider output."""

    code: str
    message: str
    retryable: bool


class QlooFailure(Exception):
    def __init__(self, error: QlooError) -> None:
        super().__init__(f"{error.code}: {error.message}")
        self.error = error


def _fail(code: str, message: str, *, retryable: bool = False) -> QlooFailure:
    return QlooFailure(QlooError(code=code, message=message, retryable=retryable))


# --- Verified workflow inputs (subset of the harness schemas Nativeproof sends) ---

InsightsType = Literal["artist", "book", "brand", "movie", "person", "place", "podcast", "tv_show", "videogame"]
_Signal = Annotated[str, Field(min_length=1)]


class _WorkflowInput(BaseModel):
    model_config = ConfigDict(extra="forbid")


class FindTagsInput(_WorkflowInput):
    query: str = Field(min_length=1, max_length=100)
    limit: int = Field(default=10, ge=1, le=20)


class RecommendInput(_WorkflowInput):
    target_type: InsightsType
    signals: list[_Signal] | None = Field(default=None, min_length=1, max_length=10)
    signal_tags: list[_Signal] | None = Field(default=None, min_length=1, max_length=10)
    include_tags: list[_Signal] | None = Field(default=None, min_length=1, max_length=10)  # filter.tags
    signal_location: str | None = Field(default=None, min_length=1, max_length=100)
    limit: int = Field(default=10, ge=1, le=20)


class SearchEntitiesInput(_WorkflowInput):
    """Lookup by name (GET /search). Candidates are ranked; the service decides whether one matches."""

    query: str = Field(min_length=1, max_length=100)
    limit: int = Field(default=5, ge=1, le=10)


class DemographicsInput(_WorkflowInput):
    """Aggregate demographic affinity for one entity (GET /v2/insights, filter.type=urn:demographics)."""

    entity: str = Field(min_length=1, max_length=100)  # a Qloo entity id
    limit: int = Field(default=10, ge=1, le=20)


class TrendsInput(_WorkflowInput):
    """Popularity time series for one entity (GET /v2/trending)."""

    entity: str = Field(min_length=1, max_length=100)  # a Qloo entity id
    entity_type: InsightsType
    start_date: str = Field(pattern=r"^\d{4}-\d{2}-\d{2}$")
    end_date: str = Field(pattern=r"^\d{4}-\d{2}-\d{2}$")
    limit: int = Field(default=20, ge=1, le=20)


# The allowlist: only these verified workflows ever run. Names never come from user input.
WORKFLOWS: dict[str, type[_WorkflowInput]] = {
    "find_tags": FindTagsInput,
    "recommend": RecommendInput,
    "search_entities": SearchEntitiesInput,
    "audience_demographics": DemographicsInput,
    "trends": TrendsInput,
}


def build_request(workflow: str, fields: dict[str, Any]) -> dict[str, Any]:
    """Validate a workflow request and return its canonical JSON form."""
    model = WORKFLOWS.get(workflow)
    if model is None:
        raise _fail("QLOO_WORKFLOW_UNAVAILABLE", "This Qloo workflow is not enabled in Nativeproof.")
    try:
        return model.model_validate(fields).model_dump(exclude_none=True)
    except ValidationError as exc:
        raise _fail("QLOO_INVALID_REQUEST", "The Qloo request failed validation.") from exc


def validate_query(value: str) -> str:
    """Normalize a search term and refuse obvious personal data before anything reaches Qloo."""
    text = " ".join(unicodedata.normalize("NFKC", value).split())
    if not 1 <= len(text) <= 100:
        raise _fail("QLOO_INVALID_REQUEST", "Search terms must be 1-100 characters.")
    if any(unicodedata.category(char) == "Cc" for char in text):
        raise _fail("QLOO_INVALID_REQUEST", "Search terms cannot contain control characters.")
    phone_like = any(sum(char.isdigit() for char in match.group()) >= 9 for match in _PHONE.finditer(text))
    if _EMAIL.search(text) or phone_like:
        raise _fail(
            "QLOO_INVALID_REQUEST",
            "Search terms that look like an email address or phone number are never sent to Qloo.",
        )
    return text


# --- Result envelope (harness result schema 1.0-preview.1) ---


class HarnessError(BaseModel):
    code: str
    layer: str | None = None
    retryable: bool = False
    recovery: str | None = None


class Envelope(BaseModel):
    model_config = ConfigDict(extra="allow")

    schema_version: Literal["1.0-preview.1"]
    operation: str
    status: Literal["ok", "empty", "needs_input", "partial", "degraded", "error"]
    summary: str | None = None
    results: list[Any] = Field(default_factory=list)
    result_count: int | None = Field(default=None, ge=0)
    warnings: list[str] = Field(default_factory=list)
    resolution: dict[str, Any] | None = None
    error: HarnessError | None = None
    execution: dict[str, Any]


def _candidate(item: dict[str, Any]) -> dict[str, Any]:
    return {key: item[key] for key in ("id", "name", "type", "popularity") if item.get(key) is not None}


def _describe_candidates(envelope: Envelope) -> Envelope:
    """`describe` (harness entity resolution) → ranked candidates, so the service applies its own match rule."""
    resolution = envelope.resolution or {}
    if envelope.status == "needs_input":
        found = [c for issue in resolution.get("issues") or [] for c in issue.get("candidates") or []]
    else:
        found = [
            candidate
            for outcome in resolution.get("outcomes") or []
            for candidate in [outcome.get("selected"), *(outcome.get("alternatives") or [])]
            if isinstance(candidate, dict)
        ]
    results = [_candidate(c) for c in found if isinstance(c, dict) and c.get("id") and c.get("name")]
    return envelope.model_copy(update={"status": "ok", "results": results, "result_count": len(results)})


def _trend_points(envelope: Envelope) -> Envelope:
    series = (envelope.model_extra or {}).get("series") or []
    points = series[0].get("points", []) if series and isinstance(series[0], dict) else []
    return envelope.model_copy(update={"results": points, "result_count": len(points)})


def _same(envelope: Envelope) -> Envelope:
    return envelope


# Nativeproof workflow → (harness `qloo exec` workflow, input adapter, output adapter). Verified against tools.json.
HARNESS_EXEC: dict[str, tuple[str, Any, Any]] = {
    "find_tags": ("find_tags", dict, _same),
    "recommend": ("recommend", dict, _same),
    "search_entities": ("describe", lambda r: {"entity": r["query"]}, _describe_candidates),
    "audience_demographics": ("audience_demographics", dict, _same),
    "trends": (
        "trends",
        lambda r: {"entities": [r["entity"]], "entity_type": r["entity_type"], "start_date": r["start_date"],
                   "end_date": r["end_date"], "limit": r["limit"]},
        _trend_points,
    ),
}


async def run_with_retries(
    label: str, attempt: Any, *, timeout_seconds: float, deadline_seconds: float, backoff_seconds: float
) -> Any:
    """Call `attempt(timeout)` with at most two retries, only for retryable failures, inside one deadline."""
    deadline = time.monotonic() + deadline_seconds
    number = 1
    while True:
        try:
            return await attempt(max(0.1, min(timeout_seconds, deadline - time.monotonic())))
        except QlooFailure as failure:
            log.warning("qloo %s failed: code=%s retryable=%s attempt=%d", label, failure.error.code,
                        failure.error.retryable, number)
            delay = backoff_seconds * 2 ** (number - 1) * random.uniform(0.5, 1.0)
            if not failure.error.retryable or number >= MAX_ATTEMPTS or deadline - time.monotonic() - delay < MIN_RETRY_BUDGET_SECONDS:
                raise
            await asyncio.sleep(delay)
            number += 1


def _harness_error(error: HarnessError | None) -> QlooError:
    if error is None or not _ERROR_CODE.match(error.code):
        return QlooError(code="QLOO_EXECUTION_FAILED", message="The Qloo harness reported an error.", retryable=False)
    message = _HARNESS_MESSAGES.get(error.code, f"The Qloo harness reported {error.code}.")
    if error.recovery:
        message = f"{message} {error.recovery[:300]}"
    return QlooError(code=error.code, message=message, retryable=error.retryable)


def resolve_qloo_command(qloo_bin: str) -> list[str] | None:
    """QLOO_BIN when it names a file, else the pinned local harness, else `qloo` on PATH."""
    configured = Path(qloo_bin)
    if configured.is_file():
        # a Windows .cmd shim here runs under cmd.exe, so a timeout kill can orphan node.
        return [str(configured.resolve())]
    node = shutil.which("node")
    if node and LOCAL_HARNESS_BIN.is_file():
        # node + bin.js rather than the .bin/qloo(.cmd) shim: on Windows the shim goes through
        # cmd.exe, which re-parses arguments and leaves node running when a timeout kills it.
        return [node, str(LOCAL_HARNESS_BIN)]
    found = shutil.which(qloo_bin)
    return [found] if found else None


class _OutputTooLarge(Exception):
    pass


async def _read(stream: asyncio.StreamReader, limit: int, *, truncate: bool) -> bytes:
    data = bytearray()
    while chunk := await stream.read(65536):
        if len(data) + len(chunk) > limit:
            if not truncate:
                raise _OutputTooLarge
            data += chunk[: limit - len(data)]  # keep the head, keep draining
        else:
            data += chunk
    return bytes(data)


async def _communicate(proc: asyncio.subprocess.Process) -> tuple[bytes, bytes]:
    assert proc.stdout is not None and proc.stderr is not None
    stderr_task = asyncio.ensure_future(_read(proc.stderr, MAX_STDERR_BYTES, truncate=True))
    try:
        stdout = await _read(proc.stdout, MAX_STDOUT_BYTES, truncate=False)
        await proc.wait()
        return stdout, await stderr_task
    finally:
        stderr_task.cancel()


async def _reap(proc: asyncio.subprocess.Process) -> None:
    if proc.returncode is None:
        with contextlib.suppress(ProcessLookupError):
            proc.kill()
    # Drain to EOF so the pipe transports close; bounded in case a grandchild still holds the pipes.
    with contextlib.suppress(TimeoutError):
        await asyncio.wait_for(proc.communicate(), 5)


def _last_json_object(text: str) -> dict[str, Any] | None:
    lines = text.splitlines()
    if not lines:
        return None
    try:
        value = json.loads(lines[-1])
    except ValueError:
        return None
    return value if isinstance(value, dict) else None


class SubprocessExecutor:
    """Live executor: one bounded `qloo exec` process per attempt, in an isolated temp directory."""

    def __init__(
        self,
        *,
        api_key: SecretStr | None,
        command: list[str] | None,
        timeout_seconds: float,
        deadline_seconds: float | None = None,
        backoff_seconds: float = 0.5,
        max_concurrency: int = 4,
        base_url: str | None = None,
    ) -> None:
        self._api_key = api_key.get_secret_value().strip() if api_key else ""
        self.command = command
        self.timeout_seconds = timeout_seconds
        self.deadline_seconds = deadline_seconds if deadline_seconds is not None else 2 * timeout_seconds
        self.backoff_seconds = backoff_seconds
        self.base_url = base_url  # None: the harness's official default, https://api.qloo.com
        self._slots = asyncio.Semaphore(max_concurrency)
        self.transport = "harness"

    def is_configured(self) -> bool:
        return bool(self._api_key and self.command)

    async def run(self, workflow: str, request: dict[str, Any]) -> Envelope:
        payload = build_request(workflow, request)
        if not self.is_configured():
            raise _fail(
                "QLOO_NOT_CONFIGURED",
                "Live Qloo access is not configured: QLOO_API_KEY or the Qloo harness is missing.",
            )
        exec_name, to_exec, from_exec = HARNESS_EXEC[workflow]
        envelope = await run_with_retries(
            f"exec {exec_name}", lambda timeout: self._attempt(exec_name, to_exec(payload), timeout),
            timeout_seconds=self.timeout_seconds, deadline_seconds=self.deadline_seconds,
            backoff_seconds=self.backoff_seconds,
        )
        return from_exec(envelope).model_copy(update={"operation": workflow})

    async def _attempt(self, workflow: str, payload: dict[str, Any], timeout: float) -> Envelope:
        assert self.command is not None
        started = time.monotonic()
        async with self._slots:
            with tempfile.TemporaryDirectory(prefix="nativeproof-qloo-", ignore_cleanup_errors=True) as work:
                request_file = Path(work, "request.json")
                request_file.write_text(json.dumps(payload), encoding="utf-8")
                try:
                    proc = await asyncio.create_subprocess_exec(
                        *self.command,
                        "exec",
                        workflow,
                        "--input-file",
                        str(request_file),
                        cwd=work,
                        env=self._env(Path(work, "home")),
                        stdin=asyncio.subprocess.DEVNULL,
                        stdout=asyncio.subprocess.PIPE,
                        stderr=asyncio.subprocess.PIPE,
                    )
                except OSError as exc:
                    raise _fail("QLOO_EXECUTION_FAILED", "The Qloo harness could not be started.") from exc
                try:
                    stdout, stderr = await asyncio.wait_for(_communicate(proc), timeout)
                except TimeoutError:
                    raise _fail(
                        "QLOO_TIMEOUT", f"Qloo did not respond within {timeout:g} seconds.", retryable=True
                    ) from None
                except _OutputTooLarge:
                    raise _fail("QLOO_INVALID_RESPONSE", "The Qloo harness output exceeded the size limit.") from None
                finally:
                    await _reap(proc)
        return self._parse(workflow, proc.returncode, stdout, stderr, round((time.monotonic() - started) * 1000))

    def _parse(self, workflow: str, returncode: int | None, stdout: bytes, stderr: bytes, elapsed_ms: int) -> Envelope:
        text = stdout.decode("utf-8", errors="replace").strip()
        if stderr:
            log.debug("qloo exec %s stderr: %s", workflow, self._redact(stderr.decode("utf-8", errors="replace")))
        if self._api_key and self._api_key in text:
            raise _fail("QLOO_INVALID_RESPONSE", "The Qloo harness output was rejected because it echoed the credential.")
        data = _last_json_object(text)
        if returncode == 0 and data is not None and "status" in data:
            try:
                envelope = Envelope.model_validate(data)
            except ValidationError:
                raise _fail("QLOO_INVALID_RESPONSE", "The Qloo harness returned an unexpected result format.") from None
            if envelope.operation != workflow:
                raise _fail("QLOO_INVALID_RESPONSE", "The Qloo harness returned a result for a different workflow.")
            if envelope.status == "error":
                raise QlooFailure(_harness_error(envelope.error))
            log.info(
                "qloo exec %s: status=%s results=%d duration_ms=%d",
                workflow,
                envelope.status,
                len(envelope.results),
                elapsed_ms,
            )
            return envelope
        if data is not None and isinstance(data.get("error"), dict):
            try:
                harness_error = HarnessError.model_validate(data["error"])
            except ValidationError:
                harness_error = None
            raise QlooFailure(_harness_error(harness_error))
        if returncode == 0:
            raise _fail("QLOO_INVALID_RESPONSE", "The Qloo harness returned output that is not a result envelope.")
        raise _fail("QLOO_EXECUTION_FAILED", f"The Qloo harness exited with code {returncode}.")

    def _env(self, home: Path) -> dict[str, str]:
        env = {name: os.environ[name] for name in _INHERITED_ENV if name in os.environ}
        # A fresh QLOO_HOME per run: no stored config can change the endpoint or the credential.
        env.update(QLOO_API_KEY=self._api_key, QLOO_HOME=str(home), NO_COLOR="1")
        if self.base_url:
            # The harness sends the key to a non-default host only when it is explicitly trusted.
            env.update(QLOO_BASE_URL=self.base_url, QLOO_TRUSTED_BASE_URL=self.base_url)
        return env

    def _redact(self, text: str) -> str:
        return text.replace(self._api_key, "[REDACTED]") if self._api_key else text
