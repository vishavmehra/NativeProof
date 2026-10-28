"""Run lifecycle: provider configuration, active-run limit, honest failure, mid-run reads, interruption (TR-005).

contracts/README.md §5 (live runs never fall back to fixtures), §6 (runs), §9 (2 active runs per user).
Engine behaviour uses the workflow double (`qa_fake`: status / raise_in / block knobs). Real provider paths use a
live project, dummy credentials, `.invalid` hosts mocked by respx, and a fake `qloo` binary; they need E/F.
"""

import asyncio
import stat
import sys
from pathlib import Path
from typing import Any

import httpx
import pytest
import respx

from app.schemas.discovery import DiscoveryResult
from app.schemas.evidence import EvidencePage
from app.schemas.runs import Run, RunPage
from app.schemas.studies import RehearsalResult
from tests.integration import invariants as inv
from tests.integration._support import (
    API,
    FakeProvider,
    auth,
    expect_error,
    fetch_all,
    parse,
    running_app,
    start_run,
    wait_for_run,
)
from tests.integration.journey import (
    DISCOVERY_REQUEST,
    JAPAN,
    STUDY_REQUEST,
    create_demo,
    create_live_campaign,
    create_live_project,
)

LIVE_DISCOVERY = {
    "product_category": "trail running shoes",
    "market": JAPAN,
    "research_question": "Which outdoor interests are associated with trail running in Japan?",
    "reference_terms": ["trail running"],
}
DUMMY_LLM_ENV = {
    "NEBIUS_API_KEY": "qa-dummy-nebius-key-0000000000",
    "NEBIUS_DEFAULT_MODEL": "qa-test-model",
    "NEBIUS_FAST_MODEL": "qa-test-model",
    "NEBIUS_REASONING_MODEL": "qa-test-model",
}
PROVIDER_CODES = ("PROVIDER_ERROR", "PROVIDER_TIMEOUT", "PROVIDER_NOT_CONFIGURED", "UNSUPPORTED_CAPABILITY", "RUN_FAILED")


async def run_count(client: httpx.AsyncClient, project_id: Any, headers: dict[str, str], **params: str) -> int:
    return parse(RunPage, await client.get(f"{API}/projects/{project_id}/runs", params=params, headers=headers)).total


def discovery_body(journey: Any) -> dict[str, Any]:
    return {**DISCOVERY_REQUEST, "campaign_id": str(journey.campaign_id)}


async def start_discovery(client: httpx.AsyncClient, journey: Any, headers: dict[str, str]) -> Any:
    path = f"{API}/projects/{journey.project_id}/discoveries"
    return await start_run(client, headers, path, discovery_body(journey), "market_discovery")


def fake_qloo(tmp_path: Path) -> Path:
    """A `qloo` stand-in that fails like a broken harness: noise on stderr and exit code 1."""
    if sys.platform == "win32":
        path = tmp_path / "fake_qloo.cmd"
        path.write_text("@echo off\r\necho qa simulated qloo harness failure 1>&2\r\nexit /b 1\r\n", encoding="utf-8")
    else:
        path = tmp_path / "fake_qloo"
        path.write_text("#!/bin/sh\necho 'qa simulated qloo harness failure' >&2\nexit 1\n", encoding="utf-8")
        path.chmod(path.stat().st_mode | stat.S_IEXEC)
    return path


async def assert_failed_honestly(client: httpx.AsyncClient, headers: dict[str, str], run: Run, result_path: str | None) -> None:
    """A failure is a failed run with Run.error; nothing is labeled completed (README §5/§6, FR-064)."""
    assert run.status == "failed", f"{run.run_type} ended {run.status} (expected failed): {run.error}"
    assert run.error is not None and run.error.message.strip(), "failed runs need Run.error with a user-facing message"
    assert run.result is None, "a failed run must not point at a result"
    assert run.completed_at is not None
    assert run.progress is not None and run.progress.stage == run.error.stage, "failed progress.stage must equal error.stage (§6)"
    if result_path is not None:  # C7: result GETs mirror the run status
        result = await client.get(result_path, headers=headers)
        assert result.status_code == 200, f"result GET for a failed run: {result.status_code} (README §6)"
        assert result.json()["status"] == "failed", "result of a failed run must mirror status failed"
    completed = parse(RunPage, await client.get(f"{API}/projects/{run.project_id}/runs", params={"status": "completed"}, headers=headers))
    assert run.id not in {r.id for r in completed.items}


# --------------------------------------------------------------------------- provider configuration (503)


async def test_live_runs_without_credentials_are_503(qa_client: httpx.AsyncClient, alice: dict[str, str]) -> None:
    project = await create_live_project(qa_client, alice)
    campaign = await create_live_campaign(qa_client, alice, project.id)
    error = expect_error(
        await qa_client.post(f"{API}/projects/{project.id}/discoveries", json=LIVE_DISCOVERY, headers=alice),
        503,
        "PROVIDER_NOT_CONFIGURED",
    )
    assert "qloo" in error.error.message.lower() or "provider" in error.error.message.lower(), error.error.message
    study = await qa_client.post(
        f"{API}/projects/{project.id}/studies", json={**STUDY_REQUEST, "campaign_id": str(campaign.id)}, headers=alice
    )
    assert study.status_code == 201, study.text
    expect_error(
        await qa_client.post(f"{API}/studies/{study.json()['id']}/rehearsals", json={}, headers=alice), 503, "PROVIDER_NOT_CONFIGURED"
    )
    expect_error(
        await qa_client.post(f"{API}/campaigns/{campaign.id}/adaptations", json={"market": JAPAN}, headers=alice),
        503,
        "PROVIDER_NOT_CONFIGURED",
    )
    assert await run_count(qa_client, project.id, alice) == 0, "a refused live run must not be persisted"


async def test_blank_credentials_count_as_not_configured(
    qa_env: dict[str, str], monkeypatch: pytest.MonkeyPatch, alice: dict[str, str]
) -> None:
    """C10: exactly what a copied .env.example produces."""
    for name in ("NEBIUS_API_KEY", "QLOO_API_KEY", "OPENROUTER_API_KEY"):
        monkeypatch.setenv(name, "")
    async with running_app() as app:
        project = await create_live_project(app.client, alice)
        expect_error(
            await app.client.post(f"{API}/projects/{project.id}/discoveries", json=LIVE_DISCOVERY, headers=alice),
            503,
            "PROVIDER_NOT_CONFIGURED",
        )


# --------------------------------------------------------------------------- active-run limit (429)


async def test_concurrent_runs_beyond_the_limit_are_429(qa_client: httpx.AsyncClient, qa_fake: Any, alice: dict[str, str]) -> None:
    """MAX_ACTIVE_RUNS_PER_USER=2: two blocked runs are active, the third start is refused, other users are not."""
    qa_fake.block = asyncio.Event()
    journey = await create_demo(qa_client, alice)
    first, second = await start_discovery(qa_client, journey, alice), await start_discovery(qa_client, journey, alice)
    for accepted in (first, second):
        run = parse(Run, await qa_client.get(f"{API}/runs/{accepted.run_id}", headers=alice))
        assert run.status in ("queued", "running"), f"blocked run is {run.status}"
    expect_error(
        await qa_client.post(f"{API}/projects/{journey.project_id}/discoveries", json=discovery_body(journey), headers=alice),
        429,
        "RATE_LIMITED",
    )
    assert await run_count(qa_client, journey.project_id, alice) == 2, "the refused start must not persist a run"
    carol = auth("qa-carol")
    other = await create_demo(qa_client, carol)
    third = await start_discovery(qa_client, other, carol)  # per-user limit
    qa_fake.block.set()
    for accepted, headers in ((first, alice), (second, alice), (third, carol)):
        assert (await wait_for_run(qa_client, accepted.run_id, headers)).status == "completed"
    await start_discovery(qa_client, journey, alice)  # finished runs no longer count


async def test_limit_zero_refuses_every_start(
    qa_env: dict[str, str], monkeypatch: pytest.MonkeyPatch, alice: dict[str, str]
) -> None:
    monkeypatch.setenv("MAX_ACTIVE_RUNS_PER_USER", "0")
    async with running_app() as app:
        journey = await create_demo(app.client, alice)
        expect_error(
            await app.client.post(f"{API}/projects/{journey.project_id}/discoveries", json=discovery_body(journey), headers=alice),
            429,
            "RATE_LIMITED",
        )
        assert await run_count(app.client, journey.project_id, alice) == 0


# --------------------------------------------------------------------------- outcomes through the engine


async def test_mid_run_reads_mirror_the_run(qa_client: httpx.AsyncClient, qa_fake: Any, alice: dict[str, str]) -> None:
    """C7: a reload mid-run sees the run status; an unfinished run cannot ground another run (D-030)."""
    qa_fake.block = asyncio.Event()
    journey = await create_demo(qa_client, alice)
    accepted = await start_discovery(qa_client, journey, alice)
    pending = parse(DiscoveryResult, await qa_client.get(f"{API}/projects/{journey.project_id}/discoveries/{accepted.run_id}", headers=alice))
    assert pending.status in ("queued", "running") and pending.references == [] and pending.evidence == []
    assert pending.market_brief is None
    refused = await qa_client.post(
        f"{API}/studies/{journey.study.id}/rehearsals", json={"discovery_run_id": str(accepted.run_id)}, headers=alice  # type: ignore[union-attr]
    )
    expect_error(refused, 409, "CONFLICT")
    qa_fake.block.set()
    run = await wait_for_run(qa_client, accepted.run_id, alice)
    assert run.status == "completed" and run.progress is not None and run.progress.stage == "completed"


async def test_failed_outcome_is_reported_honestly(qa_client: httpx.AsyncClient, qa_fake: Any, alice: dict[str, str]) -> None:
    qa_fake.status["campaign_rehearsal"] = "failed"
    journey = await create_demo(qa_client, alice)
    path = f"{API}/studies/{journey.study.id}/rehearsals"  # type: ignore[union-attr]
    accepted = await start_run(qa_client, alice, path, {}, "campaign_rehearsal")
    run = await wait_for_run(qa_client, accepted.run_id, alice)
    await assert_failed_honestly(qa_client, alice, run, f"{path}/{run.id}")
    result = parse(RehearsalResult, await qa_client.get(f"{path}/{run.id}", headers=alice))
    assert result.reactions == [] and result.summary is None, "a failed rehearsal shows no reactions (README §6)"


async def test_partial_outcome_points_at_a_labeled_result(qa_client: httpx.AsyncClient, qa_fake: Any, alice: dict[str, str]) -> None:
    qa_fake.status["market_discovery"] = "partial"
    journey = await create_demo(qa_client, alice)
    run = await wait_for_run(qa_client, (await start_discovery(qa_client, journey, alice)).run_id, alice)
    assert run.status == "partial" and run.result is not None and run.result.resource == "discovery"
    assert run.progress is not None and run.progress.stage == "completed" and run.progress.completed_steps == run.progress.total_steps
    result = parse(DiscoveryResult, await qa_client.get(run.result.url, headers=alice))
    assert result.status == "partial" and result.limitations, "partial results must name what is missing (README §6)"


async def test_workflow_bug_is_a_safe_internal_error(qa_client: httpx.AsyncClient, qa_fake: Any, alice: dict[str, str]) -> None:
    qa_fake.raise_in.add("market_discovery")
    journey = await create_demo(qa_client, alice)
    run = await wait_for_run(qa_client, (await start_discovery(qa_client, journey, alice)).run_id, alice)
    await assert_failed_honestly(qa_client, alice, run, f"{API}/projects/{journey.project_id}/discoveries/{run.id}")
    assert run.error is not None and run.error.code == "INTERNAL_ERROR"
    assert "simulated workflow bug" not in run.error.message, "exception text leaked into Run.error"


async def test_demo_runs_are_limited_to_the_seeded_market(qa_client: httpx.AsyncClient, alice: dict[str, str]) -> None:
    """D-027: a run for a market other than JP in a demo project is 409; so are new studies and brand edits."""
    journey = await create_demo(qa_client, alice)
    france = {"country_code": "FR", "display_name": "France"}
    expect_error(
        await qa_client.post(
            f"{API}/projects/{journey.project_id}/discoveries", json={**discovery_body(journey), "market": france}, headers=alice
        ),
        409,
        "CONFLICT",
    )
    expect_error(
        await qa_client.post(f"{API}/campaigns/{journey.campaign_id}/adaptations", json={"market": france}, headers=alice),
        409,
        "CONFLICT",
    )
    expect_error(
        await qa_client.post(
            f"{API}/projects/{journey.project_id}/studies", json={**STUDY_REQUEST, "campaign_id": str(journey.campaign_id)}, headers=alice
        ),
        409,
        "CONFLICT",
    )
    expect_error(
        await qa_client.patch(f"{API}/projects/{journey.project_id}", json={"protected_terms": ["Other"]}, headers=alice),
        409,
        "CONFLICT",
    )
    assert await run_count(qa_client, journey.project_id, alice) == 0


# --------------------------------------------------------------------------- real provider failure (E/F)


async def test_qloo_failure_produces_a_failed_run(
    qa_env: dict[str, str], monkeypatch: pytest.MonkeyPatch, tmp_path: Path, alice: dict[str, str]
) -> None:
    monkeypatch.setenv("QLOO_API_KEY", "qa-dummy-qloo-key-0000000000")
    monkeypatch.setenv("QLOO_BIN", str(fake_qloo(tmp_path)))
    for name, value in DUMMY_LLM_ENV.items():
        monkeypatch.setenv(name, value)
    with respx.mock(assert_all_called=False) as network:
        network.route().mock(side_effect=httpx.ConnectError("qa: network disabled"))
        async with running_app() as app:
            project = await create_live_project(app.client, alice)
            accepted = await start_run(app.client, alice, f"{API}/projects/{project.id}/discoveries", LIVE_DISCOVERY, "market_discovery")
            run = await wait_for_run(app.client, accepted.run_id, alice)
            await assert_failed_honestly(app.client, alice, run, f"{API}/projects/{project.id}/discoveries/{run.id}")
            assert run.mode == "live"
            assert run.error is not None and run.error.code in PROVIDER_CODES, f"Qloo failure surfaced as {run.error.code}"
            assert run.error.stage in inv.RUN_STAGES["market_discovery"][:2], f"failed at {run.error.stage}"
            evidence = await fetch_all(app.client, f"{API}/projects/{project.id}/evidence", alice, EvidencePage, run_id=str(run.id))
            assert not [e for e in evidence if e.evidence_type == "qloo_source"], "a failed Qloo call must not create Qloo evidence"
            assert not [e for e in evidence if e.retrieval_mode == "fixture"], "a live run never falls back to fixtures"


async def test_llm_failure_produces_a_failed_run(
    qa_env: dict[str, str], monkeypatch: pytest.MonkeyPatch, alice: dict[str, str]
) -> None:
    for name, value in DUMMY_LLM_ENV.items():
        monkeypatch.setenv(name, value)
    with FakeProvider(500, {"error": {"message": "qa simulated provider outage"}}) as provider:
        monkeypatch.setenv("NEBIUS_BASE_URL", provider.base_url)
        async with running_app() as app:
            project = await create_live_project(app.client, alice)
            campaign = await create_live_campaign(app.client, alice, project.id)
            study = await app.client.post(
                f"{API}/projects/{project.id}/studies", json={**STUDY_REQUEST, "campaign_id": str(campaign.id)}, headers=alice
            )
            assert study.status_code == 201, study.text
            path = f"{API}/studies/{study.json()['id']}/rehearsals"
            run = await wait_for_run(app.client, (await start_run(app.client, alice, path, {}, "campaign_rehearsal")).run_id, alice)
            assert provider.requests, "the live rehearsal never called the configured provider"
            await assert_failed_honestly(app.client, alice, run, f"{path}/{run.id}")
            assert run.mode == "live" and run.error is not None and run.error.code in PROVIDER_CODES


# --------------------------------------------------------------------------- interruption (D-022)


async def test_interrupted_run_is_failed_on_restart(qa_env: dict[str, str], qa_fake: Any, alice: dict[str, str]) -> None:
    qa_fake.block = asyncio.Event()  # never released: the app shuts down mid-run, like a crash or redeploy
    async with running_app() as first:
        journey = await create_demo(first.client, alice)
        accepted = await start_discovery(first.client, journey, alice)
        before = parse(Run, await first.client.get(f"{API}/runs/{accepted.run_id}", headers=alice))
        assert before.status in ("queued", "running")
    async with running_app() as second:
        after = parse(Run, await second.client.get(f"{API}/runs/{accepted.run_id}", headers=alice))
        assert after.status == "failed", f"interrupted run is {after.status} after restart"
        assert after.error is not None and after.error.code == "RUN_INTERRUPTED" and after.error.retryable
        assert after.result is None
        qa_fake.block.set()
        await start_discovery(second.client, journey, alice)  # the interrupted run no longer counts as active
