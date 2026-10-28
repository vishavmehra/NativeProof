"""Social simulation (contracts/README §14.6): a seeded peer network and bounded rounds of feeds, actions, and stances.

Illustrative only. Every post stores the exact feed it saw (`seen_post_ids`; round 1 feeds are peers' interviews, so
those ids are interview ids) and, when the stance changed, the previous stance and the participant's reason. The engine
persists each round through `checkpoint(SocialRound)`; resume replays `prior_posts` and skips `completed_rounds`.
"""

import time
from typing import Any, TypedDict
from uuid import NAMESPACE_URL, UUID, uuid5

from langchain_core.runnables import RunnableConfig

from app.agents import population as agents
from app.agents._common import DEMO_OUTPUT_NOTE, DROPPED_NOTE, content_dict, norm, pick
from app.analytics.population import (
    NETWORK_METHOD,
    PEER_SIMILARITY_DEFINITION,
    active_participants,
    group_shifts,
    peer_network,
    stance_shifts,
)
from app.llm.gateway import LLMError
from app.schemas.common import StepTrace
from app.schemas.population import NetworkDefinition, Participant, ReactionCategory, SocialPost
from app.schemas.runs import RunError
from app.workflows._common import (
    DEMO_RUN_NOTE,
    STAGES,
    announce,
    linear_graph,
    llm_error,
    local_step,
    merge_steps,
    outcome_status,
)
from app.workflows.types import CheckpointFn, ProgressFn, SocialRound, SocialSimulationInput, SocialSimulationOutcome, WorkflowDeps

RUN = "social_simulation"
S1, S2, S3, S4 = STAGES[RUN]
BATCH = 10
ILLUSTRATIVE = "Simulated social dynamics: illustrative, not a forecast of real virality, reach, or behavior."
SHARED_MODEL_NOTE = "Every agent is voiced by the same model, so agreement between agents is not independent."


class State(TypedDict, total=False):
    inp: SocialSimulationInput
    network: dict[UUID, list[UUID]]
    definition: NetworkDefinition
    initial: dict[UUID, ReactionCategory | None]
    stances: dict[UUID, ReactionCategory | None]
    posts: list[SocialPost]
    paths: list[str]
    limitations: list[str]
    steps: list[StepTrace]
    error: RunError | None
    stop: bool
    partial: bool


async def building_network(state: State, config: RunnableConfig) -> dict:
    await announce(config, RUN, 0, "Building the peer network.")
    started, inp = time.perf_counter(), state["inp"]
    stances: dict[UUID, ReactionCategory | None] = {p.id: None for p in inp.participants}
    for i in inp.interviews:
        if i.status == "completed" and i.participant_id in stances:
            stances[i.participant_id] = i.reaction
    initial = dict(stances)
    for post in sorted(inp.prior_posts, key=lambda p: p.round_index):  # resume: replay completed rounds
        stances[post.participant_id] = post.stance
    definition = NetworkDefinition(method=NETWORK_METHOD, degree=inp.degree, similarity_definition=PEER_SIMILARITY_DEFINITION)
    return {"network": peer_network(inp.participants, inp.degree, inp.seed), "definition": definition, "initial": initial,
            "stances": stances, "posts": list(inp.prior_posts), "steps": [local_step(S1, "audience", "nativeproof", started)]}


def _feed(participant: Participant, state: State, round_index: int, size: int) -> list[tuple[UUID, str, str | None, bool]]:
    """(id, text, stance, is_post): neighbours' latest posts first, then their interview answers (round 1 only uses those)."""
    inp, neighbours = state["inp"], state["network"][participant.id]
    items: list[tuple[UUID, str, str | None, bool]] = []
    if round_index > 1:
        latest: dict[UUID, SocialPost] = {}
        for post in state["posts"]:
            if post.round_index < round_index and post.action != "ignore" and post.text:
                latest[post.participant_id] = post  # later rounds overwrite earlier ones
        items = [(latest[n].id, latest[n].text, latest[n].stance, True) for n in neighbours if n in latest]
    interviews = {i.participant_id: i for i in inp.interviews if i.status == "completed" and i.answers}
    items += [(interviews[n].id, interviews[n].answers[0].answer, interviews[n].reaction, False)
              for n in neighbours if n in interviews and all(x[0] != interviews[n].id for x in items)]
    return items[:size]


def _feed_item(feed: list, handle: str | None) -> tuple | None:
    key = norm(handle or "")
    return feed[int(key[1:]) - 1] if key[:1] == "F" and key[1:].isdigit() and 0 < int(key[1:]) <= len(feed) else None


async def simulating_rounds(state: State, config: RunnableConfig) -> dict:
    await announce(config, RUN, 1, "Simulating rounds.")
    started, deps, inp = time.perf_counter(), config["configurable"]["deps"], state["inp"]
    checkpoint: CheckpointFn = config["configurable"]["checkpoint"]
    progress = config["configurable"].get("progress")
    groups = {g.id: g for g in inp.groups}
    stances, posts, traces, missing, dropped = dict(state["stances"]), list(state["posts"]), [], 0, 0
    for round_index in range(1, inp.rounds + 1):
        if round_index in set(inp.completed_rounds):
            continue
        active = active_participants(inp.participants, inp.active_share, inp.seed, round_index)
        round_posts: list[SocialPost] = []
        for start in range(0, len(active), BATCH):
            chunk = active[start : start + BATCH]
            feeds = {p.id: _feed(p, {**state, "posts": posts}, round_index, inp.feed_size) for p in chunk}
            rows = [{"participant": f"P{n}", "ordinal": p.ordinal, "group": groups[p.group_id].label, "traits": p.traits,
                     "interests": [i.name for i in p.interests], "current_stance": stances.get(p.id),
                     "feed": [{"handle": f"F{k}", "text": text, "stance": stance} for k, (_, text, stance, _) in enumerate(feeds[p.id], 1)]}
                    for n, p in enumerate(chunk, 1)]
            try:
                result = await agents.social_round(deps.llm, stage=S2, participants=rows, content=content_dict(inp.content),
                                                   seed=inp.seed + round_index)
            except LLMError as exc:
                traces.append(exc.trace)
                missing += len(chunk)
                continue
            traces.append(result.trace)
            by_handle = {norm(a.participant): a for a in result.value.actions}
            for n, p in enumerate(chunk, 1):
                action = by_handle.get(f"P{n}")
                if action is None:
                    missing += 1
                    continue
                feed = feeds[p.id]
                reply = _feed_item(feed, action.reply_to)
                if action.reply_to and reply is None:
                    dropped += 1
                previous = stances.get(p.id)
                round_posts.append(SocialPost(
                    id=uuid5(NAMESPACE_URL, f"post:{inp.simulation_id}:{round_index}:{p.id}"), round_index=round_index,
                    participant_id=p.id, group_id=p.group_id, action=action.action,
                    parent_post_id=reply[0] if reply and reply[3] and action.action in ("comment", "share") else None,
                    text=None if action.action == "ignore" else action.text, previous_stance=previous, stance=action.stance,
                    reason=action.reason,
                    seen_post_ids=[item[0] for item in feed],
                ))
                stances[p.id] = action.stance
        await checkpoint(SocialRound(index=round_index, posts=round_posts,
                                     stances={k: v for k, v in stances.items() if v is not None}))
        posts += round_posts
        if progress is not None:
            await progress(S2, 1, 4, f"Simulated round {round_index} of {inp.rounds}.")
    notes = ([f"{missing} participant actions could not be generated and were skipped."] if missing else []) + (
        [DROPPED_NOTE] if dropped else [])
    step = merge_steps(S2, "audience", traces, started) if traces else local_step(S2, "audience", None, started, status="skipped")
    return {"stances": stances, "posts": posts, "steps": [*state["steps"], step], "partial": bool(missing),
            "limitations": [*state.get("limitations", []), *notes]}


async def analysing_dynamics(state: State, config: RunnableConfig) -> dict:
    await announce(config, RUN, 2, "Analysing dynamics.")
    return {"steps": [*state["steps"], local_step(S3, "analyst", "nativeproof", time.perf_counter())]}


async def summarizing(state: State, config: RunnableConfig) -> dict:
    await announce(config, RUN, 3, "Summarizing influence paths.")
    started, deps, inp = time.perf_counter(), config["configurable"]["deps"], state["inp"]
    changed = [p for p in state["posts"] if p.previous_stance is not None and p.stance != p.previous_stance][:30]
    if not changed:
        return {"paths": [], "steps": [*state["steps"], local_step(S4, "analyst", None, started, status="skipped")],
                "limitations": [*state.get("limitations", []), "No stance changed, so no influence path is described."]}
    handles = {f"S{n}": p for n, p in enumerate(changed, 1)}
    groups = {g.id: g.label for g in inp.groups}
    shifts = {"total_shifts": stance_shifts(state["initial"], state["stances"]),
              "by_group": [{"group": s.label, "before": s.before.counts, "after": s.after.counts}
                           for s in group_shifts(inp.groups, inp.participants, state["initial"], state["stances"])]}
    rows = [{"handle": h, "group": groups.get(p.group_id), "round": p.round_index, "from": p.previous_stance, "to": p.stance,
             "reason": p.reason, "text": p.text} for h, p in handles.items()]
    try:
        result = await agents.influence_paths(deps.llm, stage=S4, shifts=shifts, posts=rows)
    except LLMError as exc:
        return {"paths": [], "partial": True, "error": llm_error(exc, S4, "The rounds and posts were saved."),
                "steps": [*state["steps"], exc.trace]}
    paths, dropped = [], 0
    for path in result.value.paths:
        cited, lost = pick(path.posts, handles)
        dropped += lost
        if cited:
            paths.append(f"{path.summary} (posts: {', '.join(str(p.id) for p in cited)})")
    return {"paths": paths, "steps": [*state["steps"], result.trace],
            "limitations": [*state.get("limitations", []), *([DROPPED_NOTE] if dropped else [])]}


GRAPH = linear_graph(State, [(S1, building_network), (S2, simulating_rounds), (S3, analysing_dynamics), (S4, summarizing)])


async def run_social_simulation(
    inp: SocialSimulationInput, deps: WorkflowDeps, progress: ProgressFn | None = None, checkpoint: CheckpointFn | None = None,
) -> SocialSimulationOutcome:
    async def ignore(event: Any) -> None:
        return None

    config = {"recursion_limit": 12, "configurable": {"deps": deps, "progress": progress, "mode": inp.context.mode,
                                                       "checkpoint": checkpoint or ignore}}
    state = await GRAPH.ainvoke({"inp": inp, "steps": [], "limitations": []}, config=config)
    demo = [DEMO_RUN_NOTE, DEMO_OUTPUT_NOTE] if inp.context.mode == "demo" else []
    definition = state.get("definition") or NetworkDefinition(method=NETWORK_METHOD, degree=inp.degree,
                                                              similarity_definition=PEER_SIMILARITY_DEFINITION)
    return SocialSimulationOutcome(
        status=outcome_status(state), network=definition, influence_paths=state.get("paths", []),
        limitations=list(dict.fromkeys([ILLUSTRATIVE, SHARED_MODEL_NOTE, *demo, *state.get("limitations", [])])),
        steps=state.get("steps", []), error=state.get("error"),
    )
