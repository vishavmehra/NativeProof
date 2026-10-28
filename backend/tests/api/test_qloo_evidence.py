"""Qloo evidence end to end (contracts/README §5, §7). The test covers:

- the provenance chain from a Qloo result to the API response;
- the live-only database cache;
- demo/live separation.

No Qloo call is made: live data comes from a fake executor shaped like harness output.
"""

from datetime import UTC, datetime
from typing import Any
from uuid import UUID, uuid4

import httpx
import pytest
from sqlalchemy import func, select
from sqlalchemy.exc import IntegrityError

from app.db import models as m
from app.db.session import session
from app.integrations.qloo.cache import CACHE_TTL, sha256_hex
from app.integrations.qloo.executor import Envelope
from app.integrations.qloo.service import HarnessQlooService
from app.services.qloo_cache import DbQlooCache
from app.workflows._common import evidence_from_draft
from tests.api.test_demo_journey import JAPAN, offline, run_to_end  # noqa: F401  (offline is a fixture)

API = "/api/v1"
T0 = datetime(2026, 10, 26, 12, tzinfo=UTC)
HIKING = {"id": "urn:tag:keyword:qloo:hiking", "name": "Hiking", "type": "urn:tag:keyword:qloo", "popularity": 0.9}
TRAIL_CO = {"entity_id": "8C1E7A52-1111-4C4B-9D2E-0A1B2C3D4E5F", "name": "Trail Co", "subtype": "urn:entity:brand",
            "affinity": 0.62}


class Executor:
    def __init__(self) -> None:
        self.calls: list[str] = []

    def is_configured(self) -> bool:
        return True

    async def run(self, workflow: str, request: dict[str, Any]) -> Envelope:
        self.calls.append(workflow)
        results = {"find_tags": [HIKING], "recommend": [TRAIL_CO]}.get(workflow, [])
        return Envelope.model_validate({"schema_version": "1.0-preview.1", "operation": workflow, "status": "ok",
                                        "results": results, "execution": {"transport": "direct", "correlation_id": "c"}})


class Clock:
    def __init__(self) -> None:
        self.now = T0

    def __call__(self) -> datetime:
        return self.now


async def cache_rows() -> list[m.QlooCacheEntry]:
    async with session() as s:
        return list((await s.execute(select(m.QlooCacheEntry))).scalars())


async def test_live_evidence_keeps_its_provenance_from_qloo_result_to_api_response(client: httpx.AsyncClient) -> None:
    project_id = UUID((await client.post(f"{API}/projects", json={"name": "P", "brand_name": "B"})).json()["id"])
    service = HarnessQlooService(Executor(), mode="live", now=lambda: T0)
    concept = await service.resolve_concept("hiking")
    related = await service.related_interests(concept.match, market=None)
    records = [evidence_from_draft(d, project_id=project_id, run_id=uuid4(), now=T0)
               for d in concept.evidence + related.evidence]
    async with session() as s, s.begin():  # persisted as the run engine does: one row per EvidenceRecord
        for record in records:
            row = record.model_dump(mode="json") | {"id": record.id, "project_id": project_id, "source_run_id": None,
                                                    "retrieved_at": record.retrieved_at, "created_at": record.created_at}
            s.add(m.EvidenceRecord(**row))

    tag, brand = records
    assert tag.provenance.request_hash == sha256_hex({"workflow": "find_tags", "input": {"query": "hiking", "limit": 5}})
    assert tag.provenance.response_hash == sha256_hex([HIKING])
    assert (brand.subject.entity_id, brand.related_entity.entity_id) == (HIKING["id"], TRAIL_CO["entity_id"])
    assert [(a.key, a.value) for a in brand.attributes] == [("affinity", 0.62)]  # not rescaled
    for record in records:
        body = (await client.get(f"{API}/evidence/{record.id}")).json()
        assert body["provenance"] == record.provenance.model_dump(mode="json") | {"fixture_origin": None}
        assert (body["retrieval_mode"], body["is_live_data"], body["evidence_type"], body["claim_type"]) == (
            "live", True, "qloo_source", "observed")
        assert (body["source_workflow"], body["source_reference"]) == (record.source_workflow, record.source_reference)
        assert body["attributes"] == [a.model_dump() for a in record.attributes]
    listed = (await client.get(f"{API}/projects/{project_id}/evidence")).json()
    assert listed["total"] == len(records)


async def test_db_cache_is_live_only_and_honours_expiry(app: Any) -> None:
    clock, executor = Clock(), Executor()
    service = HarnessQlooService(executor, mode="live", cache=DbQlooCache(), now=clock)
    await service.resolve_concept("hiking")
    cached = await service.resolve_concept("hiking")
    assert executor.calls == ["find_tags"]
    assert (cached.evidence[0].retrieval_mode, cached.evidence[0].retrieved_at) == ("cached", T0)
    assert [row.retrieval_mode for row in await cache_rows()] == ["live"]

    clock.now = T0 + CACHE_TTL["find_tags"]  # expired entries are never served
    fresh = await service.resolve_concept("hiking")
    assert executor.calls == ["find_tags", "find_tags"] and fresh.evidence[0].retrieval_mode == "live"

    with pytest.raises(IntegrityError):  # the database itself refuses non-live cache rows
        async with session() as s, s.begin():
            s.add(m.QlooCacheEntry(cache_key="fixture-row", workflow_name="find_tags", request_hash="r", response_data={},
                                   response_hash=None, retrieval_mode="fixture", retrieved_at=T0, expires_at=None))


async def test_a_demo_project_never_produces_live_evidence_or_cache_rows(client: httpx.AsyncClient, offline: Any) -> None:
    project = (await client.post(f"{API}/projects/demo")).json()
    campaign = (await client.get(f"{API}/projects/{project['id']}/campaigns")).json()["items"][0]
    run = await run_to_end(client, f"{API}/projects/{project['id']}/discoveries", {
        "campaign_id": campaign["id"], "product_category": "outdoor lifestyle apparel", "market": JAPAN,
        "research_question": "Which cultural interests could inform this launch?",
        "reference_terms": ["hiking", "minimal design", "great escape", "snowboarding"]})
    evidence = (await client.get(run["result"]["url"])).json()["evidence"]
    qloo = [e for e in evidence if e["evidence_type"] == "qloo_source"]
    assert qloo, "the demo discovery should record fixture Qloo evidence"
    for record in qloo:
        assert (record["retrieval_mode"], record["is_live_data"]) == ("fixture", False)
        assert record["provenance"]["fixture_origin"] == "hand_authored"
        assert (record["provenance"]["request_hash"], record["provenance"]["response_hash"]) == (None, None)
        assert record["summary"].startswith("Demo fixture:")
    listed = (await client.get(f"{API}/projects/{project['id']}/evidence", params={"limit": 100})).json()["items"]
    assert listed and not any(e["retrieval_mode"] in {"live", "cached"} or e["is_live_data"] for e in listed)
    assert await cache_rows() == []


async def test_live_discovery_without_a_key_is_refused_not_faked(client: httpx.AsyncClient) -> None:
    project_id = (await client.post(f"{API}/projects", json={"name": "P", "brand_name": "B"})).json()["id"]
    response = await client.post(f"{API}/projects/{project_id}/discoveries", json={
        "product_category": "outdoor apparel", "market": JAPAN, "research_question": "Which interests matter?",
        "reference_terms": ["hiking"]})
    assert response.status_code == 503 and response.json()["error"]["code"] == "PROVIDER_NOT_CONFIGURED"
    assert await cache_rows() == []
