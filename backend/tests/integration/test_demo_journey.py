"""M1 acceptance: the complete demo journey through the public API (TR-005, TR-008).

Discover → Simulate → Adapt → Compare → Prove on a demo project, validating every body against
its contract model and asserting the honesty invariants (contracts/README.md §5-§8).
"""

import httpx

from app.schemas.evidence import EvidencePage, EvidenceRecord
from app.schemas.projects import ProjectPage
from app.schemas.reports import Report
from app.schemas.runs import RunPage
from tests.integration import invariants as inv
from app.schemas.discovery import DiscoveryResult
from tests.integration._support import API, expect_error, fetch_all, parse, start_run, wait_for_run
from tests.integration.journey import (
    DISCOVERY_REQUEST,
    RESOLVABLE_TERMS,
    Journey,
    create_demo,
    discover,
    full_journey,
    project_evidence,
    rehearse,
)

DEMO_BANNER = "DEMO DATA: fixture results, not live research"


async def test_demo_journey_end_to_end(qa_client: httpx.AsyncClient, alice: dict[str, str]) -> None:
    journey = await full_journey(qa_client, alice)
    await _check_runs_listing(qa_client, journey)
    await _check_project_evidence(qa_client, journey)
    await _check_exports(qa_client, journey)


async def _check_runs_listing(client: httpx.AsyncClient, journey: Journey) -> None:
    path = f"{API}/projects/{journey.project_id}/runs"
    runs = await fetch_all(client, path, journey.headers, RunPage)
    expected = [journey.evaluation_run, journey.adaptation_run, journey.rehearsal_run, journey.discovery_run]
    assert [r.id for r in runs] == [r.id for r in expected], "runs must be listed newest first"  # type: ignore[union-attr]
    assert all(r.mode == "demo" and r.status == "completed" for r in runs)
    by_type = parse(RunPage, await client.get(path, params={"run_type": "campaign_rehearsal"}, headers=journey.headers))
    assert [r.id for r in by_type.items] == [journey.rehearsal_run.id] and by_type.total == 1  # type: ignore[union-attr]
    by_study = parse(RunPage, await client.get(path, params={"study_id": str(journey.study.id)}, headers=journey.headers))  # type: ignore[union-attr]
    assert journey.rehearsal_run.id in {r.id for r in by_study.items}  # type: ignore[union-attr]
    assert all(r.study_id == journey.study.id for r in by_study.items)  # type: ignore[union-attr]
    by_status = parse(RunPage, await client.get(path, params={"status": "failed"}, headers=journey.headers))
    assert by_status.total == 0 and by_status.items == []
    by_campaign = parse(RunPage, await client.get(path, params={"campaign_id": str(journey.campaign_id)}, headers=journey.headers))
    assert {r.id for r in by_campaign.items} >= {journey.adaptation_run.id, journey.evaluation_run.id}  # type: ignore[union-attr]


async def _check_project_evidence(client: httpx.AsyncClient, journey: Journey) -> None:
    records = await project_evidence(client, journey)
    assert records, "a completed demo journey must persist evidence"
    inv.check_demo_evidence(records, journey.project_id)
    stored = {r.id: r for r in records}
    discovery_run = journey.discovery_run.id  # type: ignore[union-attr]
    page = await fetch_all(
        client, f"{API}/projects/{journey.project_id}/evidence", journey.headers, EvidencePage, run_id=str(discovery_run)
    )
    assert page and all(r.source_run_id == discovery_run for r in page), "run_id filter returned other runs' evidence"
    qloo = await fetch_all(
        client, f"{API}/projects/{journey.project_id}/evidence", journey.headers, EvidencePage, evidence_type="qloo_source"
    )
    assert all(r.evidence_type == "qloo_source" for r in qloo)
    # Every embedded evidence record is the stored record, fetchable by id (D-009, DR-002).
    embedded: list[EvidenceRecord] = [
        *journey.discovery.evidence,  # type: ignore[union-attr]
        *journey.rehearsal.evidence,  # type: ignore[union-attr]
        *[e for a in journey.adaptations for e in a.evidence],
        *journey.evaluation.evidence,  # type: ignore[union-attr]
        *journey.report.evidence_register,  # type: ignore[union-attr]
    ]
    for record in {r.id: r for r in embedded}.values():
        if record.id in stored:
            assert stored[record.id] == record, f"embedded evidence {record.id} differs from the stored record"
        fetched = parse(EvidenceRecord, await client.get(f"{API}/evidence/{record.id}", headers=journey.headers))
        assert fetched == record, f"GET /evidence/{record.id} differs from the embedded copy"


async def _check_exports(client: httpx.AsyncClient, journey: Journey) -> None:
    report = journey.report
    assert report is not None
    path = f"{API}/reports/{report.id}/export"
    markdown = await client.get(path, params={"format": "markdown"}, headers=journey.headers)
    assert markdown.status_code == 200, markdown.text[:300]
    assert markdown.headers["content-type"].startswith("text/markdown"), markdown.headers["content-type"]
    assert "attachment" in markdown.headers.get("content-disposition", ""), "export must be a download (README §12)"
    text = markdown.text
    head = [line for line in text.splitlines() if line.strip()][:3]
    assert any(DEMO_BANNER in line for line in head), f"demo export must start with the banner (C4): {head}"
    assert report.title in text
    disclosure = report.rehearsal.simulation_disclosure.description  # type: ignore[union-attr]
    assert disclosure in text, "export must keep the synthetic-data disclosure (08 §10.4)"
    missing = [limitation for limitation in report.limitations if limitation not in text]
    assert not missing, f"export dropped limitations {missing}"
    labels = {inv.ui_label(record) for record in report.evidence_register}
    absent = sorted(label for label in labels if label not in text)
    assert not absent, f"export lacks evidence labels {absent} (README §7, 08 §10.4)"

    exported = await client.get(path, params={"format": "json"}, headers=journey.headers)
    assert exported.status_code == 200 and exported.headers["content-type"].startswith("application/json")
    assert "attachment" in exported.headers.get("content-disposition", "")
    assert Report.model_validate_json(exported.content) == report

    expect_error(await client.get(path, params={"format": "pdf"}, headers=journey.headers), 422, "VALIDATION_ERROR")


def _without_ids(value: object) -> object:
    """Drop per-project UUID references (keep their counts) so two demo projects can be compared."""
    if isinstance(value, dict):
        return {k: len(v) if k.endswith("_ids") else _without_ids(v) for k, v in value.items()}
    if isinstance(value, list):
        return [_without_ids(v) for v in value]
    return value


def _discovery_signature(journey: Journey) -> object:
    d = journey.discovery
    assert d is not None
    return (
        [(r.query_term, r.match_status, r.name, r.entity_id, [c.name for c in r.candidates]) for r in d.references],
        _without_ids(d.market_brief.model_dump(mode="json")) if d.market_brief else None,
        sorted(e.title for e in d.evidence),
    )


def _rehearsal_signature(journey: Journey) -> object:
    r = journey.rehearsal
    assert r is not None
    return (
        r.dimension_results.model_dump(),
        [s.model_dump() for s in r.segments],
        [(x.segment_label, x.sentiment, [(g.dimension, g.value) for g in x.ratings]) for x in r.reactions],
        [(f.title, f.confidence_label) for f in r.summary.key_findings] if r.summary else None,
    )


def _evaluation_signature(journey: Journey) -> object:
    e = journey.evaluation
    assert e is not None and e.recommendation is not None
    labels = {c.candidate_id: c.label for c in e.results}
    return (
        [(c.label, c.dimension_scores.model_dump(), c.overall_score) for c in e.results],
        (e.recommendation.decision, e.recommendation.rule_id, labels.get(e.recommendation.candidate_id or "")),
    )


async def test_demo_journey_is_deterministic(qa_client: httpx.AsyncClient, alice: dict[str, str]) -> None:
    """FR-063 / README §5: demo results are deterministic across demo projects."""
    first = await full_journey(qa_client, alice, check=False, terms=RESOLVABLE_TERMS)
    second = await full_journey(qa_client, alice, check=False, terms=RESOLVABLE_TERMS)
    assert first.project_id != second.project_id
    assert _discovery_signature(first) == _discovery_signature(second)
    assert _rehearsal_signature(first) == _rehearsal_signature(second)
    assert [(a.label, a.content) for a in first.adaptations] == [(a.label, a.content) for a in second.adaptations]
    assert _evaluation_signature(first) == _evaluation_signature(second)


async def test_ungrounded_rehearsal_is_disclosed(qa_client: httpx.AsyncClient, alice: dict[str, str]) -> None:
    """07 §8.2: a rehearsal without discovery context records that it was ungrounded."""
    journey = await create_demo(qa_client, alice)
    await rehearse(qa_client, journey, grounded=False)
    disclosure = journey.rehearsal.simulation_disclosure  # type: ignore[union-attr]
    assert disclosure.grounded is False and disclosure.grounding_evidence_count == 0


async def test_demo_project_is_listed_as_demo(qa_client: httpx.AsyncClient, alice: dict[str, str]) -> None:
    journey = await create_demo(qa_client, alice)
    await discover(qa_client, journey, terms=RESOLVABLE_TERMS)
    page = parse(ProjectPage, await qa_client.get(f"{API}/projects", headers=alice))
    summary = next(p for p in page.items if p.id == journey.project_id)
    assert summary.mode == "demo" and summary.brand_name == journey.project.brand.name
    assert summary.last_activity_at is not None, "last_activity_at should reflect the completed discovery"


async def test_unknown_demo_terms_come_back_unresolved(qa_client: httpx.AsyncClient, alice: dict[str, str]) -> None:
    """D-027: terms without a fixture are unresolved with a limitation, never invented."""
    journey = await create_demo(qa_client, alice)
    body = {**DISCOVERY_REQUEST, "campaign_id": str(journey.campaign_id), "reference_terms": ["hiking", "qa zzz unknown"]}
    accepted = await start_run(qa_client, alice, f"{API}/projects/{journey.project_id}/discoveries", body, "market_discovery")
    run = await wait_for_run(qa_client, accepted.run_id, alice)
    assert run.status == "completed" and run.result is not None
    result = parse(DiscoveryResult, await qa_client.get(run.result.url, headers=alice))
    inv.check_discovery(result, project_id=journey.project_id, run_id=run.id, request=body)
    unknown = next(r for r in result.references if r.query_term == "qa zzz unknown")
    assert unknown.match_status == "unresolved" and not unknown.evidence_ids
    assert "No demo fixture for this term." in unknown.limitations


async def test_journey_plumbing_with_workflow_double(qa_client: httpx.AsyncClient, qa_fake: object, alice: dict[str, str]) -> None:
    """the endpoints, run engine, report assembly, and export end to end, independent of F (the workflow double)."""
    journey = await full_journey(qa_client, alice, check=False)
    await _check_runs_listing(qa_client, journey)
    report = journey.report
    assert report is not None and report.mode == "demo" and report.status == "completed" and not report.missing_sections
    path = f"{API}/reports/{report.id}/export"
    markdown = await qa_client.get(path, params={"format": "markdown"}, headers=alice)
    assert markdown.status_code == 200 and markdown.headers["content-type"].startswith("text/markdown")
    assert "attachment" in markdown.headers.get("content-disposition", "")
    head = [line for line in markdown.text.splitlines() if line.strip()][:3]
    assert any(DEMO_BANNER in line for line in head), f"demo export must start with the banner (C4): {head}"
    assert all(limitation in markdown.text for limitation in report.limitations), "export dropped limitations"
    exported = await qa_client.get(path, params={"format": "json"}, headers=alice)
    assert exported.status_code == 200 and Report.model_validate_json(exported.content) == report
    expect_error(await qa_client.get(path, params={"format": "pdf"}, headers=alice), 422, "VALIDATION_ERROR")

