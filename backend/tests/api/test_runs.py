"""Run lifecycle with a fake app.workflows: results, failures, limits, provider checks, interruption."""

import asyncio
import sys
from typing import Any
from uuid import UUID

import httpx
import pytest

from app.core.config import get_settings
from app.db import models as m
from app.db.base import utcnow
from app.db.session import session
from app.services import runs as run_engine
from tests.api import fake_workflows
from tests.api.test_crud import CONTENT, make_campaign, make_project
from tests.conftest import BOB, wait_for_run

API = "/api/v1"
JAPAN = {"country_code": "JP", "display_name": "Japan"}
CRITERIA = {"clarity": 0.3, "brand_fidelity": 0.25, "cultural_relevance": 0.3, "cultural_risk": 0.15}


@pytest.fixture
def fake(monkeypatch: pytest.MonkeyPatch) -> fake_workflows.FakeWorkflows:
    return fake_workflows.install(monkeypatch)


def configure(monkeypatch: pytest.MonkeyPatch, **values: str) -> None:
    for name, value in values.items():
        monkeypatch.setenv(name, value)
    get_settings.cache_clear()


QLOO = {"QLOO_API_KEY": "test-key", "QLOO_BIN": sys.executable}  # any existing file counts as a runnable command
LLM = {"NEBIUS_API_KEY": "test-key", "NEBIUS_DEFAULT_MODEL": "test-model"}


@pytest.fixture
def live_providers(monkeypatch: pytest.MonkeyPatch) -> None:
    configure(monkeypatch, **QLOO, **LLM)


async def start(client: httpx.AsyncClient, url: str, body: dict[str, Any], **kwargs: Any) -> dict[str, Any]:
    response = await client.post(url, json=body, **kwargs)
    assert response.status_code == 202, response.text
    accepted = response.json()
    assert accepted["status"] == "queued" and accepted["status_url"] == f"{API}/runs/{accepted['run_id']}"
    return accepted


def discovery_body(campaign_id: str | None = None) -> dict[str, Any]:
    return {"campaign_id": campaign_id, "product_category": "outdoor apparel", "market": JAPAN,
            "research_question": "Which interests matter?", "reference_terms": ["outdoor exploration", "minimal design"]}


def study_body(campaign_id: str) -> dict[str, Any]:
    return {"campaign_id": campaign_id, "name": "Rehearsal", "market": JAPAN, "research_questions": ["Clear?"],
            "segments": [{"label": "Hikers", "description": "Weekend hikers."}, {"label": "Urban", "description": "City buyers."}],
            "simulation_config": {"response_count": 4, "segment_count": 2, "random_seed": 7}}


async def demo_setup(client: httpx.AsyncClient, **kwargs: Any) -> tuple[dict[str, Any], dict[str, Any], dict[str, Any]]:
    project = (await client.post(f"{API}/projects/demo", **kwargs)).json()
    campaign = (await client.get(f"{API}/projects/{project['id']}/campaigns", **kwargs)).json()["items"][0]
    study = (await client.get(f"{API}/projects/{project['id']}/studies", **kwargs)).json()["items"][0]
    return project, campaign, study


async def test_full_journey_persists_and_links_results(client: httpx.AsyncClient, fake: fake_workflows.FakeWorkflows) -> None:
    project, campaign, study = await demo_setup(client)
    pid, cid, version_id = project["id"], campaign["id"], campaign["current_version"]["id"]

    # Atlas
    accepted = await start(client, f"{API}/projects/{pid}/discoveries", discovery_body(cid))
    run = await wait_for_run(client, accepted["run_id"])
    assert run["status"] == "completed" and run["mode"] == "demo" and run["campaign_id"] == cid
    assert run["progress"] == {"stage": "completed", "completed_steps": 4, "total_steps": 4, "message": "Complete (demo fixtures)."}
    assert run["result"] == {"resource": "discovery", "ids": [run["id"]], "url": f"{API}/projects/{pid}/discoveries/{run['id']}"}
    assert run["started_at"] and run["completed_at"] and run["error"] is None
    discovery = (await client.get(run["result"]["url"])).json()
    assert discovery["status"] == "completed" and discovery["product_category"] == "outdoor apparel"
    assert [r["match_status"] for r in discovery["references"]] == ["resolved", "ambiguous"]
    assert len(discovery["evidence"]) == 2 and discovery["market_brief"]["observations"][0]["confidence_label"] == "moderate"
    assert [s["stage"] for s in discovery["run_metadata"]["steps"]] == list(run_engine.STAGES["market_discovery"])
    workflow_input = fake.inputs["market_discovery"]
    assert workflow_input.context.mode == "demo" and workflow_input.context.brand.name == "Northstar"
    assert workflow_input.campaign_content.headline == "Find your next great escape"

    # Audience, grounded only by the resolved Qloo evidence
    accepted = await start(client, f"{API}/studies/{study['id']}/rehearsals", {"discovery_run_id": discovery["run_id"]})
    run = await wait_for_run(client, accepted["run_id"])
    assert run["status"] == "completed" and run["study_id"] == study["id"]
    rehearsal = (await client.get(run["result"]["url"])).json()
    observed = [e for e in discovery["evidence"] if e["evidence_type"] == "qloo_source"]
    assert rehearsal["simulation_disclosure"]["grounded"] is True
    assert rehearsal["simulation_disclosure"]["grounding_evidence_count"] == 1
    assert len(rehearsal["reactions"]) == 6 and all(r["is_synthetic"] for r in rehearsal["reactions"])
    assert rehearsal["content_version_id"] == version_id and rehearsal["content"] == campaign["current_version"]["content"]
    assert {e["id"] for e in rehearsal["evidence"]} >= {observed[0]["id"]}
    assert (await client.get(f"{API}/studies/{study['id']}")).json()["latest_rehearsal_run_id"] == run["id"]

    # Voice
    accepted = await start(client, f"{API}/campaigns/{cid}/adaptations", {
        "market": JAPAN, "discovery_run_id": discovery["run_id"], "rehearsal_run_id": rehearsal["run_id"], "variant_count": 2})
    run = await wait_for_run(client, accepted["run_id"])
    assert run["status"] == "completed" and run["result"]["resource"] == "adaptations" and len(run["result"]["ids"]) == 2
    assert fake.inputs["campaign_adaptation"].protected_terms == ["Northstar"]
    assert fake.inputs["campaign_adaptation"].rehearsal_summary is not None
    page = (await client.get(run["result"]["url"])).json()
    assert page["total"] == 2 and [a["label"] for a in page["items"]] == ["Variant 1", "Variant 2"]
    adaptation = page["items"][0]
    assert adaptation["evidence"][0]["id"] == observed[0]["id"] and adaptation["context"]["grounded"] is True
    assert (await client.get(f"{API}/adaptations/{adaptation['id']}")).json() == adaptation

    # A user edit reruns only the deterministic checks.
    revision = await client.post(f"{API}/adaptations/{adaptation['id']}/revisions",
                                 json={"content": CONTENT | {"headline": "Cheap gear"}, "note": "Shorter."})
    assert revision.status_code == 201, revision.text
    edited = revision.json()
    assert edited["origin"] == "user_edit" and edited["run_id"] is None and edited["parent_adaptation_id"] == adaptation["id"]
    assert edited["checks"]["prohibited_terms_found"] == ["cheap"] and edited["checks"]["brand_voice_reviewed"] is False
    assert edited["warnings"][0]["source"] == "deterministic_check" and edited["context"]["grounded"] is False
    assert [(c["field"], c["reasoning_type"]) for c in edited["changes"]] == [
        ("headline", "user_edit"), ("body", "user_edit"), ("call_to_action", "user_edit")]
    assert edited["changes"][0]["original"] == adaptation["content"]["headline"] and edited["evidence"] == []
    body_only = (await client.post(f"{API}/adaptations/{adaptation['id']}/revisions", json={
        "content": adaptation["content"] | {"body": "Built for long weekends."}})).json()
    assert [(c["field"], c["reasoning_type"], c["original"]) for c in body_only["changes"]] == [
        ("body", "user_edit", adaptation["content"]["body"])]  # only the person's edit; the model's stay on the parent
    assert body_only["evidence"] == []

    # Loop
    accepted = await start(client, f"{API}/campaigns/{cid}/evaluations", {
        "source_content_version_id": version_id, "candidate_adaptation_ids": [adaptation["id"], edited["id"]],
        "market": JAPAN, "criteria": CRITERIA, "context": {"discovery_run_id": discovery["run_id"],
                                                          "baseline_rehearsal_run_id": rehearsal["run_id"]}})
    run = await wait_for_run(client, accepted["run_id"])
    assert run["status"] == "completed" and run["result"]["resource"] == "evaluation"
    evaluation = (await client.get(run["result"]["url"])).json()
    assert evaluation["id"] == run["result"]["ids"][0] and evaluation["run_id"] == run["id"]
    assert [r["candidate_type"] for r in evaluation["results"]] == ["original", "adaptation", "adaptation"]
    assert evaluation["criteria"] == CRITERIA and evaluation["recommendation"]["decision"] == "accept"
    assert len(evaluation["evidence"]) == 1
    assert [c.id for c in fake.inputs["campaign_evaluation"].candidates] == [
        fake.inputs["campaign_evaluation"].candidates[0].id, fake.inputs["campaign_evaluation"].candidates[1].id]

    # Proof lists
    runs_page = (await client.get(f"{API}/projects/{pid}/runs")).json()
    assert [r["run_type"] for r in runs_page["items"]] == [
        "campaign_evaluation", "campaign_adaptation", "campaign_rehearsal", "market_discovery"]
    assert (await client.get(f"{API}/projects/{pid}/runs", params={"run_type": "market_discovery"})).json()["total"] == 1
    assert (await client.get(f"{API}/projects/{pid}/runs", params={"study_id": study["id"]})).json()["total"] == 1
    assert (await client.get(f"{API}/projects/{pid}/runs", params={"status": "failed"})).json()["total"] == 0
    evidence = (await client.get(f"{API}/projects/{pid}/evidence", params={"run_id": discovery["run_id"]})).json()
    assert evidence["total"] == 2
    typed = (await client.get(f"{API}/projects/{pid}/evidence", params={"evidence_type": "qloo_source"})).json()
    assert typed["total"] == 1 and typed["items"][0]["retrieval_mode"] == "fixture" and typed["items"][0]["is_live_data"] is False
    assert (await client.get(f"{API}/evidence/{observed[0]['id']}")).json() == observed[0]
    assert (await client.get(f"{API}/evidence/{observed[0]['id']}", headers=BOB)).status_code == 404
    assert (await client.get(f"{API}/runs/{run['id']}", headers=BOB)).status_code == 404
    assert (await client.get(f"{API}/campaigns/{cid}/evaluations/{evaluation['id']}", headers=BOB)).status_code == 404


async def test_failed_and_partial_outcomes(client: httpx.AsyncClient, fake: fake_workflows.FakeWorkflows) -> None:
    project, campaign, study = await demo_setup(client)
    fake.status["market_discovery"] = "failed"
    failed = await wait_for_run(client, (await start(client, f"{API}/projects/{project['id']}/discoveries", discovery_body()))["run_id"])
    assert failed["status"] == "failed" and failed["result"] is None
    assert failed["error"]["code"] == "PROVIDER_ERROR" and failed["error"]["retryable"] is True
    assert failed["progress"]["stage"] == failed["error"]["stage"] == "retrieving_affinities"
    result = (await client.get(f"{API}/projects/{project['id']}/discoveries/{failed['id']}")).json()
    assert result["status"] == "failed" and result["references"] == [] and result["market_brief"] is None

    fake.status["market_discovery"] = "partial"
    partial = await wait_for_run(client, (await start(client, f"{API}/projects/{project['id']}/discoveries", discovery_body()))["run_id"])
    assert partial["status"] == "partial" and partial["result"]["resource"] == "discovery"
    assert partial["progress"]["stage"] == "completed"
    result = (await client.get(partial["result"]["url"])).json()
    assert result["market_brief"] is None and result["limitations"] == ["The brief could not be generated."]

    # A failed discovery cannot ground a rehearsal; a partial one can.
    refused = await client.post(f"{API}/studies/{study['id']}/rehearsals", json={"discovery_run_id": failed["id"]})
    assert refused.status_code == 409 and refused.json()["error"]["details"][0]["field"] == "discovery_run_id"
    await start(client, f"{API}/studies/{study['id']}/rehearsals", {"discovery_run_id": partial["id"]})


async def test_unexpected_workflow_error_is_internal_error(client: httpx.AsyncClient, fake: fake_workflows.FakeWorkflows) -> None:
    project, _, _ = await demo_setup(client)
    fake.raise_in.add("market_discovery")
    run = await wait_for_run(client, (await start(client, f"{API}/projects/{project['id']}/discoveries", discovery_body()))["run_id"])
    assert run["status"] == "failed" and run["error"]["code"] == "INTERNAL_ERROR"
    assert "simulated" not in run["error"]["message"]


async def test_demo_run_refuses_live_labeled_evidence(client: httpx.AsyncClient, fake: fake_workflows.FakeWorkflows) -> None:
    project, _, _ = await demo_setup(client)
    fake.mislabel_live = True
    run = await wait_for_run(client, (await start(client, f"{API}/projects/{project['id']}/discoveries", discovery_body()))["run_id"])
    assert run["status"] == "failed"
    assert (await client.get(f"{API}/projects/{project['id']}/evidence")).json()["total"] == 0


async def test_active_run_limit_and_in_progress_results(client: httpx.AsyncClient, fake: fake_workflows.FakeWorkflows) -> None:
    project, _, study = await demo_setup(client)
    fake.block = asyncio.Event()
    url = f"{API}/projects/{project['id']}/discoveries"
    first = await start(client, url, discovery_body())
    second = await start(client, f"{API}/studies/{study['id']}/rehearsals", {})

    limited = await client.post(url, json=discovery_body())
    assert limited.status_code == 429 and limited.json()["error"]["code"] == "RATE_LIMITED"
    assert (await client.get(f"{API}/projects/{project['id']}/runs")).json()["total"] == 2
    other_user, _, _ = await demo_setup(client, headers=BOB)
    await start(client, f"{API}/projects/{other_user['id']}/discoveries", discovery_body(), headers=BOB)  # per-user limit

    for _ in range(100):  # let the blocked runs report progress
        run = (await client.get(f"{API}/runs/{first['run_id']}")).json()
        if run["status"] == "running" and run["progress"]["completed_steps"] == 3:
            break
        await asyncio.sleep(0.01)
    assert run["progress"]["stage"] == "generating_brief" and run["result"] is None
    in_progress = (await client.get(f"{API}/projects/{project['id']}/discoveries/{first['run_id']}")).json()
    assert in_progress["status"] == "running" and in_progress["references"] == []
    rehearsal = (await client.get(f"{API}/studies/{study['id']}/rehearsals/{second['run_id']}")).json()
    assert rehearsal["simulation_disclosure"]["generated_responses"] == 0 and rehearsal["reactions"] == []

    fake.block.set()
    await run_engine.wait_idle()
    assert (await client.get(f"{API}/runs/{first['run_id']}")).json()["status"] == "completed"
    await start(client, url, discovery_body())


async def test_live_runs_need_configured_providers(client: httpx.AsyncClient, fake: fake_workflows.FakeWorkflows,
                                                    monkeypatch: pytest.MonkeyPatch) -> None:
    project = await make_project(client)
    campaign = await make_campaign(client, project["id"])
    study = (await client.post(f"{API}/projects/{project['id']}/studies", json=study_body(campaign["id"]))).json()

    response = await client.post(f"{API}/projects/{project['id']}/discoveries", json=discovery_body())
    assert response.status_code == 503
    assert response.json()["error"] == {
        "code": "PROVIDER_NOT_CONFIGURED", "details": [], "request_id": response.headers["X-Request-ID"],
        "message": "Live discovery is unavailable: Qloo is not configured on the server. Use a demo project or configure Qloo."}
    assert (await client.post(f"{API}/studies/{study['id']}/rehearsals", json={})).status_code == 503
    assert (await client.post(f"{API}/campaigns/{campaign['id']}/adaptations", json={"market": JAPAN})).status_code == 503
    assert (await client.get(f"{API}/projects/{project['id']}/runs")).json()["total"] == 0  # nothing was created

    configure(monkeypatch, **QLOO)
    run = await wait_for_run(client, (await start(client, f"{API}/projects/{project['id']}/discoveries", discovery_body()))["run_id"])
    assert run["mode"] == "live" and fake.inputs["market_discovery"].context.mode == "live"
    assert (await client.post(f"{API}/studies/{study['id']}/rehearsals", json={})).status_code == 503  # still no LLM


async def test_body_references_are_checked(client: httpx.AsyncClient, fake: fake_workflows.FakeWorkflows, live_providers: None) -> None:
    project = await make_project(client)
    campaign = await make_campaign(client, project["id"])
    other = await make_campaign(client, project["id"], CONTENT | {"headline": "Other"})
    v1 = campaign["current_version"]["id"]
    run = await wait_for_run(client, (await start(client, f"{API}/campaigns/{campaign['id']}/adaptations",
                                                    {"market": JAPAN, "variant_count": 1}))["run_id"])
    adaptation_id = run["result"]["ids"][0]
    v2 = (await client.patch(f"{API}/campaigns/{campaign['id']}", json={"original_content": CONTENT | {"body": "New."}})).json()

    def evaluation(**overrides: Any) -> dict[str, Any]:
        return {"source_content_version_id": v1, "candidate_adaptation_ids": [adaptation_id], "market": JAPAN,
                "criteria": CRITERIA} | overrides

    url = f"{API}/campaigns/{campaign['id']}/evaluations"
    wrong_version = await client.post(url, json=evaluation(source_content_version_id=v2["current_version"]["id"]))
    assert wrong_version.status_code == 409
    assert wrong_version.json()["error"]["details"][0]["field"] == "candidate_adaptation_ids.0"
    other_campaign = await client.post(f"{API}/campaigns/{other['id']}/evaluations",
                                       json=evaluation(source_content_version_id=other["current_version"]["id"]))
    assert other_campaign.status_code == 409
    foreign_version = await client.post(url, json=evaluation(source_content_version_id=other["current_version"]["id"]))
    assert foreign_version.status_code == 409
    assert foreign_version.json()["error"]["details"][0]["field"] == "source_content_version_id"
    unknown = await client.post(url, json=evaluation(candidate_adaptation_ids=[project["id"]]))
    assert unknown.status_code == 404
    bad_weights = await client.post(url, json=evaluation(criteria=CRITERIA | {"clarity": 0.9}))
    assert bad_weights.status_code == 422
    discovery_as_rehearsal = await client.post(f"{API}/campaigns/{campaign['id']}/adaptations",
                                               json={"market": JAPAN, "rehearsal_run_id": run["id"]})
    assert discovery_as_rehearsal.status_code == 409  # an adaptation run is not a rehearsal
    bob = await client.post(url, json=evaluation(), headers=BOB)
    assert bob.status_code == 404
    accepted = await start(client, url, evaluation())
    assert (await wait_for_run(client, accepted["run_id"]))["status"] == "completed"


async def test_archived_project_cannot_start_runs(client: httpx.AsyncClient, fake: fake_workflows.FakeWorkflows) -> None:
    project, _, _ = await demo_setup(client)
    await client.delete(f"{API}/projects/{project['id']}")
    response = await client.post(f"{API}/projects/{project['id']}/discoveries", json=discovery_body())
    assert response.status_code == 409


async def test_startup_sweep_marks_interrupted_runs(client: httpx.AsyncClient) -> None:
    project, _, _ = await demo_setup(client)
    async with session() as s, s.begin():
        for status in ("queued", "running", "completed"):
            s.add(m.AgentRun(project_id=UUID(project["id"]), run_type="market_discovery", status=status, mode="demo",
                             inputs={}, steps=[], created_at=utcnow(),
                             progress={"stage": "retrieving_affinities", "completed_steps": 1, "total_steps": 4,
                                       "message": "Retrieving."} if status == "running" else None))
    assert await run_engine.mark_interrupted_runs() == 2
    runs = (await client.get(f"{API}/projects/{project['id']}/runs")).json()["items"]
    interrupted = [r for r in runs if r["status"] == "failed"]
    assert len(interrupted) == 2 and all(r["error"]["code"] == "RUN_INTERRUPTED" and r["error"]["retryable"] for r in interrupted)
    assert {r["error"]["stage"] for r in interrupted} == {None, "retrieving_affinities"}
    assert sum(r["status"] == "completed" for r in runs) == 1


async def test_demo_scope_is_enforced(client: httpx.AsyncClient, fake: fake_workflows.FakeWorkflows) -> None:
    project, campaign, study = await demo_setup(client)
    assert study["simulation_config"] == {"response_count": 6, "segment_count": 3, "random_seed": 42}
    assert [s["label"] for s in study["segments"]] == ["Weekend hikers", "Design-led urban buyers", "Experienced mountaineers"]
    france = {"country_code": "FR", "display_name": "France"}
    for url, body in (
        (f"{API}/projects/{project['id']}/discoveries", discovery_body() | {"market": france}),
        (f"{API}/campaigns/{campaign['id']}/adaptations", {"market": france}),
    ):
        response = await client.post(url, json=body)
        assert response.status_code == 409, url
        assert response.json()["error"]["details"][0]["field"] == "market.country_code"
    created = await client.post(f"{API}/projects/{project['id']}/studies", json=study_body(campaign["id"]))
    assert created.status_code == 409
    assert (await client.get(f"{API}/projects/{project['id']}/runs")).json()["total"] == 0
