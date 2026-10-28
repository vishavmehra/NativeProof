"""Contract v2 run-backed features in a demo project with the REAL workflows (fixture Qloo and LLM, no network)."""

from typing import Any

import httpx
import pytest

from tests.api.test_demo_journey import offline  # noqa: F401  (fixture: blocks outbound HTTP and subprocesses)
from tests.api.test_runs import CRITERIA, JAPAN
from tests.conftest import BOB, wait_for_run

API = "/api/v1"
FRANCE = {"country_code": "FR", "display_name": "France"}
USABLE = {"completed", "partial"}


async def finish(client: httpx.AsyncClient, url: str, body: dict[str, Any]) -> dict[str, Any]:
    response = await client.post(url, json=body)
    assert response.status_code == 202, response.text
    run = await wait_for_run(client, response.json()["run_id"], timeout=60)
    assert run["status"] in USABLE, run["error"]
    assert run["progress"]["stage"] == "completed" and run["mode"] == "demo"
    return run


@pytest.fixture
async def demo(client: httpx.AsyncClient) -> dict[str, Any]:
    project = (await client.post(f"{API}/projects/demo")).json()
    campaign = (await client.get(f"{API}/projects/{project['id']}/campaigns")).json()["items"][0]
    study = (await client.get(f"{API}/projects/{project['id']}/studies")).json()["items"][0]
    discovery = await finish(client, f"{API}/projects/{project['id']}/discoveries", {
        "campaign_id": campaign["id"], "product_category": "outdoor lifestyle apparel", "market": JAPAN,
        "research_question": "Which cultural interests could inform this launch?", "reference_terms": ["hiking", "great escape"]})
    return {"project": project, "campaign": campaign, "study": study, "discovery": discovery}


async def test_cultural_profiles_version_under_one_lineage(client: httpx.AsyncClient, offline: Any, demo: dict[str, Any]) -> None:
    pid = demo["project"]["id"]
    body = {"subject": "brand", "title": "Northstar in Japan", "markets": [JAPAN]}
    run = await finish(client, f"{API}/projects/{pid}/cultural-profiles", body)
    assert run["result"]["resource"] == "cultural_profile"
    first = (await client.get(run["result"]["url"])).json()
    assert first["version"] == 1 and first["status"] in USABLE and first["brand_name"] == "Northstar"
    assert first["source_discovery_run_ids"] == [demo["discovery"]["id"]]
    for item in first["items"]:
        assert item["evidence_ids"] or (item["claim_type"] == "hypothesis" and item["confidence_label"] == "insufficient")
    run2 = await finish(client, f"{API}/projects/{pid}/cultural-profiles", body | {"based_on_profile_id": first["id"]})
    second = (await client.get(run2["result"]["url"])).json()
    assert second["version"] == 2 and second["lineage_id"] == first["lineage_id"] and second["id"] != first["id"]
    assert (await client.get(f"{API}/cultural-profiles/{first['id']}")).json()["version"] == 1  # never overwritten
    patched = (await client.patch(f"{API}/cultural-profiles/{first['id']}", json={"notes": "Reviewed.", "title": "Renamed"})).json()
    assert patched["notes"] == "Reviewed." and patched["title"] == "Renamed"
    assert (await client.patch(f"{API}/cultural-profiles/{first['id']}", json={"title": None})).status_code == 422
    page = (await client.get(f"{API}/projects/{pid}/cultural-profiles")).json()
    assert page["total"] == 2 and page["items"][0]["version"] == 2
    refused = await client.post(f"{API}/projects/{pid}/cultural-profiles", json=body | {"markets": [FRANCE]})
    assert refused.status_code == 409 and refused.json()["error"]["details"][0]["field"] == "markets.0.country_code"
    assert (await client.get(f"{API}/cultural-profiles/{first['id']}", headers=BOB)).status_code == 404


async def test_market_comparison_marks_non_jp_unavailable_in_demo(client: httpx.AsyncClient, offline: Any,
                                                                  demo: dict[str, Any]) -> None:
    pid = demo["project"]["id"]
    run = await finish(client, f"{API}/projects/{pid}/market-comparisons", {
        "markets": [JAPAN, FRANCE], "product_category": "outdoor apparel", "research_question": "Where first?",
        "reference_terms": ["hiking"]})
    comparison = (await client.get(run["result"]["url"])).json()
    columns = {c["market"]["country_code"]: c for c in comparison["columns"]}
    assert set(columns) == {"JP", "FR"} and columns["FR"]["status"] == "unavailable" and columns["FR"]["message"]
    assert comparison["run_id"] == run["id"] and comparison["status"] in USABLE
    assert (await client.get(f"{API}/projects/{pid}/market-comparisons")).json()["total"] == 1


async def test_arena_scores_variants_and_records_preference(client: httpx.AsyncClient, offline: Any, demo: dict[str, Any]) -> None:
    campaign, study = demo["campaign"], demo["study"]
    run = await finish(client, f"{API}/campaigns/{campaign['id']}/arenas", {
        "study_id": study["id"], "criteria": CRITERIA, "variants": [
            {"label": "Original", "content_version_id": campaign["current_version"]["id"]},
            {"label": "Custom", "content": {"headline": "Trails all weekend", "body": "Gear that keeps up."}}]})
    arena = (await client.get(run["result"]["url"])).json()
    assert [v["label"] for v in arena["variants"]] == ["Original", "Custom"]
    assert arena["simulation_disclosure"]["is_synthetic"] is True and arena["preferred_variant_id"] is None
    assert arena["variants"][1]["source"] == "custom"
    chosen = (await client.patch(f"{API}/arenas/{arena['id']}", json={"preferred_variant_id": "v1"})).json()
    assert chosen["preferred_variant_id"] == "v1"
    bad = await client.patch(f"{API}/arenas/{arena['id']}", json={"preferred_variant_id": "v9"})
    assert bad.status_code == 409
    assert (await client.get(f"{API}/campaigns/{campaign['id']}/arenas")).json()["items"][0]["preferred_variant_id"] == "v1"


async def test_risk_scan_findings_review_and_apply(client: httpx.AsyncClient, offline: Any, demo: dict[str, Any]) -> None:
    campaign = demo["campaign"]
    run = await finish(client, f"{API}/campaigns/{campaign['id']}/risk-scans", {"market": JAPAN})
    scan = (await client.get(run["result"]["url"])).json()
    assert scan["source_kind"] == "content_version" and scan["source_id"] == campaign["current_version"]["id"]
    assert scan["findings"] and all(f["status"] == "open" for f in scan["findings"])
    assert scan["counts"]["open"] == len(scan["findings"])
    finding = scan["findings"][0]
    url = f"{API}/risk-scans/{scan['id']}/findings/{finding['id']}"
    dismissed = (await client.patch(url, json={"status": "dismissed", "note": "Acceptable."})).json()
    assert dismissed["status"] == "dismissed" and dismissed["status_note"] == "Acceptable."
    assert (await client.patch(url, json={"status": "open"})).json()["status"] == "open"
    applicable = [f for f in scan["findings"] if f["suggested_alternative"] and f["text_location"]]
    if applicable:
        target = applicable[0]
        applied = await client.post(f"{API}/risk-scans/{scan['id']}/findings/{target['id']}/apply")
        assert applied.status_code == 201, applied.text
        adaptation = applied.json()
        assert adaptation["origin"] == "user_edit" and adaptation["changes"][0]["reasoning_type"] == "user_edit"
        assert target["suggested_alternative"] in adaptation["content"][target["text_location"]["field"]]
        after = (await client.get(f"{API}/risk-scans/{scan['id']}")).json()
        assert {f["id"]: f["status"] for f in after["findings"]}[target["id"]] == "applied"
        closed = await client.patch(f"{API}/risk-scans/{scan['id']}/findings/{target['id']}", json={"status": "open"})
        assert closed.status_code == 409
        campaign_now = (await client.get(f"{API}/campaigns/{campaign['id']}")).json()
        assert campaign_now["current_version"]["id"] == campaign["current_version"]["id"]  # never edited in place
    refused = await client.post(f"{API}/campaigns/{campaign['id']}/risk-scans", json={"market": FRANCE})
    assert refused.status_code == 409
    assert (await client.get(f"{API}/risk-scans/{scan['id']}", headers=BOB)).status_code == 404
