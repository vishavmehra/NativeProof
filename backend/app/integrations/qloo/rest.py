"""Direct REST transport for Qloo: the contingency when Node and the harness are not available.

Same executor interface and harness-shaped envelopes as `qloo exec`, so normalization, caching, and
evidence are identical. It mirrors the harness's own client (@qloo/qloo-harness 0.1.26,
packages/qloo-client-ts): `X-Api-Key` header, comma-joined list parameters, retries on 429/5xx with a
bounded Retry-After, and a 5 MB response cap. Request and response shapes follow docs.qloo.com
(Insights deep dive, Search Entities, Trending, Demographics) and the harness workflows.
"""

import asyncio
import contextlib
import json
import logging
import time
import uuid
from typing import Any
from urllib.parse import urlsplit

import httpx
from pydantic import SecretStr

from app.integrations.qloo.executor import (
    RESULT_SCHEMA_VERSION,
    Envelope,
    QlooError,
    QlooFailure,
    build_request,
    run_with_retries,
)

log = logging.getLogger(__name__)

DEFAULT_BASE_URL = "https://api.qloo.com"
MAX_RESPONSE_BYTES = 5 * 1024 * 1024
MAX_RETRY_AFTER_SECONDS = 10.0
DOCS = "https://docs.qloo.com/reference/"


def _fail(code: str, message: str, *, retryable: bool = False) -> QlooFailure:
    return QlooFailure(QlooError(code=code, message=message, retryable=retryable))


def normalize_base_url(value: str | None) -> str:
    """HTTPS only (plain HTTP just for a loopback test server); no credentials, query, or fragment."""
    url = (value or DEFAULT_BASE_URL).strip().rstrip("/")
    parts = urlsplit(url)
    loopback = parts.hostname in ("localhost", "127.0.0.1", "::1")
    if parts.scheme != "https" and not (parts.scheme == "http" and loopback):
        raise ValueError("QLOO_BASE_URL must use HTTPS.")
    if not parts.hostname or parts.username or parts.password or parts.query or parts.fragment:
        raise ValueError("QLOO_BASE_URL must be a plain https://host URL.")
    return url


# --- Requests: Nativeproof workflow → (path, query parameters, documentation slug) ---


def _find_tags(r: dict[str, Any]) -> tuple[str, dict[str, Any], str]:
    return "/v2/tags", {"filter.query": r["query"], "feature.semantic_search": "true", "take": r["limit"]}, "get-tags"


def _recommend(r: dict[str, Any]) -> tuple[str, dict[str, Any], str]:
    params: dict[str, Any] = {"filter.type": f"urn:entity:{r['target_type']}", "take": r["limit"],
                              "feature.explainability": "true"}
    if r.get("signals"):
        params["signal.interests.entities"] = ",".join(r["signals"])
    if r.get("signal_tags"):
        params["signal.interests.tags"] = ",".join(r["signal_tags"])
        params["operator.signal.interests.tags"] = "intersection"
    if r.get("include_tags"):
        params["filter.tags"] = ",".join(r["include_tags"])
        params["operator.filter.tags"] = "union"
    if r.get("signal_location"):
        params["signal.location.query"] = r["signal_location"]
    return "/v2/insights", params, "insights-api-deep-dive"


def _search(r: dict[str, Any]) -> tuple[str, dict[str, Any], str]:
    return "/search", {"query": r["query"], "take": r["limit"]}, "get-search"


def _demographics(r: dict[str, Any]) -> tuple[str, dict[str, Any], str]:
    params = {"filter.type": "urn:demographics", "signal.interests.entities": r["entity"], "take": r["limit"]}
    return "/v2/insights", params, "demographics-use-case"


def _trends(r: dict[str, Any]) -> tuple[str, dict[str, Any], str]:
    params = {"filter.type": f"urn:entity:{r['entity_type']}", "signal.interests.entities": r["entity"],
              "filter.start_date": r["start_date"], "filter.end_date": r["end_date"], "take": r["limit"]}
    return "/v2/trending", params, "get-trending"


# --- Responses: compact items like the harness (compactTag, compactEntity, entityCandidate) ---


def _drop_none(item: dict[str, Any]) -> dict[str, Any]:
    return {key: value for key, value in item.items() if value is not None}


def _first(record: dict[str, Any], *keys: str) -> Any:
    return next((record[key] for key in keys if record.get(key) is not None), None)


def _affinity(record: dict[str, Any]) -> Any:
    query = record.get("query")
    return record.get("affinity") if record.get("affinity") is not None else (query or {}).get("affinity") if isinstance(query, dict) else None


def _tag(tag: dict[str, Any]) -> dict[str, Any]:
    return _drop_none({"id": _first(tag, "id", "tag_id"), "name": tag.get("name"), "type": _first(tag, "type", "subtype"),
                       "popularity": tag.get("popularity"), "affinity": _affinity(tag)})


def _entity(entity: dict[str, Any]) -> dict[str, Any]:
    tag_ids = [_first(t, "id", "tag_id") for t in entity.get("tags") or [] if isinstance(t, dict)]
    return _drop_none({"entity_id": _first(entity, "entity_id", "id"), "name": entity.get("name"), "type": entity.get("type"),
                       "subtype": entity.get("subtype"), "popularity": entity.get("popularity"), "affinity": _affinity(entity),
                       # Qloo's own tags for the entity, kept so the service can re-check topical relevance.
                       "tag_ids": [t for t in tag_ids if isinstance(t, str)][:100] if entity.get("tags") is not None else None})


def _candidate(entity: dict[str, Any]) -> dict[str, Any]:
    types = [t for t in entity.get("types") or [] if isinstance(t, str)]
    kind = _first(entity, "subtype", "type") or next((t for t in types if t.startswith("urn:entity:")), None)
    return _drop_none({"id": _first(entity, "entity_id", "id"), "name": entity.get("name"), "type": kind,
                       "popularity": entity.get("popularity")})


def _raw(item: dict[str, Any]) -> dict[str, Any]:
    return item


ENDPOINTS: dict[str, tuple[Any, str | None, Any]] = {
    "find_tags": (_find_tags, "tags", _tag),
    "recommend": (_recommend, "entities", _entity),
    "search_entities": (_search, None, _candidate),
    "audience_demographics": (_demographics, "demographics", _raw),
    "trends": (_trends, "trending", _raw),
}


def _items(body: dict[str, Any], key: str | None) -> list[Any]:
    results = body.get("results")
    if isinstance(results, list):
        return results
    if isinstance(results, dict) and key:
        found = results.get(key)
        return found if isinstance(found, list) else []
    return []


class RestExecutor:
    """Live executor over the Qloo REST API. Same interface as SubprocessExecutor."""

    transport = "rest"

    def __init__(
        self,
        *,
        api_key: SecretStr | None,
        base_url: str | None,
        timeout_seconds: float,
        deadline_seconds: float | None = None,
        backoff_seconds: float = 0.5,
        max_concurrency: int = 4,
        http_client: httpx.AsyncClient | None = None,
    ) -> None:
        self._api_key = api_key.get_secret_value().strip() if api_key else ""
        self.base_url = normalize_base_url(base_url)
        self.timeout_seconds = timeout_seconds
        self.deadline_seconds = deadline_seconds if deadline_seconds is not None else 2 * timeout_seconds
        self.backoff_seconds = backoff_seconds
        self._client = http_client
        self._slots = asyncio.Semaphore(max_concurrency)

    def is_configured(self) -> bool:
        return bool(self._api_key)

    async def run(self, workflow: str, request: dict[str, Any]) -> Envelope:
        payload = build_request(workflow, request)
        if not self.is_configured():
            raise _fail("QLOO_NOT_CONFIGURED", "Live Qloo access is not configured: QLOO_API_KEY is missing.")
        build, key, compact = ENDPOINTS[workflow]
        path, params, docs = build(payload)
        started = time.monotonic()
        body = await run_with_retries(
            f"GET {path}", lambda timeout: self._get(path, params, timeout), timeout_seconds=self.timeout_seconds,
            deadline_seconds=self.deadline_seconds, backoff_seconds=self.backoff_seconds,
        )
        items = [compact(item) for item in _items(body, key)[: payload["limit"]] if isinstance(item, dict)]
        duration_ms = round((time.monotonic() - started) * 1000)
        log.info("qloo rest %s: results=%d duration_ms=%d", path, len(items), duration_ms)
        return Envelope.model_validate({
            "schema_version": RESULT_SCHEMA_VERSION, "operation": workflow, "status": "ok", "results": items,
            "result_count": len(items),
            "execution": {"transport": "rest", "transport_name": "Qloo REST API (direct)",
                          "correlation_id": f"rest-{uuid.uuid4()}", "duration_ms": duration_ms},
            "provenance": {"source": "Qloo API", "endpoint": path, "documentation": f"{DOCS}{docs}",
                           "requests": [{"method": "GET", "path": path, "query": params}]},
        })

    async def _get(self, path: str, params: dict[str, Any], timeout: float) -> dict[str, Any]:
        headers = {"X-Api-Key": self._api_key, "Accept": "application/json"}
        try:
            async with self._slots:
                if self._client is not None:
                    status, retry_after, data = await self._fetch(self._client, path, params, headers, timeout)
                else:
                    async with httpx.AsyncClient() as client:
                        status, retry_after, data = await self._fetch(client, path, params, headers, timeout)
        except httpx.TimeoutException:
            raise _fail("QLOO_TIMEOUT", f"Qloo did not respond within {timeout:g} seconds.", retryable=True) from None
        except httpx.TransportError:
            raise _fail("QLOO_CONNECT", "Qloo could not be reached.", retryable=True) from None
        try:
            body = json.loads(data) if data else {}
        except ValueError:
            body = None
        if status == 200:
            if not isinstance(body, dict):
                raise _fail("QLOO_INVALID_RESPONSE", "Qloo returned a response that is not a JSON object.")
            return body
        message = ""
        if isinstance(body, dict):
            message = str(next((body[k] for k in ("message", "reason", "error") if isinstance(body.get(k), str)), ""))
        if status in (401, 403):
            raise _fail("QLOO_AUTH", "Qloo rejected the request: the API credential is missing or invalid.")
        if status == 429:
            if retry_after:
                await asyncio.sleep(min(retry_after, MAX_RETRY_AFTER_SECONDS))
            raise _fail("QLOO_RATE_LIMIT", "Qloo's rate limit was reached.", retryable=True)
        if status == 404 and path == "/search":
            return {"results": []}  # documented: Search Entities answers 404 when nothing matches
        if status == 400 and "localit" in message.lower():
            raise _fail("QLOO_LOCALITY_NOT_FOUND", "Qloo found no locality matching the requested location.")
        if status >= 500:
            raise _fail("QLOO_UPSTREAM", f"Qloo returned a server error (HTTP {status}).", retryable=True)
        raise _fail("QLOO_CONTRACT", f"Qloo rejected the request (HTTP {status}).")

    async def _fetch(self, client: httpx.AsyncClient, path: str, params: dict[str, Any], headers: dict[str, str],
                     timeout: float) -> tuple[int, float | None, bytes]:
        async with client.stream("GET", f"{self.base_url}{path}", params=params, headers=headers,
                                 timeout=timeout) as response:
            data = bytearray()
            async for chunk in response.aiter_bytes():
                data += chunk
                if len(data) > MAX_RESPONSE_BYTES:
                    raise _fail("QLOO_INVALID_RESPONSE", "The Qloo response exceeded the size limit.")
            retry_after = None
            with contextlib.suppress(ValueError):
                retry_after = float(response.headers.get("retry-after", ""))
            return response.status_code, retry_after, bytes(data)
