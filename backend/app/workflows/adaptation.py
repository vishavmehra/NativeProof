"""Voice adaptation: generate variants, run deterministic constraint checks, then the Red Team review."""

import time
from typing import TypedDict
from uuid import uuid4

from langchain_core.runnables import RunnableConfig

from app.agents import review, voice
from app.agents.brand import applied_note, brand_block, select_examples
from app.agents._common import DEMO_OUTPUT_NOTE, evidence_digest
from app.analytics import constraint_checks, merge_terms
from app.llm.gateway import LLMError
from app.schemas.adaptations import Adaptation, AdaptationChecks, AdaptationContext
from app.schemas.common import RiskFlag, StepTrace
from app.schemas.evidence import EvidenceRecord
from app.schemas.runs import RunError
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
from app.workflows.types import AdaptationInput, AdaptationOutcome, ProgressFn, WorkflowDeps

RUN = "campaign_adaptation"
S1, S2, S3, S4 = STAGES[RUN]
NOT_REVIEWED_NOTE = "The automated risk review did not complete for this adaptation."


class State(TypedDict, total=False):
    inp: AdaptationInput
    protected: list[str]
    digest: list[dict]
    handles: dict[str, EvidenceRecord]
    variants: list[voice.VariantDraft]
    checks: list[tuple[list[str], list[str], list[RiskFlag]]]
    model_flags: dict[int, list[RiskFlag]]
    applied: list[str]
    limitations: list[str]
    steps: list[StepTrace]
    error: RunError | None
    stop: bool
    partial: bool


async def loading_context(state: State, config: RunnableConfig) -> dict:
    await announce(config, RUN, 0, "Loading campaign context.")
    started, inp = time.perf_counter(), state["inp"]
    protected = merge_terms(inp.protected_terms, inp.context.brand.protected_terms, inp.request.protected_terms)
    digest, handles = evidence_digest(inp.grounding_evidence, sources_only=True)
    return {"protected": protected, "digest": digest, "handles": handles,
            "steps": [local_step(S1, "voice", "nativeproof", started)]}


async def generating_adaptations(state: State, config: RunnableConfig) -> dict:
    await announce(config, RUN, 1, "Generating adaptations.")
    started, deps, inp = time.perf_counter(), config["configurable"]["deps"], state["inp"]
    query = " ".join(p for p in (inp.source_content.headline, inp.source_content.body) if p)
    examples, retrieval_trace, retrieval_notes = await select_examples(
        inp.context.brand, query, deps.llm.capability("embeddings"), stage=S2, agent="voice")
    block, applied = brand_block(inp.context.brand, examples)
    try:
        variants, trace, notes, discarded = await voice.generate_variants(
            deps.llm, stage=S2, source=inp.source_content, market=inp.request.market,
            brand=block, protected_terms=state["protected"],
            variant_count=inp.request.variant_count, instructions=inp.request.instructions, evidence=state["digest"],
            handles=state["handles"], rehearsal_summary=inp.rehearsal_summary,
        )
    except LLMError as exc:
        error = llm_error(exc, S2, "No adaptations were saved; retrying is safe.")
        return {"steps": [*state["steps"], exc.trace], "error": error, "stop": True}
    if retrieval_trace is not None:
        trace = merge_steps(S2, "voice", [retrieval_trace, trace], started)
    notes = [*retrieval_notes, *notes, applied_note(applied)]
    if not variants:
        error = RunError(code="RUN_FAILED", stage=S2, retryable=True,
                         message="The model produced no usable adaptation. Nothing was saved; retrying is safe.")
        return {"steps": [*state["steps"], trace], "limitations": notes, "error": error, "stop": True}
    if len(variants) < inp.request.variant_count:
        notes.append(f"{len(variants)} of {inp.request.variant_count} requested variants were produced.")
    update = {"variants": variants, "steps": [*state["steps"], trace], "applied": applied,
              "limitations": [*state.get("limitations", []), *notes]}
    if discarded:  # defect #5: invalid model output is never saved, and the outcome says so
        update |= {"partial": True, "error": RunError(
            code="RUN_FAILED", stage=S2, retryable=True,
            message=f"{discarded} generated variant(s) were invalid and were not saved; {len(variants)} valid variant(s) were saved.")}
    return update


async def checking_constraints(state: State, config: RunnableConfig) -> dict:
    await announce(config, RUN, 2, "Checking brand constraints.")
    started, inp = time.perf_counter(), state["inp"]
    prohibited = inp.context.brand.prohibited_terms
    checks = [constraint_checks(inp.source_content, v.content, state["protected"], prohibited) for v in state["variants"]]
    return {"checks": checks, "steps": [*state["steps"], local_step(S3, "red_team", "nativeproof", started)]}


async def reviewing_risks(state: State, config: RunnableConfig) -> dict:
    await announce(config, RUN, 3, "Reviewing risks.")
    deps, inp = config["configurable"]["deps"], state["inp"]
    try:
        flags, trace, notes = await review.review_risks(
            deps.llm, stage=S4, source=inp.source_content, adaptations=[(v.label, v.content) for v in state["variants"]],
            market=inp.request.market, brand=brand_block(inp.context.brand)[0],
        )
    except LLMError as exc:
        error = llm_error(exc, S4, "The adaptations and their deterministic checks were saved.")
        return {"model_flags": {}, "steps": [*state["steps"], exc.trace], "error": error, "partial": True}
    partial = len(flags) < len(state["variants"])
    return {"model_flags": flags, "steps": [*state["steps"], trace], "partial": partial,
            "limitations": [*state.get("limitations", []), *notes]}


GRAPH = linear_graph(State, [(S1, loading_context), (S2, generating_adaptations), (S3, checking_constraints), (S4, reviewing_risks)])


async def run_adaptation(inp: AdaptationInput, deps: WorkflowDeps, progress: ProgressFn | None = None) -> AdaptationOutcome:
    state = await execute(GRAPH, {"inp": inp, "steps": [], "limitations": []}, deps, progress, inp.context.mode)
    ctx, req, demo = inp.context, inp.request, inp.context.mode == "demo"
    assert ctx.campaign_id is not None, "adaptation runs belong to a campaign"
    supplied = state.get("handles", {}).values()
    context = AdaptationContext(
        discovery_run_id=req.discovery_run_id, rehearsal_run_id=req.rehearsal_run_id,
        grounded=any(e.evidence_type == "qloo_source" for e in supplied), rehearsal_informed=inp.rehearsal_summary is not None,
    )
    now, adaptations = utcnow(), []
    for index, variant in enumerate(state.get("variants", []) if "checks" in state else []):
        missing, found, warnings = state["checks"][index]
        reviewed = index in state.get("model_flags", {})
        adaptations.append(Adaptation(
            id=uuid4(), project_id=ctx.project_id, campaign_id=ctx.campaign_id, run_id=ctx.run_id,
            source_content_version_id=inp.source_content_version_id, parent_adaptation_id=None, origin="generated",
            mode=ctx.mode, market=req.market, label=variant.label, strategy=variant.strategy, content=variant.content,
            changes=variant.changes,
            checks=AdaptationChecks(protected_terms_preserved=not missing, missing_protected_terms=missing,
                                    prohibited_terms_found=found, brand_voice_reviewed=reviewed, cultural_risk_reviewed=reviewed),
            warnings=warnings + state.get("model_flags", {}).get(index, []),
            limitations=[f"Not reviewed by a native speaker or local expert for {req.market.display_name}."]
            + ([] if reviewed else [NOT_REVIEWED_NOTE]) + ([DEMO_OUTPUT_NOTE] if demo else []),
            context=context, evidence=variant.evidence, created_at=now,
        ))
    return AdaptationOutcome(
        status=outcome_status(state), adaptations=adaptations, evidence=[],
        limitations=list(dict.fromkeys(([DEMO_RUN_NOTE] if demo else []) + state.get("limitations", []))),
        steps=state.get("steps", []), error=state.get("error"), brand_rules_applied=state.get("applied", []),
    )
