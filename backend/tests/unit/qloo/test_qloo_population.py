"""collect_population_evidence: seeds, per-region relevance-checked interests with rank weights, group-level
demographics, provenance, cache, call records, and the labelled demo fixtures. No Qloo calls."""

from typing import Any
from uuid import uuid4

from app.core.config import Settings
from app.integrations.qloo import InMemoryQlooCache, collect_population_evidence, get_qloo_service
from app.integrations.qloo.executor import Envelope
from app.integrations.qloo.population import DEMOGRAPHICS_NOTE
from app.integrations.qloo.service import HarnessQlooService
from app.schemas.common import Market
from app.schemas.evidence import EvidenceRecord

JAPAN = Market(country_code="JP", display_name="Japan")
HIKING = "urn:tag:lifestyle:qloo:hiking"
PROJECT, RUN = uuid4(), uuid4()


def env(workflow: str, results: list[Any]) -> Envelope:
    return Envelope.model_validate({"schema_version": "1.0-preview.1", "operation": workflow,
                                    "status": "ok" if results else "empty", "results": results,
                                    "execution": {"transport": "rest", "correlation_id": "c", "duration_ms": 1}})


class Routed:
    """Answers by workflow; records requests."""

    transport = "rest"

    def __init__(self, answers: dict[str, list[Any]]) -> None:
        self.answers, self.calls = answers, []

    def is_configured(self) -> bool:
        return True

    async def run(self, workflow: str, request: dict[str, Any]) -> Envelope:
        self.calls.append((workflow, request))
        return env(workflow, self.answers.get((workflow, request.get("query")), self.answers.get(workflow, [])))


def records(drafts: list, project=PROJECT) -> list[EvidenceRecord]:
    return [EvidenceRecord.model_validate({**d.model_dump(), "id": uuid4(), "project_id": project,
                                           "source_run_id": uuid4(), "created_at": d.retrieved_at}) for d in drafts]


async def test_live_population_evidence_is_relevance_checked_weighted_and_recorded() -> None:
    brand = lambda i, tags: {"entity_id": f"B{i}", "name": f"Brand {i}", "subtype": "urn:entity:brand",  # noqa: E731
                             "affinity": 0.9 - i / 10, "tag_ids": tags}
    executor = Routed({
        ("find_tags", "hiking"): [{"id": HIKING, "name": "Hiking", "type": "urn:tag:lifestyle:qloo"}],
        "recommend": [brand(1, [HIKING]), brand(2, ["urn:tag:other"]), brand(3, [HIKING, "urn:tag:x"])],
        "audience_demographics": [{"entity_id": "B1", "query": {"age": {"25_to_29": 0.21}, "gender": {"female": 0.04}}}],
    })
    service = HarnessQlooService(executor, mode="live", cache=InMemoryQlooCache())
    discovery = records((await service.resolve_concept("hiking")).evidence)  # the discovery snapshot

    out = await collect_population_evidence(service, project_id=PROJECT, run_id=RUN, regions=[JAPAN],
                                            concept="outdoor lifestyle apparel", reference_terms=["hiking", "HIKING"],
                                            discovery_evidence=discovery, max_demographics=1)

    [region] = out.regions
    assert [(i.ref_id, i.ref_kind, i.weight) for i in region.interests] == [
        (HIKING, "tag", 1.0), ("B1", "entity", 0.667), ("B3", "entity", 0.333)]  # B2 lacks the Hiking tag: dropped
    assert region.interests[0].evidence_ids == [discovery[0].id] and out.grounded
    related = {e.related_entity.entity_id: e for e in out.evidence if e.source_workflow == "recommend"}
    assert set(related) == {"B1", "B3"} and region.interests[1].evidence_ids == [related["B1"].id]
    assert all(e.is_live_data and e.provenance.request_hash and e.source_run_id == RUN for e in out.evidence)
    [demographics] = [e for e in out.evidence if e.id in out.demographic_evidence_ids]
    assert demographics.subject.entity_id == "B1" and DEMOGRAPHICS_NOTE in out.limitations
    assert "'outdoor lifestyle apparel' is unresolved in Qloo, so it does not ground the population." in out.limitations
    recommend = next(request for workflow, request in executor.calls if workflow == "recommend")
    assert (recommend["include_tags"], recommend["signal_location"]) == ([HIKING], "Japan")
    assert [(c.workflow, c.retrieval_mode) for c in out.calls] == [
        ("find_tags", "live"), ("search_entities", "live"), ("find_tags", "cached"), ("recommend", "live"),
        ("audience_demographics", "live")]

    again = await collect_population_evidence(service, project_id=PROJECT, run_id=RUN, regions=[JAPAN],
                                              concept=None, reference_terms=[], discovery_evidence=discovery,
                                              max_demographics=1)
    assert {c.retrieval_mode for c in again.calls} == {"cached"}  # repeats are served by the cache


async def test_demo_population_evidence_uses_labelled_fixtures_only() -> None:
    demo = get_qloo_service("demo", Settings(_env_file=None, qloo_api_key=None))
    discovery = records((await demo.resolve_concept("hiking")).evidence)
    out = await collect_population_evidence(demo, project_id=PROJECT, run_id=RUN, regions=[JAPAN], concept=None,
                                            reference_terms=["minimalism", "great escape"], discovery_evidence=discovery)
    [region] = out.regions
    assert [(i.name, i.weight) for i in region.interests] == [
        ("Hiking", 1.0), ("Minimalism", 0.75), ("Kumo Trail Co. (fictional)", 0.5), ("Shizuka Living (fictional)", 0.25)]
    assert all(i.ref_id.startswith("fixture:") for i in region.interests)
    assert all(e.retrieval_mode == "fixture" and not e.is_live_data and e.provenance.fixture_origin == "hand_authored"
               for e in out.evidence)
    assert out.demographic_evidence_ids == [] and any("No demo fixture" in note for note in out.limitations)
    assert {c.retrieval_mode for c in out.calls} == {"fixture"} and out.grounded

    ungrounded = await collect_population_evidence(demo, project_id=PROJECT, run_id=RUN, regions=[JAPAN], concept=None,
                                                   reference_terms=["great escape"], discovery_evidence=[])
    assert not ungrounded.grounded and ungrounded.regions[0].interests == []
    assert ungrounded.limitations[0].startswith("No reference resolved in Qloo")
