"""Cultural DNA: a versioned profile grounded in completed discoveries (contracts/README §13).

Every item is checked in code: unknown evidence handles are dropped, "observed" needs Qloo source evidence, and an
item with no evidence is a hypothesis with confidence insufficient. The brand is read, never written.
"""

import time
from typing import Any, TypedDict

from langchain_core.runnables import RunnableConfig

from app.agents import insight
from app.agents._common import AFFINITY_NOTE, DEMO_OUTPUT_NOTE, DROPPED_NOTE, evidence_digest, pick
from app.agents.brand import applied_note, brand_block, top_k
from app.analytics import brief_confidence, is_source_observed
from app.llm.gateway import LLMError
from app.schemas.common import Market, StepTrace
from app.schemas.evidence import EvidenceRecord
from app.schemas.profiles import ProfileItem
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
)
from app.workflows.types import CulturalProfileInput, CulturalProfileOutcome, ProgressFn, WorkflowDeps

RUN = "cultural_profile"
S1, S2, S3, S4 = STAGES[RUN]
EVIDENCE_LIMIT = 30
NO_EVIDENCE_NOTE = "No supporting evidence: treat this as a hypothesis to validate."


class State(TypedDict, total=False):
    inp: CulturalProfileInput
    records: list[EvidenceRecord]
    market_of: dict[Any, Market]
    missing: list[str]
    digest: list[dict]
    handles: dict[str, EvidenceRecord]
    brand_text: str
    applied: list[str]
    draft: Any
    items: list[ProfileItem]
    limitations: list[str]
    steps: list[StepTrace]
    error: RunError | None
    stop: bool
    partial: bool


async def loading_evidence(state: State, config: RunnableConfig) -> dict:
    await announce(config, RUN, 0, "Loading discovery evidence.")
    started, inp = time.perf_counter(), state["inp"]
    wanted = {m.country_code: m for m in inp.request.markets}
    records, market_of, missing, seen = [], {}, [], set()
    for source in inp.discoveries:
        if source.market.country_code not in wanted:
            continue
        seen.add(source.market.country_code)
        for e in source.evidence:
            if e.id not in market_of:
                market_of[e.id] = wanted[source.market.country_code]
                records.append(e)
        for r in source.references:
            if r.match_status != "resolved":
                missing.append(f"'{r.query_term}' ({source.market.display_name}) is {r.match_status}; it was not used.")
    missing = [f"No completed discovery for {m.display_name}." for c, m in wanted.items() if c not in seen] + missing
    limitations = [] if records else ["No discovery evidence was available, so no profile items were generated."]
    return {"records": records, "market_of": market_of, "missing": missing, "limitations": limitations,
            "partial": not records, "steps": [local_step(S1, "atlas", "nativeproof", started)]}


async def retrieving_context(state: State, config: RunnableConfig) -> dict:
    await announce(config, RUN, 1, "Assembling brand and evidence context.")
    started, inp = time.perf_counter(), state["inp"]
    records, traces, notes = state["records"], [], []
    embedder = config["configurable"]["deps"].llm.capability("embeddings")
    if len(records) > EVIDENCE_LIMIT and embedder is not None:  # retrieval: keep the records closest to the request
        query = " ".join(filter(None, [inp.request.title, inp.request.focus]))
        try:
            ranked, trace = await top_k(query, [f"{e.title}. {e.summary}" for e in records], embedder, EVIDENCE_LIMIT,
                                        stage=S2, agent="atlas")
            records, traces = [records[i] for i in ranked], [trace]
            notes.append(f"Selected {EVIDENCE_LIMIT} of {len(state['records'])} evidence records by embedding similarity.")
        except LLMError:
            notes.append(f"Evidence retrieval failed; used the first {EVIDENCE_LIMIT} records.")
    digest, handles = evidence_digest(records, limit=EVIDENCE_LIMIT, sources_only=True)
    for row in digest:
        row["market"] = state["market_of"][handles[row["handle"]].id].country_code
    text, applied = brand_block(inp.context.brand)
    step = merge_steps(S2, "atlas", traces, started) if traces else local_step(S2, "atlas", "nativeproof", started)
    return {"digest": digest, "handles": handles, "brand_text": text, "applied": applied, "steps": [*state["steps"], step],
            "limitations": [*state.get("limitations", []), *notes]}


async def synthesizing_profile(state: State, config: RunnableConfig) -> dict:
    await announce(config, RUN, 2, "Synthesizing the cultural profile.")
    started, deps, inp = time.perf_counter(), config["configurable"]["deps"], state["inp"]
    if not state["digest"]:
        return {"draft": None, "steps": [*state["steps"], local_step(S3, "atlas", None, started, status="skipped")]}
    previous = [{"kind": i.kind, "title": i.title, "claim_type": i.claim_type} for i in inp.previous_items]
    try:
        result = await insight.synthesize_profile(
            deps.llm, stage=S3, subject=inp.request.subject, title=inp.request.title, focus=inp.request.focus,
            markets=[m.model_dump() for m in inp.request.markets], brand=state["brand_text"], evidence=state["digest"],
            previous=previous,
        )
    except LLMError as exc:
        return {"draft": None, "steps": [*state["steps"], exc.trace], "partial": True,
                "error": llm_error(exc, S3, "No profile items were saved; retrying is safe.")}
    return {"draft": result.value, "steps": [*state["steps"], result.trace]}


async def checking_evidence(state: State, config: RunnableConfig) -> dict:
    await announce(config, RUN, 3, "Checking evidence links.")
    started, draft, inp = time.perf_counter(), state.get("draft"), state["inp"]
    markets = {m.country_code: m for m in inp.request.markets}
    items, dropped = [], 0
    for index, item in enumerate(draft.items if draft else [], 1):
        cited, lost = pick(item.evidence, state["handles"])
        dropped += lost
        claim = item.claim_type
        if not cited:
            claim = "hypothesis"
        elif claim == "observed" and not any(is_source_observed(e) for e in cited):
            claim = "interpreted"
        items.append(ProfileItem(
            id=f"item-{index}", kind=item.kind, title=item.title, explanation=item.explanation, claim_type=claim,
            confidence_label=brief_confidence(claim, cited), market=markets.get((item.market or "").upper()),
            evidence_ids=[e.id for e in cited], limitations=[AFFINITY_NOTE] if cited else [NO_EVIDENCE_NOTE],
        ))
    limitations = [*state.get("limitations", []), *([DROPPED_NOTE] if dropped else [])]
    return {"items": items, "limitations": limitations, "steps": [*state["steps"], local_step(S4, "atlas", "nativeproof", started)]}


GRAPH = linear_graph(State, [(S1, loading_evidence), (S2, retrieving_context), (S3, synthesizing_profile), (S4, checking_evidence)])


async def run_cultural_profile(
    inp: CulturalProfileInput, deps: WorkflowDeps, progress: ProgressFn | None = None
) -> CulturalProfileOutcome:
    state = await execute(GRAPH, {"inp": inp, "steps": [], "limitations": []}, deps, progress, inp.context.mode)
    draft, applied = state.get("draft"), state.get("applied", [])
    demo = [DEMO_RUN_NOTE, DEMO_OUTPUT_NOTE] if inp.context.mode == "demo" else []
    return CulturalProfileOutcome(
        status=outcome_status(state), summary=draft.summary if draft else None, items=state.get("items", []),
        market_context=list(draft.market_context) if draft else [],
        missing_evidence=list(dict.fromkeys([*state.get("missing", []), *(draft.missing_evidence if draft else [])])),
        evidence=[], brand_rules_applied=applied,
        limitations=list(dict.fromkeys([*demo, *state.get("limitations", []), applied_note(applied)])),
        steps=state.get("steps", []), error=state.get("error"),
    )
