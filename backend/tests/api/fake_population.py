"""Test doubles for run_population_study / run_social_simulation (the approved engine interface, README section 14.5).

They emit real checkpoint events (PopulationBuilt, InterviewBatch, SocialRound) so the engine's persistence,
idempotency, cancel, and resume paths are exercised. Knobs: `block_after_batch` pauses after that batch until
`release` is set; `fail_after_batch` raises once after that batch (an interrupted run).
"""

import asyncio
import sys
from typing import Any
from uuid import uuid4

import pytest

from app.schemas.common import Market, StepTrace
from app.schemas.population import (
    Interview,
    InterviewAnswer,
    NetworkDefinition,
    Participant,
    Population,
    PopulationConstruction,
    PopulationGroup,
    SocialPost,
)
from app.db.base import utcnow
from app.integrations.qloo.service import QlooCall
from app.schemas.evidence import EvidenceProvenance, EvidenceRecord
from app.workflows import types as wt


def cited_evidence(ctx: Any) -> EvidenceRecord:
    """A fixture record the groups cite (sent with PopulationBuilt and again in the outcome, like the workflow)."""
    return EvidenceRecord(
        id=uuid4(), project_id=ctx.project_id, evidence_type="qloo_source", claim_type="observed", title="Resolved tag: Hiking",
        summary="Resolved tag: Hiking.", source_provider="fixture", source_workflow="population_evidence",
        source_reference=None, subject=None, related_entity=None, attributes=[], method="provider_result",
        retrieval_mode="fixture", is_live_data=False, source_run_id=ctx.run_id, retrieved_at=utcnow(),
        limitations=["Test fixture."], created_at=utcnow(),
        provenance=EvidenceProvenance(request_hash=None, response_hash=None, normalizer_version="1",
                                      fixture_origin="hand_authored"),
    )

REACTIONS = ["positive", "mixed", "neutral", "negative", "confused"]


class FakePopulation:
    def __init__(self) -> None:
        self.block_after_batch: int | None = None
        self.release = asyncio.Event()
        self.fail_after_batch: int | None = None
        self.batches_run: list[int] = []
        self.saved: list[int] = []  # batch indices whose checkpoint has returned (the write is committed)
        self.rounds_run: list[int] = []
        self.concepts: list[str | None] = []

    async def run_population_study(self, inp: Any, deps: Any, progress: Any = None, checkpoint: Any = None) -> Any:
        self.concepts.append(inp.concept)
        participants = list(inp.participants)
        evidence = [cited_evidence(inp.context)] if inp.population is None else []
        if inp.population is None:
            region = inp.regions[0] if inp.regions else Market(country_code="JP", display_name="Japan")
            groups = [PopulationGroup(id=f"grp-{g}", label=f"Group {g}", description="Test archetype.", region=region,
                                      share=1 / 3, participant_count=0, interests=[],
                                      evidence_ids=[e.id for e in evidence]) for g in (1, 2, 3)]
            population_id = uuid4()
            participants = [Participant(id=uuid4(), population_id=population_id, group_id=f"grp-{1 + i % 3}", ordinal=i,
                                        region=region, interests=[], traits={"adoption_style": "early"}, evidence_ids=[])
                            for i in range(inp.size)]
            for g in groups:
                g.participant_count = sum(p.group_id == g.id for p in participants)
            population = Population(
                id=population_id, project_id=inp.context.project_id, study_id=inp.study.id, size=inp.size,
                regions=[region], group_count=3, mode=inp.context.mode, created_at=utcnow(), groups=groups,
                construction=PopulationConstruction(method="Test fixture groups.", evidence_run_id=None, grounded=False,
                                                    seed=inp.seed, config_version="test", model_id=None, prompt_version=None),
                limitations=["Test fixture population."],
            )
            await checkpoint(wt.PopulationBuilt(population=population, participants=participants, evidence=evidence))
        participants.sort(key=lambda p: p.ordinal)
        chunks = [participants[i:i + inp.batch_size] for i in range(0, len(participants), inp.batch_size)]
        for index, chunk in enumerate(chunks):
            if index in inp.completed_batches:
                continue
            self.batches_run.append(index)
            interviews = [Interview(
                id=uuid4(), run_id=inp.population_study_id, participant_id=p.id, group_id=p.group_id, region=p.region,
                content_version_id=inp.content_version_id, status="completed",
                answers=[InterviewAnswer(question_id="first_impression", question="First impression?",
                                         answer=f"Answer from participant {p.ordinal}.")],
                reaction=REACTIONS[p.ordinal % len(REACTIONS)], comprehension="understood",
                themes=[f"theme-{p.ordinal % 2}"], concerns=["price"] if p.ordinal % 4 == 0 else [],
                misunderstanding=None, model_id="fixture", evidence_ids=[],
            ) for p in chunk]
            await checkpoint(wt.InterviewBatch(index=index, interviews=interviews))
            self.saved.append(index)
            if self.fail_after_batch == index:
                self.fail_after_batch = None
                raise RuntimeError("simulated provider outage after a saved batch")
            if self.block_after_batch == index:
                await self.release.wait()
        return wt.PopulationStudyOutcome(
            status="completed", group_differences=["Group 1 reacted more positively (interpretation)."],
            evidence_gaps=["No live cultural evidence (test)."], next_actions=["Test the headline with real people."],
            evidence=evidence, limitations=["Test fixture study."],
            steps=[StepTrace(stage="running_interviews", agent="test", status="completed", provider="fixture")],
            qloo_calls=[QlooCall(workflow="population_evidence", retrieval_mode="fixture", status="success", duration_ms=1)],
        )

    async def run_social_simulation(self, inp: Any, deps: Any, progress: Any = None, checkpoint: Any = None) -> Any:
        stances = {i.participant_id: i.reaction for i in inp.interviews}
        prior = list(inp.prior_posts)
        for round_index in range(1, inp.rounds + 1):
            if round_index in inp.completed_rounds:
                continue
            self.rounds_run.append(round_index)
            seen = [p.id for p in prior][-inp.feed_size:]
            posts = []
            for p in inp.participants[: max(1, int(len(inp.participants) * inp.active_share))]:
                before = stances.get(p.id)
                after = "positive" if round_index % 2 else (before or "neutral")
                posts.append(SocialPost(id=uuid4(), round_index=round_index, participant_id=p.id, group_id=p.group_id,
                                        action="post", parent_post_id=None, text=f"Round {round_index} post.",
                                        stance=after, previous_stance=before, reason="Test reason.", seen_post_ids=seen))
                stances[p.id] = after
            prior += posts
            await checkpoint(wt.SocialRound(index=round_index, posts=posts, stances=dict(stances)))
        return wt.SocialSimulationOutcome(
            status="completed", network=NetworkDefinition(method="Test network.", degree=inp.degree,
                                                          similarity_definition="Test."),
            influence_paths=["Test influence path."], limitations=["Test fixture simulation."], steps=[],
        )


def install(monkeypatch: pytest.MonkeyPatch) -> FakePopulation:
    """Patch the real app.workflows package's v3 entry points (types stay real)."""
    import app.workflows as workflows

    fake = FakePopulation()
    monkeypatch.setattr(workflows, "run_population_study", fake.run_population_study, raising=False)
    monkeypatch.setattr(workflows, "run_social_simulation", fake.run_social_simulation, raising=False)
    real = workflows.build_workflow_deps  # demo deps are fixtures (no network), so other demo workflows still run
    monkeypatch.setattr(workflows, "build_workflow_deps",
                        lambda mode, settings, **kw: real(mode, settings, **kw) if mode == "demo" else {"mode": mode})
    assert sys.modules["app.workflows"] is workflows
    return fake
