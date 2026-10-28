"""The demo journey (Discover → Simulate → Adapt → Compare → Prove) driven through the public API.

Request bodies mirror the seeded fixture journey in contracts/fixtures (Northstar, Japan), so a
demo project can answer them truthfully from its fixtures.
Every step validates the response against its contract model and, when `check=True`, the
honesty and scoring invariants from tests/integration/invariants.py.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any
from uuid import UUID

import httpx

from app.schemas.adaptations import Adaptation, AdaptationPage
from app.schemas.campaigns import Campaign, CampaignPage
from app.schemas.discovery import DiscoveryResult
from app.schemas.evaluations import EvaluationResult
from app.schemas.evidence import EvidencePage, EvidenceRecord
from app.schemas.projects import Project
from app.schemas.reports import Report
from app.schemas.runs import Run
from app.schemas.studies import RehearsalResult, Study, StudyPage
from tests.integration import invariants as inv
from tests.integration._support import API, fetch_all, parse, start_run, wait_for_run

JAPAN = {"country_code": "JP", "display_name": "Japan"}
SEEDED_BRAND = "Northstar"
SEEDED_CAMPAIGN = "Autumn Launch Campaign"
SEEDED_HEADLINE = "Find your next great escape"

DISCOVERY_REQUEST: dict[str, Any] = {
    "product_category": "outdoor lifestyle apparel",
    "market": JAPAN,
    "research_question": "Which cultural interests could inform this launch?",
    "reference_terms": ["hiking", "minimal design", "great escape"],
}

STUDY_REQUEST: dict[str, Any] = {
    "name": "Japan Launch Rehearsal",
    "market": JAPAN,
    "research_questions": [
        "Is the main message clear?",
        "What interpretations could the headline trigger?",
        "Which references might be confusing or inappropriate?",
    ],
    "dimensions": ["clarity", "brand_fidelity", "cultural_relevance", "cultural_risk"],
    "segments": [
        {"label": "Weekend hikers", "description": "Metropolitan professionals who hike one or two weekends a month."},
        {"label": "Design-led urban buyers", "description": "Style-conscious city residents who value minimal design."},
        {"label": "Experienced mountaineers", "description": "Technical climbers who judge gear on performance claims."},
    ],
    "simulation_config": {"response_count": 6, "segment_count": 3, "random_seed": 42},
}

RESOLVABLE_TERMS = DISCOVERY_REQUEST["reference_terms"]  # the agreed demo terms (contract fixtures, lead 2026-10-26)
ADAPTATION_PROTECTED_TERMS = ["Northstar"]
REPORT_TITLE = "Japan Launch Cultural Review"

LIVE_PROJECT: dict[str, Any] = {
    "name": "QA Live Project",
    "brand_name": "Trailhead",
    "brand_voice": ["calm", "precise"],
    "protected_terms": ["Trailhead"],
    "prohibited_terms": ["cheap"],
    "target_markets": [JAPAN],
}
LIVE_CAMPAIGN: dict[str, Any] = {
    "name": "Spring Trail Campaign",
    "campaign_type": "advertisement",
    "original_content": {
        "headline": "Trails worth the early start",
        "body": "Trailhead layers for long days outside.",
        "call_to_action": "Shop the range",
        "reference_terms": ["trail running"],
    },
    "objective": "Check clarity before a Japan launch",
    "target_markets": [JAPAN],
}


async def create_live_project(client: httpx.AsyncClient, headers: dict[str, str], **overrides: Any) -> Project:
    response = await client.post(f"{API}/projects", json={**LIVE_PROJECT, **overrides}, headers=headers)
    project = parse(Project, response, 201)
    assert project.mode == "live", "POST /projects creates a live project (README §5)"
    return project


async def create_live_campaign(
    client: httpx.AsyncClient, headers: dict[str, str], project_id: Any, **overrides: Any
) -> Campaign:
    response = await client.post(
        f"{API}/projects/{project_id}/campaigns", json={**LIVE_CAMPAIGN, **overrides}, headers=headers
    )
    return parse(Campaign, response, 201)


@dataclass
class Journey:
    headers: dict[str, str]
    project: Project
    campaign: Campaign
    discovery_run: Run | None = None
    discovery: DiscoveryResult | None = None
    study: Study | None = None
    rehearsal_run: Run | None = None
    rehearsal: RehearsalResult | None = None
    adaptation_run: Run | None = None
    adaptations: list[Adaptation] = field(default_factory=list)
    evaluation_run: Run | None = None
    evaluation_request: dict[str, Any] | None = None
    evaluation: EvaluationResult | None = None
    report: Report | None = None

    @property
    def project_id(self) -> UUID:
        return self.project.id

    @property
    def campaign_id(self) -> UUID:
        return self.campaign.id

    @property
    def version_id(self) -> UUID:
        return self.campaign.current_version.id


async def project_evidence(client: httpx.AsyncClient, journey: Journey) -> list[EvidenceRecord]:
    return await fetch_all(client, f"{API}/projects/{journey.project_id}/evidence", journey.headers, EvidencePage)


async def project_evidence_ids(client: httpx.AsyncClient, journey: Journey) -> set[UUID]:
    return {record.id for record in await project_evidence(client, journey)}


async def create_demo(client: httpx.AsyncClient, headers: dict[str, str], *, check: bool = True) -> Journey:
    """POST /projects/demo, then read the seeded campaign."""
    project = parse(Project, await client.post(f"{API}/projects/demo", headers=headers), 201)
    page = parse(CampaignPage, await client.get(f"{API}/projects/{project.id}/campaigns", headers=headers))
    assert page.total >= 1 and page.items, "a demo project must be seeded with its campaign"
    campaign = parse(Campaign, await client.get(f"{API}/campaigns/{page.items[0].id}", headers=headers))
    studies = parse(StudyPage, await client.get(f"{API}/projects/{project.id}/studies", headers=headers))
    assert studies.total == 1 and studies.items, "POST /projects/demo seeds exactly one study (D-027)"
    study = studies.items[0]
    if check:
        assert project.mode == "demo" and project.status == "active"
        assert project.brand.name == SEEDED_BRAND, f"seeded brand {project.brand.name!r}"
        assert any(m.country_code == "JP" for m in project.target_markets), "seeded market Japan missing"
        assert campaign.project_id == project.id and campaign.name == SEEDED_CAMPAIGN
        assert campaign.current_version.content.headline == SEEDED_HEADLINE
        assert campaign.versions and campaign.versions[0].id == campaign.current_version.id, "versions newest first"
        assert study.campaign_id == campaign.id and study.market.country_code == "JP"
        assert [s.model_dump() for s in study.segments] == STUDY_REQUEST["segments"], "seeded study != fixture study"
        assert study.simulation_config.model_dump() == STUDY_REQUEST["simulation_config"]
        assert study.research_questions == STUDY_REQUEST["research_questions"]
    return Journey(headers=headers, project=project, campaign=campaign, study=study)


async def discover(
    client: httpx.AsyncClient, journey: Journey, *, check: bool = True, terms: list[str] | None = None
) -> Journey:
    body = {**DISCOVERY_REQUEST, "campaign_id": str(journey.campaign_id)}
    if terms is not None:
        body["reference_terms"] = terms
    accepted = await start_run(client, journey.headers, f"{API}/projects/{journey.project_id}/discoveries", body, "market_discovery")
    run = await wait_for_run(client, accepted.run_id, journey.headers)
    check_completed_run(run, journey, "market_discovery", "discovery")
    expected_url = f"{API}/projects/{journey.project_id}/discoveries/{run.id}"
    assert run.result is not None and run.result.url == expected_url and run.result.ids == [run.id], run.result
    result = parse(DiscoveryResult, await client.get(run.result.url, headers=journey.headers))
    if check:
        assert result.status == "completed" and result.campaign_id == journey.campaign_id
        inv.check_discovery(
            result,
            project_id=journey.project_id,
            run_id=run.id,
            request=body,
            project_evidence=await project_evidence_ids(client, journey),
        )
    journey.discovery_run, journey.discovery = run, result
    return journey


async def rehearse(client: httpx.AsyncClient, journey: Journey, *, grounded: bool = True, check: bool = True) -> Journey:
    """Rehearse the journey's study: the seeded one in demo projects (creating studies there is 409), else a new one."""
    headers = journey.headers
    study = journey.study
    if study is None:
        study = parse(
            Study,
            await client.post(
                f"{API}/projects/{journey.project_id}/studies",
                json={**STUDY_REQUEST, "campaign_id": str(journey.campaign_id)},
                headers=headers,
            ),
            201,
        )
    if check:
        assert study.project_id == journey.project_id and study.campaign_id == journey.campaign_id
        assert parse(Study, await client.get(f"{API}/studies/{study.id}", headers=headers)).id == study.id
    body: dict[str, Any] = {}
    if grounded:
        assert journey.discovery_run is not None, "discover() first for a grounded rehearsal"
        body["discovery_run_id"] = str(journey.discovery_run.id)
    accepted = await start_run(client, headers, f"{API}/studies/{study.id}/rehearsals", body, "campaign_rehearsal")
    run = await wait_for_run(client, accepted.run_id, headers)
    check_completed_run(run, journey, "campaign_rehearsal", "rehearsal")
    assert run.study_id == study.id, f"Run.study_id {run.study_id} != {study.id}"
    expected_url = f"{API}/studies/{study.id}/rehearsals/{run.id}"
    assert run.result is not None and run.result.url == expected_url and run.result.ids == [run.id], run.result
    result = parse(RehearsalResult, await client.get(run.result.url, headers=headers))
    if check:
        assert result.status == "completed" and result.content_version_id == journey.version_id
        assert result.content == journey.campaign.current_version.content, "rehearsal must snapshot the rehearsed version"
        assert result.market.country_code == "JP"
        inv.check_rehearsal(
            result,
            study=study,
            project_id=journey.project_id,
            run_id=run.id,
            project_evidence=await project_evidence_ids(client, journey),
            expect_grounded=grounded,
        )
        refreshed = parse(Study, await client.get(f"{API}/studies/{study.id}", headers=headers))
        assert refreshed.latest_rehearsal_run_id == run.id, "Study.latest_rehearsal_run_id not updated"
    journey.study, journey.rehearsal_run, journey.rehearsal = study, run, result
    return journey


async def adapt(client: httpx.AsyncClient, journey: Journey, *, check: bool = True, variant_count: int | None = None) -> Journey:
    headers = journey.headers
    body: dict[str, Any] = {
        "source_content_version_id": str(journey.version_id),
        "market": JAPAN,
        "instructions": "Preserve the premium and adventurous brand voice.",
        "protected_terms": ADAPTATION_PROTECTED_TERMS,
    }
    if journey.discovery_run is not None:
        body["discovery_run_id"] = str(journey.discovery_run.id)
    if journey.rehearsal_run is not None:
        body["rehearsal_run_id"] = str(journey.rehearsal_run.id)
    if variant_count is not None:
        body["variant_count"] = variant_count
    requested = variant_count or 3
    accepted = await start_run(client, headers, f"{API}/campaigns/{journey.campaign_id}/adaptations", body, "campaign_adaptation")
    run = await wait_for_run(client, accepted.run_id, headers)
    check_completed_run(run, journey, "campaign_adaptation", "adaptations")
    expected_url = f"{API}/campaigns/{journey.campaign_id}/adaptations?run_id={run.id}"
    assert run.result is not None and run.result.url == expected_url, run.result
    assert 1 <= len(run.result.ids) <= requested, f"{len(run.result.ids)} adaptations for variant_count {requested}"
    if journey.project.mode == "demo":
        assert len(run.result.ids) == min(requested, 3), "demo honors variant_count up to the 3 fixture variants (D-027)"
    page = parse(AdaptationPage, await client.get(run.result.url, headers=headers))
    assert page.total == len(run.result.ids) and {a.id for a in page.items} == set(run.result.ids), (
        "GET adaptations?run_id must list exactly Run.result.ids"
    )
    adaptations = sorted(page.items, key=lambda a: run.result.ids.index(a.id))  # type: ignore[union-attr]
    if check:
        evidence_ids = await project_evidence_ids(client, journey)
        for adaptation in adaptations:
            assert parse(Adaptation, await client.get(f"{API}/adaptations/{adaptation.id}", headers=headers)) == adaptation
            assert adaptation.campaign_id == journey.campaign_id
            assert adaptation.source_content_version_id == journey.version_id
            assert adaptation.market.country_code == "JP"
            inv.check_adaptation(
                adaptation,
                brand=journey.project.brand,
                source_content=journey.campaign.current_version.content,
                request_protected_terms=ADAPTATION_PROTECTED_TERMS,
                project_id=journey.project_id,
                run_id=run.id,
                project_evidence=evidence_ids,
            )
            assert adaptation.context.discovery_run_id == (journey.discovery_run.id if journey.discovery_run else None)
            assert adaptation.context.rehearsal_run_id == (journey.rehearsal_run.id if journey.rehearsal_run else None)
            if journey.discovery is not None:
                leaked = inv.ambiguous_evidence_ids(journey.discovery) & {
                    e for change in adaptation.changes for e in change.evidence_ids
                }
                assert not leaked, f"ambiguous/unresolved reference evidence used downstream: {sorted(map(str, leaked))}"
    journey.adaptation_run, journey.adaptations = run, adaptations
    return journey


async def evaluate(client: httpx.AsyncClient, journey: Journey, *, check: bool = True) -> Journey:
    headers = journey.headers
    assert journey.adaptations, "adapt() first"
    body: dict[str, Any] = {
        "source_content_version_id": str(journey.version_id),
        "candidate_adaptation_ids": [str(a.id) for a in journey.adaptations[:3]],
        "market": JAPAN,
        "criteria": journey.campaign.evaluation_criteria.model_dump(),
        "context": {
            "discovery_run_id": str(journey.discovery_run.id) if journey.discovery_run else None,
            "baseline_rehearsal_run_id": str(journey.rehearsal_run.id) if journey.rehearsal_run else None,
        },
    }
    accepted = await start_run(client, headers, f"{API}/campaigns/{journey.campaign_id}/evaluations", body, "campaign_evaluation")
    run = await wait_for_run(client, accepted.run_id, headers)
    check_completed_run(run, journey, "campaign_evaluation", "evaluation")
    assert run.result is not None and len(run.result.ids) == 1, run.result
    evaluation_id = run.result.ids[0]
    assert run.result.url == f"{API}/campaigns/{journey.campaign_id}/evaluations/{evaluation_id}", run.result
    result = parse(EvaluationResult, await client.get(run.result.url, headers=headers))
    if check:
        assert result.id == evaluation_id and result.status == "completed" and result.campaign_id == journey.campaign_id
        inv.check_evaluation(
            result,
            project_id=journey.project_id,
            run_id=run.id,
            request=body,
            adaptations={a.id: a for a in journey.adaptations},
            source_content=journey.campaign.current_version.content,
            project_evidence=await project_evidence_ids(client, journey),
            expect_comparable=True,
        )
    journey.evaluation_run, journey.evaluation_request, journey.evaluation = run, body, result
    return journey


async def make_report(client: httpx.AsyncClient, journey: Journey, *, check: bool = True) -> Journey:
    headers = journey.headers
    body: dict[str, Any] = {"campaign_id": str(journey.campaign_id), "title": REPORT_TITLE}
    if journey.discovery_run is not None:
        body["discovery_run_id"] = str(journey.discovery_run.id)
    if journey.rehearsal_run is not None:
        body["rehearsal_run_id"] = str(journey.rehearsal_run.id)
    if journey.adaptations:
        body["adaptation_ids"] = [str(a.id) for a in journey.adaptations[:3]]
    if journey.evaluation is not None:
        body["evaluation_id"] = str(journey.evaluation.id)
    report = parse(Report, await client.post(f"{API}/projects/{journey.project_id}/reports", json=body, headers=headers), 201)
    if check:
        assert report.title == REPORT_TITLE and report.campaign_id == journey.campaign_id
        assert report.campaign.content_version_id == journey.version_id
        assert report.campaign.content == journey.campaign.current_version.content
        assert report.status == "completed" and not report.missing_sections, (
            f"all stages were supplied, yet status={report.status} missing={report.missing_sections}"
        )
        assert report.discovery is not None and report.discovery.run_id == journey.discovery_run.id  # type: ignore[union-attr]
        assert report.rehearsal is not None and report.rehearsal.run_id == journey.rehearsal_run.id  # type: ignore[union-attr]
        assert {a.id for a in report.adaptations} == {a.id for a in journey.adaptations[:3]}
        assert report.evaluation is not None and report.evaluation.id == journey.evaluation.id  # type: ignore[union-attr]
        assert report.evaluation.recommendation == journey.evaluation.recommendation  # type: ignore[union-attr]
        inv.check_report(report, project_id=journey.project_id, project_evidence=await project_evidence_ids(client, journey))
        assert parse(Report, await client.get(f"{API}/reports/{report.id}", headers=headers)) == report
    journey.report = report
    return journey


async def full_journey(
    client: httpx.AsyncClient, headers: dict[str, str], *, check: bool = True, terms: list[str] | None = None
) -> Journey:
    journey = await create_demo(client, headers, check=check)
    await discover(client, journey, check=check, terms=terms)
    await rehearse(client, journey, check=check)
    await adapt(client, journey, check=check)
    await evaluate(client, journey, check=check)
    await make_report(client, journey, check=check)
    return journey


def check_completed_run(run: Run, journey: Journey, run_type: str, resource: str) -> None:
    """A finished demo run: completed, demo mode, result reference, no error (README §5, §6)."""
    assert run.run_type == run_type, f"run_type {run.run_type} != {run_type}"
    assert run.project_id == journey.project_id
    assert run.status == "completed", f"{run_type} run ended {run.status}: error={run.error}"
    assert run.mode == "demo", f"Run.mode {run.mode!r} in a demo project"
    assert run.error is None, f"completed run carries an error {run.error}"
    assert run.result is not None and run.result.resource == resource, f"Run.result {run.result} (expected {resource})"
    assert run.completed_at is not None and run.started_at is not None
    assert run.created_at <= run.started_at <= run.completed_at, "run timestamps out of order"
    progress = run.progress
    assert progress is not None and progress.stage == "completed", f"terminal progress {progress} (README §6)"
    assert progress.completed_steps == progress.total_steps, f"terminal progress {progress} (README §6)"
    if run_type != "market_discovery" or run.campaign_id is not None:
        assert run.campaign_id == journey.campaign_id, f"Run.campaign_id {run.campaign_id} != {journey.campaign_id}"
