"""Proof reports: deterministic, synchronous assembly from stored results (D-014), plus export.

No model is called. A section whose stage was not requested, did not finish, or failed is
omitted, named in `missing_sections`, and makes the report `partial`.
"""

import json
import re
from typing import Any
from uuid import UUID, uuid4

from sqlalchemy import func, select
from sqlalchemy.exc import IntegrityError

from app.core.errors import Conflict
from app.db import models as m
from app.db.base import utcnow
from app.db.session import read_session, session
from app.schemas.adaptations import Adaptation
from app.schemas.campaigns import CampaignContent
from app.schemas.common import Market, RunMetadata
from app.schemas.discovery import DiscoveryResult
from app.schemas.evaluations import EvaluationResult
from app.schemas.evidence import EvidenceRecord
from app.schemas.reports import (
    ExecutiveSummary,
    Report,
    ReportCampaignSnapshot,
    ReportCreate,
    ReportDiscoverySection,
    ReportPage,
    ReportRehearsalSection,
    ReportSummary,
    ReproducibilityInfo,
)
from app.schemas.studies import RehearsalResult
from app.services.common import conflict, get_owned, get_project, paginate, touch
from app.services.results import discovery_result, evaluation_result, rehearsal_result, run_metadata, to_adaptations
from app.services.runs import USABLE, brand_of

SECTIONS = ("discovery", "rehearsal", "adaptations", "evaluation")
DEMO_BANNER = "DEMO DATA — fixture results, not live research."
VERSION_NOTICE = "Version notice:"


def evidence_label(e: EvidenceRecord) -> str:
    """UI label, first matching rule (contracts/README.md section 7)."""
    if e.evidence_type == "observed_outcome":
        return "Observed outcome"
    if e.evidence_type == "synthetic_response" or e.claim_type == "synthetic":
        return "Synthetic"
    if e.evidence_type == "deterministic_calculation":
        return "Calculated"
    if e.claim_type == "hypothesis":
        return "Unverified"
    if e.evidence_type == "model_interpretation":
        return "Model interpretation"
    return "Source data"


def retrieval_badge(e: EvidenceRecord) -> str:
    if e.retrieval_mode == "cached":
        return f"Cached ({e.retrieved_at.isoformat() if e.retrieved_at else 'time unknown'})"
    return {"live": "Live", "fixture": "Fixture", "user_input": "User input"}.get(e.retrieval_mode, "—")


def _norm(text: str) -> str:
    return " ".join(text.split()).rstrip(".").casefold()


def _dedupe(items: list[str]) -> list[str]:
    """Keep the first of items that differ only in case, spacing, or a trailing period; order is preserved."""
    seen: dict[str, str] = {}
    for item in items:
        if item and _norm(item) not in seen:
            seen[_norm(item)] = item
    return list(seen.values())


def shared_limitations(adaptations: list[Adaptation]) -> list[str]:
    """Limitations every included adaptation carries; reported once at report level, not per adaptation."""
    if not adaptations:
        return []
    common = set.intersection(*({_norm(x) for x in a.limitations} for a in adaptations))
    return _dedupe([x for x in adaptations[0].limitations if _norm(x) in common])


async def _run_of(s: Any, user_id: UUID, run_id: UUID, run_type: str, project_id: UUID, field: str) -> m.AgentRun:
    run, _ = await get_owned(s, m.AgentRun, run_id, user_id, "Run", field)
    if run.project_id != project_id:
        raise conflict(field, "The run belongs to another project.")
    if run.run_type != run_type:
        raise conflict(field, "The run has a different run type.")
    return run


async def create_report(user_id: UUID, project_id: UUID, body: ReportCreate) -> Report:
    async with session() as s, s.begin():
        project = await get_project(s, user_id, project_id, writable=True)
        campaign, _ = await get_owned(s, m.Campaign, body.campaign_id, user_id, "Campaign", "campaign_id")
        if campaign.project_id != project.id:
            raise conflict("campaign_id", "The campaign belongs to another project.")
        brand = await brand_of(s, project.id)
        runs: list[m.AgentRun] = []
        discovery: DiscoveryResult | None = None
        rehearsal: RehearsalResult | None = None
        evaluation: EvaluationResult | None = None
        adaptations: list[Adaptation] = []
        study_id: UUID | None = None
        discovery_version: str | None = None

        if body.discovery_run_id is not None:
            run = await _run_of(s, user_id, body.discovery_run_id, "market_discovery", project.id, "discovery_run_id")
            if run.campaign_id not in (None, campaign.id):
                raise conflict("discovery_run_id", "The discovery run belongs to another campaign.")
            if run.status in USABLE:
                discovery, runs = await discovery_result(s, run), runs + [run]
                discovery_version = run.inputs.get("content_version_id")
        if body.rehearsal_run_id is not None:
            run = await _run_of(s, user_id, body.rehearsal_run_id, "campaign_rehearsal", project.id, "rehearsal_run_id")
            if run.campaign_id != campaign.id:
                raise conflict("rehearsal_run_id", "The rehearsal belongs to another campaign.")
            if run.status in USABLE:
                study = await s.get(m.Study, run.study_id)
                rehearsal, runs, study_id = await rehearsal_result(s, run, study), runs + [run], run.study_id
        for index, adaptation_id in enumerate(body.adaptation_ids):
            field = f"adaptation_ids.{index}"
            row, _ = await get_owned(s, m.Adaptation, adaptation_id, user_id, "Adaptation", field)
            if row.campaign_id != campaign.id:
                raise conflict(field, "The adaptation belongs to another campaign.")
            adaptations += await to_adaptations(s, [row])
            if row.run_id and row.run_id not in {r.id for r in runs}:
                generating = await s.get(m.AgentRun, row.run_id)
                runs.append(generating)  # type: ignore[arg-type]
        if body.evaluation_id is not None:
            row, _ = await get_owned(s, m.Evaluation, body.evaluation_id, user_id, "Evaluation", "evaluation_id")
            if row.campaign_id != campaign.id:
                raise conflict("evaluation_id", "The evaluation belongs to another campaign.")
            if row.status in USABLE:
                evaluation_run = await s.get(m.AgentRun, row.run_id)
                evaluation, runs = await evaluation_result(s, row, evaluation_run), runs + [evaluation_run]  # type: ignore[arg-type,list-item]

        present = {"discovery": discovery, "rehearsal": rehearsal, "adaptations": adaptations, "evaluation": evaluation}
        missing = [section for section in SECTIONS if not present[section]]
        version_id = (
            (evaluation and evaluation.source_content_version_id)
            or (rehearsal and rehearsal.content_version_id)
            or (adaptations and adaptations[0].source_content_version_id)
            or discovery_version
        )
        version = await s.get(m.CampaignVersion, UUID(str(version_id))) if version_id else None
        if version is None:
            version = (
                await s.execute(
                    select(m.CampaignVersion)
                    .where(m.CampaignVersion.campaign_id == campaign.id)
                    .order_by(m.CampaignVersion.version_number.desc())
                    .limit(1)
                )
            ).scalar_one()
        number = 1 + (
            await s.scalar(select(func.max(m.Report.version_number)).where(m.Report.campaign_id == campaign.id)) or 0
        )
        numbers = {
            row.id: row.version_number
            for row in (await s.execute(select(m.CampaignVersion).where(m.CampaignVersion.campaign_id == campaign.id))).scalars()
        }
        used = {
            "discovery": [discovery_version] if discovery and discovery_version else [],
            "rehearsal": [rehearsal.content_version_id] if rehearsal else [],
            "adaptations": [a.source_content_version_id for a in adaptations],
            "evaluation": [evaluation.source_content_version_id] if evaluation else [],
        }
        report = _assemble(
            report_id=uuid4(), project=project, brand_name=brand.name, campaign=campaign, version=version,
            title=body.title, number=number, discovery=discovery, rehearsal=rehearsal, adaptations=adaptations,
            evaluation=evaluation, runs=runs, missing=missing, notices=version_notices(used, numbers),
        )
        s.add(
            m.Report(
                id=report.id, project_id=project.id, campaign_id=campaign.id, study_id=study_id, title=report.title,
                status=report.status, version_number=number, mode=project.mode, content=report.model_dump(mode="json"),
                created_at=report.created_at,
            )
        )
        touch(project)
        try:
            await s.flush()
        except IntegrityError:
            raise Conflict("Another report for this campaign was created at the same time. Try again.") from None
    return report


def version_notices(used: dict[str, list[Any]], numbers: dict[UUID, int]) -> list[str]:
    """Disclose results drawn from different content versions, or copy that changed after the results."""
    by_section = {
        section: sorted({numbers[UUID(str(i))] for i in ids if UUID(str(i)) in numbers})
        for section, ids in used.items() if ids
    }
    seen = sorted({n for ns in by_section.values() for n in ns})
    notices = []
    if len(seen) > 1:
        parts = "; ".join(f"{section} v{', v'.join(map(str, ns))}" for section, ns in by_section.items() if ns)
        notices.append(f"{VERSION_NOTICE} this report combines results from different content versions ({parts}). "
                       "A finding about one version may not hold for another.")
    if seen and numbers and max(numbers.values()) > max(seen):
        notices.append(f"{VERSION_NOTICE} the campaign copy changed after these results. The current version is "
                       f"v{max(numbers.values())}; the results describe v{', v'.join(map(str, seen))}.")
    return notices


def _assemble(
    *, report_id: UUID, project: m.Project, brand_name: str, campaign: m.Campaign, version: m.CampaignVersion,
    title: str, number: int, discovery: DiscoveryResult | None, rehearsal: RehearsalResult | None,
    adaptations: list[Adaptation], evaluation: EvaluationResult | None, runs: list[m.AgentRun], missing: list[str],
    notices: list[str],
) -> Report:
    now = utcnow()
    demo = project.mode == "demo"
    content = CampaignContent.model_validate(version.content)
    market: Market | None = (
        (evaluation and evaluation.market) or (rehearsal and rehearsal.market) or (discovery and discovery.market)
        or (adaptations[0].market if adaptations else None)
    )
    brief = discovery.market_brief if discovery else None
    summary = rehearsal.summary if rehearsal else None
    validation = _dedupe(
        (brief.validation_questions if brief else [])
        + (summary.validation_questions if summary else [])
        + [d.validation_question for d in (summary.disagreements if summary else [])]
    )
    if evaluation and evaluation.recommendation and market:
        validation.append(f"Test the original and the recommended candidate with real people in {market.display_name} before launch.")
    findings = [f"Discovery: {f.title} ({f.confidence_label} confidence)." for f in (brief.observations if brief else [])]
    findings += [f"Synthetic rehearsal: {f.title}." for f in (summary.key_findings if summary else [])]
    changes = [f"{a.label}: {a.strategy}" for a in adaptations]
    if evaluation and evaluation.recommendation:
        rec = evaluation.recommendation
        changes.append(f"Evaluation recommendation: {rec.decision} (rule {rec.rule_id}). {rec.rationale}")
    uncertainties = [DEMO_BANNER] if demo else []  # version notices live in limitations and the export banner
    if rehearsal:
        uncertainties.append(rehearsal.simulation_disclosure.description)
    for ref in discovery.references if discovery else []:
        if ref.match_status != "resolved":
            uncertainties.append(f"'{ref.query_term}' is {ref.match_status}; any reading of it is a hypothesis.")
    uncertainties += [f"No {section} results are included." for section in missing]
    limitations = _dedupe(
        notices
        + (["Demo mode: every provider result is a fixture, not live research."] if demo else [])
        + (["Synthetic reactions are AI-generated and are not consumer research."] if rehearsal else [])
        + (["Cultural affinity does not establish demand, purchase intent, or campaign success."] if discovery else [])
        + (discovery.limitations if discovery else []) + (brief.limitations if brief else [])
        + (rehearsal.limitations if rehearsal else [])
        + shared_limitations(adaptations)  # adaptation-specific ones stay with their adaptation
        + (evaluation.limitations if evaluation else [])
        + [f"The {section} section is omitted: its stage is missing, unfinished, or failed." for section in missing]
    )
    register: dict[UUID, EvidenceRecord] = {}
    for record in (
        (discovery.evidence if discovery else []) + (rehearsal.evidence if rehearsal else [])
        + [e for a in adaptations for e in a.evidence] + (evaluation.evidence if evaluation else [])
    ):
        register.setdefault(record.id, record)
    metadata: list[RunMetadata] = [run_metadata(run) for run in runs]
    steps = [step for meta in metadata for step in meta.steps]
    headline = content.headline or (content.body or "")[:80]
    where = market.display_name if market else "its target market"
    return Report(
        id=report_id, project_id=project.id, campaign_id=campaign.id, title=title,
        status="partial" if missing else "completed", version_number=number, mode=project.mode,  # type: ignore[arg-type]
        created_at=now, market=market,
        executive_summary=ExecutiveSummary(
            investigated=f"How {brand_name}'s campaign '{campaign.name}' (\"{headline}\") may be received in {where}.",
            findings=findings, changes=changes, uncertainties=_dedupe(uncertainties),
            next_steps=(
                [f"Test the {len(validation)} open question{'s' if len(validation) > 1 else ''} under Recommended "
                 "validation steps with real people before launch."] if validation else []
            ) + [f"Run the {section} stage to complete this report." for section in missing],
        ),
        campaign=ReportCampaignSnapshot(
            campaign_id=campaign.id, name=campaign.name, campaign_type=campaign.campaign_type,  # type: ignore[arg-type]
            content_version_id=version.id, content=content,
        ),
        discovery=ReportDiscoverySection(
            run_id=discovery.run_id, market=discovery.market, research_question=discovery.research_question,
            references=discovery.references, market_brief=brief,
        ) if discovery else None,
        rehearsal=ReportRehearsalSection(
            run_id=rehearsal.run_id, simulation_disclosure=rehearsal.simulation_disclosure,
            dimension_results=rehearsal.dimension_results, summary=summary,
        ) if rehearsal else None,
        adaptations=adaptations,
        evaluation=evaluation,
        evidence_register=list(register.values()),
        limitations=limitations,
        validation_steps=validation,
        missing_sections=missing,
        reproducibility=ReproducibilityInfo(
            runs=metadata,
            scoring_version=evaluation.scoring_version if evaluation else None,
            model_ids=sorted({step.model_id for step in steps if step.model_id}),
            prompt_versions=_dedupe([step.prompt_version or "" for step in steps]),
            generated_at=now,
            notes=[
                "Assembled deterministically from stored results; no model was called for this report.",
                "Demo mode: provider outputs are fixtures, so reruns reproduce identical results."
                if demo else "Live runs can differ on rerun because model and Qloo outputs may change.",
            ],
        ),
    )


def to_summary(row: m.Report) -> ReportSummary:
    return ReportSummary(
        id=row.id, project_id=row.project_id, campaign_id=row.campaign_id, title=row.title,
        status=row.status, version_number=row.version_number, mode=row.mode, created_at=row.created_at,  # type: ignore[arg-type]
    )


async def list_reports(user_id: UUID, project_id: UUID, limit: int, offset: int, campaign_id: UUID | None) -> ReportPage:
    async with read_session() as s:
        await get_project(s, user_id, project_id)
        stmt = select(m.Report).where(m.Report.project_id == project_id)
        if campaign_id is not None:
            stmt = stmt.where(m.Report.campaign_id == campaign_id)
        rows, total = await paginate(s, stmt.order_by(m.Report.created_at.desc(), m.Report.id), limit, offset)
    return ReportPage(items=[to_summary(r) for r in rows], limit=limit, offset=offset, total=total)


async def get_report(user_id: UUID, report_id: UUID) -> Report:
    async with read_session() as s:
        row, _ = await get_owned(s, m.Report, report_id, user_id, "Report")
    return Report.model_validate(row.content)


# --- export ----------------------------------------------------------------------------


def _cell(value: Any) -> str:
    return str("—" if value is None else value).replace("|", "\\|").replace("\n", " ")


def _content_lines(content: CampaignContent) -> list[str]:
    lines = [f"- **{label}:** {value}" for label, value in (
        ("Headline", content.headline), ("Body", content.body), ("Call to action", content.call_to_action)
    ) if value]
    if content.reference_terms:
        lines.append(f"- **Reference terms:** {', '.join(content.reference_terms)}")
    return lines


def _bullets(items: list[str], empty: str = "None.") -> list[str]:
    return [f"- {item}" for item in items] or [f"- {empty}"]


def to_markdown(report: Report) -> str:
    """Readable export that keeps disclosures, evidence labels, and limitations (08 section 10.4)."""
    out: list[str] = [f"# {report.title}", ""]
    if report.mode == "demo":
        out += [f"> **{DEMO_BANNER}**", ""]
    out += [x for notice in report.limitations if notice.startswith(VERSION_NOTICE) for x in (f"> **{notice}**", "")]
    if report.rehearsal:
        out += [f"> **Synthetic data:** {report.rehearsal.simulation_disclosure.description}", ""]
    out += [
        f"Report version {report.version_number} · status {report.status} · {report.mode} mode · "
        f"created {report.created_at.isoformat()}" + (f" · market {report.market.display_name}" if report.market else ""),
        "",
        "## Executive summary", "", f"**Investigated:** {report.executive_summary.investigated}", "",
        "**Findings**", *_bullets(report.executive_summary.findings), "",
        "**Changes**", *_bullets(report.executive_summary.changes), "",
        "**Uncertainties**", *_bullets(report.executive_summary.uncertainties), "",
        "**Next steps**", *_bullets(report.executive_summary.next_steps), "",
        "## Campaign reviewed", "",
        f"{report.campaign.name} ({report.campaign.campaign_type}), content version {report.campaign.content_version_id}",
        "", *_content_lines(report.campaign.content), "",
    ]
    labels = {e.id: evidence_label(e) for e in report.evidence_register}

    def cites(ids: list[UUID]) -> str:
        return ", ".join(f"{str(i)[:8]} ({labels.get(i, 'unknown')})" for i in ids) or "none"

    out += ["## Market discovery", ""]
    if report.discovery:
        d = report.discovery
        out += [f"**Research question:** {d.research_question} ({d.market.display_name})", "",
                "| Term | Match | Resolved to | Evidence |", "|---|---|---|---|"]
        out += [f"| {_cell(r.query_term)} | {r.match_status} | {_cell(r.name)} | {_cell(cites(r.evidence_ids))} |"
                for r in d.references]
        if d.market_brief:
            out += ["", f"**Brief:** {d.market_brief.summary}", ""]
            for heading, items in (("Observations", d.market_brief.observations),
                                   ("Opportunities", d.market_brief.opportunities), ("Risks", d.market_brief.risks)):
                out += [f"**{heading}**"] + _bullets([
                    f"{f.title} — {f.explanation} [{f.claim_type}; {f.confidence_label} confidence; "
                    f"evidence: {cites(f.evidence_ids)}]" for f in items
                ]) + [""]
    else:
        out += ["Not included (stage missing, unfinished, or failed).", ""]

    out += ["## Synthetic audience rehearsal", ""]
    if report.rehearsal:
        r = report.rehearsal
        disclosure = r.simulation_disclosure
        out += [
            f"> {disclosure.description} Generated {disclosure.generated_responses} of "
            f"{disclosure.requested_responses} requested reactions; not an independent human sample. "
            f"Grounded in discovery evidence: {'yes' if disclosure.grounded else 'no'} "
            f"({disclosure.grounding_evidence_count} records).", "",
            "| Dimension | Score (0-100) | Higher is better | n | Spread | Disagreement |", "|---|---|---|---|---|---|",
        ]
        for name in ("clarity", "brand_fidelity", "cultural_relevance", "cultural_risk"):
            result = getattr(r.dimension_results, name)
            if result:
                out.append(f"| {name} | {_cell(result.score)} | {'yes' if result.higher_is_better else 'no'} | "
                           f"{result.n} | {_cell(result.spread)} | {'yes' if result.disagreement else 'no'} |")
        if r.summary:
            for heading, findings in (("Key findings", r.summary.key_findings),
                                      ("Potential confusions", r.summary.potential_confusions),
                                      ("Potential cultural risks", r.summary.potential_cultural_risks)):
                out += ["", f"**{heading}** (synthetic)"] + _bullets([
                    f"{f.title} — {f.summary} [{f.claim_type}; {f.confidence_label} confidence; "
                    f"{len(f.supporting_response_ids)} supporting synthetic reactions]" for f in findings
                ])
            out += ["", "**Disagreements**"] + _bullets([
                f"{d.topic}: " + "; ".join(f"{c.label} ({len(c.response_ids)})" for c in d.interpretations)
                + f". Validate: {d.validation_question}" for d in r.summary.disagreements
            ])
        out.append("")
    else:
        out += ["Not included (stage missing, unfinished, or failed).", ""]

    out += ["## Adaptations", ""]
    shared = {_norm(x) for x in shared_limitations(report.adaptations)}
    if shared:
        out += ["Limitations shared by every adaptation are listed once, under Limitations.", ""]
    for a in report.adaptations:
        checks = a.checks
        out += [f"### {a.label} ({a.origin})", "", f"**Strategy:** {a.strategy}", "", *_content_lines(a.content), "",
                f"- Protected terms preserved: {'yes' if checks.protected_terms_preserved else 'no'}"
                + (f" (missing: {', '.join(checks.missing_protected_terms)})" if checks.missing_protected_terms else ""),
                f"- Prohibited terms found: {', '.join(checks.prohibited_terms_found) or 'none'}",
                *[f"- Change to {c.field} ({c.reasoning_type}): {c.reason} [evidence: {cites(c.evidence_ids)}]" for c in a.changes],
                *[f"- Warning ({w.severity}, {w.source}): {w.description}" for w in a.warnings],
                *[f"- Limitation: {item}" for item in a.limitations if _norm(item) not in shared], ""]
    if not report.adaptations:
        out += ["Not included (stage missing).", ""]

    out += ["## Evaluation", ""]
    if report.evaluation:
        e = report.evaluation
        if e.recommendation:
            out += [f"**Recommendation:** {e.recommendation.decision} (rule {e.recommendation.rule_id}). "
                    f"{e.recommendation.rationale}", ""]
        out += [f"Scores are model assessments aggregated deterministically (scoring version {e.scoring_version}).", "",
                "| Candidate | Overall | Clarity | Brand fidelity | Cultural relevance | Cultural risk (lower is better) |",
                "|---|---|---|---|---|---|"]
        for c in e.results:
            sc = c.dimension_scores
            out.append(f"| {_cell(c.label)} | {_cell(c.overall_score)} | {_cell(sc.clarity)} | {_cell(sc.brand_fidelity)} | "
                       f"{_cell(sc.cultural_relevance)} | {_cell(sc.cultural_risk)} |")
        out += ["", "**Comparability**", *_bullets(e.comparability.notes), ""]
    else:
        out += ["Not included (stage missing, unfinished, or failed).", ""]

    out += ["## Evidence register", "", "| ID | Label | Retrieval | Title | Source |", "|---|---|---|---|---|"]
    out += [f"| {str(e.id)[:8]} | {evidence_label(e)} | {_cell(retrieval_badge(e))} | {_cell(e.title)} | "
            f"{_cell(e.source_provider + (f' / {e.source_workflow}' if e.source_workflow else ''))} |"
            for e in report.evidence_register]
    out += ["", "## Limitations", *_bullets([x for x in report.limitations if not x.startswith(VERSION_NOTICE)]), "",
            "## Recommended validation steps", *_bullets(report.validation_steps), "",
            "## Missing sections", *_bullets(report.missing_sections), "",
            "## Reproducibility", "",
            f"- Scoring version: {report.reproducibility.scoring_version or 'n/a'}",
            f"- Model ids: {', '.join(report.reproducibility.model_ids) or 'none recorded'}",
            f"- Prompt versions: {', '.join(report.reproducibility.prompt_versions) or 'none recorded'}",
            *[f"- Run {meta.run_id} ({meta.mode}): {meta.started_at} to {meta.completed_at}" for meta in report.reproducibility.runs],
            *[f"- {note}" for note in report.reproducibility.notes], ""]
    return "\n".join(out)


def export(report: Report, fmt: str) -> tuple[bytes, str, str]:
    """(body, media type, filename) for a download."""
    slug = re.sub(r"[^a-z0-9]+", "-", report.title.lower()).strip("-")[:60] or "report"
    stem = f"nativeproof-{slug}-v{report.version_number}"
    if fmt == "json":
        return json.dumps(report.model_dump(mode="json"), indent=2).encode(), "application/json", f"{stem}.json"
    return to_markdown(report).encode(), "text/markdown; charset=utf-8", f"{stem}.md"
