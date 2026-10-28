"""Population study and social simulation in demo mode: checkpoints, resume, determinism, failures (README §14)."""

from uuid import uuid4

from app.analytics.population import TRAITS
from app.integrations.qloo import PopulationEvidence, QlooCall, RegionInterests
from app.llm.fixture import FixtureLLMProvider
from app.llm.gateway import LLMGateway, ProviderError
from app.schemas.population import InterestRef
from app.workflows import population as population_workflow
from app.workflows import run_discovery
from app.workflows.population import run_population_study
from app.workflows.social import run_social_simulation
from app.workflows.types import (
    InterviewBatch,
    PopulationBuilt,
    PopulationStudyInput,
    SocialRound,
    SocialSimulationInput,
    WorkflowDeps,
)
from tests.unit.workflows.scenario import CONTENT, JP, STUDY, VERSION_ID, context, demo_deps, discovery_input, offline_settings


class Checkpoints:
    def __init__(self):
        self.events = []

    async def __call__(self, event):
        self.events.append(event)


async def evidence():
    return (await run_discovery(discovery_input(), demo_deps())).evidence


def study_input(grounding, **overrides) -> PopulationStudyInput:
    values = dict(context=context(), population_study_id=uuid4(), study=STUDY, size=40, regions=[JP], seed=42,
                  content_version_id=VERSION_ID, content=CONTENT, interview_depth="standard", grounding_evidence=grounding,
                  batch_size=10)
    return PopulationStudyInput(**(values | overrides))


async def test_population_study_demo_end_to_end():
    grounding, events = await evidence(), Checkpoints()
    out = await run_population_study(study_input(grounding), demo_deps(), checkpoint=events)
    assert out.status == "completed" and out.error is None
    built, *batches = events.events
    assert isinstance(built, PopulationBuilt) and [type(e) for e in batches] == [InterviewBatch] * 4
    assert [b.index for b in batches] == [0, 1, 2, 3]
    population, participants = built.population, built.participants
    assert population.construction.grounded and len(population.groups) == 3 and population.mode == "demo"
    assert all(g.interests and g.evidence_ids for g in population.groups)
    assert len(participants) == 40 and all(set(p.traits) == set(TRAITS) for p in participants)
    interviews = [i for b in batches for i in b.interviews]
    assert len(interviews) == 40 and all(i.status == "completed" for i in interviews)
    assert all(len(i.answers) == 9 for i in interviews)  # 8 core questions + 1 adaptive follow-up (standard)
    assert out.group_differences and out.next_actions and out.evidence_gaps
    assert any("not a survey of real people" in note for note in out.limitations)
    # Evidence comes from the collector: the discovery seed plus its related entity, persisted with the population.
    assert {i.name for g in population.groups for i in g.interests} == {"Hiking", "Kumo Trail Co. (fictional)"}
    assert built.evidence == out.evidence and out.evidence and all(e.retrieval_mode == "fixture" for e in out.evidence)
    cited = {i for g in population.groups for i in g.evidence_ids}
    assert {e.id for e in out.evidence} <= cited | {e.id for e in grounding}  # new records are cited, never dangling
    assert out.qloo_calls and {c.retrieval_mode for c in out.qloo_calls} == {"fixture"}
    assert "weight = 1 - index / count" in population.construction.method


async def test_reused_population_gives_identical_answers_and_resume_skips_batches():
    grounding = await evidence()
    first = Checkpoints()
    await run_population_study(study_input(grounding), demo_deps(), checkpoint=first)
    built = first.events[0]
    done = [i for e in first.events[1:3] for i in e.interviews]  # batches 0 and 1 were persisted before an interruption
    resumed = Checkpoints()
    inp = study_input(grounding, population=built.population, participants=built.participants, completed_batches=[0, 1],
                      completed_interviews=done)
    out = await run_population_study(inp, demo_deps(), checkpoint=resumed)
    assert [type(e) for e in resumed.events] == [InterviewBatch, InterviewBatch]  # no rebuild, no redone batch
    assert [e.index for e in resumed.events] == [2, 3]
    assert out.qloo_calls == [] and out.evidence == []  # a reused population makes no Qloo lookup
    assert out.status == "completed" and not any("failed" in note for note in out.limitations)
    again = [i for e in resumed.events for i in e.interviews]
    original = {i.participant_id: i for e in first.events[3:] for i in e.interviews}
    assert all(i.answers == original[i.participant_id].answers for i in again)  # same people, same fixture answers


async def test_ungrounded_population_is_labeled_a_hypothesis():
    events = Checkpoints()
    out = await run_population_study(study_input([], size=20), demo_deps(), checkpoint=events)
    population = events.events[0].population
    assert not population.construction.grounded and all(not g.interests for g in population.groups)
    assert any("Ungrounded" in note for note in out.limitations)


class FailSecondInterviewBatch(FixtureLLMProvider):
    """Every attempt for batch index 1 (ordinals 10-19) fails; the other batches succeed."""

    async def complete(self, request):
        context = request.fixture_context or {}
        if request.prompt_version == "population-interviews-v1" and any(10 <= r["ordinal"] < 20 for r in context["participants"]):
            raise ProviderError("HTTP 503", transient=True)
        return await super().complete(request)


async def test_failed_batch_is_recorded_not_retried_forever():
    llm = LLMGateway(offline_settings(), provider=FailSecondInterviewBatch(), backoff_seconds=0)
    events = Checkpoints()
    inp = study_input(await evidence(), size=30)
    out = await run_population_study(inp, WorkflowDeps(qloo=demo_deps().qloo, llm=llm), checkpoint=events)
    failed = [i for e in events.events[1:] for i in e.interviews if i.status == "failed"]
    assert len(failed) == 10 and out.status == "partial"
    assert "10 of 30 interviews failed and are excluded from every rate." in out.limitations


class Recording(FixtureLLMProvider):
    def __init__(self):
        super().__init__()
        self.requests = []

    async def complete(self, request):
        self.requests.append(request)
        return await super().complete(request)


def collector(result: PopulationEvidence):
    async def fake(qloo, **kwargs):
        return result
    return fake


async def test_demographic_evidence_grounds_groups_never_participants(monkeypatch):
    grounding = await evidence()
    hiking = next(e for e in grounding if e.subject and e.subject.name == "Hiking" and e.source_workflow == "find_tags")
    audience = hiking.model_copy(update={"id": uuid4(), "source_workflow": "audience_demographics", "title": "Audience of Hiking"})
    interest = InterestRef(ref_id=hiking.subject.entity_id, ref_kind="tag", name="Hiking", weight=1.0, evidence_ids=[hiking.id])
    monkeypatch.setattr(population_workflow, "collect_population_evidence", collector(PopulationEvidence(
        evidence=[audience], regions=[RegionInterests(region=JP, interests=[interest])], demographic_evidence_ids=[audience.id],
        calls=[QlooCall(workflow="audience_demographics", retrieval_mode="fixture", status="ok", duration_ms=1)],
        grounded=True, limitations=[])))
    provider, events = Recording(), Checkpoints()
    deps = WorkflowDeps(qloo=demo_deps().qloo, llm=LLMGateway(offline_settings(), provider=provider))
    out = await run_population_study(study_input(grounding, size=20), deps, checkpoint=events)
    built = events.events[0]
    assert out.status == "completed" and built.evidence == [audience]
    assert all(audience.id in g.evidence_ids for g in built.population.groups)  # every group holds Hiking
    assert all(audience.id not in p.evidence_ids for p in built.participants)
    interviews = [i for e in events.events[1:] for i in e.interviews]
    assert interviews and all(audience.id not in i.evidence_ids for i in interviews)
    groups_request = next(r for r in provider.requests if r.prompt_version == "population-groups-v1")
    assert "Audience of Hiking" not in str(groups_request.fixture_context)  # never shown to the model


async def test_qloo_outage_stops_before_any_model_call(monkeypatch):
    monkeypatch.setattr(population_workflow, "collect_population_evidence", collector(PopulationEvidence(
        evidence=[], regions=[RegionInterests(region=JP, interests=[])], demographic_evidence_ids=[],
        calls=[QlooCall(workflow="find_tags", retrieval_mode="error", status="QLOO_TIMEOUT", duration_ms=5)],
        grounded=False, limitations=["'hiking' could not be looked up in Qloo, so it does not ground the population."])))
    provider, events = Recording(), Checkpoints()
    deps = WorkflowDeps(qloo=demo_deps().qloo, llm=LLMGateway(offline_settings(), provider=provider))
    out = await run_population_study(study_input([], size=20), deps, checkpoint=events)
    assert out.status == "failed" and out.error.code == "PROVIDER_TIMEOUT" and out.error.stage == "preparing_evidence"
    assert events.events == [] and provider.requests == [] and len(out.qloo_calls) == 1
    assert any("could not be looked up" in note for note in out.limitations)


async def test_group_text_with_demographics_is_rejected():
    def responder(ctx):
        return {"groups": [{"label": f"Women aged {20 + i}", "description": "x", "region": "JP", "share": 0.3} for i in range(ctx["count"])]}

    llm = LLMGateway(offline_settings(), provider=FixtureLLMProvider({"population-groups-v1": responder}))
    out = await run_population_study(study_input([], size=20), WorkflowDeps(qloo=demo_deps().qloo, llm=llm))
    assert out.status == "failed" and out.error.code == "RUN_FAILED" and out.error.stage == "constructing_population"


async def social_inputs():
    events = Checkpoints()
    await run_population_study(study_input(await evidence()), demo_deps(), checkpoint=events)
    built = events.events[0]
    interviews = [i for e in events.events[1:] for i in e.interviews]
    return built, interviews


async def test_social_simulation_demo_records_feeds_and_reasons():
    built, interviews = await social_inputs()
    events = Checkpoints()
    inp = SocialSimulationInput(context=context(), simulation_id=uuid4(), population_study_id=uuid4(),
                                groups=built.population.groups, participants=built.participants, interviews=interviews,
                                content=CONTENT, rounds=2, active_share=0.25, feed_size=4, seed=42)
    out = await run_social_simulation(inp, demo_deps(), checkpoint=events)
    assert out.status == "completed" and [type(e) for e in events.events] == [SocialRound, SocialRound]
    round_one, round_two = events.events
    interview_ids = {i.id for i in interviews}
    assert all(set(p.seen_post_ids) <= interview_ids for p in round_one.posts)  # round 1 feeds are peers' interviews
    assert all(p.seen_post_ids for p in round_one.posts) and len(round_one.posts) == 10
    changed = [p for e in events.events for p in e.posts if p.previous_stance and p.stance != p.previous_stance]
    assert changed and all(p.reason for p in changed)
    post_ids = {str(p.id) for e in events.events for p in e.posts}
    assert out.influence_paths and all(any(pid in path for pid in post_ids) for path in out.influence_paths)
    assert out.network.degree == 6 and any("illustrative" in note for note in out.limitations)
    resumed = Checkpoints()
    again = await run_social_simulation(inp.model_copy(update={"completed_rounds": [1], "prior_posts": round_one.posts}),
                                        demo_deps(), checkpoint=resumed)
    assert [e.index for e in resumed.events] == [2] and again.status == "completed"
    assert [p.model_dump() for p in resumed.events[0].posts] == [p.model_dump() for p in round_two.posts]
