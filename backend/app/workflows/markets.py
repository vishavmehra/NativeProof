"""Market Expansion: the Atlas pipeline per market, compared honestly (contracts/README §13).

Evidence quality is counted in code. When the Qloo signals are identical across markets, `market_specific_signals`
is false and nothing ranks markets on them. A market without data is `unavailable`; insight is never invented.
"""

import time
from typing import Any, TypedDict

from langchain_core.runnables import RunnableConfig

from app.agents import insight
from app.agents._common import DEMO_OUTPUT_NOTE
from app.agents.brand import applied_note, brand_block
from app.analytics import is_source_observed
from app.llm.gateway import LLMError
from app.schemas.common import StepTrace
from app.schemas.discovery import DiscoveryCreate
from app.schemas.evidence import EvidenceRecord
from app.schemas.markets import BrandCompatibility, EvidenceQuality, MarketColumn, MarketComparability
from app.schemas.runs import RunError
from app.workflows._common import (
    DEMO_MARKET_CODE,
    DEMO_RUN_NOTE,
    STAGES,
    announce,
    execute,
    linear_graph,
    llm_error,
    local_step,
    merge_steps,
    outcome_status,
)
from app.workflows.discovery import run_discovery
from app.workflows.types import DiscoveryInput, MarketComparisonInput, MarketComparisonOutcome, ProgressFn, WorkflowDeps

RUN = "market_comparison"
S1, S2, S3, S4 = STAGES[RUN]
DEMO_UNAVAILABLE = "Demo fixtures cover only the seeded market (Japan); no data exists for this market."
STRUCTURE_NOTE = "Qloo tag resolution does not depend on the market; only related interests use the market as a location signal."


class State(TypedDict, total=False):
    inp: MarketComparisonInput
    outcomes: dict[str, Any]  # country code -> DiscoveryOutcome, or None when no data can exist
    columns: list[MarketColumn]
    comparability: MarketComparability
    summary: str | None
    evidence: list[EvidenceRecord]
    applied: list[str]
    limitations: list[str]
    steps: list[StepTrace]
    error: RunError | None
    stop: bool
    partial: bool


async def discovering_markets(state: State, config: RunnableConfig) -> dict:
    await announce(config, RUN, 0, "Running discovery for each market.")
    started, deps, inp = time.perf_counter(), config["configurable"]["deps"], state["inp"]
    req, outcomes, traces, evidence = inp.request, {}, [], []
    for market in req.markets:
        if inp.context.mode == "demo" and market.country_code != DEMO_MARKET_CODE:
            outcomes[market.country_code] = None
            continue
        request = DiscoveryCreate(campaign_id=req.campaign_id, product_category=req.product_category, market=market,
                                  research_question=req.research_question, reference_terms=req.reference_terms)
        outcome = await run_discovery(DiscoveryInput(context=inp.context, request=request,
                                                     campaign_content=inp.campaign_content), deps)
        outcomes[market.country_code] = outcome
        traces += outcome.steps
        evidence += outcome.evidence
    attempted = [o for o in outcomes.values() if o is not None]
    step = merge_steps(S1, "atlas", traces, started) if traces else local_step(S1, "atlas", None, started, status="skipped")
    update = {"outcomes": outcomes, "evidence": evidence, "steps": [step]}
    if attempted and all(o.status == "failed" for o in attempted):
        return update | {"error": attempted[0].error, "stop": True}
    return update | {"partial": any(o is None or o.status != "completed" for o in outcomes.values())}


def _column(market, outcome) -> MarketColumn:
    if outcome is None:
        quality = EvidenceQuality(observed_records=0, resolved_references=0, ambiguous_references=0, unresolved_references=0,
                                  label="insufficient", note="No data.")
        return MarketColumn(market=market, status="unavailable", signals=[], opportunities=[], risks=[], hypotheses=[],
                            brand_compatibility=None, evidence_quality=quality, gaps=[DEMO_UNAVAILABLE], message=DEMO_UNAVAILABLE)
    refs, brief = outcome.references, outcome.market_brief
    resolved = [r for r in refs if r.match_status == "resolved"]
    ambiguous = [r for r in refs if r.match_status == "ambiguous"]
    unresolved = [r for r in refs if r.match_status == "unresolved"]
    observed = [e for e in outcome.evidence if is_source_observed(e) and (e.subject or e.related_entity)]
    findings = (brief.observations + brief.opportunities + brief.risks) if brief else []
    quality = EvidenceQuality(
        observed_records=len(observed), resolved_references=len(resolved), ambiguous_references=len(ambiguous),
        unresolved_references=len(unresolved), label="moderate" if observed else ("limited" if brief else "insufficient"),
        note=f"{len(observed)} observed Qloo record(s); {len(resolved)} resolved, {len(ambiguous)} ambiguous, "
             f"{len(unresolved)} unresolved reference(s).",
    )
    gaps = [f"'{r.query_term}' did not resolve." for r in unresolved] + [f"'{r.query_term}' is ambiguous; refine it." for r in ambiguous]
    if outcome.status == "failed":
        status, message = "failed", outcome.error.message if outcome.error else "Discovery failed for this market."
    elif not resolved:
        status, message = "unavailable", "No usable Qloo signals were found for this market."
    else:
        status, message = outcome.status, ("Some lookups failed; see gaps." if outcome.status == "partial" else None)
    return MarketColumn(
        market=market, status=status, signals=resolved,
        opportunities=[f for f in (brief.opportunities if brief else []) if f.claim_type != "hypothesis"],
        risks=[f for f in (brief.risks if brief else []) if f.claim_type != "hypothesis"],
        hypotheses=[f for f in findings if f.claim_type == "hypothesis"], brand_compatibility=None,
        evidence_quality=quality, gaps=gaps, message=message,
    )


async def assessing_evidence(state: State, config: RunnableConfig) -> dict:
    await announce(config, RUN, 1, "Assessing evidence quality.")
    started, inp = time.perf_counter(), state["inp"]
    columns = [_column(m, state["outcomes"][m.country_code]) for m in inp.request.markets]
    return {"columns": columns, "steps": [*state["steps"], local_step(S2, "atlas", "nativeproof", started)]}


async def comparing_markets(state: State, config: RunnableConfig) -> dict:
    await announce(config, RUN, 2, "Comparing markets.")
    started = time.perf_counter()
    signal_sets = {c.market.country_code: frozenset(r.entity_id for r in c.signals) for c in state["columns"] if c.signals}
    if len(signal_sets) < 2:
        specific, note = False, "Fewer than two markets have Qloo signals to compare, so markets are not ranked."
    elif len(set(signal_sets.values())) == 1:
        specific, note = False, "The verified Qloo signals were identical across markets, so they cannot rank the markets."
    else:
        specific, note = True, "Qloo signals differ by market; differences are aggregate affinity, not demand."
    return {"comparability": MarketComparability(market_specific_signals=specific, notes=[note, STRUCTURE_NOTE]),
            "steps": [*state["steps"], local_step(S3, "atlas", "nativeproof", started)]}


async def summarizing(state: State, config: RunnableConfig) -> dict:
    await announce(config, RUN, 3, "Summarizing across markets.")
    started, deps, inp = time.perf_counter(), config["configurable"]["deps"], state["inp"]
    text, applied = brand_block(inp.context.brand)
    available = [c for c in state["columns"] if c.evidence_quality.label == "moderate"]
    if not available:
        return {"summary": None, "applied": applied, "steps": [*state["steps"], local_step(S4, "atlas", None, started, status="skipped")],
                "limitations": [*state.get("limitations", []), "Evidence was insufficient for a cross-market summary."]}
    rows = [{"market": c.market.country_code, "status": c.status, "signals": [r.name for r in c.signals],
             "opportunities": [f.title for f in c.opportunities], "risks": [f.title for f in c.risks],
             "hypotheses": [f.title for f in c.hypotheses], "evidence_quality": c.evidence_quality.label} for c in available]
    try:
        result = await insight.summarize_markets(
            deps.llm, stage=S4, product_category=inp.request.product_category,
            research_question=inp.request.research_question, columns=rows, brand=text,
            market_specific=state["comparability"].market_specific_signals,
        )
    except LLMError as exc:
        return {"summary": None, "applied": applied, "steps": [*state["steps"], exc.trace], "partial": True,
                "error": llm_error(exc, S4, "The per-market results were saved.")}
    assessments = {a.market.upper(): a for a in result.value.markets}
    columns = []
    for c in state["columns"]:
        a = assessments.get(c.market.country_code) if c in available else None
        compat = BrandCompatibility(
            assessment=a.assessment, claim_type=a.claim_type, brand_rules_considered=applied,
            confidence_label="limited" if c.evidence_quality.label == "moderate" else "insufficient",
        ) if a else None
        columns.append(c.model_copy(update={"brand_compatibility": compat}))
    return {"summary": result.value.cross_market_summary, "columns": columns, "applied": applied,
            "steps": [*state["steps"], result.trace]}


GRAPH = linear_graph(State, [(S1, discovering_markets), (S2, assessing_evidence), (S3, comparing_markets), (S4, summarizing)])


async def run_market_comparison(
    inp: MarketComparisonInput, deps: WorkflowDeps, progress: ProgressFn | None = None
) -> MarketComparisonOutcome:
    state = await execute(GRAPH, {"inp": inp, "steps": [], "limitations": []}, deps, progress, inp.context.mode)
    applied = state.get("applied", [])
    demo = [DEMO_RUN_NOTE, DEMO_OUTPUT_NOTE] if inp.context.mode == "demo" else []
    comparability = state.get("comparability") or MarketComparability(
        market_specific_signals=False, notes=["The comparison did not complete."])
    return MarketComparisonOutcome(
        status=outcome_status(state), columns=state.get("columns", []), comparability=comparability,
        cross_market_summary=state.get("summary"), evidence=state.get("evidence", []), brand_rules_applied=applied,
        limitations=list(dict.fromkeys([*demo, *state.get("limitations", []), applied_note(applied)])),
        steps=state.get("steps", []), error=state.get("error"),
    )
