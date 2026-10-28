"""Run engine: validates and records runs, then executes workflows as in-process tasks (D-022).

Execution is not durable. On startup every queued or running run becomes failed with
RUN_INTERRUPTED. A semaphore bounds concurrent workflows, and a lock keeps the per-user
active-run limit exact. Both are process-wide, which is correct only for a single instance.

Workflows (app.workflows, owned by the AI workstream) are pure: this module loads their
inputs, passes a progress callback that persists Run.progress, and stores what they return.
"""

import asyncio
import importlib
import logging
from collections.abc import Callable
from typing import Any
from uuid import UUID, uuid4

from sqlalchemy import func, select, update
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import get_settings
from app.core.errors import Conflict, ProviderNotConfigured, RateLimited, ValidationFailed
from app.db import models as m
from app.db.base import utcnow
from app.db.session import read_session, session
from app.schemas.adaptations import AdaptationCreate
from app.schemas.campaigns import CampaignContent, EvaluationCriteria
from app.schemas.common import ErrorDetail, Market
from app.schemas.discovery import DiscoveryCreate
from app.schemas.evaluations import EvaluationCreate
from app.schemas.evidence import EvidenceRecord
from app.schemas.runs import RunAccepted, RunError, RunProgress, RunResultRef
from app.schemas.studies import RehearsalCreate, RehearsalSummary, SimulationConfig
from app.services.campaigns import current_version
from app.services.common import conflict, get_owned, get_project, require_writable
from app.services.projects import DEMO_MARKET, to_brand
from app.services.providers import llm_configured, qloo_configured
from app.services.qloo_cache import DbQlooCache
from app.services.results import API, evidence_by_ids, to_adaptations
from app.services.studies import to_study

logger = logging.getLogger("nativeproof.runs")

ACTIVE = ("queued", "running")
USABLE = ("completed", "partial")
STAGES: dict[str, tuple[str, ...]] = {
    "market_discovery": ("resolving_references", "retrieving_affinities", "normalizing_evidence", "generating_brief"),
    "campaign_rehearsal": ("loading_context", "generating_reactions", "aggregating_results", "analyzing_reactions"),
    "campaign_adaptation": ("loading_context", "generating_adaptations", "checking_constraints", "reviewing_risks"),
    "campaign_evaluation": ("loading_candidates", "assessing_candidates", "scoring", "recommending"),
    "cultural_profile": ("loading_evidence", "retrieving_context", "synthesizing_profile", "checking_evidence"),
    "market_comparison": ("discovering_markets", "assessing_evidence", "comparing_markets", "summarizing"),
    "campaign_arena": ("loading_variants", "analyzing_creatives", "generating_reactions", "scoring_variants"),
    "risk_scan": ("loading_content", "analyzing_creatives", "assessing_risks", "checking_evidence"),
    "population_study": ("preparing_evidence", "constructing_population", "running_interviews", "analysing_results"),
    "social_simulation": ("building_network", "simulating_rounds", "analysing_dynamics", "summarizing"),
}
LABELS = {
    "market_discovery": "discovery",
    "campaign_rehearsal": "rehearsal",
    "campaign_adaptation": "adaptation",
    "campaign_evaluation": "evaluation",
    "cultural_profile": "Cultural DNA",
    "market_comparison": "market comparison",
    "campaign_arena": "arena",
    "risk_scan": "risk scan",
    "population_study": "population study",
    "social_simulation": "social simulation",
}
ENTRY_POINTS = {
    "market_discovery": "run_discovery",
    "campaign_rehearsal": "run_rehearsal",
    "campaign_adaptation": "run_adaptation",
    "campaign_evaluation": "run_evaluation",
    "cultural_profile": "run_cultural_profile",
    "market_comparison": "run_market_comparison",
    "campaign_arena": "run_arena",
    "risk_scan": "run_risk_scan",
    "population_study": "run_population_study",
    "social_simulation": "run_social_simulation",
}
V3_RUNS = {"population_study", "social_simulation"}  # checkpointed: cancel at a checkpoint, resume from it
V3_TIMEOUT_SECONDS = 3600
QLOO_RUNS = {"market_discovery", "market_comparison"}  # the Atlas pipeline; everything else needs the LLM
MAX_CONCURRENT_RUNS = 4  # per-process semaphore; a worker queue if runs must survive restarts
RUN_TIMEOUT_SECONDS = 900
SHUTDOWN_GRACE_SECONDS = 5

class RunCancelled(Exception):
    """Raised by a checkpoint after saving, when the user asked to cancel (README section 14.5)."""


SAVED_NOTE = "Completed work is saved; resume the run to continue from the last checkpoint."
RESUMABLE = RunError(code="RUN_INTERRUPTED", message=f"The server restarted during this run. {SAVED_NOTE}", retryable=True)
INTERRUPTED = RunError(
    code="RUN_INTERRUPTED",
    message="The server restarted before this run finished. No results were saved; retrying is safe.",
    retryable=True,
)
UNEXPECTED = RunError(
    code="INTERNAL_ERROR",
    message="An unexpected error stopped this run. No results were saved; retrying is safe.",
    retryable=True,
)


class _Executor:
    """Tracks background tasks. Rebinds its asyncio primitives when the event loop changes (tests)."""

    def __init__(self) -> None:
        self.loop: asyncio.AbstractEventLoop | None = None
        self.tasks: set[asyncio.Task[None]] = set()

    def bind(self) -> "_Executor":
        loop = asyncio.get_running_loop()
        if loop is not self.loop:
            self.loop, self.tasks = loop, set()
            self.slots, self.start_lock = asyncio.Semaphore(MAX_CONCURRENT_RUNS), asyncio.Lock()
        return self

    def submit(self, run_id: UUID, run_type: str) -> None:
        task = asyncio.create_task(_execute(run_id, run_type), name=f"run-{run_id}")
        self.tasks.add(task)
        task.add_done_callback(self.tasks.discard)


executor = _Executor()


def _workflows() -> Any:
    """The AI workstream's package, resolved at call time (via sys.modules, so tests can substitute it)."""
    return importlib.import_module("app.workflows")


def _workflow_types() -> Any:
    return importlib.import_module("app.workflows.types")


# --- starting runs ---------------------------------------------------------------------


def _check_demo_market(project: m.Project, country_code: str, field: str | None = "market") -> None:
    """Demo fixtures describe one scenario (D-027): the seeded Japan market only."""
    if project.mode == "demo" and country_code != DEMO_MARKET["country_code"]:
        message = "Demo projects cover only the seeded market (Japan). Create a live project for other markets."
        raise conflict(field, message) if field else Conflict(message)


def _check_provider(mode: str, run_type: str) -> None:
    if mode == "demo":
        return
    settings, label = get_settings(), LABELS[run_type]
    if run_type in QLOO_RUNS and not qloo_configured(settings):
        raise ProviderNotConfigured(
            f"Live {label} is unavailable: Qloo is not configured on the server. Use a demo project or configure Qloo."
        )
    if run_type not in QLOO_RUNS and not llm_configured(settings):
        raise ProviderNotConfigured(
            f"Live {label} is unavailable: no language model provider is configured on the server. "
            "Use a demo project or configure Nebius."
        )


async def _create_run(
    user_id: UUID, project: m.Project, run_type: str, inputs: dict[str, Any], *,
    campaign_id: UUID | None = None, study_id: UUID | None = None,
    extra_rows: Callable[[m.AgentRun], list[Any]] | None = None,
) -> RunAccepted:
    """Record a queued run (plus any resource rows it fills later, same transaction) and start it."""
    _check_provider(project.mode, run_type)
    engine = executor.bind()
    async with engine.start_lock:  # count and insert atomically on this instance
        async with session() as s, s.begin():
            await _check_active_limit(s, user_id)
            run = m.AgentRun(
                id=uuid4(), project_id=project.id, campaign_id=campaign_id, study_id=study_id, run_type=run_type,
                status="queued", mode=project.mode, inputs=inputs, steps=[], created_at=utcnow(),
            )
            s.add(run)
            await s.execute(update(m.Project).where(m.Project.id == project.id).values(last_activity_at=run.created_at))
            if extra_rows is not None:
                await s.flush()
                s.add_all(extra_rows(run))
                try:
                    await s.flush()
                except IntegrityError:
                    raise Conflict("A concurrent request created the same resource version. Try again.") from None
    engine.submit(run.id, run_type)
    return RunAccepted(run_id=run.id, status="queued", run_type=run_type, status_url=f"{API}/runs/{run.id}")  # type: ignore[arg-type]


async def _campaign_in(s: AsyncSession, user_id: UUID, campaign_id: UUID, project_id: UUID, field: str) -> m.Campaign:
    campaign, _ = await get_owned(s, m.Campaign, campaign_id, user_id, "Campaign", field)
    if campaign.project_id != project_id:
        raise conflict(field, "The campaign belongs to another project.")
    return campaign


async def _version_of(
    s: AsyncSession, user_id: UUID, version_id: UUID | None, campaign: m.Campaign, field: str
) -> m.CampaignVersion:
    if version_id is None:
        return await current_version(s, campaign.id)
    version, _ = await get_owned(s, m.CampaignVersion, version_id, user_id, "Content version", field)
    if version.campaign_id != campaign.id:
        raise conflict(field, "The content version belongs to another campaign.")
    return version


async def usable_run(
    s: AsyncSession, user_id: UUID, run_id: UUID, run_type: str, project_id: UUID, field: str,
    campaign_id: UUID | None = None,
) -> m.AgentRun:
    run, _ = await get_owned(s, m.AgentRun, run_id, user_id, "Run", field)
    if run.project_id != project_id:
        raise conflict(field, "The run belongs to another project.")
    if run.run_type != run_type:
        raise conflict(field, f"The run is not a {LABELS[run_type]} run.")
    if campaign_id is not None and run.campaign_id != campaign_id:
        raise conflict(field, "The run belongs to another campaign.")
    if run.status not in USABLE:
        raise conflict(field, f"The run has no usable result (status: {run.status}).")
    return run


async def _grounding_ids(s: AsyncSession, discovery: m.AgentRun) -> list[str]:
    """Qloo source evidence of resolved references only; ambiguous matches never ground later stages."""
    references = (discovery.result or {}).get("references", [])
    ids = [i for ref in references if ref.get("match_status") == "resolved" for i in ref.get("evidence_ids", [])]
    return [str(e.id) for e in await evidence_by_ids(s, discovery.project_id, ids) if e.evidence_type == "qloo_source"]


async def brand_of(s: AsyncSession, project_id: UUID) -> m.BrandKit:
    return (await s.execute(select(m.BrandKit).where(m.BrandKit.project_id == project_id))).scalar_one()


def brand_context(types: Any, brand: m.BrandKit) -> Any:
    """Brand Memory as the run reads it (all fields; workflows never write it, D-036)."""
    return types.BrandContext.model_validate(to_brand(brand).model_dump(exclude={"id", "updated_at"}))


def merge_terms(*groups: list[str]) -> list[str]:
    merged: dict[str, str] = {}
    for term in (t for group in groups for t in group):
        merged.setdefault(term.casefold(), term)
    return list(merged.values())


async def start_discovery(user_id: UUID, project_id: UUID, body: DiscoveryCreate) -> RunAccepted:
    async with read_session() as s:
        project = await get_project(s, user_id, project_id, writable=True)
        _check_demo_market(project, body.market.country_code, "market.country_code")
        version_id = None
        if body.campaign_id is not None:
            campaign = await _campaign_in(s, user_id, body.campaign_id, project.id, "campaign_id")
            version_id = str((await current_version(s, campaign.id)).id)
    inputs = {"request": body.model_dump(mode="json"), "content_version_id": version_id}
    return await _create_run(user_id, project, "market_discovery", inputs, campaign_id=body.campaign_id)


async def start_rehearsal(user_id: UUID, study_id: UUID, body: RehearsalCreate) -> RunAccepted:
    async with read_session() as s:
        study, project = await get_owned(s, m.Study, study_id, user_id, "Study")
        require_writable(project)
        _check_demo_market(project, study.market["country_code"], None)
        campaign = await s.get(m.Campaign, study.campaign_id)
        assert campaign is not None
        version = await _version_of(s, user_id, body.content_version_id, campaign, "content_version_id")
        grounding: list[str] = []
        if body.discovery_run_id is not None:
            discovery = await usable_run(
                s, user_id, body.discovery_run_id, "market_discovery", project.id, "discovery_run_id"
            )
            grounding = await _grounding_ids(s, discovery)
    config = body.simulation_config or SimulationConfig.model_validate(study.simulation_config)
    if study.segments and config.segment_count != len(study.segments):
        message = f"This study defines {len(study.segments)} segments; segment_count must match."
        raise ValidationFailed(
            "The supplied request is invalid.",
            details=[ErrorDetail(field="simulation_config.segment_count", message=message)],
        )
    inputs = {
        "content_version_id": str(version.id),
        "content": version.content,
        "discovery_run_id": str(body.discovery_run_id) if body.discovery_run_id else None,
        "simulation_config": config.model_dump(mode="json"),
        "grounding_evidence_ids": grounding,
    }
    return await _create_run(
        user_id, project, "campaign_rehearsal", inputs, campaign_id=study.campaign_id, study_id=study.id
    )


async def start_adaptation(user_id: UUID, campaign_id: UUID, body: AdaptationCreate) -> RunAccepted:
    async with read_session() as s:
        campaign, project = await get_owned(s, m.Campaign, campaign_id, user_id, "Campaign")
        require_writable(project)
        _check_demo_market(project, body.market.country_code, "market.country_code")
        version = await _version_of(s, user_id, body.source_content_version_id, campaign, "source_content_version_id")
        grounding: list[str] = []
        if body.discovery_run_id is not None:
            discovery = await usable_run(
                s, user_id, body.discovery_run_id, "market_discovery", project.id, "discovery_run_id"
            )
            grounding = await _grounding_ids(s, discovery)
        if body.rehearsal_run_id is not None:
            await usable_run(
                s, user_id, body.rehearsal_run_id, "campaign_rehearsal", project.id, "rehearsal_run_id", campaign.id
            )
        brand = await brand_of(s, project.id)
    inputs = {
        "request": body.model_dump(mode="json"),
        "source_content_version_id": str(version.id),
        "grounding_evidence_ids": grounding,
        "protected_terms": merge_terms(brand.protected_terms, body.protected_terms),
    }
    return await _create_run(user_id, project, "campaign_adaptation", inputs, campaign_id=campaign.id)


async def start_evaluation(user_id: UUID, campaign_id: UUID, body: EvaluationCreate) -> RunAccepted:
    async with read_session() as s:
        campaign, project = await get_owned(s, m.Campaign, campaign_id, user_id, "Campaign")
        require_writable(project)
        _check_demo_market(project, body.market.country_code, "market.country_code")
        version = await _version_of(s, user_id, body.source_content_version_id, campaign, "source_content_version_id")
        for index, adaptation_id in enumerate(body.candidate_adaptation_ids):
            field = f"candidate_adaptation_ids.{index}"
            adaptation, _ = await get_owned(s, m.Adaptation, adaptation_id, user_id, "Adaptation", field)
            if adaptation.campaign_id != campaign.id:
                raise conflict(field, "The adaptation belongs to another campaign.")
            if adaptation.source_content_version_id != version.id:
                raise conflict(field, "The adaptation was made from a different content version.")
        grounding: list[str] = []
        if body.context.discovery_run_id is not None:
            discovery = await usable_run(
                s, user_id, body.context.discovery_run_id, "market_discovery", project.id, "context.discovery_run_id"
            )
            grounding = await _grounding_ids(s, discovery)
        if body.context.baseline_rehearsal_run_id is not None:
            await usable_run(
                s, user_id, body.context.baseline_rehearsal_run_id, "campaign_rehearsal", project.id,
                "context.baseline_rehearsal_run_id", campaign.id,
            )
    inputs = {
        "request": body.model_dump(mode="json"),
        "evaluation_id": str(uuid4()),
        "grounding_evidence_ids": grounding,
    }
    return await _create_run(user_id, project, "campaign_evaluation", inputs, campaign_id=campaign.id)


# --- executing runs --------------------------------------------------------------------


async def _execute(run_id: UUID, run_type: str) -> None:
    try:
        async with executor.bind().slots:
            if not await _mark_running(run_id, run_type):
                return
            async with asyncio.timeout(V3_TIMEOUT_SECONDS if run_type in V3_RUNS else RUN_TIMEOUT_SECONDS):
                workflow_input, deps = await _build_input(run_id)
                run_workflow = getattr(_workflows(), ENTRY_POINTS[run_type])
                extra = {}
                if run_type in V3_RUNS:
                    from app.services import population

                    extra["checkpoint"] = population.checkpoint_for(run_id, run_type)
                outcome = await run_workflow(workflow_input, deps, _progress_callback(run_id), **extra)
            await _persist(run_id, outcome)
        await index_project(run_id=run_id)
    except RunCancelled:
        await _cancelled(run_id)
    except asyncio.CancelledError:
        if await _cancel_requested(run_id):
            await _cancelled(run_id)
        else:
            await _fail(run_id, INTERRUPTED)
        raise
    except TimeoutError:
        limit = (V3_TIMEOUT_SECONDS if run_type in V3_RUNS else RUN_TIMEOUT_SECONDS) // 60
        await _fail(
            run_id,
            RunError(
                code="RUN_FAILED", retryable=True,
                message=f"The run exceeded the {limit}-minute limit. No results were saved; retrying is safe.",
            ),
        )
    except Exception:
        logger.exception("Run failed unexpectedly", extra={"run_id": str(run_id), "run_type": run_type})
        await _fail(run_id, UNEXPECTED)


async def index_project(*, run_id: UUID | None = None, project_id: UUID | None = None) -> None:
    """Best-effort retrieval indexing after a write (live projects, embeddings configured). Never fails the caller."""
    try:
        from app.retrieval import get_retrieval_service
        from app.services.search import DbRetrievalStore, project_documents, sync_index

        async with read_session() as s:
            if project_id is None:
                run = await s.get(m.AgentRun, run_id)
                project_id = run.project_id if run else None
            project = await s.get(m.Project, project_id) if project_id else None
            if project is None or project.mode != "live":
                return
            store = DbRetrievalStore()
            service = get_retrieval_service("live", get_settings(), store)
            if not service.is_configured():
                return
            documents = await project_documents(s, project.id)
        await sync_index(service, store, project.id, documents)
    except Exception:
        logger.warning("Retrieval indexing failed; search re-indexes on its next query", exc_info=True)


async def _mark_running(run_id: UUID, run_type: str) -> bool:
    first = RunProgress(stage=STAGES[run_type][0], completed_steps=0, total_steps=len(STAGES[run_type]), message="Starting.")
    async with session() as s, s.begin():
        result = await s.execute(
            update(m.AgentRun)
            .where(m.AgentRun.id == run_id, m.AgentRun.status == "queued")
            .values(status="running", started_at=utcnow(), progress=first.model_dump())
        )
    return result.rowcount == 1  # type: ignore[attr-defined]


def _progress_callback(run_id: UUID) -> Any:
    async def progress(stage: str, completed_steps: int, total_steps: int, message: str) -> None:
        try:
            value = RunProgress(stage=stage, completed_steps=completed_steps, total_steps=total_steps, message=message)
            async with session() as s, s.begin():
                await s.execute(
                    update(m.AgentRun)
                    .where(m.AgentRun.id == run_id, m.AgentRun.status == "running")
                    .values(progress=value.model_dump())
                )
        except Exception:  # progress is best-effort and must never break the run
            logger.warning("Progress update skipped", extra={"run_id": str(run_id), "stage": stage}, exc_info=True)

    return progress


async def _build_input(run_id: UUID) -> tuple[Any, Any]:
    types, settings = _workflow_types(), get_settings()
    async with read_session() as s:
        run = await s.get(m.AgentRun, run_id)
        assert run is not None
        inputs, brand = run.inputs, await brand_of(s, run.project_id)
        context = types.WorkflowContext(
            run_id=run.id, project_id=run.project_id, campaign_id=run.campaign_id, mode=run.mode,
            brand=brand_context(types, brand),
        )
        grounding = await evidence_by_ids(s, run.project_id, inputs.get("grounding_evidence_ids", []))

        async def content_of(version_id: str) -> CampaignContent:
            version = await s.get(m.CampaignVersion, UUID(version_id))
            assert version is not None
            return CampaignContent.model_validate(version.content)

        async def summary_of(rehearsal_run_id: Any) -> RehearsalSummary | None:
            if not rehearsal_run_id:
                return None
            rehearsal = await s.get(m.AgentRun, UUID(str(rehearsal_run_id)))
            summary = (rehearsal.result or {}).get("summary") if rehearsal else None
            return RehearsalSummary.model_validate(summary) if summary else None

        if run.run_type == "market_discovery":
            version_id = inputs["content_version_id"]
            workflow_input = types.DiscoveryInput(
                context=context, request=DiscoveryCreate.model_validate(inputs["request"]),
                campaign_content=await content_of(version_id) if version_id else None,
            )
        elif run.run_type == "campaign_rehearsal":
            study = await s.get(m.Study, run.study_id)
            assert study is not None
            workflow_input = types.RehearsalInput(
                context=context, study=to_study(study, run.id), content_version_id=UUID(inputs["content_version_id"]),
                content=CampaignContent.model_validate(inputs["content"]),
                simulation_config=SimulationConfig.model_validate(inputs["simulation_config"]),
                grounding_evidence=grounding,
            )
        elif run.run_type == "campaign_adaptation":
            request = AdaptationCreate.model_validate(inputs["request"])
            workflow_input = types.AdaptationInput(
                context=context, source_content_version_id=UUID(inputs["source_content_version_id"]),
                source_content=await content_of(inputs["source_content_version_id"]), request=request,
                protected_terms=inputs["protected_terms"], grounding_evidence=grounding,
                rehearsal_summary=await summary_of(request.rehearsal_run_id),
            )
        elif run.run_type == "campaign_evaluation":
            request = EvaluationCreate.model_validate(inputs["request"])
            rows = (
                await s.execute(select(m.Adaptation).where(m.Adaptation.id.in_(request.candidate_adaptation_ids)))
            ).scalars()
            by_id = {a.id: a for a in await to_adaptations(s, list(rows))}
            workflow_input = types.EvaluationInput(
                context=context, evaluation_id=UUID(inputs["evaluation_id"]),
                source_content_version_id=request.source_content_version_id,
                source_content=await content_of(str(request.source_content_version_id)),
                candidates=[by_id[i] for i in request.candidate_adaptation_ids],
                criteria=EvaluationCriteria.model_validate(request.criteria.model_dump()),
                market=Market.model_validate(request.market.model_dump()), grounding_evidence=grounding,
                rehearsal_summary=await summary_of(request.context.baseline_rehearsal_run_id),
            )
        elif run.run_type in V3_RUNS:
            from app.services import population

            workflow_input = await population.build_input(s, run, types, context, grounding)
        else:
            from app.services import insights  # v2 run types

            workflow_input = await insights.build_input(s, run, types, context, grounding)
        mode = run.mode
    # Fixture results never enter the live cache, so demo runs get none.
    deps = _workflows().build_workflow_deps(mode, settings, qloo_cache=DbQlooCache() if mode == "live" else None)
    return workflow_input, deps


# --- persisting outcomes ---------------------------------------------------------------


def _dump(value: Any) -> Any:
    if value is None:
        return None
    if isinstance(value, list):
        return [_dump(item) for item in value]
    return value.model_dump(mode="json")


def _referenced(payload: Any) -> list[str]:
    """Every id listed under an `evidence_ids` key anywhere in a dumped result."""
    found: list[str] = []
    if isinstance(payload, dict):
        for key, value in payload.items():
            found += [str(i) for i in value] if key == "evidence_ids" and isinstance(value, list) else _referenced(value)
    elif isinstance(payload, list):
        for item in payload:
            found += _referenced(item)
    return found


def _union(*groups: list[Any]) -> list[str]:
    return list(dict.fromkeys(str(i) for group in groups for i in group))


def _evidence_row(run: m.AgentRun, record: EvidenceRecord) -> m.EvidenceRecord:
    if run.mode == "demo" and (record.is_live_data or record.retrieval_mode in ("live", "cached")):
        raise ValueError("A demo run produced evidence labeled as live data; refusing to store it.")
    data = record.model_dump(mode="json")
    return m.EvidenceRecord(
        id=record.id, project_id=run.project_id, source_run_id=record.source_run_id or run.id,
        evidence_type=record.evidence_type, claim_type=record.claim_type, title=record.title, summary=record.summary,
        source_provider=record.source_provider, source_workflow=record.source_workflow,
        source_reference=record.source_reference, subject=data["subject"], related_entity=data["related_entity"],
        attributes=data["attributes"], method=record.method, retrieval_mode=record.retrieval_mode,
        is_live_data=record.is_live_data, retrieved_at=record.retrieved_at, limitations=data["limitations"],
        provenance=data["provenance"], created_at=record.created_at,
    )


def _final_progress(run: m.AgentRun, status: str, error: RunError | None) -> dict[str, Any]:
    total = len(STAGES[run.run_type])
    if status in USABLE:
        message = "Complete." if status == "completed" else "Finished with partial results; see the limitations."
        if run.mode == "demo":
            message = message[:-1] + " (demo fixtures)."
        return RunProgress(stage="completed", completed_steps=total, total_steps=total, message=message).model_dump()
    current = dict(run.progress or {"stage": STAGES[run.run_type][0], "completed_steps": 0, "total_steps": total, "message": ""})
    if error is not None and error.stage:
        current["stage"] = error.stage
    return current


async def _persist(run_id: UUID, outcome: Any) -> None:
    now = utcnow()
    async with session() as s, s.begin():
        run = await s.get(m.AgentRun, run_id)
        if run is None or run.status != "running":
            return
        inputs, status = run.inputs, outcome.status
        evidence = getattr(outcome, "evidence", [])  # a social simulation reuses its population study's evidence
        existing = set(
            (await s.execute(select(m.EvidenceRecord.id).where(m.EvidenceRecord.id.in_([e.id for e in evidence])))).scalars()
        )
        new_rows = [_evidence_row(run, e) for e in evidence if e.id not in existing]  # only records new in this run
        s.add_all(new_rows)
        await s.flush()
        new_ids = [str(row.id) for row in new_rows]
        ref: tuple[str, list[Any], str]

        if run.run_type == "market_discovery":
            payload: dict[str, Any] = {
                "references": _dump(outcome.references), "market_brief": _dump(outcome.market_brief),
                "limitations": list(outcome.limitations),
            }
            payload["evidence_ids"] = _union(new_ids, _referenced(payload))
            ref = ("discovery", [run.id], f"{API}/projects/{run.project_id}/discoveries/{run.id}")
        elif run.run_type == "campaign_rehearsal":
            reactions = _dump(outcome.reactions)
            s.add_all(
                m.SyntheticResponse(
                    id=UUID(r["id"]), project_id=run.project_id, study_id=run.study_id, run_id=run.id, position=i,
                    segment_label=r["segment_label"], sentiment=r["sentiment"], payload=r, created_at=now,
                )
                for i, r in enumerate(reactions)
            )
            payload = {
                "simulation_disclosure": _dump(outcome.simulation_disclosure), "segments": _dump(outcome.segments),
                "dimension_results": _dump(outcome.dimension_results), "summary": _dump(outcome.summary),
                "limitations": list(outcome.limitations),
            }
            payload["evidence_ids"] = _union(
                inputs["grounding_evidence_ids"], new_ids, _referenced(payload), _referenced(reactions)
            )
            ref = ("rehearsal", [run.id], f"{API}/studies/{run.study_id}/rehearsals/{run.id}")
        elif run.run_type == "campaign_adaptation":
            ids = []
            for position, adaptation in enumerate(outcome.adaptations):
                data = adaptation.model_dump(mode="json")
                s.add(
                    m.Adaptation(
                        id=adaptation.id, project_id=run.project_id, campaign_id=run.campaign_id, study_id=run.study_id,
                        run_id=run.id, source_content_version_id=UUID(inputs["source_content_version_id"]),
                        parent_adaptation_id=None, position=position, origin="generated", mode=run.mode,
                        market=data["market"], label=adaptation.label, strategy=adaptation.strategy,
                        content=data["content"], changes=data["changes"], checks=data["checks"],
                        warnings=data["warnings"], limitations=data["limitations"], context=data["context"],
                        evidence_ids=_union([e["id"] for e in data["evidence"]], _referenced(data["changes"])),
                        # One timestamp per run keeps generation order (position) stable in newest-first lists.
                        protected_terms=inputs["protected_terms"], created_at=now,
                    )
                )
                ids.append(adaptation.id)
            payload = {"adaptation_ids": [str(i) for i in ids], "limitations": list(outcome.limitations)}
            ref = ("adaptations", ids, f"{API}/campaigns/{run.campaign_id}/adaptations?run_id={run.id}")
        elif run.run_type == "campaign_evaluation":
            evaluation_id = UUID(inputs["evaluation_id"])
            request = inputs["request"]
            if status in USABLE:  # the evaluation resource exists only for completed or partial runs
                results = _dump(outcome.results)
                s.add(
                    m.Evaluation(
                        id=evaluation_id, project_id=run.project_id, campaign_id=run.campaign_id, study_id=run.study_id,
                        run_id=run.id, source_content_version_id=UUID(request["source_content_version_id"]),
                        status=status, market=request["market"], criteria=request["criteria"], results=results,
                        recommendation=_dump(outcome.recommendation), comparability=_dump(outcome.comparability),
                        scoring_version=outcome.scoring_version, scoring_definition=_dump(outcome.scoring_definition),
                        limitations=list(outcome.limitations), evidence_ids=_union(new_ids, _referenced(results)),
                        created_at=now,
                    )
                )
            payload = {"evaluation_id": str(evaluation_id), "limitations": list(outcome.limitations)}
            ref = ("evaluation", [evaluation_id], f"{API}/campaigns/{run.campaign_id}/evaluations/{evaluation_id}")
        elif run.run_type in V3_RUNS:
            from app.services import population

            payload, ref = await population.persist(s, run, outcome, new_ids, now)
        else:
            from app.services import insights  # v2 run types

            payload, ref = await insights.persist(s, run, outcome, new_ids, now)

        error = outcome.error
        if status == "failed" and error is None:
            error = RunError(code="RUN_FAILED", message="The workflow failed without a reported cause.", retryable=True)
        run.result = payload
        run.status = status
        run.result_ref = (
            RunResultRef(resource=ref[0], ids=ref[1], url=ref[2]).model_dump(mode="json")  # type: ignore[arg-type]
            if status in USABLE else None
        )
        run.error = error.model_dump(mode="json") if error else None
        run.steps = _dump(list(outcome.steps))
        run.progress = _final_progress(run, status, error)
        run.completed_at = now
        await s.execute(update(m.Project).where(m.Project.id == run.project_id).values(last_activity_at=now))


async def _fail(run_id: UUID, error: RunError) -> None:
    """Record a terminal failure. Retried briefly: a run left non-terminal would hold the user's run quota."""
    for attempt in range(3):
        try:
            async with session() as s, s.begin():
                run = await s.get(m.AgentRun, run_id)
                if run is not None and run.status in ACTIVE:
                    if run.run_type in V3_RUNS and await _has_checkpoint(s, run):  # saved work stays and is resumable
                        saved = RESUMABLE if error.code == "RUN_INTERRUPTED" else error.model_copy(
                            update={"message": f"{error.message.split('. ')[0]}. {SAVED_NOTE}"})
                        _mark_failed(run, saved)
                        run.result_ref = _saved_work_ref(run)
                    else:
                        _mark_failed(run, error)
            return
        except Exception:
            if attempt == 2:
                logger.exception("Could not record run failure", extra={"run_id": str(run_id)})
            else:
                await asyncio.sleep(0.5 * (attempt + 1))


def _mark_failed(run: m.AgentRun, error: RunError) -> None:
    stage = error.stage or (run.progress or {}).get("stage")
    error = error.model_copy(update={"stage": stage})
    run.status, run.result_ref, run.completed_at = "failed", None, utcnow()
    run.error = error.model_dump(mode="json")
    run.progress = _final_progress(run, "failed", error) if run.progress else None


async def _has_checkpoint(s: AsyncSession, run: m.AgentRun) -> bool:
    if run.run_type == "population_study":
        row = await s.get(m.PopulationStudy, run.id)
        return bool(row and (row.population_id or row.checkpoint.get("completed_batches")))
    if run.run_type == "social_simulation":
        row = await s.get(m.SocialSimulation, run.id)
        return bool(row and row.checkpoint.get("completed_rounds"))
    return False


async def mark_interrupted_runs() -> int:
    """Startup sweep (a restart or a sleeping free-tier host loses in-process runs). Checkpointed population and
    social runs become resumable: failed with RUN_INTERRUPTED, saved work linked. Others fail as interrupted."""
    try:
        async with session() as s, s.begin():
            rows = (await s.execute(select(m.AgentRun).where(m.AgentRun.status.in_(ACTIVE)))).scalars().all()
            for run in rows:
                if await _has_checkpoint(s, run):
                    _mark_failed(run, RESUMABLE)
                    run.result_ref = _saved_work_ref(run)
                else:
                    _mark_failed(run, INTERRUPTED)
    except Exception:
        logger.exception("Startup sweep failed. Is the database migrated? Run: uv run alembic upgrade head")
        return 0
    if rows:
        logger.warning("Marked interrupted runs as failed", extra={"count": len(rows)})
    return len(rows)


def _saved_work_ref(run: m.AgentRun) -> dict[str, Any]:
    from app.services import population

    return population.result_ref(run)


async def _cancel_requested(run_id: UUID) -> bool:
    try:
        async with read_session() as s:
            return bool(await s.scalar(select(m.AgentRun.cancel_requested_at).where(m.AgentRun.id == run_id)))
    except Exception:
        return False


async def _cancelled(run_id: UUID) -> None:
    """Terminal `cancelled`; saved population or social work stays and stays linked."""
    async with session() as s, s.begin():
        run = await s.get(m.AgentRun, run_id)
        if run is not None and run.status in ACTIVE:
            run.status, run.completed_at, run.error = "cancelled", utcnow(), None
            run.result_ref = _saved_work_ref(run) if run.run_type in V3_RUNS else None


async def _check_active_limit(s: AsyncSession, user_id: UUID) -> None:
    active = await s.scalar(
        select(func.count(m.AgentRun.id)).join(m.Project, m.Project.id == m.AgentRun.project_id)
        .where(m.Project.owner_id == user_id, m.AgentRun.status.in_(ACTIVE))
    )
    limit = get_settings().max_active_runs_per_user
    if (active or 0) >= limit:
        raise RateLimited(f"You already have {active} active runs (limit {limit}). Wait for one to finish, then try again.")


async def cancel_run(user_id: UUID, run_id: UUID) -> Any:
    from app.services.results import to_run

    async with session() as s, s.begin():
        run, _ = await get_owned(s, m.AgentRun, run_id, user_id, "Run")
        if run.status not in ACTIVE:
            raise Conflict(f"The run has already finished ({run.status}).")
        if run.status == "queued":
            run.status, run.completed_at = "cancelled", utcnow()
            run.result_ref = _saved_work_ref(run) if run.run_type in V3_RUNS else None
        else:
            run.cancel_requested_at = utcnow()
    if run.status == "running" and run.run_type not in V3_RUNS:  # no checkpoints: stop the task now
        for task in list(executor.bind().tasks):
            if task.get_name() == f"run-{run_id}":
                task.cancel()
    return to_run(run)


async def resume_run(user_id: UUID, run_id: UUID) -> RunAccepted:
    async with read_session() as s:
        run, project = await get_owned(s, m.AgentRun, run_id, user_id, "Run")
        require_writable(project)
        if run.run_type not in V3_RUNS or run.status != "failed":
            raise Conflict("Only a failed or interrupted population study or social simulation can be resumed.")
        if not await _has_checkpoint(s, run):
            raise Conflict("This run saved no checkpoint; start a new run instead.")
    _check_provider(project.mode, run.run_type)
    engine = executor.bind()
    async with engine.start_lock:
        async with session() as s, s.begin():
            await _check_active_limit(s, user_id)
            run = await s.get(m.AgentRun, run_id)
            assert run is not None
            run.status, run.error, run.result_ref, run.completed_at, run.cancel_requested_at = "queued", None, None, None, None
    engine.submit(run.id, run.run_type)
    return RunAccepted(run_id=run.id, status="queued", run_type=run.run_type, status_url=f"{API}/runs/{run.id}")  # type: ignore[arg-type]


async def wait_idle() -> None:
    """Wait until every background run on this loop has finished (tests and shutdown)."""
    engine = executor.bind()
    while engine.tasks:
        await asyncio.wait(list(engine.tasks))


async def shutdown() -> None:
    engine = executor.bind()
    tasks = list(engine.tasks)
    for task in tasks:
        task.cancel()
    if tasks:
        await asyncio.wait(tasks, timeout=SHUTDOWN_GRACE_SECONDS)
