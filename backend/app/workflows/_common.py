"""Workflow plumbing: stage names (contracts/README §6), progress, step traces, errors, and graph building."""

import time
from collections.abc import Callable, Sequence
from datetime import UTC, datetime
from typing import Any
from uuid import UUID, uuid4

from langgraph.graph import END, START, StateGraph

from app.llm.gateway import LLMError, merge_usage
from app.schemas.common import ErrorCode, StepTrace
from app.schemas.evidence import EvidenceRecord
from app.schemas.runs import RunError

STAGES: dict[str, tuple[str, str, str, str]] = {
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
DEMO_MARKET_CODE = "JP"  # contracts/README §5: demo projects describe one seeded scenario (Northstar, Japan)
DEMO_UPLOADS_MESSAGE = "Demo projects do not analyze uploads"
NO_VISION_MESSAGE = "No verified vision model is configured; the text analysis still ran."
DEMO_RUN_NOTE = "Demo mode: every provider result in this run is a fixture."
RECURSION_LIMIT = 12  # four linear stages; no cycles exist, so this only guards against misuse
QLOO_CODES: dict[str, ErrorCode] = {
    "QLOO_TIMEOUT": "PROVIDER_TIMEOUT",
    "QLOO_NOT_CONFIGURED": "PROVIDER_NOT_CONFIGURED",
    "QLOO_WORKFLOW_UNAVAILABLE": "UNSUPPORTED_CAPABILITY",
}


def utcnow() -> datetime:
    return datetime.now(UTC)


async def announce(config: dict, run_type: str, index: int, message: str) -> None:
    progress = config["configurable"].get("progress")
    if progress is not None:
        if config["configurable"]["mode"] == "demo":
            message = message.rstrip(".") + " (demo fixtures)."
        await progress(STAGES[run_type][index], index, 4, message)


def local_step(stage: str, agent: str, provider: str | None, started: float, *, status: str = "completed",
               error_code: str | None = None) -> StepTrace:
    return StepTrace(stage=stage, agent=agent, status=status, provider=provider,
                     latency_ms=int((time.perf_counter() - started) * 1000), error_code=error_code)


def merge_steps(stage: str, agent: str, traces: Sequence[StepTrace], started: float) -> StepTrace:
    """One StepTrace per stage, even when the stage made several model calls."""
    ok = any(t.status == "completed" for t in traces)

    def joined(values) -> str | None:
        return ",".join(dict.fromkeys(v for v in values if v)) or None

    samplings = {t.sampling.model_dump_json() if t.sampling else "" for t in traces}
    return StepTrace(
        stage=stage, agent=agent, status="completed" if ok else "failed",
        provider=joined(t.provider for t in traces), model_id=joined(t.model_id for t in traces),
        prompt_version=joined(t.prompt_version for t in traces), schema_version=joined(t.schema_version for t in traces),
        latency_ms=int((time.perf_counter() - started) * 1000), retries=sum(t.retries for t in traces),
        fallback_used=any(t.fallback_used for t in traces), usage=merge_usage([t.usage for t in traces]),
        error_code=None if ok else next((t.error_code for t in traces if t.error_code), None),
        sampling=traces[0].sampling if traces and len(samplings) == 1 else None,
    )


def llm_error(exc: LLMError, stage: str, saved: str) -> RunError:
    return RunError(code=exc.code, message=f"{exc.message} {saved}".strip(), stage=stage, retryable=exc.retryable)


def qloo_error(error: Any, stage: str, message: str) -> RunError:
    code = QLOO_CODES.get(getattr(error, "code", "") or "", "PROVIDER_ERROR")
    return RunError(code=code, message=message, stage=stage, retryable=bool(getattr(error, "retryable", False)))


def evidence_from_draft(draft: Any, *, project_id: UUID, run_id: UUID, now: datetime) -> EvidenceRecord:
    """the EvidenceDraft is EvidenceRecord minus id, project_id, source_run_id, created_at."""
    return EvidenceRecord.model_validate(
        {**draft.model_dump(), "id": uuid4(), "project_id": project_id, "source_run_id": run_id, "created_at": now}
    )


def linear_graph(state_type: type, nodes: list[tuple[str, Callable]]) -> Any:
    """START -> stage 1 -> ... -> stage 4 -> END; a node that sets `stop` ends the run early."""
    graph = StateGraph(state_type)
    for name, fn in nodes:
        graph.add_node(name, fn)
    graph.add_edge(START, nodes[0][0])
    for (name, _), (following, _) in zip(nodes, nodes[1:]):
        graph.add_conditional_edges(name, lambda s, nxt=following: END if s.get("stop") else nxt, [following, END])
    graph.add_edge(nodes[-1][0], END)
    return graph.compile()


async def execute(graph: Any, state: dict, deps: Any, progress: Any, mode: str) -> dict:
    config = {"recursion_limit": RECURSION_LIMIT, "configurable": {"deps": deps, "progress": progress, "mode": mode}}
    return await graph.ainvoke(state, config=config)


async def observe_assets(deps: Any, assets: list[tuple[str, Any]], mode: str, stage: str) -> tuple[Any, dict, list]:
    """Vision through the adapter only; an image never goes to a text model. Returns (VisionStatus, {key: observations},
    traces)."""
    from app.schemas.assets import VisionStatus

    if not assets:
        return VisionStatus(status="not_requested", provider=None, model_id=None, message=None), {}, []
    if mode == "demo" or deps.vision is None:
        message = DEMO_UPLOADS_MESSAGE if mode == "demo" else NO_VISION_MESSAGE
        return VisionStatus(status="unavailable", provider=None, model_id=None, message=message), {}, []
    observations, traces, statuses = {}, [], []
    for key, asset in assets:
        try:
            result = await deps.vision.observe(asset.asset_id, asset.data, asset.media_type, stage=stage, agent="vision")
        except LLMError as exc:  # the gateway deadline expired; the image never goes to a text model instead
            statuses.append(VisionStatus(status="failed", provider=exc.trace.provider, model_id=exc.trace.model_id,
                                         message=exc.message))
            traces.append(exc.trace)
            continue
        statuses.append(result.status)
        observations[key] = list(result.observations)
        if result.trace is not None:
            traces.append(result.trace)
    analyzed = next((s for s in statuses if s.status == "analyzed"), None)
    return analyzed or statuses[-1], observations, traces


def outcome_status(state: dict) -> str:
    if state.get("stop") and state.get("error") is not None:
        return "failed"
    return "partial" if state.get("partial") or state.get("error") is not None else "completed"
