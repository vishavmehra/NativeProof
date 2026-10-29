"""Run-backed v2 features: Cultural DNA, Market Expansion, Campaign Arena, Risk Radar (README section 13).

Each resource row is created with its run (same transaction) and filled by `persist` when the run ends.
Status always mirrors the run. Workflow inputs and outcomes are the AI workstream's models (app.workflows.types).
"""

from typing import Any
from uuid import UUID, uuid4

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.analytics import SCORING_DEFINITION
from app.core.errors import Conflict
from app.db import models as m
from app.db.blobs import read as stored_bytes
from app.db.base import utcnow
from app.db.session import read_session, session
from app.schemas.adaptations import Adaptation, AdaptationContext, ContentChange
from app.schemas.arena import ArenaCreate, ArenaPage, ArenaResult, ArenaSummary, ArenaUpdate
from app.schemas.campaigns import CampaignContent, EvaluationCriteria
from app.schemas.markets import MarketComparability, MarketComparison, MarketComparisonCreate, MarketComparisonPage, MarketComparisonSummary
from app.schemas.profiles import (
    CulturalProfile,
    CulturalProfileCreate,
    CulturalProfilePage,
    CulturalProfileSummary,
    CulturalProfileUpdate,
    ProfileItem,
)
from app.schemas.risk import FindingCounts, RiskFinding, RiskFindingUpdate, RiskScan, RiskScanCreate, RiskScanPage, RiskScanSummary
from app.schemas.assets import VisionStatus
from app.schemas.studies import SimulationDisclosure
from app.services.adaptations import constraint_checks, deterministic_warnings
from app.services.campaigns import current_version
from app.services.common import apply_patch, conflict, get_owned, get_project, paginate, require_writable, touch
from app.services.results import API, discovery_result, evidence_by_ids, run_metadata, to_adaptations
from app.services.runs import (
    USABLE,
    _campaign_in,
    _check_demo_market,
    _create_run,
    _dump,
    _grounding_ids,
    _referenced,
    _union,
    _version_of,
    brand_of,
    merge_terms,
    usable_run,
)
from app.services.studies import to_study

APPLY_LIMITATION = (
    "Applied a Risk Radar alternative: a person chose it; it was not reviewed by a model or a native speaker. "
    "Only the deterministic protected- and prohibited-term checks were rerun."
)
PENDING = "The run has not finished, or it failed before producing this result."


# --- shared ------------------------------------------------------------------------------


async def _run(s: AsyncSession, run_id: UUID) -> m.AgentRun:
    run = await s.get(m.AgentRun, run_id)
    assert run is not None
    return run


async def _asset_ids(s: AsyncSession, user_id: UUID, project_id: UUID, ids: list[UUID], field: str) -> list[str]:
    out = []
    for index, asset_id in enumerate(ids):
        name = f"{field}.{index}" if field.endswith("asset_ids") else field
        asset, _ = await get_owned(s, m.Asset, asset_id, user_id, "Asset", name)
        if asset.project_id != project_id:
            raise conflict(name, "The asset belongs to another project.")
        if asset.kind != "image":
            raise conflict(name, "Only image assets can be analyzed here.")
        out.append(str(asset.id))
    return out


async def _blobs(s: AsyncSession, types: Any, asset_ids: list[str]) -> list[Any]:
    out = []
    for asset_id in asset_ids:
        asset = await s.get(m.Asset, UUID(asset_id))
        assert asset is not None
        out.append(types.AssetBlob(asset_id=asset.id, media_type=asset.content_type, data=await stored_bytes(asset)))
    return out


async def _source_content(s: AsyncSession, user_id: UUID, campaign: m.Campaign, field_prefix: str,
                          version_id: UUID | None, adaptation_id: UUID | None, content: CampaignContent | None,
                          default_current: bool) -> tuple[str, UUID | None, dict]:
    if version_id is not None:
        version = await _version_of(s, user_id, version_id, campaign, f"{field_prefix}content_version_id")
        return "content_version", version.id, version.content
    if adaptation_id is not None:
        field = f"{field_prefix}adaptation_id"
        adaptation, _ = await get_owned(s, m.Adaptation, adaptation_id, user_id, "Adaptation", field)
        if adaptation.campaign_id != campaign.id:
            raise conflict(field, "The adaptation belongs to another campaign.")
        return "adaptation", adaptation.id, adaptation.content
    if content is not None:
        return "custom", None, content.model_dump(mode="json")
    assert default_current
    version = await current_version(s, campaign.id)
    return "content_version", version.id, version.content


# --- Cultural DNA ------------------------------------------------------------------------


async def start_cultural_profile(user_id: UUID, project_id: UUID, body: CulturalProfileCreate) -> Any:
    async with read_session() as s:
        project = await get_project(s, user_id, project_id, writable=True)
        for index, market in enumerate(body.markets):
            _check_demo_market(project, market.country_code, f"markets.{index}.country_code")
        if body.campaign_id is not None:
            await _campaign_in(s, user_id, body.campaign_id, project.id, "campaign_id")
        discovery_ids = [
            str((await usable_run(s, user_id, run_id, "market_discovery", project.id, f"discovery_run_ids.{i}")).id)
            for i, run_id in enumerate(body.discovery_run_ids)
        ]
        if not discovery_ids:  # latest finished discovery per requested market
            stmt = (select(m.AgentRun).where(m.AgentRun.project_id == project.id, m.AgentRun.run_type == "market_discovery",
                                             m.AgentRun.status.in_(USABLE)).order_by(m.AgentRun.created_at.desc()))
            latest: dict[str, str] = {}
            for run in (await s.execute(stmt)).scalars():
                latest.setdefault(run.inputs["request"]["market"]["country_code"], str(run.id))
            discovery_ids = [latest[c.country_code] for c in body.markets if c.country_code in latest]
        lineage, version, previous = uuid4(), 1, None
        if body.based_on_profile_id is not None:
            prior, _ = await get_owned(s, m.CulturalProfile, body.based_on_profile_id, user_id, "Cultural profile",
                                       "based_on_profile_id")
            if prior.project_id != project.id:
                raise conflict("based_on_profile_id", "The profile belongs to another project.")
            lineage, previous = prior.lineage_id, str(prior.id)
            version = 1 + (await s.scalar(select(func.max(m.CulturalProfile.version))
                                          .where(m.CulturalProfile.lineage_id == lineage)) or 0)
        brand = await brand_of(s, project.id)
    profile_id = uuid4()
    data = body.model_dump(mode="json")
    inputs = {"request": data, "profile_id": str(profile_id), "discovery_run_ids": discovery_ids,
              "previous_profile_id": previous}

    def rows(run: m.AgentRun) -> list[Any]:
        return [m.CulturalProfile(
            id=profile_id, project_id=project.id, campaign_id=body.campaign_id, run_id=run.id, lineage_id=lineage,
            version=version, subject=body.subject, title=body.title, markets=data["markets"], notes=None,
            mode=project.mode, brand_name=brand.name, source_discovery_run_ids=discovery_ids, result=None,
            created_at=run.created_at, updated_at=run.created_at,
        )]

    return await _create_run(user_id, project, "cultural_profile", inputs, campaign_id=body.campaign_id, extra_rows=rows)


async def _profile(s: AsyncSession, row: m.CulturalProfile, summary_only: bool = False) -> Any:
    run = await _run(s, row.run_id) if row.run_id else None
    base = {"id": row.id, "project_id": row.project_id, "campaign_id": row.campaign_id, "lineage_id": row.lineage_id,
            "version": row.version, "subject": row.subject, "title": row.title, "markets": row.markets,
            "status": run.status if run else "completed", "mode": row.mode, "created_at": row.created_at,
            "updated_at": row.updated_at}
    if summary_only:
        return CulturalProfileSummary.model_validate(base)
    stored = row.result or {}
    return CulturalProfile.model_validate(base | {
        "run_id": row.run_id, "summary": stored.get("summary"), "items": stored.get("items", []),
        "market_context": stored.get("market_context", []), "missing_evidence": stored.get("missing_evidence", []),
        "limitations": stored.get("limitations", [] if row.result else [PENDING]), "notes": row.notes,
        "brand_name": row.brand_name, "source_discovery_run_ids": row.source_discovery_run_ids,
        "evidence": await evidence_by_ids(s, row.project_id, stored.get("evidence_ids", [])),
        "run_metadata": run_metadata(run) if run else None,
    })


async def list_cultural_profiles(user_id: UUID, project_id: UUID, limit: int, offset: int, campaign_id: UUID | None) -> CulturalProfilePage:
    async with read_session() as s:
        await get_project(s, user_id, project_id)
        stmt = select(m.CulturalProfile).where(m.CulturalProfile.project_id == project_id)
        if campaign_id is not None:
            stmt = stmt.where(m.CulturalProfile.campaign_id == campaign_id)
        rows, total = await paginate(s, stmt.order_by(m.CulturalProfile.created_at.desc(), m.CulturalProfile.id), limit, offset)
        items = [await _profile(s, r, summary_only=True) for r in rows]
    return CulturalProfilePage(items=items, limit=limit, offset=offset, total=total)


async def get_cultural_profile(user_id: UUID, profile_id: UUID) -> CulturalProfile:
    async with read_session() as s:
        row, _ = await get_owned(s, m.CulturalProfile, profile_id, user_id, "Cultural profile")
        return await _profile(s, row)


async def update_cultural_profile(user_id: UUID, profile_id: UUID, body: CulturalProfileUpdate) -> CulturalProfile:
    changes = body.model_dump(exclude_unset=True)
    async with session() as s, s.begin():
        row, project = await get_owned(s, m.CulturalProfile, profile_id, user_id, "Cultural profile")
        require_writable(project)
        apply_patch(row, changes, {"title": "title", "notes": "notes"}, {"title"})
        if changes:
            row.updated_at = utcnow()
        await s.flush()
        return await _profile(s, row)


# --- Market Expansion --------------------------------------------------------------------


async def start_market_comparison(user_id: UUID, project_id: UUID, body: MarketComparisonCreate) -> Any:
    async with read_session() as s:
        project = await get_project(s, user_id, project_id, writable=True)  # demo: non-JP columns are unavailable
        version_id = None
        if body.campaign_id is not None:
            campaign = await _campaign_in(s, user_id, body.campaign_id, project.id, "campaign_id")
            version_id = str((await current_version(s, campaign.id)).id)
    comparison_id, data = uuid4(), body.model_dump(mode="json")
    inputs = {"request": data, "comparison_id": str(comparison_id), "content_version_id": version_id}

    def rows(run: m.AgentRun) -> list[Any]:
        return [m.MarketComparison(
            id=comparison_id, project_id=project.id, campaign_id=body.campaign_id, run_id=run.id, markets=data["markets"],
            product_category=data["product_category"], research_question=data["research_question"],
            reference_terms=data["reference_terms"], result=None, created_at=run.created_at,
        )]

    return await _create_run(user_id, project, "market_comparison", inputs, campaign_id=body.campaign_id, extra_rows=rows)


async def _comparison(s: AsyncSession, row: m.MarketComparison, summary_only: bool = False) -> Any:
    run = await _run(s, row.run_id)
    base = {"id": row.id, "project_id": row.project_id, "campaign_id": row.campaign_id, "run_id": row.run_id,
            "status": run.status, "mode": run.mode, "markets": row.markets, "created_at": row.created_at}
    if summary_only:
        return MarketComparisonSummary.model_validate(base)
    stored = row.result or {}
    return MarketComparison.model_validate(base | {
        "product_category": row.product_category, "research_question": row.research_question,
        "reference_terms": row.reference_terms, "columns": stored.get("columns", []),
        "confirmed_references": run.inputs.get("request", {}).get("confirmed_references", []),
        "comparability": stored.get("comparability") or MarketComparability(market_specific_signals=False, notes=[PENDING]),
        "cross_market_summary": stored.get("cross_market_summary"),
        "evidence": await evidence_by_ids(s, row.project_id, stored.get("evidence_ids", [])),
        "limitations": stored.get("limitations", [] if row.result else [PENDING]), "run_metadata": run_metadata(run),
    })


async def list_market_comparisons(user_id: UUID, project_id: UUID, limit: int, offset: int) -> MarketComparisonPage:
    async with read_session() as s:
        await get_project(s, user_id, project_id)
        stmt = select(m.MarketComparison).where(m.MarketComparison.project_id == project_id)
        rows, total = await paginate(s, stmt.order_by(m.MarketComparison.created_at.desc(), m.MarketComparison.id), limit, offset)
        items = [await _comparison(s, r, summary_only=True) for r in rows]
    return MarketComparisonPage(items=items, limit=limit, offset=offset, total=total)


async def get_market_comparison(user_id: UUID, comparison_id: UUID) -> MarketComparison:
    async with read_session() as s:
        row, _ = await get_owned(s, m.MarketComparison, comparison_id, user_id, "Market comparison")
        return await _comparison(s, row)


# --- Campaign Arena ----------------------------------------------------------------------


async def start_arena(user_id: UUID, campaign_id: UUID, body: ArenaCreate) -> Any:
    async with read_session() as s:
        campaign, project = await get_owned(s, m.Campaign, campaign_id, user_id, "Campaign")
        require_writable(project)
        study, _ = await get_owned(s, m.Study, body.study_id, user_id, "Study", "study_id")
        if study.project_id != project.id or study.campaign_id != campaign.id:
            raise conflict("study_id", "The study belongs to another campaign.")
        _check_demo_market(project, study.market["country_code"], None)
        variants = []
        for index, variant in enumerate(body.variants):
            prefix = f"variants.{index}."
            source, source_id, content = await _source_content(
                s, user_id, campaign, prefix, variant.content_version_id, variant.adaptation_id, variant.content, False
            )
            assets = await _asset_ids(s, user_id, project.id, [variant.asset_id], f"{prefix}asset_id") if variant.asset_id else []
            variants.append({"variant_id": f"v{index + 1}", "label": variant.label, "source": source,
                             "source_id": str(source_id) if source_id else None, "content": content,
                             "asset_id": assets[0] if assets else None})
        grounding: list[str] = []
        if body.discovery_run_id is not None:
            discovery = await usable_run(s, user_id, body.discovery_run_id, "market_discovery", project.id, "discovery_run_id")
            grounding = await _grounding_ids(s, discovery)
    arena_id, data = uuid4(), body.model_dump(mode="json")
    inputs = {"arena_id": str(arena_id), "criteria": data["criteria"], "responses_per_variant": body.responses_per_variant,
              "grounding_evidence_ids": grounding}

    def rows(run: m.AgentRun) -> list[Any]:
        return [m.Arena(id=arena_id, project_id=project.id, campaign_id=campaign.id, study_id=study.id, run_id=run.id,
                        variants=variants, criteria=data["criteria"], preferred_variant_id=None, result=None,
                        created_at=run.created_at, updated_at=run.created_at)]

    return await _create_run(user_id, project, "campaign_arena", inputs, campaign_id=campaign.id, extra_rows=rows)


async def _arena(s: AsyncSession, row: m.Arena, summary_only: bool = False) -> Any:
    run = await _run(s, row.run_id)
    base = {"id": row.id, "project_id": row.project_id, "campaign_id": row.campaign_id, "study_id": row.study_id,
            "run_id": row.run_id, "status": run.status, "mode": run.mode,
            "variant_labels": [v["label"] for v in row.variants], "preferred_variant_id": row.preferred_variant_id,
            "created_at": row.created_at}
    if summary_only:
        return ArenaSummary.model_validate(base)
    stored = row.result or {}
    grounding = run.inputs.get("grounding_evidence_ids", [])
    pending_disclosure = SimulationDisclosure(
        description="Synthetic reactions are generated by an AI model; they are not responses from real people.",
        requested_responses=run.inputs.get("responses_per_variant", 0) * len(row.variants), generated_responses=0,
        grounded=bool(grounding), grounding_evidence_count=len(grounding),
    )
    has_assets = any(v.get("asset_id") for v in row.variants)
    pending_vision = VisionStatus(status="unavailable" if has_assets else "not_requested", provider=None, model_id=None,
                                  message=PENDING if has_assets else None)
    return ArenaResult.model_validate(base | {
        "criteria": row.criteria, "variants": stored.get("variants", []), "ranking": stored.get("ranking", []),
        "segment_differences": stored.get("segment_differences", []), "tradeoffs": stored.get("tradeoffs", []),
        "recommended_improvements": stored.get("recommended_improvements", []),
        "simulation_disclosure": stored.get("simulation_disclosure") or pending_disclosure,
        "vision": stored.get("vision") or pending_vision,
        "scoring_definition": stored.get("scoring_definition") or SCORING_DEFINITION,
        "evidence": await evidence_by_ids(s, row.project_id, stored.get("evidence_ids", [])),
        "limitations": stored.get("limitations", [] if row.result else [PENDING]), "run_metadata": run_metadata(run),
    })


async def list_arenas(user_id: UUID, campaign_id: UUID, limit: int, offset: int) -> ArenaPage:
    async with read_session() as s:
        await get_owned(s, m.Campaign, campaign_id, user_id, "Campaign")
        stmt = select(m.Arena).where(m.Arena.campaign_id == campaign_id)
        rows, total = await paginate(s, stmt.order_by(m.Arena.created_at.desc(), m.Arena.id), limit, offset)
        items = [await _arena(s, r, summary_only=True) for r in rows]
    return ArenaPage(items=items, limit=limit, offset=offset, total=total)


async def get_arena(user_id: UUID, arena_id: UUID) -> ArenaResult:
    async with read_session() as s:
        row, _ = await get_owned(s, m.Arena, arena_id, user_id, "Arena")
        return await _arena(s, row)


async def update_arena(user_id: UUID, arena_id: UUID, body: ArenaUpdate) -> ArenaResult:
    async with session() as s, s.begin():
        row, project = await get_owned(s, m.Arena, arena_id, user_id, "Arena")
        require_writable(project)
        if body.preferred_variant_id is not None and body.preferred_variant_id not in {v["variant_id"] for v in row.variants}:
            raise conflict("preferred_variant_id", "No variant with this id in the arena.")
        row.preferred_variant_id, row.updated_at = body.preferred_variant_id, utcnow()
        await s.flush()
        return await _arena(s, row)


# --- Risk Radar --------------------------------------------------------------------------


async def start_risk_scan(user_id: UUID, campaign_id: UUID, body: RiskScanCreate) -> Any:
    async with read_session() as s:
        campaign, project = await get_owned(s, m.Campaign, campaign_id, user_id, "Campaign")
        require_writable(project)
        _check_demo_market(project, body.market.country_code, "market.country_code")
        source_kind, source_id, content = await _source_content(
            s, user_id, campaign, "", body.content_version_id, body.adaptation_id, body.content, True
        )
        asset_ids = await _asset_ids(s, user_id, project.id, body.asset_ids, "asset_ids")
        grounding: list[str] = []
        if body.discovery_run_id is not None:
            discovery = await usable_run(s, user_id, body.discovery_run_id, "market_discovery", project.id, "discovery_run_id")
            grounding = await _grounding_ids(s, discovery)
    scan_id = uuid4()
    inputs = {"scan_id": str(scan_id), "grounding_evidence_ids": grounding}

    def rows(run: m.AgentRun) -> list[Any]:
        return [m.RiskScan(id=scan_id, project_id=project.id, campaign_id=campaign.id, run_id=run.id,
                           market=body.market.model_dump(mode="json"), source_kind=source_kind, source_id=source_id,
                           content=content, asset_ids=asset_ids, result=None, created_at=run.created_at)]

    return await _create_run(user_id, project, "risk_scan", inputs, campaign_id=campaign.id, extra_rows=rows)


def _finding(row: m.RiskFinding) -> RiskFinding:
    return RiskFinding.model_validate(row.payload | {"id": row.id, "status": row.status, "status_note": row.status_note,
                                                     "updated_at": row.updated_at})


async def _scan(s: AsyncSession, row: m.RiskScan, summary_only: bool = False) -> Any:
    run = await _run(s, row.run_id)
    findings = [_finding(f) for f in (await s.execute(
        select(m.RiskFinding).where(m.RiskFinding.scan_id == row.id).order_by(m.RiskFinding.position))).scalars()]
    counts = FindingCounts(**{status: sum(f.status == status for f in findings) for status in ("open", "dismissed", "resolved", "applied")},
                           **{level: sum(f.severity == level for f in findings) for level in ("high", "medium", "low")})
    base = {"id": row.id, "project_id": row.project_id, "campaign_id": row.campaign_id, "run_id": row.run_id,
            "status": run.status, "mode": run.mode, "market": row.market, "source_kind": row.source_kind,
            "source_id": row.source_id, "counts": counts, "created_at": row.created_at}
    if summary_only:
        return RiskScanSummary.model_validate(base)
    stored = row.result or {}
    pending_vision = VisionStatus(status="unavailable" if row.asset_ids else "not_requested", provider=None,
                                  model_id=None, message=PENDING if row.asset_ids else None)
    return RiskScan.model_validate(base | {
        "content": row.content, "asset_ids": row.asset_ids, "visual_observations": stored.get("visual_observations", []),
        "vision": stored.get("vision") or pending_vision, "findings": findings,
        "evidence": await evidence_by_ids(s, row.project_id, stored.get("evidence_ids", [])),
        "limitations": stored.get("limitations", [] if row.result else [PENDING]), "run_metadata": run_metadata(run),
    })


async def list_risk_scans(user_id: UUID, campaign_id: UUID, limit: int, offset: int) -> RiskScanPage:
    async with read_session() as s:
        await get_owned(s, m.Campaign, campaign_id, user_id, "Campaign")
        stmt = select(m.RiskScan).where(m.RiskScan.campaign_id == campaign_id)
        rows, total = await paginate(s, stmt.order_by(m.RiskScan.created_at.desc(), m.RiskScan.id), limit, offset)
        items = [await _scan(s, r, summary_only=True) for r in rows]
    return RiskScanPage(items=items, limit=limit, offset=offset, total=total)


async def get_risk_scan(user_id: UUID, scan_id: UUID) -> RiskScan:
    async with read_session() as s:
        row, _ = await get_owned(s, m.RiskScan, scan_id, user_id, "Risk scan")
        return await _scan(s, row)


async def _owned_finding(s: AsyncSession, user_id: UUID, scan_id: UUID, finding_id: UUID) -> tuple[m.RiskScan, m.RiskFinding, m.Project]:
    scan, project = await get_owned(s, m.RiskScan, scan_id, user_id, "Risk scan")
    finding = await s.get(m.RiskFinding, finding_id)
    if finding is None or finding.scan_id != scan.id:
        from app.services.common import not_found
        raise not_found("Risk finding")
    require_writable(project)
    return scan, finding, project


async def update_risk_finding(user_id: UUID, scan_id: UUID, finding_id: UUID, body: RiskFindingUpdate) -> RiskFinding:
    async with session() as s, s.begin():
        _, finding, project = await _owned_finding(s, user_id, scan_id, finding_id)
        if finding.status == "applied":
            raise Conflict("This finding's alternative was applied; the finding is closed.")
        finding.status, finding.status_note, finding.updated_at = body.status, body.note, utcnow()
        touch(project)
    return _finding(finding)


async def apply_risk_alternative(user_id: UUID, scan_id: UUID, finding_id: UUID) -> Adaptation:
    """Apply the suggested alternative as a new user-edit adaptation; the campaign is never edited in place."""
    async with session() as s, s.begin():
        scan, finding, project = await _owned_finding(s, user_id, scan_id, finding_id)
        payload, location = finding.payload, finding.payload.get("text_location")
        if finding.status == "applied":
            raise Conflict("This alternative was already applied.")
        if scan.source_kind == "custom":
            raise Conflict("The scanned text is custom text, not a campaign version or adaptation; copy the alternative manually.")
        if not payload.get("suggested_alternative") or not location:
            raise Conflict("This finding has no text alternative to apply.")
        content = CampaignContent.model_validate(scan.content)
        field, excerpt = location["field"], location["excerpt"]
        before = getattr(content, field) or ""
        if excerpt not in before:
            raise Conflict("The scanned text no longer contains the flagged excerpt.")
        after = before.replace(excerpt, payload["suggested_alternative"], 1)
        edited = content.model_copy(update={field: after})
        if scan.source_kind == "adaptation":
            parent = await s.get(m.Adaptation, scan.source_id)
            assert parent is not None
            version_id, parent_id, protected = parent.source_content_version_id, parent.id, parent.protected_terms
        else:
            version_id, parent_id, protected = scan.source_id, None, []
        version = await s.get(m.CampaignVersion, version_id)
        assert version is not None
        brand = await brand_of(s, project.id)
        protected = merge_terms(brand.protected_terms, protected)
        checks = constraint_checks(CampaignContent.model_validate(version.content), edited, protected, brand.prohibited_terms)
        change = ContentChange(field=field, original=before, adapted=after, reasoning_type="user_edit", evidence_ids=[],
                               reason=f"Applied the Risk Radar alternative for a {payload['severity']} {payload['category']} finding.")
        row = m.Adaptation(
            id=uuid4(), project_id=project.id, campaign_id=scan.campaign_id, study_id=None, run_id=None,
            source_content_version_id=version_id, parent_adaptation_id=parent_id, position=0, origin="user_edit",
            mode=project.mode, market=scan.market, label=f"Risk fix: {payload['category'].replace('_', ' ')}",
            strategy=f"Applied the suggested alternative for: {payload['observation']}"[:500],
            content=edited.model_dump(mode="json"), changes=[change.model_dump(mode="json")],
            checks=checks.model_dump(mode="json"), warnings=[w.model_dump(mode="json") for w in deterministic_warnings(checks)],
            limitations=[APPLY_LIMITATION],
            context=AdaptationContext(discovery_run_id=None, rehearsal_run_id=None, grounded=False,
                                      rehearsal_informed=False).model_dump(mode="json"),
            evidence_ids=[], protected_terms=protected, created_at=utcnow(),
        )
        s.add(row)
        finding.status, finding.status_note, finding.updated_at = "applied", f"Applied as adaptation {row.id}.", utcnow()
        touch(project)
        await s.flush()
        return (await to_adaptations(s, [row]))[0]


# --- run engine hooks --------------------------------------------------------------------


async def build_input(s: AsyncSession, run: m.AgentRun, types: Any, context: Any, grounding: list[Any]) -> Any:
    inputs = run.inputs
    if run.run_type == "cultural_profile":
        sources = []
        for run_id in inputs["discovery_run_ids"]:
            result = await discovery_result(s, await _run(s, UUID(run_id)))
            sources.append(types.DiscoverySource(run_id=result.run_id, market=result.market, references=result.references,
                                                 market_brief=result.market_brief, evidence=result.evidence))
        previous: list[ProfileItem] = []
        if inputs.get("previous_profile_id"):
            prior = await s.get(m.CulturalProfile, UUID(inputs["previous_profile_id"]))
            previous = [ProfileItem.model_validate(i) for i in ((prior.result or {}).get("items", []) if prior else [])]
        return types.CulturalProfileInput(context=context, profile_id=UUID(inputs["profile_id"]),
                                          request=CulturalProfileCreate.model_validate(inputs["request"]),
                                          discoveries=sources, previous_items=previous)
    if run.run_type == "market_comparison":
        version = await s.get(m.CampaignVersion, UUID(inputs["content_version_id"])) if inputs.get("content_version_id") else None
        return types.MarketComparisonInput(context=context, comparison_id=UUID(inputs["comparison_id"]),
                                           request=MarketComparisonCreate.model_validate(inputs["request"]),
                                           campaign_content=CampaignContent.model_validate(version.content) if version else None)
    if run.run_type == "campaign_arena":
        arena = await s.get(m.Arena, UUID(inputs["arena_id"]))
        assert arena is not None
        study = await s.get(m.Study, arena.study_id)
        assert study is not None
        variants = []
        for v in arena.variants:
            blobs = await _blobs(s, types, [v["asset_id"]]) if v.get("asset_id") else []
            variants.append(types.ArenaVariantSpec(variant_id=v["variant_id"], label=v["label"], source=v["source"],
                                                   source_id=v["source_id"], content=CampaignContent.model_validate(v["content"]),
                                                   asset=blobs[0] if blobs else None))
        return types.ArenaInput(context=context, arena_id=arena.id, study=to_study(study, None), variants=variants,
                                criteria=EvaluationCriteria.model_validate(inputs["criteria"]),
                                responses_per_variant=inputs["responses_per_variant"], grounding_evidence=grounding)
    scan = await s.get(m.RiskScan, UUID(inputs["scan_id"]))
    assert scan is not None
    return types.RiskScanInput(context=context, scan_id=scan.id, market=scan.market, source_kind=scan.source_kind,
                               source_id=scan.source_id, content=CampaignContent.model_validate(scan.content),
                               assets=await _blobs(s, types, scan.asset_ids), grounding_evidence=grounding)


async def persist(s: AsyncSession, run: m.AgentRun, outcome: Any, new_ids: list[str], now: Any) -> tuple[dict, tuple[str, list, str]]:
    """Store the outcome on the resource row created at run start; returns (run payload, result ref)."""
    common = {"limitations": list(outcome.limitations), "brand_rules_applied": list(outcome.brand_rules_applied)}
    inputs = run.inputs
    if run.run_type == "cultural_profile":
        row = await s.get(m.CulturalProfile, UUID(inputs["profile_id"]))
        items = _dump(outcome.items)
        row.result = common | {"summary": outcome.summary, "items": items, "market_context": list(outcome.market_context),
                               "missing_evidence": list(outcome.missing_evidence),
                               "evidence_ids": _union(new_ids, _referenced(items))}
        row.updated_at = now
        return {"profile_id": str(row.id)}, ("cultural_profile", [row.id], f"{API}/cultural-profiles/{row.id}")
    if run.run_type == "market_comparison":
        row = await s.get(m.MarketComparison, UUID(inputs["comparison_id"]))
        columns = _dump(outcome.columns)
        row.result = common | {"columns": columns, "comparability": _dump(outcome.comparability),
                               "cross_market_summary": outcome.cross_market_summary,
                               "evidence_ids": _union(new_ids, _referenced(columns))}
        return {"comparison_id": str(row.id)}, ("market_comparison", [row.id], f"{API}/market-comparisons/{row.id}")
    if run.run_type == "campaign_arena":
        row = await s.get(m.Arena, UUID(inputs["arena_id"]))
        variants, improvements = _dump(outcome.variants), _dump(outcome.recommended_improvements)
        row.result = common | {
            "variants": variants, "ranking": list(outcome.ranking), "segment_differences": list(outcome.segment_differences),
            "tradeoffs": list(outcome.tradeoffs), "recommended_improvements": improvements,
            "simulation_disclosure": _dump(outcome.simulation_disclosure), "vision": _dump(outcome.vision),
            "scoring_definition": _dump(outcome.scoring_definition),
            "evidence_ids": _union(inputs.get("grounding_evidence_ids", []), new_ids, _referenced(variants), _referenced(improvements)),
        }
        row.updated_at = now
        return {"arena_id": str(row.id)}, ("arena", [row.id], f"{API}/arenas/{row.id}")
    row = await s.get(m.RiskScan, UUID(inputs["scan_id"]))
    findings = _dump(outcome.findings)
    for position, finding in enumerate(findings):
        payload = {k: v for k, v in finding.items() if k not in ("id", "status", "status_note", "updated_at")}
        s.add(m.RiskFinding(id=UUID(finding["id"]), project_id=run.project_id, scan_id=row.id, position=position,
                            payload=payload, status="open", status_note=None, created_at=now, updated_at=now))
    row.result = common | {"visual_observations": _dump(outcome.visual_observations), "vision": _dump(outcome.vision),
                           "evidence_ids": _union(new_ids, _referenced(findings))}
    return {"scan_id": str(row.id)}, ("risk_scan", [row.id], f"{API}/risk-scans/{row.id}")
