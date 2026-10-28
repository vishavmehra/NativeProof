"""Projects, demo seeding, campaigns and content versions, studies: ownership, archive, PATCH semantics."""

import json
from pathlib import Path
from typing import Any

import httpx

from tests.conftest import BOB

API = "/api/v1"
FIXTURES = Path(__file__).resolve().parents[3] / "contracts" / "fixtures"
CONTENT = {"headline": "Find your trail", "body": "Gear for weekends.", "call_to_action": "Shop", "reference_terms": ["trail"]}


async def make_project(client: httpx.AsyncClient, **extra: Any) -> dict[str, Any]:
    body = {"name": "Launch", "brand_name": "Acme", "protected_terms": ["Acme"], "target_markets": [
        {"country_code": "JP", "display_name": "Japan"}]} | extra
    response = await client.post(f"{API}/projects", json=body)
    assert response.status_code == 201, response.text
    return response.json()


async def make_campaign(client: httpx.AsyncClient, project_id: str, content: dict[str, Any] = CONTENT) -> dict[str, Any]:
    response = await client.post(
        f"{API}/projects/{project_id}/campaigns",
        json={"name": "Autumn", "campaign_type": "advertisement", "original_content": content},
    )
    assert response.status_code == 201, response.text
    return response.json()


async def test_project_lifecycle(client: httpx.AsyncClient) -> None:
    project = await make_project(client, description="d", brand_voice=["calm"])
    assert project["mode"] == "live" and project["status"] == "active"
    assert project["brand"]["name"] == "Acme" and project["brand"]["voice"] == ["calm"]

    got = await client.get(f"{API}/projects/{project['id']}")
    assert got.json() == project

    patched = (await client.patch(f"{API}/projects/{project['id']}", json={"name": "Renamed", "description": None,
                                                                          "prohibited_terms": ["cheap"]})).json()
    assert patched["name"] == "Renamed" and patched["description"] is None
    assert patched["brand"]["prohibited_terms"] == ["cheap"] and patched["brand"]["voice"] == ["calm"]
    null_name = await client.patch(f"{API}/projects/{project['id']}", json={"name": None})
    assert null_name.status_code == 422 and null_name.json()["error"]["details"][0]["field"] == "name"

    page = (await client.get(f"{API}/projects")).json()
    assert page["total"] == 1 and page["items"][0]["brand_name"] == "Acme" and page["items"][0]["last_activity_at"]

    assert (await client.delete(f"{API}/projects/{project['id']}")).status_code == 204
    assert (await client.get(f"{API}/projects")).json()["total"] == 0
    assert (await client.get(f"{API}/projects", params={"include_archived": True})).json()["total"] == 1
    archived = await client.get(f"{API}/projects/{project['id']}")
    assert archived.json()["status"] == "archived"
    for response in (
        await client.patch(f"{API}/projects/{project['id']}", json={"name": "x"}),
        await client.post(f"{API}/projects/{project['id']}/campaigns",
                          json={"name": "C", "campaign_type": "slogan", "original_content": CONTENT}),
    ):
        assert response.status_code == 409 and response.json()["error"]["code"] == "CONFLICT"
    assert (await client.delete(f"{API}/projects/{project['id']}")).status_code == 204  # idempotent


async def test_other_user_gets_404_everywhere(client: httpx.AsyncClient) -> None:
    project = await make_project(client)
    campaign = await make_campaign(client, project["id"])
    for method, url in (
        ("GET", f"{API}/projects/{project['id']}"),
        ("PATCH", f"{API}/projects/{project['id']}"),
        ("DELETE", f"{API}/projects/{project['id']}"),
        ("GET", f"{API}/projects/{project['id']}/campaigns"),
        ("GET", f"{API}/campaigns/{campaign['id']}"),
        ("PATCH", f"{API}/campaigns/{campaign['id']}"),
        ("GET", f"{API}/projects/{project['id']}/runs"),
        ("GET", f"{API}/projects/{project['id']}/evidence"),
        ("GET", f"{API}/projects/{project['id']}/reports"),
    ):
        response = await client.request(method, url, headers=BOB, json={} if method == "PATCH" else None)
        assert response.status_code == 404, (method, url, response.text)
        assert response.json()["error"]["code"] == "NOT_FOUND"


async def test_pagination(client: httpx.AsyncClient) -> None:
    for i in range(3):
        await make_project(client, name=f"P{i}")
    page = (await client.get(f"{API}/projects", params={"limit": 2, "offset": 0})).json()
    rest = (await client.get(f"{API}/projects", params={"limit": 2, "offset": 2})).json()
    assert page["total"] == rest["total"] == 3 and len(page["items"]) == 2 and len(rest["items"]) == 1
    assert [p["name"] for p in page["items"]] == ["P2", "P1"]  # most recent activity first


async def test_demo_project_matches_fixture_seed(client: httpx.AsyncClient) -> None:
    response = await client.post(f"{API}/projects/demo")
    assert response.status_code == 201
    project = response.json()
    expected = json.loads((FIXTURES / "Project.json").read_text(encoding="utf-8"))
    volatile = {"id", "created_at", "updated_at"}
    assert {k: v for k, v in project.items() if k not in volatile | {"brand"}} == {
        k: v for k, v in expected.items() if k not in volatile | {"brand"}}
    assert {k: v for k, v in project["brand"].items() if k not in volatile} == {
        k: v for k, v in expected["brand"].items() if k not in volatile}
    assert project["id"] != expected["id"]

    campaigns = (await client.get(f"{API}/projects/{project['id']}/campaigns")).json()
    expected_campaign = json.loads((FIXTURES / "Campaign.json").read_text(encoding="utf-8"))
    campaign = campaigns["items"][0]
    for key in ("name", "campaign_type", "objective", "target_markets", "evaluation_criteria"):
        assert campaign[key] == expected_campaign[key]
    assert campaign["current_version"]["content"] == expected_campaign["current_version"]["content"]
    assert campaign["current_version"]["version_number"] == 1

    # Demo content is fixed so the fixtures stay truthful.
    locked = await client.patch(f"{API}/campaigns/{campaign['id']}", json={"original_content": {"headline": "New"}})
    assert locked.status_code == 409
    renamed = await client.patch(f"{API}/campaigns/{campaign['id']}", json={"name": "Renamed"})
    assert renamed.status_code == 200 and renamed.json()["name"] == "Renamed"
    assert (await client.post(f"{API}/projects/{project['id']}/campaigns",
                              json={"name": "C", "campaign_type": "slogan", "original_content": CONTENT})).status_code == 409
    assert (await client.patch(f"{API}/projects/{project['id']}", json={"protected_terms": []})).status_code == 409
    assert (await client.patch(f"{API}/projects/{project['id']}", json={"name": "Mine"})).status_code == 200

    studies = (await client.get(f"{API}/projects/{project['id']}/studies")).json()
    expected_study = json.loads((FIXTURES / "Study.json").read_text(encoding="utf-8"))
    assert studies["total"] == 1 and studies["items"][0]["campaign_id"] == campaign["id"]
    for key in ("name", "market", "research_questions", "dimensions", "segments", "simulation_config"):
        assert studies["items"][0][key] == expected_study[key]


async def test_campaign_versions(client: httpx.AsyncClient) -> None:
    project = await make_project(client)
    campaign = await make_campaign(client, project["id"])
    assert campaign["current_version"]["version_number"] == 1 and len(campaign["versions"]) == 1

    same = (await client.patch(f"{API}/campaigns/{campaign['id']}", json={"original_content": CONTENT})).json()
    assert len(same["versions"]) == 1  # unchanged copy is not a new version

    new_content = CONTENT | {"headline": "Find your next trail"}
    updated = (await client.patch(f"{API}/campaigns/{campaign['id']}", json={"original_content": new_content,
                                                                             "objective": "Clarity"})).json()
    assert updated["current_version"]["version_number"] == 2
    assert updated["current_version"]["content"]["headline"] == "Find your next trail"
    assert [v["version_number"] for v in updated["versions"]] == [2, 1]
    assert updated["versions"][1]["content"] == campaign["current_version"]["content"]
    assert updated["objective"] == "Clarity"

    bad = await client.patch(f"{API}/campaigns/{campaign['id']}", json={"original_content": None})
    assert bad.status_code == 422
    weights = await client.patch(f"{API}/campaigns/{campaign['id']}", json={"evaluation_criteria": {
        "clarity": 0.5, "brand_fidelity": 0.5, "cultural_relevance": 0.5, "cultural_risk": 0}})
    assert weights.status_code == 422

    listed = (await client.get(f"{API}/projects/{project['id']}/campaigns")).json()
    assert listed["total"] == 1 and listed["items"][0]["current_version"]["version_number"] == 2


async def test_studies(client: httpx.AsyncClient) -> None:
    project = await make_project(client)
    campaign = await make_campaign(client, project["id"])
    other_project = await make_project(client, name="Other")
    other_campaign = await make_campaign(client, other_project["id"])
    body = {"campaign_id": campaign["id"], "name": "Rehearsal", "market": {"country_code": "JP", "display_name": "Japan"},
            "research_questions": ["Is it clear?"]}

    created = await client.post(f"{API}/projects/{project['id']}/studies", json=body)
    assert created.status_code == 201, created.text
    study = created.json()
    assert study["simulation_config"] == {"response_count": 12, "segment_count": 3, "random_seed": 42}
    assert study["latest_rehearsal_run_id"] is None and study["dimensions"] == [
        "clarity", "brand_fidelity", "cultural_relevance", "cultural_risk"]
    assert (await client.get(f"{API}/studies/{study['id']}")).json() == study
    assert (await client.get(f"{API}/studies/{study['id']}", headers=BOB)).status_code == 404

    wrong_project = await client.post(f"{API}/projects/{project['id']}/studies", json=body | {"campaign_id": other_campaign["id"]})
    assert wrong_project.status_code == 409
    assert wrong_project.json()["error"]["details"][0]["field"] == "campaign_id"
    bob_project = (await client.post(f"{API}/projects", json={"name": "B", "brand_name": "B"}, headers=BOB)).json()
    not_mine = await client.post(f"{API}/projects/{bob_project['id']}/studies", json=body, headers=BOB)
    assert not_mine.status_code == 404  # Alice's campaign does not exist for Bob

    mismatch = await client.post(f"{API}/projects/{project['id']}/studies", json=body | {
        "segments": [{"label": "A", "description": "a"}]})
    assert mismatch.status_code == 422

    second_campaign = await make_campaign(client, project["id"])
    await client.post(f"{API}/projects/{project['id']}/studies", json=body | {"campaign_id": second_campaign["id"]})
    filtered = (await client.get(f"{API}/projects/{project['id']}/studies", params={"campaign_id": campaign["id"]})).json()
    assert filtered["total"] == 1 and filtered["items"][0]["id"] == study["id"]
    assert (await client.get(f"{API}/projects/{project['id']}/studies")).json()["total"] == 2
