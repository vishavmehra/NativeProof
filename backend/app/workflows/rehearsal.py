"""Audience rehearsal: synthetic reactions, deterministic aggregation (mvp-1), and the Analyst summary."""

import asyncio
import time
from typing import TypedDict
from uuid import uuid4

from langchain_core.runnables import RunnableConfig

from app.agents import analyst, audience
from app.agents._common import DEMO_OUTPUT_NOTE, DROPPED_NOTE, evidence_digest
from app.analytics import DEFINITIONS, aggregate, rating_score
from app.analytics.scoring import SYNTHETIC_NOTE
from app.llm.gateway import LLMError
from app.schemas.common import DimensionScores, StepTrace
from app.schemas.evidence import EvidenceRecord, SourceAttribute
from app.schemas.runs import RunError
from app.schemas.studies import (
    DimensionResults,
    RehearsalSummary,
    SegmentSummary,
    SimulationDisclosure,
    SyntheticReaction,
)
from app.workflows._common import (
    DEMO_RUN_NOTE,
    STAGES,
    announce,
    execute,
    linear_graph,
    llm_error,
    local_step,
    merge_steps,
    outcome_status,
    utcnow,
)
from app.workflows.types import ProgressFn, RehearsalInput, RehearsalOutcome, WorkflowDeps

RUN = "campaign_rehearsal"
S1, S2, S3, S4 = STAGES[RUN]
GENERATION_CONCURRENCY = 2
INDEPENDENCE_NOTE = "Repeated generations from one model are not independent confirmation."


class State(TypedDict, total=False):
    inp: RehearsalInput
    segments: list[audience.SegmentDraft]
    allocation: list[int]
    digest: list[dict]
    handles: dict[str, EvidenceRecord]
    reactions: list[SyntheticReaction]
    dimension_results: DimensionResults
    segment_summaries: list[SegmentSummary]
    evidence: list[EvidenceRecord]
    summary: RehearsalSummary | None
    limitations: list[str]
    steps: list[StepTrace]
    error: RunError | None
    stop: bool
    partial: bool


def _brand(inp: RehearsalInput) -> dict:
    return inp.context.brand.model_dump(exclude_none=True)


async def loading_context(state: State, config: RunnableConfig) -> dict:
    await announce(config, RUN, 0, "Loading study context.")
    started, deps, inp = time.perf_counter(), config["configurable"]["deps"], state["inp"]
    cfg, study = inp.simulation_config, inp.study
    digest, handles = evidence_digest(inp.grounding_evidence, sources_only=True)
    update: dict = {"digest": digest, "handles": handles}
    if study.segments:
        segments = [audience.SegmentDraft(s.label, s.description, "user") for s in study.segments[: cfg.segment_count]]
        step = local_step(S1, "audience", "nativeproof", started)
    else:
        try:
            segments, step = await audience.generate_segments(
                deps.llm, stage=S1, count=cfg.segment_count, market=study.market, content=inp.content, brand=_brand(inp),
                research_questions=study.research_questions, seed=cfg.random_seed,
            )
        except LLMError as exc:
            error = llm_error(exc, S1, "No reactions were generated or saved; retrying is safe.")
            return update | {"steps": [exc.trace], "error": error, "stop": True}
    base, extra = divmod(cfg.response_count, len(segments))
    allocation = [base + (i < extra) for i in range(len(segments))]
    return update | {"segments": segments, "allocation": allocation, "steps": [step]}


async def generating_reactions(state: State, config: RunnableConfig) -> dict:
    await announce(config, RUN, 1, "Generating synthetic reactions.")
    started, deps, inp = time.perf_counter(), config["configurable"]["deps"], state["inp"]
    gate = asyncio.Semaphore(GENERATION_CONCURRENCY)
    calls = [
        (index, segment, offset, min(audience.MAX_REACTIONS_PER_CALL, count - offset))
        for index, (segment, count) in enumerate(zip(state["segments"], state["allocation"]))
        for offset in range(0, count, audience.MAX_REACTIONS_PER_CALL)
    ]

    async def call(index: int, segment: audience.SegmentDraft, offset: int, count: int):
        async with gate:
            try:
                return await audience.generate_reactions(
                    deps.llm, stage=S2, segment=segment, segment_index=index, count=count, offset=offset,
                    dimensions=inp.study.dimensions, market=inp.study.market, content=inp.content, brand=_brand(inp),
                    research_questions=inp.study.research_questions, evidence=state["digest"], handles=state["handles"],
                    seed=inp.simulation_config.random_seed,
                )
            except LLMError as exc:
                return exc

    results = await asyncio.gather(*(call(*c) for c in calls))
    reactions, traces, limitations, failures, dropped = [], [], list(state.get("limitations", [])), [], 0
    for (_, segment, _, _), result in zip(calls, results):
        if isinstance(result, LLMError):
            failures.append(result)
            traces.append(result.trace)
            limitations.append(f"Reactions for segment '{segment.label}' could not be generated ({result.code}).")
            continue
        made, trace, lost = result
        reactions += made
        traces.append(trace)
        dropped += lost
    step = merge_steps(S2, "audience", traces, started)
    if not reactions:
        error = llm_error(failures[0], S2, "No reactions were saved; retrying is safe.") if failures else RunError(
            code="RUN_FAILED", message="No synthetic reactions were generated.", stage=S2, retryable=True)
        return {"reactions": [], "steps": [*state["steps"], step], "limitations": limitations, "error": error, "stop": True}
    requested = inp.simulation_config.response_count
    if len(reactions) < requested and not failures:
        limitations.append(
            f"Demo fixtures include {len(reactions)} reactions for this study; {requested} were requested."
            if config["configurable"]["mode"] == "demo"
            else f"The model generated {len(reactions)} of {requested} requested reactions."
        )
    update = {"reactions": reactions, "steps": [*state["steps"], step], "limitations": limitations + ([DROPPED_NOTE] if dropped else [])}
    if failures:
        update |= {"partial": True, "error": llm_error(failures[0], S2, f"{len(reactions)} reactions were saved.")}
    return update


async def aggregating_results(state: State, config: RunnableConfig) -> dict:
    await announce(config, RUN, 2, "Aggregating ratings.")
    started, inp, reactions = time.perf_counter(), state["inp"], state["reactions"]
    dims = inp.study.dimensions

    def values(subset: list[SyntheticReaction], d: str) -> list[int]:
        return [r.value for x in subset for r in x.ratings if r.dimension == d]

    results = {d: aggregate(d, values(reactions, d)) for d in dims}
    summaries = []
    for s in state["segments"]:
        members = [x for x in reactions if x.segment_label == s.label]
        summaries.append(SegmentSummary(
            label=s.label, assumptions=s.assumptions, source=s.source, response_count=len(members),
            dimension_scores=DimensionScores(**{d: rating_score(values(members, d)) for d in dims}),
        ))
    now, ctx = utcnow(), inp.context
    evidence = [
        EvidenceRecord(
            id=uuid4(), project_id=ctx.project_id, evidence_type="deterministic_calculation", claim_type="derived",
            title=f"{DEFINITIONS[d][0]} score from synthetic rehearsal",
            summary=f"{DEFINITIONS[d][0]} {res.score} of 100 from {res.n} synthetic ratings; spread {res.spread}.",
            source_provider="nativeproof", source_workflow=None, source_reference=None, subject=None, related_entity=None,
            attributes=[
                SourceAttribute(key="score", label="Score (0-100)", value=res.score,
                                description="round((mean rating - 1) / 4 * 100, 1), scoring version mvp-1."),
                SourceAttribute(key="spread", label="Spread (1-5 scale)", value=res.spread,
                                description="Population standard deviation of the ratings."),
                SourceAttribute(key="disagreement", label="Disagreement", value=res.disagreement,
                                description="n >= 3 and (spread >= 1.0, or at least 25% rated <= 2 and 25% rated >= 4)."),
            ],
            method="deterministic_aggregation", retrieval_mode="generated", is_live_data=False, source_run_id=ctx.run_id,
            retrieved_at=None, limitations=[SYNTHETIC_NOTE], provenance=None, created_at=now,
        )
        for d, res in results.items()
        if res.n
    ]
    return {"dimension_results": DimensionResults(**results), "segment_summaries": summaries, "evidence": evidence,
            "steps": [*state["steps"], local_step(S3, "analyst", "nativeproof", started)]}


async def analyzing_reactions(state: State, config: RunnableConfig) -> dict:
    await announce(config, RUN, 3, "Analyzing reactions.")
    deps, inp = config["configurable"]["deps"], state["inp"]
    digest, handles = evidence_digest([*state["handles"].values(), *state["evidence"]], limit=24)
    try:
        result = await analyst.analyze(
            deps.llm, stage=S4, reactions=state["reactions"], dimension_results=state["dimension_results"],
            dimensions=inp.study.dimensions, research_questions=inp.study.research_questions, content=inp.content,
            evidence=digest, handles=handles,
        )
    except LLMError as exc:
        error = state.get("error") or llm_error(exc, S4, "The reactions and scores were saved.")
        return {"summary": None, "steps": [*state["steps"], exc.trace], "error": error, "partial": True}
    return {"summary": result.summary, "steps": [*state["steps"], result.trace],
            "limitations": [*state.get("limitations", []), *result.notes]}


GRAPH = linear_graph(State, [(S1, loading_context), (S2, generating_reactions), (S3, aggregating_results), (S4, analyzing_reactions)])


async def run_rehearsal(inp: RehearsalInput, deps: WorkflowDeps, progress: ProgressFn | None = None) -> RehearsalOutcome:
    state = await execute(GRAPH, {"inp": inp, "steps": [], "limitations": []}, deps, progress, inp.context.mode)
    reactions = state.get("reactions", [])
    supplied = len(state.get("handles", {}))
    demo = inp.context.mode == "demo"
    disclosure = SimulationDisclosure(
        description=(
            f"These reactions were generated by an AI model{' (demo fixtures)' if demo else ''} "
            "and are not responses from real people."
        ),
        requested_responses=inp.simulation_config.response_count, generated_responses=len(reactions),
        grounded=supplied > 0, grounding_evidence_count=supplied,
    )
    notes = [SYNTHETIC_NOTE, INDEPENDENCE_NOTE]
    if not supplied:
        notes.append("Ungrounded rehearsal: no discovery evidence was supplied to the generator.")
    if demo:
        notes += [DEMO_RUN_NOTE, DEMO_OUTPUT_NOTE]
    return RehearsalOutcome(
        status=outcome_status(state), simulation_disclosure=disclosure, segments=state.get("segment_summaries", []),
        reactions=reactions, dimension_results=state.get("dimension_results", DimensionResults()),
        summary=state.get("summary"), evidence=state.get("evidence", []),
        limitations=list(dict.fromkeys([*notes, *state.get("limitations", [])])), steps=state.get("steps", []),
        error=state.get("error"),
    )
