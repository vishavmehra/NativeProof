"""Direct REST transport with a mocked HTTP transport. Response bodies are shaped after docs.qloo.com
examples; they are test data only and never ship as fixtures."""

import json
import logging
from typing import Any

import httpx
import pytest
from pydantic import SecretStr

from app.integrations.qloo.executor import QlooFailure
from app.integrations.qloo.rest import DEFAULT_BASE_URL, RestExecutor, normalize_base_url

KEY = "dummy-rest-key-91c2"
TAGS = {"success": True, "duration": 12, "results": {"tags": [
    {"id": "urn:tag:keyword:qloo:hiking", "name": "Hiking", "type": "urn:tag:keyword:qloo", "popularity": 0.9}]}}
INSIGHTS = {"success": True, "results": {"entities": [
    {"entity_id": "B1A2", "name": "Trail Co", "types": ["urn:entity:brand"], "subtype": "urn:entity:brand",
     "popularity": 0.81, "query": {"affinity": 0.62}, "properties": {"description": "Outdoor gear"}}]}}
SEARCH = {"success": True, "duration": 0.1, "results": [
    {"entity_id": "E1", "name": "Patagonia", "types": ["urn:entity:brand"], "popularity": 0.95},
    {"entity_id": "E2", "name": "Patagonia (region)", "types": ["urn:entity:locality"]}]}
DEMOGRAPHICS = {"success": True, "results": {"demographics": [
    {"entity_id": "B1A2", "query": {"age": {"24_and_younger": -0.08, "25_to_29": 0.21}, "gender": {"female": 0.04}}}]}}
TRENDING = {"success": True, "results": {"trending": [
    {"date": "2026-10-01", "population_percentile": 0.81, "population_rank": 1200, "population_rank_velocity": -15,
     "velocity_fold_change": 1.1, "population_percent_delta": 0.02}]}}


def executor_for(handler: Any, **overrides: Any) -> tuple[RestExecutor, list[httpx.Request]]:
    seen: list[httpx.Request] = []

    def record(request: httpx.Request) -> httpx.Response:
        seen.append(request)
        return handler(request)

    options: dict[str, Any] = {"api_key": SecretStr(KEY), "base_url": None, "timeout_seconds": 5, "backoff_seconds": 0,
                               "http_client": httpx.AsyncClient(transport=httpx.MockTransport(record))}
    options.update(overrides)
    return RestExecutor(**options), seen


def respond(body: Any, status: int = 200, **headers: str) -> Any:
    return lambda request: httpx.Response(status, json=body, headers=headers)


async def failure_of(executor: RestExecutor, workflow: str, request: dict[str, Any]) -> Any:
    with pytest.raises(QlooFailure) as caught:
        await executor.run(workflow, request)
    return caught.value.error


async def test_find_tags_sends_documented_params_with_the_key_in_a_header_only() -> None:
    executor, seen = executor_for(respond(TAGS))
    envelope = await executor.run("find_tags", {"query": "hiking", "limit": 5})
    request = seen[0]
    assert (request.url.host, request.url.path) == ("api.qloo.com", "/v2/tags")
    assert dict(request.url.params) == {"filter.query": "hiking", "feature.semantic_search": "true", "take": "5"}
    assert request.headers["x-api-key"] == KEY and KEY not in str(request.url)
    assert envelope.results == [{"id": "urn:tag:keyword:qloo:hiking", "name": "Hiking", "type": "urn:tag:keyword:qloo",
                                 "popularity": 0.9}]
    assert envelope.execution["transport"] == "rest" and envelope.model_extra["provenance"]["endpoint"] == "/v2/tags"


async def test_recommend_maps_signals_location_and_affinity() -> None:
    executor, seen = executor_for(respond(INSIGHTS))
    envelope = await executor.run("recommend", {"target_type": "brand", "signal_tags": ["urn:tag:a", "urn:tag:b"],
                                                "signal_location": "Japan", "limit": 3})
    assert dict(seen[0].url.params) == {
        "filter.type": "urn:entity:brand", "take": "3", "feature.explainability": "true",
        "signal.interests.tags": "urn:tag:a,urn:tag:b", "operator.signal.interests.tags": "intersection",
        "signal.location.query": "Japan",
    }
    assert envelope.results == [{"entity_id": "B1A2", "name": "Trail Co", "subtype": "urn:entity:brand",
                                 "popularity": 0.81, "affinity": 0.62}]


async def test_tag_filter_and_entity_tags_for_the_relevance_check() -> None:
    body = {"success": True, "results": {"entities": [{"entity_id": "E9", "name": "Ridge Co", "subtype": "urn:entity:brand",
                                                       "tags": [{"id": "urn:tag:lifestyle:qloo:hiking", "name": "Hiking"},
                                                                {"tag_id": "urn:tag:genre:brand:fashion"}, {"name": "no id"}]}]}}
    executor, seen = executor_for(respond(body))
    envelope = await executor.run("recommend", {"target_type": "brand", "include_tags": ["urn:tag:lifestyle:qloo:hiking"],
                                                "signal_location": "Japan", "limit": 5})
    params = dict(seen[0].url.params)
    assert (params["filter.tags"], params["operator.filter.tags"]) == ("urn:tag:lifestyle:qloo:hiking", "union")
    assert "signal.interests.tags" not in params
    assert envelope.results[0]["tag_ids"] == ["urn:tag:lifestyle:qloo:hiking", "urn:tag:genre:brand:fashion"]


async def test_search_entities_returns_ranked_candidates_and_404_means_none() -> None:
    executor, seen = executor_for(respond(SEARCH))
    envelope = await executor.run("search_entities", {"query": "Patagonia"})
    assert (seen[0].url.path, dict(seen[0].url.params)) == ("/search", {"query": "Patagonia", "take": "5"})
    assert envelope.results == [{"id": "E1", "name": "Patagonia", "type": "urn:entity:brand", "popularity": 0.95},
                                {"id": "E2", "name": "Patagonia (region)", "type": "urn:entity:locality"}]
    executor, _ = executor_for(respond({"code": 404, "reason": "Not Found", "message": "No results"}, 404))
    assert (await executor.run("search_entities", {"query": "zzz"})).results == []


async def test_demographics_and_trending_requests() -> None:
    executor, seen = executor_for(respond(DEMOGRAPHICS))
    envelope = await executor.run("audience_demographics", {"entity": "B1A2"})
    assert dict(seen[0].url.params) == {"filter.type": "urn:demographics", "signal.interests.entities": "B1A2", "take": "10"}
    assert envelope.results == DEMOGRAPHICS["results"]["demographics"]

    executor, seen = executor_for(respond(TRENDING))
    envelope = await executor.run("trends", {"entity": "B1A2", "entity_type": "brand", "start_date": "2026-07-01",
                                             "end_date": "2026-10-01"})
    assert (seen[0].url.path, dict(seen[0].url.params)) == ("/v2/trending", {
        "filter.type": "urn:entity:brand", "signal.interests.entities": "B1A2", "filter.start_date": "2026-07-01",
        "filter.end_date": "2026-10-01", "take": "20"})
    assert envelope.results == TRENDING["results"]["trending"]


@pytest.mark.parametrize(
    ("status", "body", "code", "retryable", "attempts"),
    [
        (401, {"message": "Invalid API key"}, "QLOO_AUTH", False, 1),
        (403, {"message": "Forbidden"}, "QLOO_AUTH", False, 1),
        (429, {"message": "Too many requests"}, "QLOO_RATE_LIMIT", True, 3),
        (500, {"message": "Internal Server Error"}, "QLOO_UPSTREAM", True, 3),
        (400, {"message": "No localities were found for the query"}, "QLOO_LOCALITY_NOT_FOUND", False, 1),
        (400, {"message": "entity_ids must be specified."}, "QLOO_CONTRACT", False, 1),
    ],
)
async def test_http_errors_map_to_codes_with_bounded_retries(
    status: int, body: dict, code: str, retryable: bool, attempts: int
) -> None:
    executor, seen = executor_for(respond(body, status, **({"Retry-After": "0"} if status == 429 else {})))
    error = await failure_of(executor, "recommend", {"target_type": "brand", "signal_tags": ["urn:tag:a"],
                                                    "signal_location": "Atlantis"})
    assert (error.code, error.retryable, len(seen)) == (code, retryable, attempts)
    assert KEY not in error.message


async def test_transport_failures_and_bad_bodies() -> None:
    def timeout(request: httpx.Request) -> httpx.Response:
        raise httpx.ReadTimeout("slow", request=request)

    def refused(request: httpx.Request) -> httpx.Response:
        raise httpx.ConnectError("refused", request=request)

    for handler, code in ((timeout, "QLOO_TIMEOUT"), (refused, "QLOO_CONNECT"),
                          (lambda r: httpx.Response(200, text="not json"), "QLOO_INVALID_RESPONSE"),
                          (lambda r: httpx.Response(200, content=b"x" * (5 * 1024 * 1024 + 10)), "QLOO_INVALID_RESPONSE")):
        executor, _ = executor_for(handler)
        assert (await failure_of(executor, "find_tags", {"query": "hiking"})).code == code


async def test_unconfigured_and_custom_base_url() -> None:
    executor, seen = executor_for(respond(TAGS), api_key=None)
    assert not executor.is_configured()
    assert (await failure_of(executor, "find_tags", {"query": "hiking"})).code == "QLOO_NOT_CONFIGURED" and seen == []
    executor, seen = executor_for(respond(TAGS), base_url="https://hackathon.api.qloo.com/")
    await executor.run("find_tags", {"query": "hiking"})
    assert seen[0].url.host == "hackathon.api.qloo.com"


@pytest.mark.parametrize("url", ["http://api.qloo.com", "https://user:pw@api.qloo.com", "https://api.qloo.com?x=1", "ftp://x"])
def test_base_url_must_be_plain_https(url: str) -> None:
    with pytest.raises(ValueError):
        normalize_base_url(url)
    assert normalize_base_url(None) == DEFAULT_BASE_URL and normalize_base_url("http://localhost:9000/") == "http://localhost:9000"


async def test_the_key_never_reaches_logs(caplog: pytest.LogCaptureFixture) -> None:
    caplog.set_level(logging.DEBUG)
    executor, _ = executor_for(respond(TAGS))
    await executor.run("find_tags", {"query": "hiking"})
    executor, _ = executor_for(respond({"message": "Invalid API key"}, 401))
    await failure_of(executor, "find_tags", {"query": "hiking"})
    assert KEY not in caplog.text
    assert json.dumps(TAGS)  # bodies are test data only
