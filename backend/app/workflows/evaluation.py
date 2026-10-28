"""Loop evaluation: one judge call for every candidate, then deterministic scoring and rules R0-R5 (mvp-1)."""

import time
from typing import TypedDict

from langchain_core.runnables import RunnableConfig

from app.agents import review
from app.agents._common import DEMO_OUTPUT_NOTE, evidence_digest
from app.analytics import SCORING_DEFINITION, SCORING_VERSION, best_candidate, comparability, overall, recommend, tradeoff
from app.llm.gateway import LLMError
from app.schemas.common import DimensionScores, RiskFlag, StepTrace
from app.schemas.evaluations import CandidateResult, DimensionRationales, Recommendation
from app.schemas.runs import RunError
from app.workflows._common import (
    DEMO_RUN_NOTE,
    STAGES,
    announce,
    execute,
    linear_graph,
    llm_error,
    local_step,
    outcome_status,
)
from app.workflows.types import EvaluationInput, EvaluationOutcome, ProgressFn, WorkflowDeps

RUN = "campaign_evaluation"
S1, S2, S3, S4 = STAGES[RUN]
EDITED_TEXT_NOTE = "Demo fixtures cannot assess edited text."
LIMITATIONS = [
    "Scores are model assessments of the text, aggregated deterministically; not consumer measurements.",
    "Differences under 5 points are treated as not meaningful.",
]


class State(TypedDict, total=False):
    inp: EvaluationInput
    assessments: dict[str, review.Assessment]
    results: list[CandidateResult]
    recommendation: Recommendation | None
    limitations: list[str]
    steps: list[StepTrace]
    error: RunError | None
    stop: bool
    partial: bool


def _candidates(inp: EvaluationInput) -> list[tuple[str, str, object]]:
    """(candidate_id, label, content) in request order, original first."""
    return [("original", "Original", inp.source_content)] + [(str(a.id), a.label, a.content) for a in inp.candidates]


async def loading_candidates(state: State, config: RunnableConfig) -> dict:
    await announce(config, RUN, 0, "Loading candidates.")
    return {"steps": [local_step(S1, "loop", "nativeproof", time.perf_counter())]}


async def assessing_candidates(state: State, config: RunnableConfig) -> dict:
    await announce(config, RUN, 1, "Assessing candidates.")
    deps, inp = config["configurable"]["deps"], state["inp"]
    digest, handles = evidence_digest(inp.grounding_evidence, sources_only=True)
    try:
        assessments, trace, notes = await review.assess_candidates(
            deps.llm, stage=S2, candidates=[(key, content) for key, _, content in _candidates(inp)], market=inp.market,
            brand=inp.context.brand.model_dump(exclude_none=True), evidence=digest, handles=handles,
            order_seed=str(inp.evaluation_id),
        )
    except LLMError as exc:
        error = llm_error(exc, S2, "No evaluation was saved; retrying is safe.")
        return {"steps": [*state["steps"], exc.trace], "error": error, "stop": True}
    return {"assessments": assessments, "steps": [*state["steps"], trace], "limitations": notes}


async def scoring(state: State, config: RunnableConfig) -> dict:
    await announce(config, RUN, 2, "Scoring candidates.")
    started, inp = time.perf_counter(), state["inp"]
    assessments, limitations = state["assessments"], list(state.get("limitations", []))
    adaptations = {str(a.id): a for a in inp.candidates}
    original_scores = assessments["original"].scores if "original" in assessments else DimensionScores()
    results = []
    for key, label, content in _candidates(inp):
        found = assessments.get(key)
        adaptation = adaptations.get(key)
        if found is None:
            limitations.append(
                EDITED_TEXT_NOTE if config["configurable"]["mode"] == "demo"
                else f"No assessment was returned for '{label}'; its scores are null."
            )
        scores = found.scores if found else DimensionScores()
        flags: list[RiskFlag] = list(adaptation.warnings) if adaptation else []
        flags += [f for f in (found.risk_flags if found else []) if (f.category, f.description) not in {(x.category, x.description) for x in flags}]
        violations = (
            [f"Missing protected term: {t}" for t in adaptation.checks.missing_protected_terms]
            + [f"Prohibited term found: {t}" for t in adaptation.checks.prohibited_terms_found]
        ) if adaptation else []
        change = tradeoff(scores, original_scores) if adaptation else None
        results.append(CandidateResult(
            candidate_id=key, candidate_type="adaptation" if adaptation else "original",
            adaptation_id=adaptation.id if adaptation else None, label=label, content=content,
            dimension_scores=scores, dimension_rationales=found.rationales if found else DimensionRationales(),
            overall_score=overall(scores, inp.criteria), risk_flags=flags, constraint_violations=violations,
            strengths=found.strengths if found else [], weaknesses=found.weaknesses if found else [],
            tradeoffs=[change] if change else [], evidence_ids=found.evidence_ids if found else [],
        ))
    missing = any(r.overall_score is None for r in results)
    return {"results": results, "limitations": list(dict.fromkeys(limitations)), "partial": missing,
            "steps": [*state["steps"], local_step(S3, "loop", "nativeproof", started)]}


async def recommending(state: State, config: RunnableConfig) -> dict:
    await announce(config, RUN, 3, "Applying recommendation rules.")
    started, inp, results = time.perf_counter(), state["inp"], state["results"]
    original = next((r for r in results if r.candidate_type == "original"), None)
    recommendation = recommend(original, best_candidate(results), inp.market)
    return {"recommendation": recommendation, "steps": [*state["steps"], local_step(S4, "loop", "nativeproof", started)]}


GRAPH = linear_graph(State, [(S1, loading_candidates), (S2, assessing_candidates), (S3, scoring), (S4, recommending)])


async def run_evaluation(inp: EvaluationInput, deps: WorkflowDeps, progress: ProgressFn | None = None) -> EvaluationOutcome:
    state = await execute(GRAPH, {"inp": inp, "steps": [], "limitations": []}, deps, progress, inp.context.mode)
    demo = [DEMO_RUN_NOTE, DEMO_OUTPUT_NOTE] if inp.context.mode == "demo" else []
    return EvaluationOutcome(
        status=outcome_status(state), results=state.get("results", []), recommendation=state.get("recommendation"),
        comparability=comparability(inp.market, inp.source_content_version_id, inp.candidates),
        scoring_version=SCORING_VERSION, scoring_definition=SCORING_DEFINITION, evidence=[],
        limitations=list(dict.fromkeys([*LIMITATIONS, *demo, *state.get("limitations", [])])),
        steps=state.get("steps", []), error=state.get("error"),
    )
