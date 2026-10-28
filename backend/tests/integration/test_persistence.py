"""Persistence across an app restart: a new app instance on the same database file (TR-002, FR-052)."""

from pathlib import Path

from app.schemas.campaigns import Campaign
from app.schemas.discovery import DiscoveryResult
from app.schemas.evaluations import EvaluationResult
from app.schemas.projects import Project
from app.schemas.reports import Report
from app.schemas.runs import RunPage
from app.schemas.studies import RehearsalResult
from tests.integration._support import API, parse, running_app
from tests.integration.journey import full_journey


async def test_journey_survives_restart(qa_env: dict[str, str], qa_fake: object, alice: dict[str, str]) -> None:
    """Runs use the workflow double; persistence is the database layer's job, not the."""
    async with running_app() as first:
        journey = await full_journey(first.client, alice, check=False)
    if qa_env["DATABASE_URL"].startswith("sqlite"):
        database = Path(qa_env["DATABASE_URL"].split("///", 1)[1])
        assert database.exists() and database.stat().st_size > 0, "the app ignored DATABASE_URL (seam S2)"

    async with running_app() as second:
        client = second.client
        assert parse(Project, await client.get(f"{API}/projects/{journey.project_id}", headers=alice)) == journey.project
        campaign = parse(Campaign, await client.get(f"{API}/campaigns/{journey.campaign_id}", headers=alice))
        assert campaign == journey.campaign
        discovery = parse(DiscoveryResult, await client.get(journey.discovery_run.result.url, headers=alice))  # type: ignore[union-attr]
        assert discovery == journey.discovery
        rehearsal = parse(RehearsalResult, await client.get(journey.rehearsal_run.result.url, headers=alice))  # type: ignore[union-attr]
        assert rehearsal == journey.rehearsal
        evaluation = parse(EvaluationResult, await client.get(journey.evaluation_run.result.url, headers=alice))  # type: ignore[union-attr]
        assert evaluation == journey.evaluation
        assert parse(Report, await client.get(f"{API}/reports/{journey.report.id}", headers=alice)) == journey.report  # type: ignore[union-attr]
        runs = parse(RunPage, await client.get(f"{API}/projects/{journey.project_id}/runs", headers=alice))
        assert runs.total == 4 and all(run.status == "completed" for run in runs.items), "restart altered finished runs"
