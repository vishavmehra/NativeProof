"""Atlas market discovery: resolve terms through Qloo, retrieve related interests, normalize evidence, write the brief.

Ambiguous matches are shown, never used downstream. In live mode a Qloo failure yields a failed or partial
outcome; fixtures are used only by the demo Qloo service.
"""

import asyncio
import time
from typing import Any, TypedDict

from langchain_core.runnables import RunnableConfig

from app.agents import atlas
from app.agents._common import AFFINITY_NOTE
from app.analytics import merge_terms
from app.llm.gateway import LLMError
from app.schemas.common import StepTrace
from app.schemas.discovery import CulturalReference, MarketBrief
from app.schemas.evidence import EvidenceRecord
from app.schemas.runs import RunError
from app.workflows._common import (
    DEMO_RUN_NOTE,
    STAGES,
    announce,
    evidence_from_draft,
    execute,
    linear_graph,
    llm_error,
    local_step,
    outcome_status,
    qloo_error,
    utcnow,
)
from app.workflows.types import DiscoveryInput, DiscoveryOutcome, ProgressFn, WorkflowDeps

RUN = "market_discovery"
S1, S2, S3, S4 = STAGES[RUN]
AMBIGUOUS_NOTE = "Ambiguous: refine the term before relying on it."
UNRESOLVED_NOTE = "No usable Qloo match; any interpretation of this phrase is a hypothesis."
QLOO_CONCURRENCY = 3


class State(TypedDict, total=False):
    inp: DiscoveryInput
    concepts: list[tuple[str, str, Any]]  # (role, query, ResolvedConcept)
    related: list[Any]  # RelatedInterests
    references: list[CulturalReference]
    roles: dict[str, tuple[str, str | None]]
    evidence: list[EvidenceRecord]
    brief: MarketBrief | None
    limitations: list[str]
    steps: list[StepTrace]
    error: RunError | None
    stop: bool
    partial: bool


def _provider(deps: WorkflowDeps) -> str:
    return "qloo" if deps.qloo.mode == "live" else "fixture"


async def resolving_references(state: State, config: RunnableConfig) -> dict:
    await announce(config, RUN, 0, "Resolving references with Qloo.")
    started, deps, req = time.perf_counter(), config["configurable"]["deps"], state["inp"].request
    content = state["inp"].campaign_content
    terms = req.reference_terms or (content.reference_terms[:10] if content else [])
    queries = merge_terms([req.product_category], terms)
    limit = req.discovery_options.max_references
    limitations = [f"Not looked up (max_references is {limit}): {', '.join(queries[limit:])}."] if len(queries) > limit else []
    queries = queries[:limit]
    roles = ["product_category"] + ["reference_term"] * (len(queries) - 1)
    gate = asyncio.Semaphore(QLOO_CONCURRENCY)
    confirmed = {c.term.casefold(): c for c in req.confirmed_references}

    async def resolve(query: str) -> Any:
        async with gate:  # a confirmation is passed only when present, so resolvers without the keyword keep working
            choice = confirmed.get(query.casefold())
            return await (deps.qloo.resolve_concept(query, confirmed=choice) if choice else deps.qloo.resolve_concept(query))

    results = await asyncio.gather(*(resolve(q) for q in queries))
    concepts = list(zip(roles, queries, results))
    failed = [c for c in results if c.status == "error"]
    if failed and len(failed) == len(results):
        error = qloo_error(failed[0].error, S1, "Qloo could not be queried, so no references were resolved. Nothing was saved.")
        step = local_step(S1, "atlas", _provider(deps), started, status="failed", error_code=error.code)
        return {"concepts": concepts, "steps": [step], "limitations": limitations, "error": error, "stop": True}
    limitations += [f"'{c.query}' could not be looked up in Qloo; it is shown as unresolved." for c in failed]
    return {"concepts": concepts, "steps": [local_step(S1, "atlas", _provider(deps), started)],
            "limitations": limitations, "partial": bool(failed)}


async def retrieving_affinities(state: State, config: RunnableConfig) -> dict:
    await announce(config, RUN, 1, "Retrieving related interests.")
    started, deps, req = time.perf_counter(), config["configurable"]["deps"], state["inp"].request
    seeds = [c.match for _, _, c in state["concepts"] if c.status == "resolved" and c.match is not None]
    if not req.discovery_options.include_related_interests or not seeds:
        return {"related": [], "steps": [*state["steps"], local_step(S2, "atlas", None, started, status="skipped")]}
    capacity = req.discovery_options.max_references - len(state["concepts"])
    related, limitations, partial = [], list(state.get("limitations", [])), state.get("partial", False)
    for seed in seeds:
        if capacity <= 0:
            limitations.append(f"Related interests for {seed.name} were not retrieved: max_references was reached.")
            continue
        result = await deps.qloo.related_interests(seed, market=req.market, limit=min(capacity, 10))
        related.append(result)
        capacity -= len(result.items)
        if result.status == "error":
            partial = True
            limitations.append(f"Related interests for {seed.name} could not be retrieved from Qloo.")
        elif result.status == "empty":
            limitations.append(f"Qloo returned no related interests for {seed.name}.")
    step = local_step(S2, "atlas", _provider(deps), started)
    return {"related": related, "steps": [*state["steps"], step], "limitations": limitations, "partial": partial}


async def normalizing_evidence(state: State, config: RunnableConfig) -> dict:
    await announce(config, RUN, 2, "Normalizing evidence.")
    started, ctx = time.perf_counter(), state["inp"].context
    limit = state["inp"].request.discovery_options.max_references
    now = utcnow()
    references: list[CulturalReference] = []
    roles: dict[str, tuple[str, str | None]] = {}
    evidence: list[EvidenceRecord] = []

    def records(drafts: list) -> list[EvidenceRecord]:
        made = [evidence_from_draft(d, project_id=ctx.project_id, run_id=ctx.run_id, now=now) for d in drafts]
        evidence.extend(made)
        return made

    def add(role: str, seed: str | None, **fields: Any) -> None:
        ref_id = f"ref-{len(references) + 1}"
        roles[ref_id] = (role, seed)
        defaults = {"name": None, "entity_id": None, "entity_type": None, "candidates": [], "attributes": [],
                    "relevance_explanation": None}
        references.append(CulturalReference(id=ref_id, **(defaults | fields)))

    seen_entities: set[str] = set()
    for role, query, c in state["concepts"]:
        ids = [r.id for r in records(c.evidence)]
        notes = list(dict.fromkeys(c.limitations))
        if c.status == "resolved" and c.match is not None:
            seen_entities.add(c.match.entity_id)
            add(role, None, query_term=query, match_status="resolved", name=c.match.name, entity_id=c.match.entity_id,
                entity_type=c.match.entity_type, attributes=c.match.attributes, evidence_ids=ids,
                limitations=list(dict.fromkeys([AFFINITY_NOTE, *notes])))
        elif c.status == "ambiguous":
            add(role, None, query_term=query, match_status="ambiguous", candidates=[x.ref() for x in c.candidates],
                evidence_ids=ids, limitations=list(dict.fromkeys([AMBIGUOUS_NOTE, *notes])))
        else:
            add(role, None, query_term=query, match_status="unresolved", evidence_ids=ids, limitations=notes or [UNRESOLVED_NOTE])
    for result in state.get("related", []):
        made = records(result.evidence)
        for item in result.items:
            if len(references) >= limit or item.entity_id in seen_entities:
                continue
            seen_entities.add(item.entity_id)
            own = [r.id for r in made if (r.related_entity and r.related_entity.entity_id == item.entity_id)
                   or (r.subject and r.subject.entity_id == item.entity_id)]
            add("related_interest", result.seed.name, query_term=f"related to {result.seed.name}", match_status="resolved",
                name=item.name, entity_id=item.entity_id, entity_type=item.entity_type, attributes=item.attributes,
                evidence_ids=own, limitations=list(dict.fromkeys([AFFINITY_NOTE, *result.limitations])))
    step = local_step(S3, "atlas", "nativeproof", started)
    return {"references": references, "roles": roles, "evidence": evidence, "steps": [*state["steps"], step]}


async def generating_brief(state: State, config: RunnableConfig) -> dict:
    await announce(config, RUN, 3, "Generating the market brief.")
    started, deps, inp = time.perf_counter(), config["configurable"]["deps"], state["inp"]
    references, limitations = state["references"], list(state.get("limitations", []))
    if not any(r.match_status == "resolved" and r.evidence_ids for r in references):
        limitations.append("No usable cultural evidence was found, so no market brief was generated.")
        step = local_step(S4, "atlas", None, started, status="skipped")
        return {"brief": None, "limitations": limitations, "steps": [*state["steps"], step], "partial": True}
    try:
        result = await atlas.generate_brief(
            deps.llm, stage=S4, project_id=inp.context.project_id, run_id=inp.context.run_id, market=inp.request.market,
            product_category=inp.request.product_category, research_question=inp.request.research_question,
            brand=inp.context.brand.model_dump(exclude_none=True), references=references, roles=state["roles"],
            evidence=state["evidence"], campaign_content=inp.campaign_content,
        )
    except LLMError as exc:
        error = llm_error(exc, S4, "The references and evidence were saved.")
        return {"brief": None, "error": error, "steps": [*state["steps"], exc.trace], "partial": True}
    references = [r.model_copy(update={"relevance_explanation": result.relevance.get(r.id)}) for r in references]
    return {
        "brief": result.brief, "references": references, "evidence": [*state["evidence"], *result.new_evidence],
        "limitations": limitations + result.notes, "steps": [*state["steps"], result.trace],
    }


GRAPH = linear_graph(State, [(S1, resolving_references), (S2, retrieving_affinities), (S3, normalizing_evidence), (S4, generating_brief)])


async def run_discovery(inp: DiscoveryInput, deps: WorkflowDeps, progress: ProgressFn | None = None) -> DiscoveryOutcome:
    state = await execute(GRAPH, {"inp": inp, "steps": [], "limitations": []}, deps, progress, inp.context.mode)
    demo = [DEMO_RUN_NOTE] if inp.context.mode == "demo" else []
    return DiscoveryOutcome(
        status=outcome_status(state), references=state.get("references", []), market_brief=state.get("brief"),
        evidence=state.get("evidence", []), limitations=list(dict.fromkeys([*demo, *state.get("limitations", [])])),
        steps=state.get("steps", []), error=state.get("error"),
    )
