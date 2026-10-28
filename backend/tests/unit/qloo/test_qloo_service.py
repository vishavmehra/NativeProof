"""Service tests with a fake executor: resolution rule, envelope mapping, normalization,
provenance, cache, and demo fixtures. No subprocesses, no Qloo calls."""

import json
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any
from uuid import uuid4

import pytest

from app.core.config import Settings
from app.integrations.qloo import CachedEntry, InMemoryQlooCache, QlooEntity, get_qloo_service
from app.integrations.qloo.cache import CACHE_TTL, cache_key, canonical_json, sha256_hex
from app.integrations.qloo.executor import Envelope, QlooError, QlooFailure
from app.integrations.qloo.fixtures import FIXTURE_LIMITATION, FIXTURE_VALUE_DESCRIPTION, NO_FIXTURE
from app.integrations.qloo.service import (
    AFFINITY_LIMITATION,
    AMBIGUOUS_LIMITATION,
    CONFIRMED_LIMITATION,
    UNRESOLVED_LIMITATION,
    HarnessQlooService,
)
from app.schemas.common import Market
from app.schemas.discovery import ConfirmedReference
from app.schemas.evidence import EvidenceRecord

T0 = datetime(2026, 10, 25, 12, tzinfo=UTC)
JAPAN = Market(country_code="JP", display_name="Japan")
SETTINGS = Settings(_env_file=None, qloo_api_key=None)
HIKING = {"id": "urn:tag:keyword:qloo:hiking", "name": "Hiking", "type": "urn:tag:keyword:qloo", "popularity": 0.98765}
HIKING_SEED = QlooEntity(entity_id=HIKING["id"], name="Hiking", entity_type=HIKING["type"])
CONTRACT_FIXTURE = Path(__file__).parents[4] / "contracts" / "fixtures" / "DiscoveryResult.json"


def envelope(workflow: str = "find_tags", status: str = "ok", results: Any = (), **fields: Any) -> Envelope:
    execution = {"transport": "direct", "transport_name": "Qloo API", "duration_ms": 5}
    execution["correlation_id"] = fields.pop("correlation_id", "exec-1")
    return Envelope.model_validate(
        {"schema_version": "1.0-preview.1", "operation": workflow, "status": status, "results": list(results),
         "execution": execution, **fields}
    )


def tags(*names: str) -> list[dict[str, Any]]:
    return [{"id": f"urn:tag:keyword:qloo:{i}", "name": name} for i, name in enumerate(names)]


class FakeExecutor:
    """Positional outcomes for find_tags/recommend/demographics/trends; entity search answers `entities`
    (default: no candidates)."""

    def __init__(self, *outcomes: Envelope | QlooFailure, entities: Envelope | QlooFailure | None = None) -> None:
        self.outcomes = outcomes
        self.entities = entities or envelope("search_entities")
        self.calls: list[tuple[str, dict[str, Any]]] = []
        self._served = 0

    def is_configured(self) -> bool:
        return True

    async def run(self, workflow: str, request: dict[str, Any]) -> Envelope:
        self.calls.append((workflow, request))
        if workflow == "search_entities":
            outcome = self.entities
        else:
            self._served += 1
            outcome = self.outcomes[min(self._served, len(self.outcomes)) - 1]
        if isinstance(outcome, QlooFailure):
            raise outcome
        return outcome


class Clock:
    def __init__(self) -> None:
        self.now = T0

    def __call__(self) -> datetime:
        return self.now


def live(*outcomes: Envelope | QlooFailure, cache: Any = None, clock: Clock | None = None,
         entities: Envelope | QlooFailure | None = None):
    executor = FakeExecutor(*outcomes, entities=entities)
    return HarnessQlooService(executor, mode="live", cache=cache, now=clock or Clock()), executor


def failure(code: str = "QLOO_TIMEOUT", retryable: bool = True) -> QlooFailure:
    return QlooFailure(QlooError(code=code, message="Qloo did not respond.", retryable=retryable))


# --- Resolution rule: the top candidate must be a near-exact, unique name match ---


@pytest.mark.parametrize(
    ("query", "top"),
    [
        ("hiking", "Hiking"),
        ("  HIKING ", "Hiking"),
        ("trail running", "Trail-Running"),
        ("hiking boots", "Hiking boot"),
        ("ｈｉｋｉｎｇ", "Hiking"),
        ("東京", "東京"),
    ],
)
async def test_near_exact_top_candidate_resolves(query: str, top: str) -> None:
    service, _ = live(envelope(results=tags(top, "Something else")))
    result = await service.resolve_concept(query)
    assert result.status == "resolved"
    assert result.match is not None and result.match.name == top


@pytest.mark.parametrize(
    ("query", "names"),
    [
        ("outdoor exploration", ["Hiking", "Exploration"]),  # semantic neighbour, not a name match
        ("outdoor exploration", ["Hiking"]),  # a single candidate is still not proof
        ("hiking", ["Hiking trails", "Hiking"]),  # exact match only at rank 2
        ("hiking", ["Hiking", "hiking"]),  # two candidates match equally
        ("hike", ["Hiking"]),
        ("glass", ["Glasses"]),
    ],
)
async def test_anything_else_is_ambiguous_with_the_top_candidates(query: str, names: list[str]) -> None:
    service, _ = live(envelope(results=tags(*names)))
    result = await service.resolve_concept(query)
    assert result.status == "ambiguous"
    assert result.match is None
    assert [candidate.name for candidate in result.candidates] == names
    assert result.limitations[0] == AMBIGUOUS_LIMITATION
    [draft] = result.evidence
    assert (draft.title, draft.subject, draft.source_reference) == (f"Ambiguous match: '{query.strip()}'", None, None)


async def test_ambiguous_candidates_are_capped_at_the_limit_in_qloo_order() -> None:
    service, _ = live(envelope(results=tags("A", "B", "C", "D", "E", "F")))
    result = await service.resolve_concept("x", limit=3)
    assert [c.name for c in result.candidates] == ["A", "B", "C"]
    assert [a.value for c in result.candidates for a in c.attributes if a.key == "match_rank"] == [1, 2, 3]


# --- Envelope statuses ---


async def test_resolved_concept_preserves_source_fields_and_provenance() -> None:
    service, executor = live(envelope(results=[HIKING]))
    result = await service.resolve_concept("hiking")

    assert executor.calls == [("find_tags", {"query": "hiking", "limit": 5})]
    match = result.match
    assert match is not None
    assert (match.entity_id, match.name, match.entity_type) == (HIKING["id"], "Hiking", HIKING["type"])
    assert {a.key: a.value for a in match.attributes} == {"match_rank": 1, "popularity": 0.98765}  # not rescaled
    assert result.limitations == [AFFINITY_LIMITATION]
    [draft] = result.evidence
    assert (draft.evidence_type, draft.claim_type, draft.method) == ("qloo_source", "observed", "provider_result")
    assert (draft.source_provider, draft.source_workflow, draft.source_reference) == ("qloo", "find_tags", HIKING["id"])
    assert (draft.retrieval_mode, draft.is_live_data, draft.retrieved_at) == ("live", True, T0)
    assert draft.provenance is not None and draft.provenance.fixture_origin is None
    assert draft.provenance.normalizer_version == "1"


@pytest.mark.parametrize(("status", "summary"), [("ok", None), ("empty", "Qloo found no matching tags.")])
async def test_no_candidates_is_unresolved(status: str, summary: str | None) -> None:
    service, _ = live(envelope(status=status, summary=summary))
    result = await service.resolve_concept("great escape")
    assert (result.status, result.evidence) == ("unresolved", [])
    assert result.limitations == [summary or UNRESOLVED_LIMITATION]


async def test_needs_input_is_ambiguous_even_for_an_exact_name() -> None:
    issue = {"input": "a", "kind": "ambiguous", "candidates": [{"id": "urn:tag:a", "name": "A", "rank": 1},
                                                              {"id": "urn:tag:b", "name": "B", "rank": 2}]}
    service, _ = live(envelope(status="needs_input", summary="Choose one.", resolution={"issues": [issue]}))
    result = await service.resolve_concept("a")
    assert result.status == "ambiguous"
    assert [c.entity_id for c in result.candidates] == ["urn:tag:a", "urn:tag:b"]


@pytest.mark.parametrize("status", ["partial", "degraded"])
async def test_partial_and_degraded_results_say_so(status: str) -> None:
    service, _ = live(envelope(status=status, results=[HIKING], summary="Some sources timed out."))
    result = await service.resolve_concept("hiking")
    note = f"Qloo returned a {status} result: Some sources timed out."
    assert result.status == "resolved"
    assert note in result.limitations
    assert note in result.evidence[0].limitations


async def test_provider_failure_is_an_error_result_not_an_exception() -> None:
    service, _ = live(failure("QLOO_TIMEOUT"))
    result = await service.resolve_concept("hiking")
    assert result.status == "error"
    assert result.error is not None and result.error.code == "QLOO_TIMEOUT"
    assert result.evidence == [] and "QLOO_TIMEOUT" in result.limitations[0]


async def test_warnings_become_limitations() -> None:
    service, _ = live(envelope(results=[HIKING], warnings=["Tag candidates lacked parent metadata."]))
    result = await service.resolve_concept("hiking")
    assert "Qloo warning: Tag candidates lacked parent metadata." in result.limitations


# --- Normalization ---


async def test_normalization_keeps_ids_handles_nulls_and_unknown_types() -> None:
    results = [
        {"id": "urn:tag:x", "name": "X", "type": None, "popularity": None, "affinity": True},
        {"name": "No id"},
        {"id": "urn:tag:no-name"},
        "not an object",
        {"entity_id": "E1", "name": "Trail Co", "subtype": "urn:entity:brand", "type": "urn:entity", "affinity": 0.123456},
        {"id": "urn:tag:z", "name": "Z", "type": "urn:tag:brand_new_kind:qloo"},
    ]
    service, _ = live(envelope(results=results))
    result = await service.resolve_concept("something else")

    x, brand, z = result.candidates
    assert (x.entity_id, x.entity_type, [a.key for a in x.attributes]) == ("urn:tag:x", None, ["match_rank"])
    assert (brand.entity_id, brand.entity_type) == ("E1", "urn:entity:brand")
    assert {a.key: a.value for a in brand.attributes} == {"match_rank": 5, "affinity": 0.123456}
    assert z.entity_type == "urn:tag:brand_new_kind:qloo"
    assert "3 Qloo result(s) without an id or name were left out." in result.limitations


async def test_provenance_hashes_are_stable_and_ignore_execution_metadata() -> None:
    first, _ = live(envelope(results=[HIKING], correlation_id="exec-1"))
    second, _ = live(envelope(results=[HIKING], correlation_id="exec-2"))
    changed, _ = live(envelope(results=[{**HIKING, "popularity": 0.5}]))
    a = (await first.resolve_concept("hiking")).evidence[0].provenance
    b = (await second.resolve_concept("hiking")).evidence[0].provenance
    c = (await changed.resolve_concept("hiking")).evidence[0].provenance

    assert a == b
    assert a.request_hash == sha256_hex({"workflow": "find_tags", "input": {"query": "hiking", "limit": 5}})
    assert a.response_hash == sha256_hex([HIKING])
    assert c.response_hash != a.response_hash
    assert canonical_json({"b": 1, "a": "é"}) == '{"a":"é","b":1}'


# --- Cache ---


async def test_cache_hit_is_labeled_cached_with_the_original_timestamp() -> None:
    cache, clock = InMemoryQlooCache(), Clock()
    service, executor = live(envelope(results=[HIKING]), cache=cache, clock=clock)
    first = await service.resolve_concept("hiking")

    [entry] = cache.entries.values()
    assert entry.key == cache_key("find_tags", {"query": "hiking", "limit": 5})
    assert entry.expires_at == T0 + timedelta(days=7) == T0 + CACHE_TTL["find_tags"]

    clock.now = T0 + timedelta(days=6, hours=23)
    second = await service.resolve_concept("hiking")
    assert len(executor.calls) == 1
    draft = second.evidence[0]
    assert (draft.retrieval_mode, draft.is_live_data, draft.retrieved_at) == ("cached", True, T0)
    assert "Cached Qloo result retrieved 2026-10-25 12:00 UTC; Qloo data may have changed since." in draft.limitations
    assert draft.provenance == first.evidence[0].provenance


async def test_expired_entries_are_never_served() -> None:
    cache, clock = InMemoryQlooCache(), Clock()
    service, executor = live(envelope(results=[HIKING]), cache=cache, clock=clock)
    await service.resolve_concept("hiking")
    clock.now = T0 + CACHE_TTL["find_tags"]
    result = await service.resolve_concept("hiking")
    assert len(executor.calls) == 2
    assert (result.evidence[0].retrieval_mode, result.evidence[0].retrieved_at) == ("live", clock.now)
    assert next(iter(cache.entries.values())).expires_at == clock.now + CACHE_TTL["find_tags"]


async def test_errors_and_partial_results_are_not_cached() -> None:
    cache = InMemoryQlooCache()
    service, _ = live(failure(), envelope(status="partial", results=[HIKING], summary="s"), cache=cache)
    assert (await service.resolve_concept("hiking")).status == "error"
    assert (await service.resolve_concept("hiking")).status == "resolved"
    assert cache.entries == {}


async def test_related_interests_are_cached_for_24_hours() -> None:
    cache = InMemoryQlooCache()
    service, _ = live(envelope("recommend", results=[{"entity_id": "B1", "name": "Trail Co"}]), cache=cache)
    await service.related_interests(HIKING_SEED, market=None)
    [entry] = cache.entries.values()
    assert entry.expires_at == T0 + timedelta(hours=24)


async def test_cache_failures_never_break_a_lookup() -> None:
    class BrokenCache:
        async def get(self, key: str) -> CachedEntry | None:
            raise RuntimeError("database unavailable")

        async def put(self, entry: CachedEntry) -> None:
            raise RuntimeError("database unavailable")

    service, _ = live(envelope(results=[HIKING]), cache=BrokenCache())
    assert (await service.resolve_concept("hiking")).status == "resolved"


async def test_naive_cached_timestamps_are_read_as_utc() -> None:
    cache = InMemoryQlooCache()
    request = {"query": "hiking", "limit": 5}
    await cache.put(
        CachedEntry(
            key=cache_key("find_tags", request), workflow="find_tags", request_hash="r",
            response=envelope(results=[HIKING]).model_dump(mode="json"), response_hash="h",
            retrieved_at=datetime(2026, 10, 25, 11), expires_at=datetime(2026, 10, 26, 11),
        )
    )
    service, executor = live(envelope(results=[]), cache=cache)
    result = await service.resolve_concept("hiking")
    assert executor.calls == []
    assert result.evidence[0].retrieved_at == datetime(2026, 10, 25, 11, tzinfo=UTC)


# --- related_interests ---


async def test_related_interests_filter_by_the_seed_tag_with_the_market_as_signal() -> None:
    item = {"entity_id": "B1", "name": "Trail Co", "subtype": "urn:entity:brand", "affinity": 0.42, "popularity": 0.7}
    service, executor = live(envelope("recommend", results=[item]))
    result = await service.related_interests(HIKING_SEED, market=JAPAN, limit=5)

    assert executor.calls == [
        ("recommend", {"target_type": "brand", "include_tags": [HIKING["id"]], "signal_location": "Japan", "limit": 5})
    ]
    assert any("tag filter" in note for note in result.limitations)  # no entity tags returned: says so
    assert result.status == "ok"
    [brand] = result.items
    assert (brand.entity_id, brand.entity_type) == ("B1", "urn:entity:brand")
    assert {a.key: a.value for a in brand.attributes} == {"affinity": 0.42, "popularity": 0.7}
    assert any("audience-location signal" in note for note in result.limitations)
    [draft] = result.evidence
    assert (draft.subject.entity_id, draft.related_entity.entity_id, draft.source_reference) == (HIKING["id"], "B1", "B1")
    assert draft.source_workflow == "recommend" and draft.retrieval_mode == "live"


async def test_relevance_check_drops_results_without_the_seed_tag() -> None:
    """Live 2026-10-28: Qloo returned unrelated brands when the tag was only a signal; results must carry it."""
    tagged = {"entity_id": "B1", "name": "Ridge Co", "tag_ids": [HIKING["id"], "urn:tag:genre:brand:fashion"]}
    untagged = {"entity_id": "B2", "name": "Rohto Eye Drops", "tag_ids": ["urn:tag:genre:brand:health"]}
    service, executor = live(envelope("recommend", results=[tagged, untagged]))
    result = await service.related_interests(HIKING_SEED, market=None)
    assert executor.calls[0][1]["include_tags"] == executor.calls[0][1]["signal_tags"] == [HIKING["id"]]
    assert [item.name for item in result.items] == ["Ridge Co"]
    note = "1 result(s) did not carry Qloo's 'Hiking' tag and were dropped by the relevance check."
    assert note in result.limitations and note in result.evidence[0].limitations

    service, _ = live(envelope("recommend", results=[untagged]))
    none_left = await service.related_interests(HIKING_SEED, market=None)
    assert (none_left.status, none_left.items, none_left.evidence) == ("empty", [], [])  # never shown as evidence


async def test_entity_seeds_use_entity_signals() -> None:
    service, executor = live(envelope("recommend"))
    seed = QlooEntity(entity_id="2B1A4C3D-0000-4000-8000-000000000001", name="Some Brand", entity_type="urn:entity:brand")
    result = await service.related_interests(seed, market=None, target_type="place")
    assert executor.calls == [("recommend", {"target_type": "place", "signals": [seed.entity_id], "limit": 10})]
    assert any("shared audience affinity" in note for note in result.limitations)
    assert result.status == "empty"


async def test_related_interests_statuses() -> None:
    service, _ = live(envelope("recommend", status="needs_input", summary="Choose the intended entity."))
    needs = await service.related_interests(HIKING_SEED, market=None)
    assert needs.status == "error" and needs.error is not None and needs.error.code == "QLOO_INVALID_REQUEST"

    service, _ = live(envelope("recommend", status="degraded", results=[{"entity_id": "B1", "name": "B"}], summary="s"))
    assert (await service.related_interests(HIKING_SEED, market=None)).status == "partial"

    service, _ = live(failure("QLOO_RATE_LIMIT"))
    limited = await service.related_interests(HIKING_SEED, market=None)
    assert limited.status == "error" and limited.error.code == "QLOO_RATE_LIMIT"


async def test_live_service_refuses_fixture_entities() -> None:
    service, executor = live(envelope("recommend"))
    seed = QlooEntity(entity_id="fixture:tag:hiking", name="Hiking", entity_type="tag")
    result = await service.related_interests(seed, market=None)
    assert result.status == "error" and result.error.code == "QLOO_INVALID_REQUEST"
    assert executor.calls == []


# --- Privacy ---


@pytest.mark.parametrize("term", ["email jane.doe@example.com", "call +1 (415) 555-0100"])
async def test_personal_data_is_never_sent(term: str) -> None:
    service, executor = live(envelope(results=[HIKING]))
    for candidate in (service, get_qloo_service("demo", SETTINGS)):
        result = await candidate.resolve_concept(term)
        assert result.status == "error" and result.error.code == "QLOO_INVALID_REQUEST"
    assert executor.calls == []


# --- Demo fixtures and the factory ---


async def test_demo_service_is_fixture_only_and_never_cached() -> None:
    cache = InMemoryQlooCache()
    demo = get_qloo_service("demo", SETTINGS, cache=cache)
    assert (demo.mode, demo.is_configured()) == ("fixture", True)

    concept = await demo.resolve_concept("hiking")
    related = await demo.related_interests(concept.match, market=JAPAN)
    assert cache.entries == {}
    for draft in concept.evidence + related.evidence:
        assert (draft.retrieval_mode, draft.is_live_data) == ("fixture", False)
        assert draft.provenance.fixture_origin == "hand_authored"
        assert FIXTURE_LIMITATION in draft.limitations
        assert draft.retrieved_at == datetime(2026, 10, 25, tzinfo=UTC)


async def test_demo_terms() -> None:
    demo = get_qloo_service("demo", SETTINGS)

    hiking = await demo.resolve_concept("hiking")
    assert (hiking.status, hiking.match.entity_id, hiking.match.entity_type) == ("resolved", "fixture:tag:hiking", "tag")
    assert hiking.evidence[0].title == "Resolved tag: Hiking"

    outdoor = await demo.resolve_concept("outdoor exploration")  # semantic neighbours only: never auto-resolved
    assert outdoor.status == "ambiguous"
    assert [c.entity_id for c in outdoor.candidates] == ["fixture:tag:hiking", "fixture:tag:trail-running"]

    minimal = await demo.resolve_concept("minimal design")
    assert minimal.status == "ambiguous"
    assert [(c.entity_id, c.name) for c in minimal.candidates] == [
        ("fixture:tag:minimalism", "Minimalism"),
        ("fixture:tag:minimalist-architecture", "Minimalist architecture"),
    ]

    escape = await demo.resolve_concept("great escape")
    assert (escape.status, escape.evidence, escape.limitations) == ("unresolved", [], [UNRESOLVED_LIMITATION])

    unknown = await demo.resolve_concept("snowboarding")
    assert (unknown.status, unknown.limitations) == ("unresolved", [NO_FIXTURE])

    related = await demo.related_interests(hiking.match, market=JAPAN)
    [kumo] = related.items
    assert (related.status, kumo.entity_id, kumo.name, kumo.entity_type) == (
        "ok", "fixture:brand:kumo-trail", "Kumo Trail Co. (fictional)", "brand")
    assert [(a.key, a.value, a.description) for a in kumo.attributes] == [("affinity", 0.71, FIXTURE_VALUE_DESCRIPTION)]
    assert related.evidence[0].title == "Related brand: Kumo Trail Co. (fictional)"

    no_fixture = await demo.related_interests(kumo, market=JAPAN)
    assert no_fixture.status == "empty" and NO_FIXTURE in no_fixture.limitations


async def test_demo_values_match_the_contract_fixture() -> None:
    contract = json.loads(CONTRACT_FIXTURE.read_text(encoding="utf-8"))
    by_term = {reference["query_term"]: reference for reference in contract["references"]}
    demo = get_qloo_service("demo", SETTINGS)

    minimal = await demo.resolve_concept("minimal design")
    assert [c.entity_id for c in minimal.candidates] == [c["entity_id"] for c in by_term["minimal design"]["candidates"]]
    assert (await demo.resolve_concept("great escape")).limitations == by_term["great escape"]["limitations"]
    hiking = await demo.resolve_concept("hiking")
    kumo = (await demo.related_interests(hiking.match, market=JAPAN)).items[0]
    expected = by_term["related to Hiking"]
    assert (kumo.entity_id, kumo.name, kumo.entity_type) == (expected["entity_id"], expected["name"], expected["entity_type"])
    assert kumo.attributes[0].model_dump() == expected["attributes"][0]


async def test_evidence_drafts_become_valid_evidence_records() -> None:
    demo = get_qloo_service("demo", SETTINGS)
    hiking = await demo.resolve_concept("hiking")
    related = await demo.related_interests(hiking.match, market=JAPAN)
    for draft in hiking.evidence + related.evidence:
        record = EvidenceRecord(id=uuid4(), project_id=uuid4(), source_run_id=None, created_at=T0, **draft.model_dump())
        assert record.retrieval_mode == "fixture"


@pytest.mark.parametrize("api_key", [None, ""])
async def test_live_service_without_a_key_is_not_configured(api_key: str | None) -> None:
    service = get_qloo_service("live", Settings(_env_file=None, qloo_api_key=api_key))
    assert (service.mode, service.is_configured()) == ("live", False)
    result = await service.resolve_concept("hiking")
    assert result.status == "error" and result.error.code == "QLOO_NOT_CONFIGURED"


def test_unknown_mode_is_rejected() -> None:
    with pytest.raises(ValueError):
        get_qloo_service("staging", SETTINGS)  # type: ignore[arg-type]


# --- Live readiness: entity search, locality, demographics, trends, transports ---

SEARCH_PATAGONIA = envelope("search_entities", results=[
    {"id": "E1", "name": "Patagonia", "type": "urn:entity:brand", "popularity": 0.95},
    {"id": "E2", "name": "Patagonia (region)", "type": "urn:entity:locality"},
])
ATLANTIS = Market(country_code="AQ", display_name="Atlantis")
BRAND = QlooEntity(entity_id="B1", name="Trail Co", entity_type="urn:entity:brand")


async def test_entities_resolve_when_no_tag_matches() -> None:
    service, executor = live(envelope(results=tags("Patagonian food")), entities=SEARCH_PATAGONIA)
    result = await service.resolve_concept("patagonia")
    assert [call[0] for call in executor.calls] == ["find_tags", "search_entities"]
    assert (result.status, result.match.entity_id, result.match.entity_type) == ("resolved", "E1", "urn:entity:brand")
    [draft] = result.evidence
    assert (draft.title, draft.source_workflow, draft.source_reference) == ("Resolved brand: Patagonia", "search_entities", "E1")


async def test_tag_and_entity_candidates_are_both_listed() -> None:
    service, _ = live(envelope(results=tags("Hiking boots", "Trail")), entities=SEARCH_PATAGONIA)
    result = await service.resolve_concept("outdoor gear")
    assert result.status == "ambiguous"
    assert [c.name for c in result.candidates] == ["Hiking boots", "Trail", "Patagonia", "Patagonia (region)"]
    assert [d.title for d in result.evidence] == ["Ambiguous match: 'outdoor gear'", "Ambiguous entity match: 'outdoor gear'"]


async def test_entity_search_failure_keeps_the_tag_outcome() -> None:
    service, _ = live(envelope(results=tags("Hiking boots")), entities=failure("QLOO_TIMEOUT"))
    result = await service.resolve_concept("outdoor gear")
    assert result.status == "ambiguous"
    assert "Entity search failed (QLOO_TIMEOUT); only Qloo tags were checked." in result.limitations


async def test_a_confirmed_candidate_replaces_name_matching() -> None:
    hikings = envelope(results=[{"id": f"urn:tag:{kind}:qloo:hiking", "name": "Hiking", "type": f"urn:tag:{kind}:qloo"}
                                     for kind in ("hobby", "activity", "lifestyle")])
    service, executor = live(hikings)
    assert (await service.resolve_concept("hiking")).status == "ambiguous"
    choice = ConfirmedReference(term="hiking", ref_id="urn:tag:lifestyle:qloo:hiking", ref_kind="tag")
    result = await service.resolve_concept("hiking", confirmed=choice)
    assert (result.status, result.match.entity_id) == ("resolved", "urn:tag:lifestyle:qloo:hiking")
    assert CONFIRMED_LIMITATION in result.limitations and result.evidence[0].title == "Confirmed tag: Hiking"
    assert "confirmed by the person" in result.evidence[0].summary and executor.calls[-1][0] == "find_tags"

    entity_choice = ConfirmedReference(term="patagonia", ref_id="E2", ref_kind="entity")
    service, executor = live(envelope(results=tags("Patagonian food")), entities=SEARCH_PATAGONIA)
    result = await service.resolve_concept("patagonia", confirmed=entity_choice)
    assert (result.status, result.match.name, [c[0] for c in executor.calls]) == ("resolved", "Patagonia (region)",
                                                                                   ["search_entities"])


async def test_a_venue_named_like_the_phrase_is_listed_never_auto_resolved() -> None:
    venue = envelope("search_entities", results=[{"id": "P1", "name": "Minimal Design", "type": "urn:entity:place"}])
    service, _ = live(envelope(results=tags("Minimalism")), entities=venue)
    result = await service.resolve_concept("minimal design")
    assert (result.status, [c.entity_id for c in result.candidates]) == ("ambiguous", ["urn:tag:keyword:qloo:0", "P1"])
    choice = ConfirmedReference(term="minimal design", ref_id="P1", ref_kind="entity")
    assert (await service.resolve_concept("minimal design", confirmed=choice)).match.entity_id == "P1"


async def test_a_confirmed_id_qloo_does_not_return_is_never_used() -> None:
    service, _ = live(envelope(results=tags("Hiking boots", "Trail")))
    choice = ConfirmedReference(term="outdoor gear", ref_id="urn:tag:made-up", ref_kind="tag")
    result = await service.resolve_concept("outdoor gear", confirmed=choice)
    assert (result.status, result.match) == ("ambiguous", None)
    assert result.limitations[0] == "The confirmed tag is not among Qloo's candidates for 'outdoor gear', so it was not used."
    demo = get_qloo_service("demo", SETTINGS)  # demo: fixture candidates only, still never a guess
    fixture_choice = ConfirmedReference(term="minimal design", ref_id="fixture:tag:minimalism", ref_kind="tag")
    confirmed = await demo.resolve_concept("minimal design", confirmed=fixture_choice)
    assert (confirmed.status, confirmed.match.name, confirmed.evidence[0].retrieval_mode) == ("resolved", "Minimalism", "fixture")
    service, _ = live(failure("QLOO_TIMEOUT"))
    assert (await service.resolve_concept("hiking", confirmed=choice)).status == "error"


async def test_locality_not_found_is_an_honest_empty_result() -> None:
    service, executor = live(failure("QLOO_LOCALITY_NOT_FOUND", retryable=False))
    result = await service.related_interests(HIKING_SEED, market=ATLANTIS)
    assert (result.status, result.items, result.error) == ("empty", [], None)
    assert any("'Atlantis'" in note for note in result.limitations) and len(executor.calls) == 1


async def test_harness_4xx_with_a_location_is_confirmed_by_one_probe() -> None:
    probe_ok = envelope("recommend", results=[{"entity_id": "B1", "name": "Trail Co"}])
    service, executor = live(failure("QLOO_CONTRACT", retryable=False), probe_ok)
    result = await service.related_interests(HIKING_SEED, market=ATLANTIS)
    assert result.status == "empty" and result.items == []  # probe results are not market-specific; not returned
    assert "signal_location" not in executor.calls[1][1]

    service, _ = live(failure("QLOO_CONTRACT", retryable=False), failure("QLOO_CONTRACT", retryable=False))
    assert (await service.related_interests(HIKING_SEED, market=ATLANTIS)).status == "error"
    service, executor = live(failure("QLOO_CONTRACT", retryable=False))
    assert (await service.related_interests(HIKING_SEED, market=None)).status == "error" and len(executor.calls) == 1


async def test_demographics_keep_qloo_scores_as_returned() -> None:
    from app.integrations.qloo.service import DEMOGRAPHIC_DESCRIPTION

    block = {"entity_id": "B1", "query": {"age": {"25_to_29": 0.21, "bad": "x"}, "gender": {"female": -0.04}}}
    service, executor = live(envelope("audience_demographics", results=[block]))
    result = await service.audience_demographics(BRAND)
    assert executor.calls == [("audience_demographics", {"entity": "B1", "limit": 10})]
    assert [(s.dimension, s.bucket, s.affinity) for s in result.segments] == [
        ("age", "25_to_29", 0.21), ("gender", "female", -0.04)]
    [draft] = result.evidence
    assert [(a.key, a.value, a.description) for a in draft.attributes] == [
        ("age.25_to_29", 0.21, DEMOGRAPHIC_DESCRIPTION), ("gender.female", -0.04, DEMOGRAPHIC_DESCRIPTION)]
    assert (draft.source_workflow, draft.subject.entity_id, draft.retrieval_mode) == ("audience_demographics", "B1", "live")

    tag_result = await service.audience_demographics(HIKING_SEED)
    assert tag_result.status == "error" and len(executor.calls) == 1  # tags are refused before any call
    demo = await get_qloo_service("demo", SETTINGS).audience_demographics(BRAND)
    assert (demo.status, demo.segments) == ("empty", []) and NO_FIXTURE in demo.limitations  # no invented scores


async def test_trends_are_real_dated_points_only() -> None:
    points = [{"date": "2026-10-01", "population_percentile": 0.81, "population_rank": 1200},
              {"date": "2026-09-01", "population_percentile": "n/a"}, {"population_percentile": 0.5}]
    service, executor = live(envelope("trends", results=points))
    result = await service.trends(BRAND, entity_type="brand", start_date="2026-07-01", end_date="2026-10-01")
    assert [(p.date, p.population_percentile) for p in result.points] == [("2026-10-01", 0.81), ("2026-09-01", None)]
    assert {a.key for a in result.evidence[0].attributes} == {"population_percentile", "population_rank"}
    assert executor.calls[0][1] == {"entity": "B1", "entity_type": "brand", "start_date": "2026-07-01",
                                    "end_date": "2026-10-01", "limit": 20}
    bad = await service.trends(BRAND, entity_type="brand", start_date="2026-10-02", end_date="2026-10-01")
    assert bad.status == "error" and len(executor.calls) == 1
    demo = await get_qloo_service("demo", SETTINGS).trends(BRAND, entity_type="brand", start_date="2026-07-01",
                                                            end_date="2026-10-01")
    assert demo.status == "empty" and demo.points == []


def test_factory_selects_the_transport(monkeypatch: pytest.MonkeyPatch) -> None:
    from types import SimpleNamespace

    from pydantic import SecretStr

    from app.integrations.qloo import service as module
    from app.integrations.qloo.executor import SubprocessExecutor
    from app.integrations.qloo.rest import RestExecutor

    def settings(**values: Any) -> Any:
        return SimpleNamespace(qloo_api_key=SecretStr("k"), qloo_bin="qloo", qloo_timeout_seconds=5, **values)

    monkeypatch.setattr(module, "resolve_qloo_command", lambda _: ["node", "bin.js"])
    default = get_qloo_service("live", settings())  # auto prefers REST (measured 10x faster, same results)
    assert isinstance(default._executor, RestExecutor) and default.transport == "rest" and default.is_configured()
    custom = get_qloo_service("live", settings(qloo_base_url="https://hackathon.api.qloo.com"))._executor
    assert custom.base_url == "https://hackathon.api.qloo.com"
    harness = get_qloo_service("live", settings(qloo_transport="harness"))._executor
    assert isinstance(harness, SubprocessExecutor) and harness.base_url is None
    harness_custom = get_qloo_service("live", settings(qloo_transport="harness",
                                                       qloo_base_url="https://hackathon.api.qloo.com"))._executor
    assert harness_custom.base_url == "https://hackathon.api.qloo.com"

    monkeypatch.setattr(module, "resolve_qloo_command", lambda _: None)
    assert not get_qloo_service("live", settings(qloo_transport="harness")).is_configured()
    assert not get_qloo_service("live", settings(qloo_base_url="http://evil.example")).is_configured()


# --- Live vs fixture separation and fixture honesty (audit) ---


async def test_live_mode_rejects_fixture_data_fresh_or_cached() -> None:
    from app.integrations.qloo.executor import SubprocessExecutor
    from app.integrations.qloo.fixtures import FixtureExecutor

    with pytest.raises(ValueError):
        HarnessQlooService(FixtureExecutor(), mode="live")
    with pytest.raises(ValueError):
        HarnessQlooService(SubprocessExecutor(api_key=None, command=None, timeout_seconds=1), mode="fixture")

    fixture_transport = envelope(results=[HIKING])
    fixture_transport.execution["transport"] = "fixture"
    for outcome in (fixture_transport, envelope(results=[{"id": "fixture:tag:hiking", "name": "Hiking"}])):
        service, _ = live(outcome)
        result = await service.resolve_concept("hiking")
        assert result.status == "error" and result.error.code == "QLOO_INVALID_RESPONSE"

    cache = InMemoryQlooCache()
    request = {"query": "hiking", "limit": 5}
    await cache.put(CachedEntry(key=cache_key("find_tags", request), workflow="find_tags", request_hash="r",
                                response=fixture_transport.model_dump(mode="json"), response_hash="h",
                                retrieved_at=T0, expires_at=T0 + timedelta(days=1)))
    service, executor = live(envelope(results=[HIKING]), cache=cache)
    result = await service.resolve_concept("hiking")
    assert len(executor.calls) == 1 and result.evidence[0].retrieval_mode == "live"  # the fixture entry was ignored


def test_fixture_data_cannot_pass_for_live_data() -> None:
    from app.integrations.qloo.fixtures import FIND_TAGS, RECOMMEND

    items = [item for group in (*FIND_TAGS.values(), *RECOMMEND.values()) for item in group]
    assert items and all(str(item.get("id") or item.get("entity_id")).startswith("fixture:") for item in items)
    assert not any("popularity" in item for item in items)  # no invented popularity metric
    assert all("(fictional)" in item["name"] for group in RECOMMEND.values() for item in group)


async def test_every_demo_evidence_record_is_labelled_fixture() -> None:
    from app.integrations.qloo.fixtures import FIND_TAGS

    demo = get_qloo_service("demo", SETTINGS)
    drafts = [draft for term in FIND_TAGS for draft in (await demo.resolve_concept(term)).evidence]
    hiking = (await demo.resolve_concept("hiking")).match
    drafts += (await demo.related_interests(hiking, market=JAPAN)).evidence
    assert len(drafts) >= 4
    for draft in drafts:
        assert (draft.retrieval_mode, draft.is_live_data, draft.provenance.fixture_origin) == ("fixture", False, "hand_authored")
        assert (draft.provenance.request_hash, draft.provenance.response_hash) == (None, None)
        assert draft.summary.startswith("Demo fixture:") and FIXTURE_LIMITATION in draft.limitations
        refs = [r for r in (draft.subject, draft.related_entity) if r is not None]
        assert all(ref.entity_id.startswith("fixture:") for ref in refs)
        assert all(a.description == FIXTURE_VALUE_DESCRIPTION for a in draft.attributes if a.key != "match_rank")
