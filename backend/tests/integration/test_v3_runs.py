"""Contract v3 run control on SQLite: cancel keeps saved work; resume after a crash redoes no batch (README §14.5).

Race-tolerant: if a demo study finishes before the test can cancel or crash it, the test skips with that reason
rather than passing vacuously. Skipped (not xfailed) until D replaces the handler stubs.
"""

import asyncio
from typing import Any

import httpx
import pytest

from app.schemas.population import InterviewPage, PopulationStudyResult
from app.schemas.runs import Run
from tests.integration._support import API, expect_error, fetch_all, parse, running_app, start_run, wait_for_run
from tests.integration.journey import create_demo
from tests.integration.v3_support import RUNS, ROUTES, needs, needs_workflow

R = ROUTES
NEEDS = needs(R.start_population_study, R.get_population_study, R.list_interviews, RUNS.cancel_run, RUNS.resume_run)
WORKFLOW = needs_workflow("run_population_study")
BIG = {"population_size": 120, "interview_depth": "deep", "seed": 7}  # the demo cap, so there are several batches


async def start_big_study(client: httpx.AsyncClient, headers: dict[str, str]) -> tuple[Any, Any]:
    journey = await create_demo(client, headers, check=False)
    accepted = await start_run(client, headers, f"{API}/studies/{journey.study.id}/population-studies", BIG, "population_study")
    return journey, accepted.run_id


async def wait_mid_run(client: httpx.AsyncClient, headers: dict[str, str], run_id: Any, timeout: float = 60) -> PopulationStudyResult | None:
    """Poll until some interviews are saved but the run is still active; None if it finished first."""
    loop = asyncio.get_running_loop()
    deadline = loop.time() + timeout
    while loop.time() < deadline:
        result = parse(PopulationStudyResult, await client.get(f"{API}/population-studies/{run_id}", headers=headers))
        if result.status in ("completed", "partial", "failed", "cancelled"):
            return None
        if 0 < result.completed_interviews < result.requested_participants:
            return result
        await asyncio.sleep(0.02)
    pytest.fail("the population study never reached a checkpoint", pytrace=False)


@NEEDS
@WORKFLOW
async def test_cancel_stops_at_a_checkpoint_and_keeps_saved_work(qa_client: httpx.AsyncClient, alice: dict[str, str]) -> None:
    _, run_id = await start_big_study(qa_client, alice)
    if await wait_mid_run(qa_client, alice, run_id) is None:
        pytest.skip("the demo study finished before it could be cancelled")
    cancelled = await qa_client.post(f"{API}/runs/{run_id}/cancel", headers=alice)
    if cancelled.status_code == 409:
        pytest.skip("the run reached a terminal state between the check and the cancel")
    parse(Run, cancelled)
    run = await wait_for_run(qa_client, run_id, alice)
    assert run.status == "cancelled", f"cancel ended as {run.status}"
    result = parse(PopulationStudyResult, await qa_client.get(f"{API}/population-studies/{run_id}", headers=alice))
    assert result.status == "cancelled" and 0 < result.completed_interviews < result.requested_participants, "saved work is kept"
    interviews = await fetch_all(qa_client, f"{API}/population-studies/{run_id}/interviews", alice, InterviewPage)
    assert len({i.participant_id for i in interviews}) == len(interviews), "duplicate interviews after cancel"
    expect_error(await qa_client.post(f"{API}/runs/{run_id}/cancel", headers=alice), 409, "CONFLICT")
    expect_error(await qa_client.post(f"{API}/runs/{run_id}/resume", headers=alice), 409, "CONFLICT")


@NEEDS
@WORKFLOW
async def test_resume_after_a_crash_redoes_no_batch(qa_env: dict[str, str], alice: dict[str, str]) -> None:
    async with running_app() as first:
        _, run_id = await start_big_study(first.client, alice)
        before = await wait_mid_run(first.client, alice, run_id)
        if before is None:
            pytest.skip("the demo study finished before the simulated crash")
        current = asyncio.current_task()
        for task in asyncio.all_tasks():  # crash between batches: in-flight work never finishes
            if task is not current and task.get_name() != "qa-lifespan":
                task.cancel()
        await asyncio.sleep(0)
        saved = await fetch_all(first.client, f"{API}/population-studies/{run_id}/interviews", alice, InterviewPage)
    async with running_app() as second:
        client = second.client
        run = parse(Run, await client.get(f"{API}/runs/{run_id}", headers=alice))
        assert run.status == "failed" and run.error is not None and run.error.code == "RUN_INTERRUPTED"
        await start_run(client, alice, f"{API}/runs/{run_id}/resume", {}, "population_study")
        run = await wait_for_run(client, run_id, alice, timeout=180)
        assert run.status in ("completed", "partial"), f"resume ended {run.status}: {run.error}"
        interviews = await fetch_all(client, f"{API}/population-studies/{run_id}/interviews", alice, InterviewPage)
        result = parse(PopulationStudyResult, await client.get(f"{API}/population-studies/{run_id}", headers=alice))
    participants = [i.participant_id for i in interviews]
    assert len(participants) == len(set(participants)) == result.requested_participants, "a batch was redone or skipped"
    assert {i.id for i in saved} <= {i.id for i in interviews}, "interviews saved before the crash were replaced"
    assert result.completed_interviews + result.failed_interviews == result.requested_participants
