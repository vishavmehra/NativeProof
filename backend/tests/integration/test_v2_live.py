"""Contract v2 in live mode with stubbed providers (README §5, §13).

No test reaches the network: Qloo is a missing or fake binary, and every model endpoint (LLM, vision,
embeddings) points at a local FakeProvider. Covers "not configured" behaviour, honest provider failure, and the
rule that an image is never sent to a text-only model.
"""

from typing import Any

import httpx
import pytest

from app.schemas.search import SearchResults
from tests.integration._support import API, FakeProvider, expect_error, parse, running_app, start_run, wait_for_run
from tests.integration.journey import JAPAN, STUDY_REQUEST, create_live_campaign, create_live_project
from tests.integration.v2_support import PNG, upload

LLM_ENV = {
    "NEBIUS_API_KEY": "qa-dummy-nebius-key-0000000000",
    "NEBIUS_DEFAULT_MODEL": "qa-text-model",
    "NEBIUS_FAST_MODEL": "qa-text-model",
    "NEBIUS_REASONING_MODEL": "qa-text-model",
}
PROVIDER_CODES = ("PROVIDER_ERROR", "PROVIDER_TIMEOUT", "RUN_FAILED")


async def live_setup(client: httpx.AsyncClient, headers: dict[str, str]) -> tuple[Any, Any, str]:
    project = await create_live_project(client, headers)
    campaign = await create_live_campaign(client, headers, project.id)
    study = await client.post(f"{API}/projects/{project.id}/studies", json={**STUDY_REQUEST, "campaign_id": str(campaign.id)}, headers=headers)
    assert study.status_code == 201, study.text
    return project, campaign, study.json()["id"]


def arena_body(campaign: Any, study_id: str, **extra: Any) -> dict[str, Any]:
    return {
        "study_id": study_id,
        "variants": [
            {"label": "Original", "content_version_id": str(campaign.current_version.id), **extra},
            {"label": "Alt", "content": {"headline": "Early starts, longer trails"}},
        ],
        "criteria": campaign.evaluation_criteria.model_dump(),
    }


async def test_live_v2_without_credentials(qa_client: httpx.AsyncClient, alice: dict[str, str]) -> None:
    """Run-creating v2 endpoints refuse with 503 when providers are not configured."""
    project, campaign, study_id = await live_setup(qa_client, alice)
    starts = [
        (f"{API}/projects/{project.id}/cultural-profiles", {"subject": "brand", "title": "DNA", "markets": [JAPAN]}),
        (
            f"{API}/projects/{project.id}/market-comparisons",
            {"markets": [JAPAN, {"country_code": "FR", "display_name": "France"}], "product_category": "apparel", "research_question": "Where next?"},
        ),
        (f"{API}/campaigns/{campaign.id}/arenas", arena_body(campaign, study_id)),
        (f"{API}/campaigns/{campaign.id}/risk-scans", {"market": JAPAN}),
    ]
    for path, body in starts:
        expect_error(await qa_client.post(path, json=body, headers=alice), 503, "PROVIDER_NOT_CONFIGURED")
    assert (await qa_client.get(f"{API}/projects/{project.id}/runs", headers=alice)).json()["total"] == 0


async def test_live_optional_capabilities_report_unavailable(qa_client: httpx.AsyncClient, alice: dict[str, str]) -> None:
    """Search reports unavailable when embeddings are not configured (no lexical guesses)."""
    project, _, _ = await live_setup(qa_client, alice)
    search = parse(SearchResults, await qa_client.get(f"{API}/projects/{project.id}/search", params={"q": "trail"}, headers=alice))
    assert search.status == "unavailable" and search.hits == [] and search.message and search.embedding_model is None


async def test_live_brand_memory_put_is_full_replacement(qa_client: httpx.AsyncClient, alice: dict[str, str]) -> None:
    project = await create_live_project(qa_client, alice)
    path = f"{API}/projects/{project.id}/brand"
    full = {
        "name": "Trailhead",
        "description": "Quiet outdoor gear",
        "positioning": "Calm confidence outdoors",
        "voice": ["calm", "precise"],
        "communication_style": "Short sentences",
        "target_audience": "Weekend hikers",
        "audience_preferences": "Practical detail",
        "preferred_terms": ["trail"],
        "prohibited_terms": ["cheap"],
        "protected_terms": ["Trailhead"],
        "approved_examples": [{"text": "Trailhead: made for the long way up.", "note": "Approved 2026"}],
        "constraints": ["No medical claims"],
    }
    brand = (await qa_client.put(path, json=full, headers=alice))
    assert brand.status_code == 200, brand.text
    stored = brand.json()
    for key, value in full.items():
        assert stored[key] == value, f"Brand.{key} not stored as written"
    minimal = (await qa_client.put(path, json={"name": "Trailhead"}, headers=alice)).json()
    assert minimal["voice"] == [] and minimal["approved_examples"] == [] and minimal["positioning"] is None, "PUT replaces the whole brand"
    assert (await qa_client.get(path, headers=alice)).json() == minimal
    expect_error(await qa_client.put(path, json={"name": "Trailhead", "learned_preferences": ["x"]}, headers=alice), 422, "VALIDATION_ERROR")


@pytest.mark.parametrize("feature", ["arena", "risk_scan"])
async def test_live_v2_provider_failure_is_a_failed_run(
    qa_env: dict[str, str], monkeypatch: pytest.MonkeyPatch, alice: dict[str, str], feature: str
) -> None:
    for name, value in LLM_ENV.items():
        monkeypatch.setenv(name, value)
    with FakeProvider(500, {"error": {"message": "qa simulated provider outage"}}) as provider:
        monkeypatch.setenv("NEBIUS_BASE_URL", provider.base_url)
        async with running_app() as app:
            project, campaign, study_id = await live_setup(app.client, alice)
            if feature == "arena":
                path, body, run_type = f"{API}/campaigns/{campaign.id}/arenas", arena_body(campaign, study_id), "campaign_arena"
            else:
                path, body, run_type = f"{API}/campaigns/{campaign.id}/risk-scans", {"market": JAPAN}, "risk_scan"
            run = await wait_for_run(app.client, (await start_run(app.client, alice, path, body, run_type)).run_id, alice)
            assert provider.requests, f"the live {feature} never called the configured provider"
            assert run.mode == "live" and run.status in ("failed", "partial"), f"{feature} ended {run.status}"
            if run.status == "failed":  # README §5: a provider failure yields a failed or partial run
                assert run.result is None and run.error is not None and run.error.code in PROVIDER_CODES
                assert "qa simulated" not in run.error.message
            else:
                assert run.result is not None, "a partial run points at its result"
                result = (await app.client.get(run.result.url, headers=alice)).json()
                assert result["limitations"], "a partial result names what is missing (README §6)"
                assert "qa simulated" not in str(result), "raw provider detail reached the client"
                for finding in result.get("findings", []):
                    assert finding["source"] == "deterministic_check", "model findings appeared although the model failed"


async def test_images_never_reach_a_text_only_model(
    qa_env: dict[str, str], monkeypatch: pytest.MonkeyPatch, alice: dict[str, str]
) -> None:
    """§13 Vision: with no verified vision model configured, no request carries the image, and vision is unavailable."""
    for name, value in LLM_ENV.items():
        monkeypatch.setenv(name, value)
    with FakeProvider(500, {"error": {"message": "qa text model unavailable"}}) as provider:
        monkeypatch.setenv("NEBIUS_BASE_URL", provider.base_url)
        async with running_app() as app:
            project, campaign, study_id = await live_setup(app.client, alice)
            image = await upload(app.client, alice, project.id, kind="image", filename="ad.png", data=PNG, content_type="image/png")
            assert image.status_code == 201, image.text
            asset_id = image.json()["id"]
            scan = await start_run(
                app.client, alice, f"{API}/campaigns/{campaign.id}/risk-scans", {"market": JAPAN, "asset_ids": [asset_id]}, "risk_scan"
            )
            await wait_for_run(app.client, scan.run_id, alice)
            arena = await start_run(
                app.client, alice, f"{API}/campaigns/{campaign.id}/arenas", arena_body(campaign, study_id, asset_id=asset_id), "campaign_arena"
            )
            await wait_for_run(app.client, arena.run_id, alice)
    for body in provider.bodies:
        assert b"image_url" not in body and b"data:image" not in body and b"iVBORw0KGgo" not in body, (
            "an image was sent to a text-only model (README §13 Vision)"
        )
