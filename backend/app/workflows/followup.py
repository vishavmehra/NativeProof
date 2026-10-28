"""Participant follow-ups and group questions (contracts/README §14.8).

One bounded model call each, in character, from the stored profile and a bounded window of stored memories (most
recent first). `memory_refs` cite only stored ids. The engine samples the group (seeded), stores the answers, and
tallies the sample. Demo projects get a labeled fixture answer quoting the stored interview, with no provider call;
live projects never fall back to it. Invalid output gets the gateway's bounded retries and repair, then LLMError.
"""

from uuid import UUID

from app.agents import population as agents
from app.agents._common import norm, pick
from app.core.config import get_settings
from app.llm.gateway import LLMError, LLMGateway
from app.schemas.common import DataMode
from app.schemas.population import MemoryItem, ParticipantDetail
from app.workflows.types import FollowUpReply, GroupReply

WINDOW = 50  # stored memories per call (README §14.8); a group shares it
STAGE = "answering_question"
DEMO_PREFIX = "Demo fixture answer (no model was called)."


def _window(participant: ParticipantDetail, limit: int) -> dict[str, MemoryItem]:
    return {f"M{n}": m for n, m in enumerate(participant.memories[:limit], 1)}


def _profile(participant: ParticipantDetail, memories: dict[str, MemoryItem]) -> dict:
    return {"region": participant.region.display_name, "interests": [i.name for i in participant.interests],
            "traits": participant.traits, "current_stance": participant.state.stance,
            "memories": [{"handle": h, "kind": m.kind, "round": m.round_index, "text": m.summary[:300]}
                         for h, m in memories.items()]}


def _refs(handles: list[str], memories: dict[str, MemoryItem]) -> list[UUID]:
    cited, _ = pick(handles, memories)
    return list(dict.fromkeys(m.ref_id for m in cited))


def _demo(participant: ParticipantDetail) -> FollowUpReply:
    interview = next((m for m in participant.memories if m.kind == "interview"), None)
    answer = (f'{DEMO_PREFIX} From my stored interview: "{interview.summary}"' if interview
              else f"{DEMO_PREFIX} There is no stored interview to quote.")
    return FollowUpReply(participant_id=participant.id, answer=answer, stance=participant.state.stance,
                         memory_refs=[interview.ref_id] if interview else [], model_id=None)


async def answer_followup(
    *, population_study_id: UUID, participant: ParticipantDetail, question: str, mode: DataMode,
    llm: LLMGateway | None = None,
) -> FollowUpReply:
    if mode == "demo":
        return _demo(participant)
    memories = _window(participant, WINDOW)
    result = await agents.followup(llm or LLMGateway(get_settings()), stage=STAGE, profile=_profile(participant, memories),
                                   question=question)
    out = result.value
    return FollowUpReply(participant_id=participant.id, answer=out.answer, stance=out.stance,
                         memory_refs=_refs(out.memory_refs, memories), model_id=result.trace.model_id, trace=result.trace)


async def answer_group_question(
    *, population_study_id: UUID, group_id: str, participants: list[ParticipantDetail], question: str, mode: DataMode,
    llm: LLMGateway | None = None,
) -> GroupReply:
    if mode == "demo":
        answers = [_demo(p) for p in participants]
        return GroupReply(answers=answers, summary=f"Demo fixture: {len(answers)} sampled participants quoted their stored "
                                                   "interviews; no model was called.")
    limit = max(1, WINDOW // max(1, len(participants)))
    sampled = {f"P{n}": (p, _window(p, limit)) for n, p in enumerate(participants, 1)}
    rows = [{"participant": h, **_profile(p, memories)} for h, (p, memories) in sampled.items()]
    result = await agents.group_question(llm or LLMGateway(get_settings()), stage=STAGE, participants=rows, question=question)
    answers: dict[UUID, FollowUpReply] = {}
    for item in result.value.answers:  # unknown handles are dropped; the first answer per participant counts
        if (entry := sampled.get(norm(item.participant))) and entry[0].id not in answers:
            p, memories = entry
            answers[p.id] = FollowUpReply(participant_id=p.id, answer=item.answer, stance=item.stance,
                                          memory_refs=_refs(item.memory_refs, memories), model_id=result.trace.model_id)
    if not answers:
        raise LLMError("RUN_FAILED", "The model's answers named none of the sampled participants.", retryable=True,
                       trace=result.trace)
    return GroupReply(answers=list(answers.values()), summary=result.value.summary, trace=result.trace)
