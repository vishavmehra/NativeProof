"""Request validation, authentication, error envelope, pagination, and state conflicts (TR-002, TR-006).

contracts/README.md §3 (conventions, errors), §4 (auth), §5 (demo campaign content), D-011 (archive).
"""

from uuid import uuid4

import httpx
import pytest

from app.schemas.campaigns import Campaign
from app.schemas.health import Health, Readiness
from app.schemas.projects import Project, ProjectPage
from tests.integration._support import API, detail_fields, expect_error, parse
from tests.integration.journey import (
    JAPAN,
    LIVE_CAMPAIGN,
    LIVE_PROJECT,
    create_demo,
    create_live_campaign,
    create_live_project,
)


# --------------------------------------------------------------------------- health


async def test_health_needs_no_auth(qa_client: httpx.AsyncClient) -> None:
    response = await qa_client.get("/health")
    assert response.status_code == 200
    assert Health.model_validate_json(response.content).status == "ok"


async def test_ready_reports_configuration_without_providers(qa_client: httpx.AsyncClient) -> None:
    ready = parse(Readiness, await qa_client.get("/ready"))
    assert ready.dependencies.llm_provider == "not_configured" and ready.dependencies.qloo == "not_configured"
    caps = ready.capabilities
    assert (caps.embeddings, caps.vision, caps.reranking) == ("not_configured",) * 3
    assert ready.live_mode_available is False and ready.demo_mode_available is True
    assert ready.status != "ready", "live providers are missing, so the service is at most degraded"


# --------------------------------------------------------------------------- authentication (§4)


@pytest.mark.parametrize(
    "headers",
    [
        {},
        {"Authorization": "Bearer"},
        {"Authorization": "Basic cWE6cWE="},
        {"Authorization": "Bearer not-a-dev-token"},
        {"Authorization": "Bearer dev-"},
        {"Authorization": "Bearer eyJhbGciOiJIUzI1NiJ9.e30.c2lnbmF0dXJl"},
    ],
    ids=["missing", "empty-bearer", "basic", "non-dev-token", "empty-label", "jwt-in-dev-mode"],
)
async def test_missing_or_invalid_token_is_401(qa_client: httpx.AsyncClient, headers: dict[str, str]) -> None:
    for method, path in (("GET", f"{API}/projects"), ("POST", f"{API}/projects/demo"), ("GET", f"{API}/runs/{uuid4()}")):
        expect_error(await qa_client.request(method, path, headers=headers), 401, "UNAUTHENTICATED")


async def test_request_id_is_echoed_or_generated(qa_client: httpx.AsyncClient, alice: dict[str, str]) -> None:
    echoed = await qa_client.get("/health", headers={"X-Request-ID": "qa-req-123"})
    assert echoed.headers.get("x-request-id") == "qa-req-123"
    generated = await qa_client.get("/health")
    assert generated.headers.get("x-request-id"), "every response carries X-Request-ID (README §3)"
    error = expect_error(await qa_client.get(f"{API}/projects", headers={"X-Request-ID": "qa-req-456"}), 401, "UNAUTHENTICATED")
    assert error.error.request_id == "qa-req-456"


# --------------------------------------------------------------------------- envelope for framework errors


async def test_framework_errors_use_the_envelope(qa_client: httpx.AsyncClient, alice: dict[str, str]) -> None:
    expect_error(await qa_client.get(f"{API}/does-not-exist", headers=alice), 404, "NOT_FOUND")
    invalid_id = expect_error(await qa_client.get(f"{API}/projects/not-a-uuid", headers=alice), 422, "VALIDATION_ERROR")
    assert "project_id" in detail_fields(invalid_id), f"invalid path id should name project_id: {invalid_id}"
    malformed = await qa_client.post(
        f"{API}/projects", content=b'{"name": "x",', headers={**alice, "Content-Type": "application/json"}
    )
    expect_error(malformed, 422, "VALIDATION_ERROR")


async def test_unknown_fields_are_rejected(qa_client: httpx.AsyncClient, alice: dict[str, str]) -> None:
    owner = expect_error(
        await qa_client.post(f"{API}/projects", json={**LIVE_PROJECT, "owner_id": str(uuid4())}, headers=alice),
        422,
        "VALIDATION_ERROR",
    )
    assert "owner_id" in detail_fields(owner), f"unknown field should be named: {owner}"
    project = await create_live_project(qa_client, alice)
    mode = expect_error(
        await qa_client.patch(f"{API}/projects/{project.id}", json={"mode": "demo"}, headers=alice), 422, "VALIDATION_ERROR"
    )
    assert "mode" in detail_fields(mode), "mode is fixed at creation and not a PATCH field"
    assert parse(Project, await qa_client.get(f"{API}/projects/{project.id}", headers=alice)).mode == "live"


async def test_invalid_weights_are_rejected_with_field_detail(qa_client: httpx.AsyncClient, alice: dict[str, str]) -> None:
    project = await create_live_project(qa_client, alice)
    body = {**LIVE_CAMPAIGN, "evaluation_criteria": {"clarity": 0.3, "brand_fidelity": 0.25, "cultural_relevance": 0.25, "cultural_risk": 0.15}}
    error = expect_error(
        await qa_client.post(f"{API}/projects/{project.id}/campaigns", json=body, headers=alice), 422, "VALIDATION_ERROR"
    )
    assert error.error.details, "weights error needs field-level detail"
    detail = error.error.details[0]
    assert detail.field == "evaluation_criteria", f"field {detail.field!r} (fixture ErrorResponse.validation.json)"
    assert "sum to 1.0" in detail.message, detail.message
    campaigns = await qa_client.get(f"{API}/projects/{project.id}/campaigns", headers=alice)
    assert campaigns.json()["total"] == 0, "a rejected campaign must not be persisted"


async def test_input_limits_are_enforced(qa_client: httpx.AsyncClient, alice: dict[str, str]) -> None:
    """README §9 limits and the CampaignContent rule (headline or body)."""
    project = await create_live_project(qa_client, alice)
    campaigns = f"{API}/projects/{project.id}/campaigns"
    too_long = {**LIVE_CAMPAIGN, "original_content": {"headline": "x" * 301}}
    assert "original_content.headline" in detail_fields(
        expect_error(await qa_client.post(campaigns, json=too_long, headers=alice), 422, "VALIDATION_ERROR")
    )
    empty = {**LIVE_CAMPAIGN, "original_content": {"call_to_action": "Shop"}}
    expect_error(await qa_client.post(campaigns, json=empty, headers=alice), 422, "VALIDATION_ERROR")
    campaign = await create_live_campaign(qa_client, alice, project.id)
    studies = f"{API}/projects/{project.id}/studies"
    study = {"campaign_id": str(campaign.id), "name": "Limits", "market": JAPAN, "research_questions": ["Clear?"]}
    for config in ({"response_count": 25}, {"response_count": 2}, {"response_count": 3, "segment_count": 4}):
        expect_error(
            await qa_client.post(studies, json={**study, "simulation_config": config}, headers=alice), 422, "VALIDATION_ERROR"
        )
    mismatched = {**study, "segments": [{"label": "A", "description": "One segment"}], "simulation_config": {"segment_count": 2}}
    expect_error(await qa_client.post(studies, json=mismatched, headers=alice), 422, "VALIDATION_ERROR")
    discoveries = f"{API}/projects/{project.id}/discoveries"
    base = {"product_category": "apparel", "market": JAPAN, "research_question": "What matters?"}
    for bad in (
        {"reference_terms": [f"term {i}" for i in range(11)]},
        {"discovery_options": {"max_references": 21}},
        {"market": {"country_code": "jp", "display_name": "Japan"}},
    ):
        expect_error(await qa_client.post(discoveries, json={**base, **bad}, headers=alice), 422, "VALIDATION_ERROR")


# --------------------------------------------------------------------------- pagination (§3)


async def test_pagination_bounds_and_totals(qa_client: httpx.AsyncClient, alice: dict[str, str]) -> None:
    for params, field in (({"limit": 101}, "limit"), ({"limit": 0}, "limit"), ({"offset": -1}, "offset")):
        error = expect_error(await qa_client.get(f"{API}/projects", params=params, headers=alice), 422, "VALIDATION_ERROR")
        assert field in detail_fields(error), f"query error should name {field}: {error}"
    for index in range(3):
        await create_live_project(qa_client, alice, name=f"QA Paging {index}")
    first = parse(ProjectPage, await qa_client.get(f"{API}/projects", params={"limit": 2}, headers=alice))
    assert (first.limit, first.offset, first.total, len(first.items)) == (2, 0, 3, 2)
    rest = parse(ProjectPage, await qa_client.get(f"{API}/projects", params={"limit": 2, "offset": 2}, headers=alice))
    assert (rest.offset, rest.total, len(rest.items)) == (2, 3, 1)
    assert not {p.id for p in first.items} & {p.id for p in rest.items}, "pages overlap"
    assert len(parse(ProjectPage, await qa_client.get(f"{API}/projects", params={"limit": 100}, headers=alice)).items) == 3


# --------------------------------------------------------------------------- projects and campaigns


async def test_live_project_create_and_partial_update(qa_client: httpx.AsyncClient, alice: dict[str, str]) -> None:
    project = await create_live_project(qa_client, alice, description="Before")
    assert project.status == "active" and project.brand.name == "Trailhead"
    assert project.brand.protected_terms == ["Trailhead"] and project.brand.prohibited_terms == ["cheap"]
    updated = parse(Project, await qa_client.patch(f"{API}/projects/{project.id}", json={"description": "After"}, headers=alice))
    assert updated.description == "After"
    assert updated.name == project.name and updated.brand.voice == project.brand.voice, "omitted fields must stay unchanged"
    assert updated.updated_at >= project.updated_at and updated.created_at == project.created_at


async def test_archived_project_is_read_only(qa_client: httpx.AsyncClient, alice: dict[str, str]) -> None:
    project = await create_live_project(qa_client, alice)
    campaign = await create_live_campaign(qa_client, alice, project.id)
    deleted = await qa_client.delete(f"{API}/projects/{project.id}", headers=alice)
    assert deleted.status_code == 204, deleted.text
    archived = parse(Project, await qa_client.get(f"{API}/projects/{project.id}", headers=alice))
    assert archived.status == "archived"
    writes = [
        ("PATCH", f"{API}/projects/{project.id}", {"name": "Renamed"}),
        ("POST", f"{API}/projects/{project.id}/campaigns", LIVE_CAMPAIGN),
        ("PATCH", f"{API}/campaigns/{campaign.id}", {"name": "Renamed"}),
    ]
    for method, path, body in writes:
        expect_error(await qa_client.request(method, path, json=body, headers=alice), 409, "CONFLICT")
    listed = parse(ProjectPage, await qa_client.get(f"{API}/projects", headers=alice))
    assert project.id not in {p.id for p in listed.items}, "archived projects are excluded by default"
    included = parse(ProjectPage, await qa_client.get(f"{API}/projects", params={"include_archived": "true"}, headers=alice))
    assert project.id in {p.id for p in included.items}
    assert parse(Campaign, await qa_client.get(f"{API}/campaigns/{campaign.id}", headers=alice)).name == campaign.name


async def test_demo_campaign_content_edit_is_conflict(qa_client: httpx.AsyncClient, alice: dict[str, str]) -> None:
    journey = await create_demo(qa_client, alice)
    new_content = {"headline": "Something else entirely", "body": "Changed body."}
    expect_error(
        await qa_client.patch(f"{API}/campaigns/{journey.campaign_id}", json={"original_content": new_content}, headers=alice),
        409,
        "CONFLICT",
    )
    after = parse(Campaign, await qa_client.get(f"{API}/campaigns/{journey.campaign_id}", headers=alice))
    assert after.current_version == journey.campaign.current_version and len(after.versions) == len(journey.campaign.versions)


async def test_live_campaign_content_edit_creates_a_version(qa_client: httpx.AsyncClient, alice: dict[str, str]) -> None:
    project = await create_live_project(qa_client, alice)
    campaign = await create_live_campaign(qa_client, alice, project.id)
    assert campaign.current_version.version_number == 1 and len(campaign.versions) == 1
    content = {**LIVE_CAMPAIGN["original_content"], "headline": "Early starts, longer trails"}
    updated = parse(
        Campaign, await qa_client.patch(f"{API}/campaigns/{campaign.id}", json={"original_content": content}, headers=alice)
    )
    assert updated.current_version.version_number == 2 and updated.current_version.content.headline == content["headline"]
    assert [v.version_number for v in updated.versions] == [2, 1], "versions are newest first"
    assert updated.versions[1] == campaign.current_version, "earlier versions stay intact (FR-003, D-006)"
    renamed = parse(Campaign, await qa_client.patch(f"{API}/campaigns/{campaign.id}", json={"name": "Renamed"}, headers=alice))
    assert renamed.current_version.version_number == 2, "a metadata-only PATCH must not create a content version"
