"""The contract fixtures obey the same honesty and scoring rules the live API is held to.

contracts/fixtures is one demo journey (Northstar, Japan). If a fixture breaks a rule in
contracts/README.md §5/§7/§8, either the fixture or the rule is wrong — both feed the frontend.
"""

import json
from pathlib import Path

import pytest

from app.schemas.adaptations import Adaptation, AdaptationPage
from app.schemas.campaigns import Campaign
from app.schemas.discovery import DiscoveryResult
from app.schemas.evaluations import EvaluationResult
from app.schemas.evidence import EvidencePage
from app.schemas.projects import Project
from app.schemas.reports import Report
from app.schemas.runs import Run, RunPage
from app.schemas.studies import RehearsalResult, Study
from tests.integration import invariants as inv
from tests.integration.journey import ADAPTATION_PROTECTED_TERMS, DISCOVERY_REQUEST, STUDY_REQUEST

FIXTURES = Path(__file__).resolve().parents[3] / "contracts" / "fixtures"


def load(model, name):  # type: ignore[no-untyped-def]
    return model.model_validate_json((FIXTURES / f"{name}.json").read_bytes())


@pytest.fixture(scope="module")
def fx() -> dict:
    return {
        "project": load(Project, "Project"),
        "campaign": load(Campaign, "Campaign"),
        "study": load(Study, "Study"),
        "discovery": load(DiscoveryResult, "DiscoveryResult"),
        "rehearsal": load(RehearsalResult, "RehearsalResult"),
        "adaptations": load(AdaptationPage, "AdaptationPage"),
        "adaptation": load(Adaptation, "Adaptation"),
        "evaluation": load(EvaluationResult, "EvaluationResult"),
        "report": load(Report, "Report"),
        "evidence": load(EvidencePage, "EvidencePage"),
        "runs": load(RunPage, "RunPage"),
    }


def evidence_ids(fx: dict) -> set:
    return {record.id for record in fx["evidence"].items}


def test_demo_evidence_page_is_labeled(fx: dict) -> None:
    inv.check_demo_evidence(fx["evidence"].items, fx["project"].id)


def test_discovery_fixture(fx: dict) -> None:
    request = {**DISCOVERY_REQUEST, "campaign_id": str(fx["campaign"].id)}
    inv.check_discovery(
        fx["discovery"], project_id=fx["project"].id, request=request, project_evidence=evidence_ids(fx)
    )


def test_rehearsal_fixture(fx: dict) -> None:
    inv.check_rehearsal(
        fx["rehearsal"], study=fx["study"], project_id=fx["project"].id, project_evidence=evidence_ids(fx),
        expect_grounded=True,
    )


def test_study_fixture_matches_journey_request(fx: dict) -> None:
    study = fx["study"]
    assert [s.model_dump() for s in study.segments] == STUDY_REQUEST["segments"]
    assert study.simulation_config.model_dump() == STUDY_REQUEST["simulation_config"]
    assert study.research_questions == STUDY_REQUEST["research_questions"]


def test_adaptation_fixtures(fx: dict) -> None:
    for adaptation in [*fx["adaptations"].items, fx["adaptation"]]:
        inv.check_adaptation(
            adaptation,
            brand=fx["project"].brand,
            source_content=fx["campaign"].current_version.content,
            request_protected_terms=ADAPTATION_PROTECTED_TERMS,
            project_id=fx["project"].id,
            project_evidence=evidence_ids(fx),
        )
        assert inv.ambiguous_evidence_ids(fx["discovery"]).isdisjoint(
            e for change in adaptation.changes for e in change.evidence_ids
        )


def test_evaluation_fixture(fx: dict) -> None:
    adaptations = {a.id: a for a in fx["adaptations"].items}
    evaluation = fx["evaluation"]
    request = {
        "source_content_version_id": str(fx["campaign"].current_version.id),
        "candidate_adaptation_ids": [str(r.adaptation_id) for r in evaluation.results if r.adaptation_id],
        "criteria": fx["campaign"].evaluation_criteria.model_dump(),
    }
    inv.check_evaluation(
        evaluation,
        project_id=fx["project"].id,
        request=request,
        adaptations=adaptations,
        source_content=fx["campaign"].current_version.content,
        project_evidence=evidence_ids(fx),
        expect_comparable=True,
    )


def test_report_fixture(fx: dict) -> None:
    report = fx["report"]
    inv.check_report(report, project_id=fx["project"].id, project_evidence=evidence_ids(fx))
    assert report.evaluation == fx["evaluation"]
    assert report.discovery.run_id == fx["discovery"].run_id
    assert report.rehearsal.run_id == fx["rehearsal"].run_id


def test_run_fixtures(fx: dict) -> None:
    project_id = fx["project"].id
    expected = {
        "market_discovery": f"/api/v1/projects/{project_id}/discoveries/{fx['discovery'].run_id}",
        "campaign_rehearsal": f"/api/v1/studies/{fx['study'].id}/rehearsals/{fx['rehearsal'].run_id}",
        "campaign_evaluation": f"/api/v1/campaigns/{fx['campaign'].id}/evaluations/{fx['evaluation'].id}",
    }
    for run in fx["runs"].items:
        assert run.mode == "demo" and run.status == "completed" and run.error is None
        if run.run_type in expected:
            assert run.result.url == expected[run.run_type]
    failed = load(Run, "Run.failed")
    assert failed.status == "failed" and failed.result is None and failed.error is not None
    assert failed.error.stage == failed.progress.stage, "failed run: error.stage should equal progress.stage"
    assert failed.error.retryable is True and "retrying is safe" in failed.error.message


def test_fixture_stage_names_follow_section_6(fx: dict) -> None:
    """Review C8: terminal runs use progress.stage 'completed', which §6 does not list."""
    stages = {run.progress.stage for run in fx["runs"].items if run.progress}
    undocumented = stages - {s for stages in inv.RUN_STAGES.values() for s in stages}
    assert undocumented <= {"completed"}, f"undocumented progress stages {undocumented}"


def test_failed_run_fixture_is_the_only_live_example() -> None:
    """Fixtures are demo data; the single live example is the failed run (README §11)."""
    live = [p.name for p in FIXTURES.glob("*.json") if '"mode": "live"' in p.read_text(encoding="utf-8")]
    assert live == ["Run.failed.json"], live
    assert json.loads((FIXTURES / "Run.failed.json").read_text(encoding="utf-8"))["result"] is None
