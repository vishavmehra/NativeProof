"""Proof reports: deterministic assembly, partial reports, reference checks, versioning, and exports."""

import json
from typing import Any

import httpx
import pytest

from tests.api import fake_workflows
from tests.api.test_crud import CONTENT, make_campaign, make_project
from tests.api.test_runs import CRITERIA, JAPAN, LLM, QLOO, configure, demo_setup, discovery_body, start, study_body
from tests.conftest import BOB, wait_for_run

API = "/api/v1"


@pytest.fixture
def fake(monkeypatch: pytest.MonkeyPatch) -> fake_workflows.FakeWorkflows:
    return fake_workflows.install(monkeypatch)


async def journey(client: httpx.AsyncClient) -> dict[str, Any]:
    project, campaign, study = await demo_setup(client)
    pid, cid = project["id"], campaign["id"]
    discovery = await wait_for_run(client, (await start(client, f"{API}/projects/{pid}/discoveries", discovery_body(cid)))["run_id"])
    rehearsal = await wait_for_run(client, (await start(client, f"{API}/studies/{study['id']}/rehearsals",
                                                        {"discovery_run_id": discovery["id"]}))["run_id"])
    adaptation = await wait_for_run(client, (await start(client, f"{API}/campaigns/{cid}/adaptations", {
        "market": JAPAN, "discovery_run_id": discovery["id"], "rehearsal_run_id": rehearsal["id"], "variant_count": 2}))["run_id"])
    evaluation = await wait_for_run(client, (await start(client, f"{API}/campaigns/{cid}/evaluations", {
        "source_content_version_id": campaign["current_version"]["id"], "candidate_adaptation_ids": adaptation["result"]["ids"],
        "market": JAPAN, "criteria": CRITERIA}))["run_id"])
    return {"project": project, "campaign": campaign, "discovery": discovery, "rehearsal": rehearsal,
            "adaptation_ids": adaptation["result"]["ids"], "evaluation_id": evaluation["result"]["ids"][0]}


async def test_full_report_snapshot_versions_and_exports(client: httpx.AsyncClient, fake: fake_workflows.FakeWorkflows) -> None:
    j = await journey(client)
    pid, cid = j["project"]["id"], j["campaign"]["id"]
    body = {"campaign_id": cid, "title": "Japan Launch Cultural Review", "discovery_run_id": j["discovery"]["id"],
            "rehearsal_run_id": j["rehearsal"]["id"], "adaptation_ids": j["adaptation_ids"], "evaluation_id": j["evaluation_id"]}
    response = await client.post(f"{API}/projects/{pid}/reports", json=body)
    assert response.status_code == 201, response.text
    report = response.json()
    assert report["status"] == "completed" and report["missing_sections"] == [] and report["version_number"] == 1
    assert report["mode"] == "demo" and report["market"] == JAPAN
    assert report["campaign"]["content"]["headline"] == "Find your next great escape"
    assert report["discovery"]["run_id"] == j["discovery"]["id"] and report["rehearsal"]["run_id"] == j["rehearsal"]["id"]
    assert [a["id"] for a in report["adaptations"]] == j["adaptation_ids"] and report["evaluation"]["id"] == j["evaluation_id"]
    ids = [e["id"] for e in report["evidence_register"]]
    assert len(ids) == len(set(ids)) >= 4
    assert len(report["reproducibility"]["runs"]) == 4 and report["reproducibility"]["scoring_version"] == "mvp-1"
    assert report["reproducibility"]["model_ids"] == ["fixture-model"]
    assert any("Demo mode" in item for item in report["limitations"])
    assert any("not responses from real people" in item for item in report["executive_summary"]["uncertainties"])
    assert report["validation_steps"] and report["executive_summary"]["findings"]

    assert (await client.get(f"{API}/reports/{report['id']}")).json() == report
    assert (await client.get(f"{API}/reports/{report['id']}", headers=BOB)).status_code == 404
    again = (await client.post(f"{API}/projects/{pid}/reports", json=body)).json()
    assert again["version_number"] == 2
    listed = (await client.get(f"{API}/projects/{pid}/reports", params={"campaign_id": cid})).json()
    assert listed["total"] == 2 and listed["items"][0]["version_number"] == 2 and "evidence_register" not in listed["items"][0]

    markdown = await client.get(f"{API}/reports/{report['id']}/export", params={"format": "markdown"})
    assert markdown.status_code == 200 and markdown.headers["content-type"].startswith("text/markdown")
    assert markdown.headers["content-disposition"] == 'attachment; filename="nativeproof-japan-launch-cultural-review-v1.md"'
    text = markdown.text
    assert text.startswith("# Japan Launch Cultural Review\n\n> **DEMO DATA — fixture results, not live research.**")
    for expected in ("**Synthetic data:**", "| Source data | Fixture |", "| Calculated | — |", "Model interpretation",
                     "## Limitations", "## Evidence register", "not an independent human sample", "R4_meets_review_threshold"):
        assert expected in text, expected
    exported = await client.get(f"{API}/reports/{report['id']}/export", params={"format": "json"})
    assert exported.headers["content-disposition"].endswith('-v1.json"') and json.loads(exported.content) == report
    assert (await client.get(f"{API}/reports/{report['id']}/export", params={"format": "pdf"})).status_code == 422
    assert (await client.get(f"{API}/reports/{report['id']}/export", headers=BOB)).status_code == 404


async def test_missing_or_failed_stages_make_a_partial_report(client: httpx.AsyncClient, fake: fake_workflows.FakeWorkflows) -> None:
    project, campaign, _ = await demo_setup(client)
    fake.status["market_discovery"] = "failed"
    failed = await wait_for_run(client, (await start(client, f"{API}/projects/{project['id']}/discoveries", discovery_body()))["run_id"])
    report = (await client.post(f"{API}/projects/{project['id']}/reports", json={
        "campaign_id": campaign["id"], "title": "Partial", "discovery_run_id": failed["id"]})).json()
    assert report["status"] == "partial"
    assert report["missing_sections"] == ["discovery", "rehearsal", "adaptations", "evaluation"]
    assert report["discovery"] is None and report["evidence_register"] == []
    assert report["campaign"]["content_version_id"] == campaign["current_version"]["id"]
    markdown = (await client.get(f"{API}/reports/{report['id']}/export")).text
    assert "Not included" in markdown and "## Missing sections" in markdown


async def test_reports_disclose_mixed_and_outdated_content_versions(
    client: httpx.AsyncClient, fake: fake_workflows.FakeWorkflows, monkeypatch: pytest.MonkeyPatch
) -> None:
    configure(monkeypatch, **QLOO, **LLM)
    project = await make_project(client)
    campaign = await make_campaign(client, project["id"])
    pid, cid, v1 = project["id"], campaign["id"], campaign["current_version"]["id"]
    study = (await client.post(f"{API}/projects/{pid}/studies", json=study_body(cid))).json()
    rehearsal = await wait_for_run(client, (await start(client, f"{API}/studies/{study['id']}/rehearsals", {}))["run_id"])
    old = await wait_for_run(client, (await start(client, f"{API}/campaigns/{cid}/adaptations",
                                                  {"market": JAPAN, "variant_count": 1}))["run_id"])
    evaluation = await wait_for_run(client, (await start(client, f"{API}/campaigns/{cid}/evaluations", {
        "source_content_version_id": v1, "candidate_adaptation_ids": old["result"]["ids"], "market": JAPAN,
        "criteria": CRITERIA}))["run_id"])
    await client.patch(f"{API}/campaigns/{cid}", json={"original_content": CONTENT | {"headline": "Edited copy"}})
    new = await wait_for_run(client, (await start(client, f"{API}/campaigns/{cid}/adaptations",
                                                  {"market": JAPAN, "variant_count": 1}))["run_id"])
    url = f"{API}/projects/{pid}/reports"

    mixed = (await client.post(url, json={"campaign_id": cid, "title": "Mixed", "rehearsal_run_id": rehearsal["id"],
                                          "adaptation_ids": new["result"]["ids"]})).json()
    notice = next(x for x in mixed["limitations"] if x.startswith("Version notice:"))
    assert "different content versions (rehearsal v1; adaptations v2)" in notice
    assert notice not in mixed["executive_summary"]["uncertainties"]  # stated once, not repeated per section
    markdown = (await client.get(f"{API}/reports/{mixed['id']}/export")).text
    assert f"> **{notice}**" in markdown.split("## Executive summary")[0]  # shown before the content
    assert markdown.count(notice) == 1

    outdated = (await client.post(url, json={"campaign_id": cid, "title": "Outdated", "adaptation_ids": old["result"]["ids"],
                                             "evaluation_id": evaluation["result"]["ids"][0]})).json()
    assert any("copy changed after these results. The current version is v2; the results describe v1" in x
               for x in outdated["limitations"])
    current = (await client.post(url, json={"campaign_id": cid, "title": "Current", "adaptation_ids": new["result"]["ids"]})).json()
    assert not any(x.startswith("Version notice:") for x in current["limitations"])


async def test_report_references_are_checked(client: httpx.AsyncClient, fake: fake_workflows.FakeWorkflows) -> None:
    j = await journey(client)
    pid, cid = j["project"]["id"], j["campaign"]["id"]
    other, other_campaign, _ = await demo_setup(client)
    url = f"{API}/projects/{pid}/reports"
    base = {"campaign_id": cid, "title": "R"}

    wrong_type = await client.post(url, json=base | {"discovery_run_id": j["rehearsal"]["id"]})
    assert wrong_type.status_code == 409 and wrong_type.json()["error"]["details"][0]["field"] == "discovery_run_id"
    other_project = await client.post(url, json=base | {"campaign_id": other_campaign["id"]})
    assert other_project.status_code == 409
    foreign_run = await client.post(f"{API}/projects/{other['id']}/reports", json={
        "campaign_id": other_campaign["id"], "title": "R", "rehearsal_run_id": j["rehearsal"]["id"]})
    assert foreign_run.status_code == 409
    bob = await client.post(url, json=base | {"evaluation_id": j["evaluation_id"]}, headers=BOB)
    assert bob.status_code == 404
    unknown = await client.post(url, json=base | {"adaptation_ids": [pid]})
    assert unknown.status_code == 404 and unknown.json()["error"]["details"][0]["field"] == "adaptation_ids.0"
    await client.delete(f"{API}/projects/{pid}")
    assert (await client.post(url, json=base)).status_code == 409
