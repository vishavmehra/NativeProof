"""Population study (contracts/README §14.3-14.5): evidence -> groups -> seeded participants -> batched interviews ->
deterministic tallies and an interpretation of them.

The engine persists through `checkpoint`: PopulationBuilt once, then InterviewBatch per batch (idempotent by index).
Resume skips `completed_batches`. A failed batch records its participants as failed interviews and is never retried
in a loop.
"""

import asyncio
import time
from datetime import UTC, datetime
from typing import Any, TypedDict
from uuid import NAMESPACE_URL, uuid4, uuid5

from langchain_core.runnables import RunnableConfig

from app.agents import population as agents
from app.agents._common import DEMO_OUTPUT_NOTE, DROPPED_NOTE, content_dict, evidence_digest, norm, pick
from app.agents.brand import brand_block
from app.analytics.population import (
    CONFIG_VERSION,
    batches,
    distribution,
    expand_participants,
    group_results,
    theme_counts,
)
from app.integrations.qloo import QlooCall, collect_population_evidence
from app.llm.gateway import LLMError
from app.schemas.common import Market, StepTrace
from app.schemas.evidence import EvidenceRecord
from app.schemas.population import (
    InterestRef,
    Interview,
    InterviewAnswer,
    Participant,
    Population,
    PopulationConstruction,
    PopulationGroup,
)
from app.schemas.runs import RunError
from app.workflows._common import (
    DEMO_RUN_NOTE,
    QLOO_CODES,
    STAGES,
    announce,
    linear_graph,
    llm_error,
    local_step,
    merge_steps,
    observe_assets,
    outcome_status,
)
from app.workflows.types import (
    CheckpointFn,
    InterviewBatch,
    PopulationBuilt,
    PopulationStudyInput,
    PopulationStudyOutcome,
    ProgressFn,
    WorkflowDeps,
)

RUN = "population_study"
S1, S2, S3, S4 = STAGES[RUN]
CONCURRENCY = 3  # interview batches in flight; checkpoints are still written in batch order
SYNTHETIC_NOTE = "Every participant and answer is AI-generated; this is not a survey of real people."
SHARED_MODEL_NOTE = "All participants share one model's biases, so agreement between them is not confirmation."


class State(TypedDict, total=False):
    inp: PopulationStudyInput
    digest: list[dict]
    handles: dict[str, EvidenceRecord]
    interest_rows: list[dict]
    interests: dict[str, tuple[str, InterestRef]]
    grounded: bool
    new_evidence: list[EvidenceRecord]
    demographics: list[EvidenceRecord]
    weight_definition: str | None
    qloo_calls: list[QlooCall]
    observations: list[str]
    population: Population
    participants: list[Participant]
    interviews: list[Interview]
    analysis: Any
    limitations: list[str]
    steps: list[StepTrace]
    error: RunError | None
    stop: bool
    partial: bool


def group_count(size: int, regions: int) -> int:
    base = 3 if size <= 60 else 4 if size <= 150 else 6 if size <= 500 else 8
    return min(12, max(base, 2 * regions))


async def preparing_evidence(state: State, config: RunnableConfig) -> dict:
    """Qloo interests per region from the collector (discovery seeds and campaign terms, then related entities). A
    reused population keeps its groups, so it makes no Qloo lookup."""
    await announce(config, RUN, 0, "Preparing evidence.")
    started, deps, inp = time.perf_counter(), config["configurable"]["deps"], state["inp"]
    collected = None if inp.population is not None else await collect_population_evidence(
        deps.qloo, project_id=inp.context.project_id, run_id=inp.context.run_id, regions=inp.regions, concept=inp.concept,
        reference_terms=inp.content.reference_terms, discovery_evidence=inp.grounding_evidence,
    )
    calls = collected.calls if collected else []
    failed = [c for c in calls if c.retrieval_mode == "error"]
    if collected and not collected.grounded and failed and len(failed) == len(calls):  # Qloo unreachable: stop, spend nothing
        code = QLOO_CODES.get(failed[0].status, "PROVIDER_ERROR")
        error = RunError(code=code, stage=S1, retryable=code in ("PROVIDER_ERROR", "PROVIDER_TIMEOUT", "RATE_LIMITED"),
                         message="Qloo could not be queried, so the population could not be grounded. Nothing was saved.")
        return {"steps": [local_step(S1, "atlas", "qloo", started, status="failed", error_code=code)], "error": error,
                "stop": True, "qloo_calls": calls, "limitations": list(collected.limitations)}
    demographic = set(collected.demographic_evidence_ids) if collected else set()
    new = [e for e in collected.evidence if e.id not in demographic] if collected else []
    digest, handles = evidence_digest([*inp.grounding_evidence, *new], limit=30, sources_only=True)
    handle_of = {e.id: h for h, e in handles.items()}
    interests: dict[str, tuple[str, InterestRef]] = {}
    for region in collected.regions if collected else []:
        for ref in region.interests:
            interests[f"I{len(interests) + 1}"] = (region.region.country_code, ref)
    rows = [{"handle": h, "region": code, "name": ref.name, "kind": ref.ref_kind, "weight": ref.weight,
             "evidence": [handle_of[i] for i in ref.evidence_ids if i in handle_of]} for h, (code, ref) in interests.items()]
    assets = [(str(inp.asset.asset_id), inp.asset)] if inp.asset else []
    vision, by_asset, traces = await observe_assets(deps, assets, config["configurable"]["mode"], S1)
    observations = [o.description for rows_ in by_asset.values() for o in rows_]
    notes = list(collected.limitations) if collected else []
    if inp.asset and vision.status != "analyzed":
        notes.append(f"The creative was not analyzed ({vision.message}); participants saw the text only.")
    provider = "qloo" if any(c.retrieval_mode in ("live", "cached") for c in calls) else "fixture" if calls else "nativeproof"
    step = merge_steps(S1, "atlas", traces, started) if traces else local_step(S1, "atlas", provider, started)
    return {"digest": digest, "handles": handles, "interest_rows": rows, "interests": interests,
            "grounded": bool(collected and collected.grounded), "new_evidence": collected.evidence if collected else [],
            "demographics": [e for e in collected.evidence if e.id in demographic] if collected else [],
            "weight_definition": collected.weight_definition if collected else None, "qloo_calls": calls,
            "observations": observations, "steps": [step], "limitations": notes}


def build_groups_from(
    out_groups: list, handles: dict[str, EvidenceRecord], interests: dict[str, tuple[str, InterestRef]],
    regions: list[Market], demographics: list[EvidenceRecord] = (),
) -> tuple[list[PopulationGroup], int]:
    """Map handles in code: interests must belong to the group's own (requested) region, shares are normalized, and
    aggregate demographic evidence is attached to the groups whose interests it describes (never shown to the model)."""
    by_code = {r.country_code: r for r in regions}
    dropped, groups = 0, []
    total_share = sum(g.share for g in out_groups) or 0.0
    for n, g in enumerate(out_groups, 1):
        region = by_code.get(norm(g.region), regions[0])
        cited, lost_e = pick(g.evidence, handles)
        picked, lost_i = pick(g.interests, interests)
        own = {ref.ref_id: ref for code, ref in picked if code == region.country_code}
        dropped += lost_e + lost_i + len(picked) - len(own)
        audience = [d.id for d in demographics if d.subject and d.subject.entity_id in own]
        evidence_ids = list(dict.fromkeys([e.id for e in cited] + [i for ref in own.values() for i in ref.evidence_ids] + audience))
        share = (g.share / total_share) if total_share else 1 / len(out_groups)
        groups.append(PopulationGroup(
            id=f"grp-{n}", label=g.label, description=g.description, region=region, share=round(share, 4),
            participant_count=0, interests=list(own.values()), evidence_ids=evidence_ids,
        ))
    return groups, dropped


async def constructing_population(state: State, config: RunnableConfig) -> dict:
    await announce(config, RUN, 1, "Constructing the population.")
    started, deps, inp = time.perf_counter(), config["configurable"]["deps"], state["inp"]
    checkpoint: CheckpointFn = config["configurable"]["checkpoint"]
    if inp.population is not None:  # reuse (or resume): the same people, never rebuilt
        return {"population": inp.population, "participants": list(inp.participants),
                "steps": [*state["steps"], local_step(S2, "audience", "nativeproof", started)]}
    try:
        result = await agents.build_groups(
            deps.llm, stage=S2, count=group_count(inp.size, len(inp.regions)), regions=[r.model_dump() for r in inp.regions],
            interests=state["interest_rows"], evidence=state["digest"], content=content_dict(inp.content),
            brand=brand_block(inp.context.brand)[0], seed=inp.seed,
        )
    except LLMError as exc:
        error = llm_error(exc, S2, "No population was saved; retrying is safe.")
        return {"steps": [*state["steps"], exc.trace], "error": error, "stop": True}
    demographics = state["demographics"]
    groups, dropped = build_groups_from(result.value.groups, state["handles"], state["interests"], inp.regions, demographics)
    grounded = state["grounded"]
    population_id = uuid4()
    groups, participants = expand_participants(population_id, groups, inp.size, inp.seed, group_only={d.id for d in demographics})
    limitations = ([] if grounded else ["Ungrounded: groups are model hypotheses, not built from cultural evidence."]) + (
        [DROPPED_NOTE] if dropped else [])
    population = Population(
        id=population_id, project_id=inp.context.project_id, study_id=inp.study.id, size=inp.size, regions=inp.regions,
        group_count=len(groups), mode=inp.context.mode, created_at=datetime.now(UTC), groups=groups,
        construction=PopulationConstruction(
            method="A model proposed archetype groups from each region's Qloo interests (references resolved in discovery "
                   "or from the campaign terms, then related entities) and the cited evidence; participants were expanded "
                   "from the groups with the seed (interest subsets and four style knobs only). Interest "
                   + (state["weight_definition"] or "weights: none (no interests)."),
            evidence_run_id=inp.evidence_run_id if grounded else None, grounded=grounded, seed=inp.seed,
            config_version=CONFIG_VERSION, model_id=result.trace.model_id, prompt_version=agents.GROUPS_PROMPT_VERSION,
        ),
        limitations=limitations + ["Group shares are a configuration choice, not market share or prevalence."],
    )
    await checkpoint(PopulationBuilt(population=population, participants=participants, evidence=state["new_evidence"]))
    return {"population": population, "participants": participants, "steps": [*state["steps"], result.trace],
            "limitations": [*state.get("limitations", []), *limitations]}


def _interview(inp: PopulationStudyInput, participant: Participant, item: Any | None, model_id: str | None) -> Interview:
    base = {"id": uuid5(NAMESPACE_URL, f"interview:{inp.population_study_id}:{participant.id}"), "run_id": inp.context.run_id,
            "participant_id": participant.id, "group_id": participant.group_id, "region": participant.region,
            "content_version_id": inp.content_version_id, "model_id": model_id, "evidence_ids": list(participant.evidence_ids)}
    if item is None:
        return Interview(**base, status="failed", answers=[], reaction=None, comprehension=None, themes=[], concerns=[],
                         misunderstanding=None)
    answers = [InterviewAnswer(question_id=q, question=text, answer=getattr(item.answers, q)) for q, text in agents.CORE_QUESTIONS]
    answers += [InterviewAnswer(question_id=f"follow_up_{k}", question=f.question, answer=f.answer)
                for k, f in enumerate(item.follow_ups, 1)]
    return Interview(**base, status="completed", answers=answers, reaction=item.reaction, comprehension=item.comprehension,
                     themes=item.themes, concerns=item.concerns, misunderstanding=item.misunderstanding)


async def running_interviews(state: State, config: RunnableConfig) -> dict:
    await announce(config, RUN, 2, "Running interviews.")
    started, deps, inp = time.perf_counter(), config["configurable"]["deps"], state["inp"]
    checkpoint: CheckpointFn = config["configurable"]["checkpoint"]
    progress = config["configurable"].get("progress")
    groups = {g.id: g for g in state["population"].groups}
    todo = [(i, b) for i, b in enumerate(batches(state["participants"], inp.batch_size)) if i not in set(inp.completed_batches)]
    total = len(batches(state["participants"], inp.batch_size))
    interviews, traces, failed_batches = [], [], 0

    async def run(index: int, batch: list[Participant]) -> tuple[int, list[Interview], StepTrace]:
        rows = [{"participant": f"P{n}", "ordinal": p.ordinal, "group": groups[p.group_id].label,
                 "group_description": groups[p.group_id].description, "region": p.region.display_name,
                 "interests": [i.name for i in p.interests], "traits": p.traits} for n, p in enumerate(batch, 1)]
        try:
            result = await agents.interview_batch(
                deps.llm, stage=S3, participants=rows, depth=inp.interview_depth, content=content_dict(inp.content),
                market=", ".join(r.display_name for r in inp.regions), observations=state["observations"], seed=inp.seed + index,
            )
        except LLMError as exc:
            return index, [_interview(inp, p, None, exc.trace.model_id) for p in batch], exc.trace
        by_handle = {norm(item.participant): item for item in result.value.interviews}
        made = [_interview(inp, p, by_handle.get(f"P{n}"), result.trace.model_id) for n, p in enumerate(batch, 1)]
        return index, made, result.trace

    for start in range(0, len(todo), CONCURRENCY):  # bounded windows; checkpoints in batch order
        for index, made, trace in await asyncio.gather(*(run(i, b) for i, b in todo[start : start + CONCURRENCY])):
            traces.append(trace)
            failed_batches += trace.status == "failed"
            await checkpoint(InterviewBatch(index=index, interviews=made))  # may raise the engine's RunCancelled
            interviews += made
            if progress is not None:
                await progress(S3, 2, 4, f"Interviewed batch {index + 1} of {total}.")
    step = merge_steps(S3, "audience", traces, started) if traces else local_step(S3, "audience", None, started, status="skipped")
    update: dict = {"interviews": interviews, "steps": [*state["steps"], step]}
    if failed_batches:
        update["partial"] = True
    return update


async def analysing_results(state: State, config: RunnableConfig) -> dict:
    await announce(config, RUN, 3, "Analysing results.")
    started, deps, inp = time.perf_counter(), config["configurable"]["deps"], state["inp"]
    rows = {i.id: i for i in [*inp.completed_interviews, *state.get("interviews", [])]}
    interviews = list(rows.values())
    done = [i for i in interviews if i.status == "completed"]
    failed = len(interviews) - len(done)
    notes = [f"{failed} of {len(interviews)} interviews failed and are excluded from every rate."] if failed else []
    if not done:
        error = RunError(code="RUN_FAILED", stage=S4, retryable=True, message="No interview completed, so nothing was analysed.")
        return {"analysis": None, "error": error, "stop": True, "limitations": [*state.get("limitations", []), *notes],
                "steps": [*state["steps"], local_step(S4, "analyst", None, started, status="skipped")]}
    groups = state["population"].groups
    tallies = {
        "overall": distribution(interviews).model_dump(),
        "by_group": [{"group": r.label, "region": r.region.country_code, "distribution": r.distribution.model_dump(),
                      "themes": [t.label for t in r.themes[:5]], "concerns": [t.label for t in r.concerns[:5]]}
                     for r in group_results(groups, interviews, limit=5)],
        "themes": [t.model_dump(include={"label", "count", "share"}) for t in theme_counts(done, "themes", 10)],
        "concerns": [t.model_dump(include={"label", "count", "share"}) for t in theme_counts(done, "concerns", 10)],
        "misunderstandings": [t.model_dump(include={"label", "count", "share"}) for t in theme_counts(done, "misunderstanding", 5)],
    }
    by_participant = {p.id: p for p in state["participants"]}
    quotes = []
    for g in groups:  # deterministic sample: the two lowest-ordinal completed interviews per group
        mine = sorted((i for i in done if i.group_id == g.id), key=lambda i: by_participant[i.participant_id].ordinal
                      if i.participant_id in by_participant else 0)[:2]
        quotes += [{"group": g.label, "reaction": i.reaction, "first_impression": i.answers[0].answer} for i in mine]
    try:
        result = await agents.analyse(deps.llm, stage=S4, tallies=tallies, quotes=quotes)
    except LLMError as exc:
        return {"analysis": None, "partial": True, "error": llm_error(exc, S4, "The interviews and tallies were saved."),
                "limitations": [*state.get("limitations", []), *notes], "steps": [*state["steps"], exc.trace]}
    return {"analysis": result.value, "partial": state.get("partial", False) or bool(failed),
            "limitations": [*state.get("limitations", []), *notes], "steps": [*state["steps"], result.trace]}


GRAPH = linear_graph(State, [(S1, preparing_evidence), (S2, constructing_population), (S3, running_interviews), (S4, analysing_results)])


async def run_population_study(
    inp: PopulationStudyInput, deps: WorkflowDeps, progress: ProgressFn | None = None, checkpoint: CheckpointFn | None = None,
) -> PopulationStudyOutcome:
    async def ignore(event) -> None:
        return None

    config = {"recursion_limit": 12, "configurable": {"deps": deps, "progress": progress, "mode": inp.context.mode,
                                                       "checkpoint": checkpoint or ignore}}
    state = await GRAPH.ainvoke({"inp": inp, "steps": [], "limitations": []}, config=config)
    analysis = state.get("analysis")
    demo = [DEMO_RUN_NOTE, DEMO_OUTPUT_NOTE] if inp.context.mode == "demo" else []
    return PopulationStudyOutcome(
        status=outcome_status(state), group_differences=list(analysis.group_differences) if analysis else [],
        evidence_gaps=list(analysis.evidence_gaps) if analysis else [], next_actions=list(analysis.next_actions) if analysis else [],
        evidence=state.get("new_evidence", []),
        limitations=list(dict.fromkeys([SYNTHETIC_NOTE, SHARED_MODEL_NOTE, *demo, *state.get("limitations", [])])),
        steps=state.get("steps", []), error=state.get("error"), qloo_calls=state.get("qloo_calls", []),
    )

