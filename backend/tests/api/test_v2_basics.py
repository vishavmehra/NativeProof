"""Contract v2: Brand Memory, Trend Watch (deterministic), and the Evidence Graph (persisted links only)."""

from datetime import datetime
from typing import Any

import httpx
import pytest

from tests.api import fake_workflows
from tests.api.test_crud import make_project
from tests.api.test_runs import CRITERIA, JAPAN, LLM, QLOO, configure, demo_setup, discovery_body, start
from tests.conftest import BOB, wait_for_run

API = "/api/v1"
BRAND = {
    "name": "Acme", "description": "Outdoor gear", "positioning": "Gear for weekends", "voice": ["calm"],
    "communication_style": "Plain", "target_audience": "Hikers", "audience_preferences": "Craft",
    "preferred_terms": ["trail"], "prohibited_terms": ["cheap"], "protected_terms": ["Acme"],
    "approved_examples": [{"text": "Go further.", "note": None}], "constraints": ["No unverified claims."],
}


@pytest.fixture
def fake(monkeypatch: pytest.MonkeyPatch) -> fake_workflows.FakeWorkflows:
    return fake_workflows.install(monkeypatch)


async def test_brand_memory(client: httpx.AsyncClient) -> None:
    project = await make_project(client)
    url = f"{API}/projects/{project['id']}/brand"
    assert (await client.get(url)).json()["name"] == "Acme"
    replaced = await client.put(url, json=BRAND)
    assert replaced.status_code == 200, replaced.text
    assert {k: v for k, v in replaced.json().items() if k not in ("id", "updated_at")} == BRAND
    assert (await client.get(url)).json() == replaced.json()
    assert (await client.get(f"{API}/projects/{project['id']}")).json()["brand"] == replaced.json()
    partial = await client.put(url, json={"name": "Only name"})  # full replacement: omitted lists become empty
    assert partial.json()["protected_terms"] == [] and partial.json()["positioning"] is None
    assert (await client.put(url, json={"name": ""})).status_code == 422
    assert (await client.get(url, headers=BOB)).status_code == 404
    assert (await client.put(url, json=BRAND, headers=BOB)).status_code == 404

    demo, _, _ = await demo_setup(client)
    demo_brand = (await client.get(f"{API}/projects/{demo['id']}/brand")).json()
    assert demo_brand["constraints"] == ["Never promise performance we have not tested."]
    locked = await client.put(f"{API}/projects/{demo['id']}/brand", json=BRAND)
    assert locked.status_code == 409 and locked.json()["error"]["code"] == "CONFLICT"
    await client.delete(f"{API}/projects/{project['id']}")
    assert (await client.put(url, json=BRAND)).status_code == 409  # archived


def test_reference_diff_is_deterministic() -> None:
    from app.services.trends import diff_references, implications_for

    def ref(term: str, status: str, entity: str | None, affinity: float | None = None) -> dict[str, Any]:
        attrs = [{"key": "affinity", "label": "Affinity", "value": affinity, "description": None}] if affinity is not None else []
        return {"query_term": term, "match_status": status, "name": entity, "entity_id": f"tag:{entity}" if entity else None,
                "entity_type": "tag" if entity else None, "attributes": attrs, "evidence_ids": []}

    before = [ref("hiking", "resolved", "Hiking", 0.5), ref("camping", "resolved", "Camping"), ref("zen", "ambiguous", None)]
    after = [ref("hiking", "resolved", "Hiking", 0.75), ref("zen", "resolved", None), ref("surf", "resolved", "Surf")]
    changes = diff_references(before, after)
    assert [(c.kind, c.reference_key) for c in changes] == [
        ("attribute_changed", "tag:Hiking"), ("removed", "tag:Camping"), ("status_changed", "zen"), ("added", "tag:Surf")]
    assert changes[0].delta == 0.25 and changes[0].before == "0.5" and changes[0].after == "0.75"
    assert diff_references(before, before)[0].kind == "unchanged"
    implications = implications_for(changes)
    assert len(implications) == 4 and all(i.claim_type == "hypothesis" for i in implications)
    assert implications == implications_for(diff_references(before, after))


async def test_snapshots_and_trend_comparisons(client: httpx.AsyncClient, fake: fake_workflows.FakeWorkflows,
                                               monkeypatch: pytest.MonkeyPatch) -> None:
    configure(monkeypatch, **QLOO, **LLM)
    project = await make_project(client)
    pid = project["id"]
    runs = []
    for market in (JAPAN, JAPAN, {"country_code": "FR", "display_name": "France"}):
        accepted = await start(client, f"{API}/projects/{pid}/discoveries", discovery_body() | {"market": market})
        runs.append(await wait_for_run(client, accepted["run_id"]))
    snaps = []
    for i, run in enumerate(runs):
        response = await client.post(f"{API}/projects/{pid}/snapshots", json={"discovery_run_id": run["id"], "label": f"S{i}"})
        assert response.status_code == 201, response.text
        snaps.append(response.json())
    assert snaps[0]["reference_count"] == 2 and snaps[0]["evidence_count"] == 2 and snaps[0]["mode"] == "live"
    parse = datetime.fromisoformat
    assert parse(snaps[0]["captured_at"]) == parse(runs[0]["completed_at"])  # when the run finished, not when saved
    assert (await client.get(f"{API}/projects/{pid}/snapshots")).json()["total"] == 3

    same = await client.post(f"{API}/projects/{pid}/trend-comparisons",
                             json={"base_snapshot_id": snaps[0]["id"], "target_snapshot_id": snaps[1]["id"]})
    assert same.status_code == 201, same.text
    comparison = same.json()
    assert comparison["comparable"] is True and comparison["change_count"] == 0 and comparison["implications"] == []
    assert {c["kind"] for c in comparison["changes"]} == {"unchanged"}
    assert (await client.get(f"{API}/trend-comparisons/{comparison['id']}")).json() == comparison
    assert (await client.get(f"{API}/projects/{pid}/trend-comparisons")).json()["items"][0]["id"] == comparison["id"]

    other_market = (await client.post(f"{API}/projects/{pid}/trend-comparisons",
                                      json={"base_snapshot_id": snaps[0]["id"], "target_snapshot_id": snaps[2]["id"]})).json()
    assert other_market["comparable"] is False and "Markets differ" in other_market["comparability_notes"][0]

    twice = await client.post(f"{API}/projects/{pid}/trend-comparisons",
                              json={"base_snapshot_id": snaps[0]["id"], "target_snapshot_id": snaps[0]["id"]})
    assert twice.status_code == 409
    fake.status["market_discovery"] = "failed"
    failed = await wait_for_run(client, (await start(client, f"{API}/projects/{pid}/discoveries", discovery_body()))["run_id"])
    refused = await client.post(f"{API}/projects/{pid}/snapshots", json={"discovery_run_id": failed["id"], "label": "x"})
    assert refused.status_code == 409 and refused.json()["error"]["details"][0]["field"] == "discovery_run_id"
    assert (await client.get(f"{API}/trend-comparisons/{comparison['id']}", headers=BOB)).status_code == 404


async def test_evidence_graph_draws_only_persisted_links(client: httpx.AsyncClient, fake: fake_workflows.FakeWorkflows) -> None:
    project, campaign, study = await demo_setup(client)
    pid, cid = project["id"], campaign["id"]
    discovery = await wait_for_run(client, (await start(client, f"{API}/projects/{pid}/discoveries", discovery_body(cid)))["run_id"])
    rehearsal = await wait_for_run(client, (await start(client, f"{API}/studies/{study['id']}/rehearsals",
                                                        {"discovery_run_id": discovery["id"]}))["run_id"])
    adaptation = await wait_for_run(client, (await start(client, f"{API}/campaigns/{cid}/adaptations", {
        "market": JAPAN, "discovery_run_id": discovery["id"], "variant_count": 1}))["run_id"])
    await wait_for_run(client, (await start(client, f"{API}/campaigns/{cid}/evaluations", {
        "source_content_version_id": campaign["current_version"]["id"], "candidate_adaptation_ids": adaptation["result"]["ids"],
        "market": JAPAN, "criteria": CRITERIA}))["run_id"])

    graph = (await client.get(f"{API}/projects/{pid}/evidence-graph")).json()
    kinds = {n["kind"] for n in graph["nodes"]}
    assert {"campaign", "content_version", "run", "source_signal", "adaptation", "evaluation"} <= kinds
    ids = {n["id"] for n in graph["nodes"]}
    assert graph["edges"] and all(e["source"] in ids and e["target"] in ids and e["provenance"] for e in graph["edges"])
    relations = {(e["relation"], e["provenance"]) for e in graph["edges"]}
    assert ("supports", "adaptations.evidence_ids") in relations
    assert ("evaluates", "evaluations.results[].adaptation_id") in relations
    assert ("produced", "evidence_records.source_run_id") in relations
    assert all(n["is_demo"] for n in graph["nodes"]) and graph["truncated"] is False

    scoped = (await client.get(f"{API}/projects/{pid}/evidence-graph", params={"campaign_id": cid})).json()
    assert {n["id"] for n in scoped["nodes"]} <= ids and scoped["campaign_id"] == cid
    small = (await client.get(f"{API}/projects/{pid}/evidence-graph", params={"limit": 10})).json()
    assert len(small["nodes"]) == 10 and small["truncated"] is True
    note = next(x for x in small["limitations"] if x.startswith("Capped at 10 nodes"))
    assert f"showing 10 of {len(graph['nodes'])} nodes and {len(small['edges'])} of {len(graph['edges'])} links" in note
    kept = {n["id"] for n in small["nodes"]}
    assert all(e["source"] in kept and e["target"] in kept for e in small["edges"])
    assert not any(x.startswith("Capped") for x in graph["limitations"])
    assert (await client.get(f"{API}/projects/{pid}/evidence-graph", headers=BOB)).status_code == 404

    typed = (await client.get(f"{API}/projects/{pid}/evidence-graph", params={"evidence_type": "qloo_source"})).json()
    assert {n["evidence_type"] for n in typed["nodes"]} - {None} == {"qloo_source"}
    assert any("Evidence filtered to type qloo_source" in x for x in typed["limitations"])
    elsewhere = (await client.get(f"{API}/projects/{pid}/evidence-graph", params={"region": "FR"})).json()
    kinds = {n["kind"] for n in elsewhere["nodes"]}
    assert "campaign" in kinds and not kinds & {"run", "source_signal", "adaptation", "evaluation"}  # all demo work is JP
    here = (await client.get(f"{API}/projects/{pid}/evidence-graph", params={"region": "JP"})).json()
    assert {n["id"] for n in here["nodes"]} == ids
    assert (await client.get(f"{API}/projects/{pid}/evidence-graph", params={"region": "jp"})).status_code == 422
    assert rehearsal["status"] == "completed"
