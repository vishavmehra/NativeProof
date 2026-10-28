"""Participant follow-ups and group questions (README §14.8): stored-memory refs only, demo never calls a model."""

from datetime import UTC, datetime
from uuid import uuid4

import pytest

from app.llm.fixture import FixtureLLMProvider
from app.llm.gateway import LLMError, LLMGateway
from app.schemas.population import MemoryItem, ParticipantDetail, ParticipantState
from app.workflows import answer_followup, answer_group_question
from tests.unit.workflows.scenario import JP, offline_settings

TRAITS = {"adoption_style": "early", "price_sensitivity": "low", "media_habit": "social", "tone_preference": "calm"}


def participant(ordinal: int) -> ParticipantDetail:
    study, now = uuid4(), datetime.now(UTC)
    interview = MemoryItem(kind="interview", ref_id=uuid4(), round_index=None, summary=f"Reads like a travel offer ({ordinal}).",
                           created_at=now)
    post = MemoryItem(kind="own_post", ref_id=uuid4(), round_index=1, summary="Is this clothing or a trip?", created_at=now)
    return ParticipantDetail(
        id=uuid4(), population_id=uuid4(), group_id="grp-1", ordinal=ordinal, region=JP, interests=[], traits=TRAITS,
        evidence_ids=[], memories=[post, interview],
        state=ParticipantState(population_study_id=study, stance="confused", stance_source="social_round",
                               last_round_index=1, interview_id=interview.ref_id),
    )


class Recording(FixtureLLMProvider):
    def __init__(self, responders):
        super().__init__(responders)
        self.requests = []

    async def complete(self, request):
        self.requests.append(request)
        return await super().complete(request)


def gateway(responders) -> tuple[LLMGateway, Recording]:
    provider = Recording(responders)
    return LLMGateway(offline_settings(), provider=provider, backoff_seconds=0), provider


async def test_demo_answer_quotes_the_stored_interview_without_a_model():
    p = participant(0)
    llm, provider = gateway({})
    reply = await answer_followup(population_study_id=uuid4(), participant=p, question="Why?", mode="demo", llm=llm)
    interview = p.memories[1]
    assert reply.answer.startswith("Demo fixture answer") and interview.summary in reply.answer
    assert reply.memory_refs == [interview.ref_id] and reply.model_id is None and provider.requests == []
    group = await answer_group_question(population_study_id=uuid4(), group_id="grp-1", participants=[p, participant(1)],
                                        question="Why?", mode="demo", llm=llm)
    assert len(group.answers) == 2 and "no model was called" in group.summary and provider.requests == []


async def test_live_followup_cites_only_stored_memories():
    p = participant(0)
    llm, provider = gateway({"participant-followup-v1": lambda ctx: {
        "answer": "I still can't tell what is sold.", "stance": "confused", "memory_refs": ["M2", "M9", "m1"]}})
    reply = await answer_followup(population_study_id=uuid4(), participant=p, question="Why?", mode="live", llm=llm)
    assert reply.memory_refs == [p.memories[1].ref_id, p.memories[0].ref_id]  # M9 is not stored: dropped
    assert len(provider.requests) == 1 and reply.trace is not None


async def test_group_question_is_one_batched_call_over_the_sample_only():
    sample = [participant(0), participant(1), participant(2)]
    llm, provider = gateway({"group-question-v1": lambda ctx: {"summary": "Two of three are confused.", "answers": [
        {"participant": "P1", "answer": "a", "stance": "confused", "memory_refs": ["M1"]},
        {"participant": "P1", "answer": "duplicate", "stance": "positive"},
        {"participant": "P3", "answer": "c", "stance": "mixed", "memory_refs": ["M7"]},
        {"participant": "P9", "answer": "not sampled", "stance": "positive"}]}})
    group = await answer_group_question(population_study_id=uuid4(), group_id="grp-1", participants=sample,
                                        question="What is sold?", mode="live", llm=llm)
    assert len(provider.requests) == 1
    assert [(a.participant_id, a.answer) for a in group.answers] == [(sample[0].id, "a"), (sample[2].id, "c")]
    assert group.answers[0].memory_refs == [sample[0].memories[0].ref_id] and group.answers[1].memory_refs == []
    rows = provider.requests[0].fixture_context["participants"]
    assert all(len(r["memories"]) <= 50 // 3 for r in rows)


async def test_invalid_output_fails_clearly_and_never_falls_back_to_fixtures():
    llm, provider = gateway({"participant-followup-v1": lambda ctx: {"answer": ""}})
    with pytest.raises(LLMError) as failure:
        await answer_followup(population_study_id=uuid4(), participant=participant(0), question="Why?", mode="live", llm=llm)
    assert failure.value.code == "RUN_FAILED" and len(provider.requests) == 2  # one repair, then a clear failure
