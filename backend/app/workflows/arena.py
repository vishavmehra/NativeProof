"""Campaign Arena: 2-4 variants rehearsed with the same segments, dimensions, and criteria (contracts/README §13).

Scores aggregate synthetic ratings under mvp-1; improvements are labeled interpretations or hypotheses; images go
only to a verified vision model. Choosing a preferred variant is not approval.
"""

import asyncio
import time
from typing import Any, TypedDict

from langchain_core.runnables import RunnableConfig

from app.agents import audience, creative
from app.agents._common import DEMO_OUTPUT_NOTE, DROPPED_NOTE, evidence_digest, pick
from app.agents.brand import applied_note, brand_block, select_examples
from app.analytics import DEFINITIONS, SCORING_DEFINITION, aggregate, overall, rating_score
from app.analytics.scoring import SYNTHETIC_NOTE
from app.llm.gateway import LLMError
from app.schemas.arena import ArenaVariantResult, Improvement
from app.schemas.assets import VisionStatus
from app.schemas.common import DIMENSIONS, DimensionScores, StepTrace
from app.schemas.evidence import EvidenceRecord
from app.schemas.runs import RunError
from app.schemas.studies import DimensionResults, SegmentSummary, SimulationDisclosure
from app.workflows._common import (
    DEMO_RUN_NOTE,
    STAGES,
    announce,
    execute,
    linear_graph,
    llm_error,
    local_step,
    merge_steps,
    observe_assets,
    outcome_status,
)
from app.workflows.types import ArenaInput, ArenaOutcome, ProgressFn, WorkflowDeps

RUN = "campaign_arena"
S1, S2, S3, S4 = STAGES[RUN]
REACTIONS_PROMPT_VERSION = "arena-reactions-v1"
CUSTOM_VARIANT_NOTE = "Demo fixtures cannot assess custom variants; their scores are null."
CONCURRENCY = 2


class State(TypedDict, total=False):
    inp: ArenaInput
    segments: list[audience.SegmentDraft]
    allocation: list[int]
    digest: list[dict]
    handles: dict[str, EvidenceRecord]
    brand_text: str
    applied: list[str]
    vision: VisionStatus
    observations: dict[str, list]
    reactions: dict[str, list]
    results: list[ArenaVariantResult]
    ranking: list[str]
    differences: list[str]
    tradeoffs: list[str]
    improvements: list[Improvement]
    limitations: list[str]
    steps: list[StepTrace]
    error: RunError | None
    stop: bool
    partial: bool


async def loading_variants(state: State, config: RunnableConfig) -> dict:
    await announce(config, RUN, 0, "Loading variants and shared segments.")
    started, deps, inp = time.perf_counter(), config["configurable"]["deps"], state["inp"]
    study, traces, notes = inp.study, [], []
    if study.segments:
        segments = [audience.SegmentDraft(s.label, s.description, "user") for s in study.segments[: study.simulation_config.segment_count]]
    else:
        try:
            segments, trace = await audience.generate_segments(
                deps.llm, stage=S1, count=study.simulation_config.segment_count, market=study.market,
                content=inp.variants[0].content, brand=inp.context.brand.model_dump(exclude_none=True),
                research_questions=study.research_questions, seed=study.simulation_config.random_seed,
            )
            traces.append(trace)
        except LLMError as exc:
            return {"steps": [exc.trace], "error": llm_error(exc, S1, "Nothing was saved; retrying is safe."), "stop": True}
    query = " ".join(v.content.headline or v.content.body or "" for v in inp.variants)
    examples, trace, notes = await select_examples(inp.context.brand, query, deps.llm.capability("embeddings"), stage=S1, agent="audience")
    traces += [trace] if trace else []
    text, applied = brand_block(inp.context.brand, examples)
    base, extra = divmod(inp.responses_per_variant, len(segments))
    digest, handles = evidence_digest(inp.grounding_evidence, sources_only=True)
    step = merge_steps(S1, "audience", traces, started) if traces else local_step(S1, "audience", "nativeproof", started)
    return {"segments": segments, "allocation": [base + (i < extra) for i in range(len(segments))], "digest": digest,
            "handles": handles, "brand_text": text, "applied": applied, "limitations": notes, "steps": [step]}


async def analyzing_creatives(state: State, config: RunnableConfig) -> dict:
    await announce(config, RUN, 1, "Analyzing creatives.")
    started, deps, inp = time.perf_counter(), config["configurable"]["deps"], state["inp"]
    assets = [(v.variant_id, v.asset) for v in inp.variants if v.asset is not None]
    vision, observations, traces = await observe_assets(deps, assets, config["configurable"]["mode"], S2)
    step = merge_steps(S2, "vision", traces, started) if traces else local_step(S2, "vision", None, started, status="skipped")
    notes = [f"Vision: {vision.message}"] if vision.message else []
    return {"vision": vision, "observations": observations, "steps": [*state["steps"], step],
            "limitations": [*state.get("limitations", []), *notes]}


async def generating_reactions(state: State, config: RunnableConfig) -> dict:
    await announce(config, RUN, 2, "Generating synthetic reactions per variant.")
    started, deps, inp = time.perf_counter(), config["configurable"]["deps"], state["inp"]
    gate = asyncio.Semaphore(CONCURRENCY)
    calls = [(v, i, s, count) for v in inp.variants for i, (s, count) in enumerate(zip(state["segments"], state["allocation"])) if count]

    async def call(variant, index, segment, count):
        async with gate:
            try:
                return await audience.generate_reactions(
                    deps.llm, stage=S3, segment=segment, segment_index=index, count=count, offset=0,
                    dimensions=inp.study.dimensions, market=inp.study.market, content=variant.content,
                    brand=state["brand_text"], research_questions=inp.study.research_questions, evidence=state["digest"],
                    handles=state["handles"], seed=inp.study.simulation_config.random_seed,
                    prompt_version=REACTIONS_PROMPT_VERSION,
                    observations=[o.description for o in state["observations"].get(variant.variant_id, [])],
                )
            except LLMError as exc:
                return exc

    results = await asyncio.gather(*(call(*c) for c in calls))
    reactions = {v.variant_id: [] for v in inp.variants}
    traces, notes, failed, error, dropped = [], list(state.get("limitations", [])), set(), None, 0
    for (variant, _, _, _), result in zip(calls, results):
        if isinstance(result, LLMError):
            traces.append(result.trace)
            failed.add(variant.variant_id)
            if deps.llm.is_fixture:
                notes.append(CUSTOM_VARIANT_NOTE)
            else:
                error = error or llm_error(result, S3, "Reactions for the other variants were saved.")
                notes.append(f"Some reactions for '{variant.label}' could not be generated ({result.code}).")
            continue
        made, trace, lost = result
        reactions[variant.variant_id] += made
        traces.append(trace)
        dropped += lost
    step = merge_steps(S3, "audience", traces, started)
    if not any(reactions.values()):
        if not deps.llm.is_fixture:
            error = error or RunError(code="RUN_FAILED", stage=S3, retryable=True, message="No synthetic reactions were generated.")
        return {"reactions": reactions, "steps": [*state["steps"], step], "limitations": notes, "error": error,
                "stop": not deps.llm.is_fixture, "partial": True}
    return {"reactions": reactions, "steps": [*state["steps"], step], "partial": bool(failed), "error": error,
            "limitations": notes + ([DROPPED_NOTE] if dropped else [])}


def _scores(results: DimensionResults) -> DimensionScores:
    return DimensionScores(**{d: getattr(results, d).score if getattr(results, d) else None for d in DIMENSIONS})


async def scoring_variants(state: State, config: RunnableConfig) -> dict:
    await announce(config, RUN, 3, "Scoring variants.")
    started, deps, inp = time.perf_counter(), config["configurable"]["deps"], state["inp"]
    dims, crit = inp.study.dimensions, inp.criteria
    results = []
    for v in inp.variants:
        mine = state["reactions"][v.variant_id]
        values = lambda subset, d: [r.value for x in subset for r in x.ratings if r.dimension == d]  # noqa: E731
        dim_results = DimensionResults(**{d: aggregate(d, values(mine, d)) for d in dims}) if mine else DimensionResults()
        segments = [SegmentSummary(label=s.label, assumptions=s.assumptions, source=s.source,
                                   response_count=len(members := [x for x in mine if x.segment_label == s.label]),
                                   dimension_scores=DimensionScores(**{d: rating_score(values(members, d)) for d in dims}))
                    for s in state["segments"]]
        flags = {(f.category, f.description): f for x in mine for f in x.risk_flags}
        results.append(ArenaVariantResult(
            variant_id=v.variant_id, label=v.label, source=v.source, source_id=v.source_id, content=v.content,
            asset_id=v.asset.asset_id if v.asset else None, visual_observations=state["observations"].get(v.variant_id, []),
            dimension_results=dim_results, segments=segments, overall_score=overall(_scores(dim_results), crit) if mine else None,
            strengths=[], weaknesses=[], risk_flags=list(flags.values()), reactions=mine,
            evidence_ids=list(dict.fromkeys(i for x in mine for i in x.evidence_ids)),
        ))
    order = sorted(range(len(results)), key=lambda i: (results[i].overall_score is None, -(results[i].overall_score or 0), i))
    scored = [results[i] for i in order if results[i].overall_score is not None]
    differences = []
    for s in state["segments"]:
        by = [(r.label, overall(next(x.dimension_scores for x in r.segments if x.label == s.label), crit)) for r in scored]
        by = [(label, score) for label, score in by if score is not None]
        if len(by) >= 2:
            label, score = max(by, key=lambda t: t[1])
            differences.append(f"{s.label}: {label} scored highest ({score}) among synthetic reactions.")
    tradeoffs = []
    if len(scored) >= 2:
        a, b = scored[0], scored[1]
        parts = [f"{DEFINITIONS[d][0].lower()} {x - y:+.1f}" for d in dims
                 if (x := getattr(_scores(a.dimension_results), d)) is not None and (y := getattr(_scores(b.dimension_results), d)) is not None and x != y]
        if parts:
            tradeoffs.append(f"{a.label} versus {b.label}: {', '.join(parts)} (synthetic scores; cultural risk: lower is better).")
    rows = [{"variant": f"V{n}", "label": r.label, "content": r.content.model_dump(include={"headline", "body", "call_to_action"}),
             "scores": _scores(r.dimension_results).model_dump(), "overall": r.overall_score,
             "reactions": [x.reaction_summary for x in r.reactions[:4]],
             "confusions": list(dict.fromkeys(c for x in r.reactions for c in x.potential_confusions))[:4],
             "visual_observations": [o.description for o in r.visual_observations]} for n, r in enumerate(results, 1)]
    improvements, notes, traces = [], list(state.get("limitations", [])), []
    for r in results:  # defect #1: an incomplete score is never renormalized; say exactly what is missing
        if r.overall_score is None:
            missing = [DEFINITIONS[d][0].lower() for d in DIMENSIONS if getattr(_scores(r.dimension_results), d) is None]
            notes.append(f"'{r.label}' has no overall score: no synthetic score for {', '.join(missing)}. "
                         "Scores are never renormalized; unscored variants rank last.")
    try:
        review = await creative.review_variants(deps.llm, stage=S4, variants=rows, brand=state["brand_text"],
                                                evidence=state["digest"], market=inp.study.market.display_name)
        traces.append(review.trace)
        by_handle = {f"V{n}": i for n, i in enumerate(range(len(results)), 1)}
        dropped = 0
        for item in review.value.reviews:
            index = by_handle.get(item.variant.strip().upper())
            if index is None:
                dropped += 1
                continue
            results[index] = results[index].model_copy(update={"strengths": item.strengths, "weaknesses": item.weaknesses})
            for imp in item.improvements:
                cited, lost = pick(imp.evidence, state["handles"])
                dropped += lost
                improvements.append(Improvement(variant_id=results[index].variant_id, suggestion=imp.suggestion,
                                                rationale=imp.rationale, claim_type="interpreted" if cited else "hypothesis",
                                                evidence_ids=[e.id for e in cited]))
        notes += [DROPPED_NOTE] if dropped else []
    except LLMError as exc:
        traces.append(exc.trace)
        if not deps.llm.is_fixture:
            notes.append(f"The variant review could not be generated ({exc.code}); scores were saved.")
    step = merge_steps(S4, "loop", traces, started)
    return {"results": results, "ranking": [results[i].variant_id for i in order], "differences": differences,
            "tradeoffs": tradeoffs, "improvements": improvements, "limitations": notes, "steps": [*state["steps"], step]}


GRAPH = linear_graph(State, [(S1, loading_variants), (S2, analyzing_creatives), (S3, generating_reactions), (S4, scoring_variants)])


async def run_arena(inp: ArenaInput, deps: WorkflowDeps, progress: ProgressFn | None = None) -> ArenaOutcome:
    state = await execute(GRAPH, {"inp": inp, "steps": [], "limitations": []}, deps, progress, inp.context.mode)
    reactions = [x for rows in state.get("reactions", {}).values() for x in rows]
    supplied = len(state.get("handles", {}))
    demo = inp.context.mode == "demo"
    disclosure = SimulationDisclosure(
        description=f"These reactions were generated by an AI model{' (demo fixtures)' if demo else ''} and are not responses from real people.",
        requested_responses=inp.responses_per_variant * len(inp.variants), generated_responses=len(reactions),
        grounded=supplied > 0, grounding_evidence_count=supplied,
    )
    applied = state.get("applied", [])
    notes = [SYNTHETIC_NOTE, "Choosing a preferred variant is not approval."] + ([DEMO_RUN_NOTE, DEMO_OUTPUT_NOTE] if demo else [])
    return ArenaOutcome(
        status=outcome_status(state), variants=state.get("results", []), ranking=state.get("ranking", []),
        segment_differences=state.get("differences", []), tradeoffs=state.get("tradeoffs", []),
        recommended_improvements=state.get("improvements", []), simulation_disclosure=disclosure,
        vision=state.get("vision") or VisionStatus(status="not_requested", provider=None, model_id=None, message=None),
        scoring_definition=SCORING_DEFINITION, evidence=[], brand_rules_applied=applied,
        limitations=list(dict.fromkeys([*notes, *state.get("limitations", []), applied_note(applied)])),
        steps=state.get("steps", []), error=state.get("error"),
    )
