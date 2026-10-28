"""M1: the demo journey end to end over HTTP with the real workflows, fixture Qloo, and fixture LLM.

External calls are blocked (respx refuses every outbound HTTP request and subprocesses raise), so a
pass also shows that demo runs never reach a provider.
"""

import asyncio
from typing import Any

import httpx
import pytest
import respx

from app.schemas.runs import RunError
from tests.conftest import wait_for_run

API = "/api/v1"
JAPAN = {"country_code": "JP", "display_name": "Japan"}
USABLE = {"completed", "partial"}


@pytest.fixture
def offline(monkeypatch: pytest.MonkeyPatch) -> Any:
    async def no_subprocess(*args: Any, **kwargs: Any) -> None:
        raise AssertionError("demo runs must not start a subprocess")

    monkeypatch.setattr(asyncio, "create_subprocess_exec", no_subprocess)
    with respx.mock(assert_all_called=False) as router:  # any outbound request fails: no route matches
        yield router


async def run_to_end(client: httpx.AsyncClient, url: str, body: dict[str, Any]) -> dict[str, Any]:
    response = await client.post(url, json=body)
    assert response.status_code == 202, response.text
    run = await wait_for_run(client, response.json()["run_id"], timeout=60)
    assert run["mode"] == "demo"
    assert run["status"] in USABLE, RunError.model_validate(run["error"]) if run["error"] else run
    assert run["progress"]["stage"] == "completed"
    return run


def assert_demo_labels(evidence: list[dict[str, Any]], steps: list[dict[str, Any]]) -> None:
    assert all(e["is_live_data"] is False and e["retrieval_mode"] in {"fixture", "generated"} for e in evidence)
    assert all(e["provenance"]["fixture_origin"] for e in evidence if e["retrieval_mode"] == "fixture")
    assert all(step["provider"] in {"fixture", "nativeproof", None} for step in steps)


async def test_demo_journey_over_http(client: httpx.AsyncClient, offline: Any) -> None:
    project = (await client.post(f"{API}/projects/demo")).json()
    pid = project["id"]
    campaign = (await client.get(f"{API}/projects/{pid}/campaigns")).json()["items"][0]
    study = (await client.get(f"{API}/projects/{pid}/studies")).json()["items"][0]
    cid, version_id = campaign["id"], campaign["current_version"]["id"]

    # Discover
    run = await run_to_end(client, f"{API}/projects/{pid}/discoveries", {
        "campaign_id": cid, "product_category": "outdoor lifestyle apparel", "market": JAPAN,
        "research_question": "Which cultural interests could inform this launch?",
        "reference_terms": ["outdoor exploration", "minimal design", "great escape"]})
    discovery = (await client.get(run["result"]["url"])).json()
    assert discovery["references"] and discovery["evidence"]
    assert_demo_labels(discovery["evidence"], discovery["run_metadata"]["steps"])

    # Simulate
    run = await run_to_end(client, f"{API}/studies/{study['id']}/rehearsals", {"discovery_run_id": discovery["run_id"]})
    rehearsal = (await client.get(run["result"]["url"])).json()
    disclosure = rehearsal["simulation_disclosure"]
    assert disclosure["is_synthetic"] is True and disclosure["independent_human_sample"] is False
    assert len(rehearsal["reactions"]) == disclosure["generated_responses"] > 0
    assert all(r["is_synthetic"] for r in rehearsal["reactions"])
    assert_demo_labels(rehearsal["evidence"], rehearsal["run_metadata"]["steps"])

    # Adapt
    run = await run_to_end(client, f"{API}/campaigns/{cid}/adaptations", {
        "market": JAPAN, "discovery_run_id": discovery["run_id"], "rehearsal_run_id": rehearsal["run_id"]})
    adaptations = (await client.get(run["result"]["url"])).json()["items"]
    assert 1 <= len(adaptations) <= 3 and {a["id"] for a in adaptations} == set(run["result"]["ids"])
    assert all(a["mode"] == "demo" and a["source_content_version_id"] == version_id for a in adaptations)

    # Compare
    run = await run_to_end(client, f"{API}/campaigns/{cid}/evaluations", {
        "source_content_version_id": version_id, "candidate_adaptation_ids": [a["id"] for a in adaptations],
        "market": JAPAN, "criteria": campaign["evaluation_criteria"],
        "context": {"discovery_run_id": discovery["run_id"], "baseline_rehearsal_run_id": rehearsal["run_id"]}})
    evaluation = (await client.get(run["result"]["url"])).json()
    assert evaluation["results"][0]["candidate_type"] == "original" and len(evaluation["results"]) == len(adaptations) + 1
    assert evaluation["recommendation"] is not None and evaluation["scoring_version"] == "mvp-1"

    # Prove
    response = await client.post(f"{API}/projects/{pid}/reports", json={
        "campaign_id": cid, "title": "Japan Launch Cultural Review", "discovery_run_id": discovery["run_id"],
        "rehearsal_run_id": rehearsal["run_id"], "adaptation_ids": [a["id"] for a in adaptations],
        "evaluation_id": evaluation["id"]})
    assert response.status_code == 201, response.text
    report = response.json()
    assert report["status"] == "completed" and report["missing_sections"] == [] and report["mode"] == "demo"
    assert_demo_labels(report["evidence_register"], [s for r in report["reproducibility"]["runs"] for s in r["steps"]])
    markdown = (await client.get(f"{API}/reports/{report['id']}/export")).text
    assert markdown.startswith("# Japan Launch Cultural Review\n\n> **DEMO DATA — fixture results, not live research.**")
    assert "**Synthetic data:**" in markdown

    runs = (await client.get(f"{API}/projects/{pid}/runs")).json()
    assert runs["total"] == 4 and {r["status"] for r in runs["items"]} <= USABLE
