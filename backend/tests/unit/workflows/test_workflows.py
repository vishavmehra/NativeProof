"""Each workflow end to end in demo mode (fixture Qloo + fixture LLM), plus live-mode failure handling."""

from uuid import uuid4

from app.integrations.qloo import QlooError, ResolvedConcept
from app.llm.fixture import FixtureLLMProvider
from app.llm.gateway import LLMGateway, ProviderError
from app.schemas.campaigns import DEFAULT_EVALUATION_CRITERIA, CampaignContent
from app.schemas.common import RunMetadata
from app.schemas.discovery import ConfirmedReference, DiscoveryResult
from app.schemas.evaluations import EvaluationResult
from app.schemas.studies import RehearsalResult
from app.workflows import (
    EvaluationInput,
    WorkflowDeps,
    run_adaptation,
    run_discovery,
    run_evaluation,
    run_rehearsal,
)
from app.workflows._common import STAGES
from tests.unit.workflows.scenario import (
    CAMPAIGN,
    CONTENT,
    JP,
    PROJECT,
    STUDY,
    VERSION_ID,
    Progress,
    adaptation_input,
    context,
    demo_deps,
    discovery_input,
    normalized,
    offline_settings,
    rehearsal_input,
)


def assert_stages(run_type: str, progress: Progress, steps) -> None:
    assert [(c[0], c[1], c[2]) for c in progress.calls] == [(s, i, 4) for i, s in enumerate(STAGES[run_type])]
    assert all(c[3].endswith("(demo fixtures).") for c in progress.calls)
    assert [s.stage for s in steps] == list(STAGES[run_type])


async def journey():
    deps = demo_deps()
    discovery = await run_discovery(discovery_input(), deps)
    rehearsal = await run_rehearsal(rehearsal_input(discovery.evidence), deps)
    adaptation = await run_adaptation(adaptation_input(discovery.evidence, rehearsal.summary), deps)
    return deps, discovery, rehearsal, adaptation


def evaluation_input(candidates, grounding=()):
    return EvaluationInput(
        context=context(), evaluation_id=uuid4(), source_content_version_id=VERSION_ID, source_content=CONTENT,
        candidates=candidates, criteria=DEFAULT_EVALUATION_CRITERIA, market=JP, grounding_evidence=list(grounding),
    )


async def test_discovery_demo_end_to_end():
    progress = Progress()
    inp = discovery_input()
    out = await run_discovery(inp, demo_deps(), progress)
    assert out.status == "completed" and out.error is None
    assert_stages("market_discovery", progress, out.steps)
    refs = {r.query_term: r for r in out.references}
    assert refs["hiking"].match_status == "resolved" and refs["hiking"].name == "Hiking"
    assert refs["minimal design"].match_status == "ambiguous" and refs["minimal design"].entity_id is None
    assert len(refs["minimal design"].candidates) == 2 and refs["minimal design"].relevance_explanation is None
    assert refs["great escape"].match_status == "unresolved"
    assert refs["related to Hiking"].name  # E's demo related interest for Hiking
    brief = out.market_brief
    assert [(f.claim_type, f.confidence_label) for f in brief.observations + brief.opportunities + brief.risks] == [
        ("observed", "moderate"), ("interpreted", "limited"), ("hypothesis", "insufficient")]
    ids = {e.id for e in out.evidence}
    assert all(i in ids for f in brief.observations + brief.opportunities for i in f.evidence_ids)
    assert all(e.is_live_data is False and e.source_run_id == inp.context.run_id for e in out.evidence)
    assert {e.retrieval_mode for e in out.evidence} == {"fixture", "generated"}
    assert [s.provider for s in out.steps] == ["fixture", "fixture", "nativeproof", "fixture"]
    DiscoveryResult(  # the engine's result model accepts the outcome
        run_id=inp.context.run_id, status=out.status, project_id=PROJECT.id, campaign_id=CAMPAIGN.id, market=JP,
        product_category=inp.request.product_category, research_question=inp.request.research_question,
        reference_terms=inp.request.reference_terms, references=out.references, market_brief=out.market_brief,
        evidence=out.evidence, limitations=out.limitations,
        run_metadata=RunMetadata(run_id=inp.context.run_id, mode="demo", steps=out.steps),
    )


async def test_confirmed_reference_resolves_while_unconfirmed_ambiguous_term_lists_candidates():
    inp = discovery_input(terms=["hiking", "minimal design", "outdoor exploration"])
    choice = ConfirmedReference(term="Minimal Design", ref_id="fixture:tag:minimalism", ref_kind="tag")
    inp = inp.model_copy(update={"request": inp.request.model_copy(update={"confirmed_references": [choice]})})
    out = await run_discovery(inp, demo_deps())
    refs = {r.query_term: r for r in out.references}
    confirmed, open_term = refs["minimal design"], refs["outdoor exploration"]
    assert (confirmed.match_status, confirmed.entity_id, confirmed.name) == ("resolved", "fixture:tag:minimalism", "Minimalism")
    assert confirmed.candidates == [] and confirmed.evidence_ids
    assert open_term.match_status == "ambiguous" and open_term.entity_id is None and len(open_term.candidates) == 2
    assert any(e.title == "Confirmed tag: Minimalism" for e in out.evidence)


async def test_rehearsal_demo_reproduces_contract_story():
    deps = demo_deps()
    discovery = await run_discovery(discovery_input(), deps)
    progress = Progress()
    inp = rehearsal_input(discovery.evidence)
    out = await run_rehearsal(inp, deps, progress)
    assert out.status == "completed"
    assert_stages("campaign_rehearsal", progress, out.steps)
    clarity = out.dimension_results.clarity
    assert [next(r.value for r in x.ratings if r.dimension == "clarity") for x in out.reactions] == [4, 3, 2, 4, 2, 3]
    assert (clarity.score, clarity.spread, clarity.disagreement) == (50.0, 0.82, True)
    assert all(x.is_synthetic for x in out.reactions)
    d = out.simulation_disclosure
    assert (d.requested_responses, d.generated_responses, d.grounded, d.grounding_evidence_count) == (6, 6, True, 2)
    reaction_ids = {x.id for x in out.reactions}
    findings = out.summary.key_findings + out.summary.potential_confusions + out.summary.potential_cultural_risks
    assert all(set(f.supporting_response_ids) <= reaction_ids for f in findings)
    assert out.summary.disagreements[0].spread == 0.82
    assert {e.evidence_type for e in out.evidence} == {"deterministic_calculation"}
    assert [s.source for s in out.segments] == ["user"] * 3
    RehearsalResult(
        run_id=inp.context.run_id, status=out.status, study_id=STUDY.id, campaign_id=CAMPAIGN.id,
        content_version_id=VERSION_ID, content=CONTENT, market=JP, simulation_disclosure=d, segments=out.segments,
        reactions=out.reactions, dimension_results=out.dimension_results, summary=out.summary,
        evidence=out.evidence + discovery.evidence, limitations=out.limitations,
        run_metadata=RunMetadata(run_id=inp.context.run_id, mode="demo", steps=out.steps),
    )


async def test_rehearsal_demo_caps_response_count_at_fixture_reactions():
    out = await run_rehearsal(rehearsal_input([], response_count=12), demo_deps())
    assert out.simulation_disclosure.generated_responses == 6
    assert out.simulation_disclosure.requested_responses == 12 and not out.simulation_disclosure.grounded
    assert "Demo fixtures include 6 reactions for this study; 12 were requested." in out.limitations


async def test_adaptation_demo_variants_checks_and_review():
    deps = demo_deps()
    discovery = await run_discovery(discovery_input(), deps)
    progress = Progress()
    out = await run_adaptation(adaptation_input(discovery.evidence), deps, progress)
    assert out.status == "completed"
    assert_stages("campaign_adaptation", progress, out.steps)
    assert [a.label for a in out.adaptations] == ["Clearer message", "Brand-first", "More conservative"]
    clearer, brand_first, _ = out.adaptations
    assert clearer.changes[0].reasoning_type == "evidence_supported" and clearer.changes[0].evidence_ids
    assert clearer.evidence and clearer.evidence[0].id == clearer.changes[0].evidence_ids[0]
    assert all(a.checks.protected_terms_preserved and a.checks.cultural_risk_reviewed for a in out.adaptations)
    assert [w.source for w in brand_first.warnings] == ["model_assessment"]
    assert all(c.reasoning_type != "user_edit" for a in out.adaptations for c in a.changes)
    assert all(a.context.grounded and a.mode == "demo" and a.origin == "generated" for a in out.adaptations)
    one = await run_adaptation(adaptation_input(discovery.evidence, variant_count=1), deps)
    assert [a.label for a in one.adaptations] == ["Clearer message"]


async def test_evaluation_demo_reproduces_contract_story():
    deps, discovery, _, adaptation = await journey()
    progress = Progress()
    inp = evaluation_input(adaptation.adaptations[:2], discovery.evidence)
    out = await run_evaluation(inp, deps, progress)
    assert out.status == "completed"
    assert_stages("campaign_evaluation", progress, out.steps)
    assert [(r.label, r.overall_score) for r in out.results] == [("Original", 63.0), ("Clearer message", 76.4), ("Brand-first", 73.1)]
    rec = out.recommendation
    assert (rec.decision, rec.rule_id, rec.candidate_id) == ("accept", "R4_meets_review_threshold", str(adaptation.adaptations[0].id))
    assert out.comparability.same_model and out.scoring_version == "mvp-1"
    EvaluationResult(
        id=inp.evaluation_id, run_id=inp.context.run_id, status=out.status, project_id=PROJECT.id,
        campaign_id=CAMPAIGN.id, source_content_version_id=VERSION_ID, market=JP, criteria=inp.criteria,
        results=out.results, recommendation=rec, comparability=out.comparability, scoring_version=out.scoring_version,
        scoring_definition=out.scoring_definition, evidence=out.evidence, limitations=out.limitations,
        run_metadata=RunMetadata(run_id=inp.context.run_id, mode="demo", steps=out.steps), created_at=discovery.evidence[0].created_at,
    )
    three = await run_evaluation(evaluation_input(adaptation.adaptations), deps)
    assert [r.overall_score for r in three.results] == [63.0, 76.4, 73.1, 69.8]
    assert three.recommendation.rule_id == "R4_meets_review_threshold"


async def test_evaluation_demo_edited_revision_is_inconclusive():
    deps, _, _, adaptation = await journey()
    edited = adaptation.adaptations[0].model_copy(update={
        "id": uuid4(), "origin": "user_edit", "parent_adaptation_id": adaptation.adaptations[0].id,
        "content": CampaignContent(headline="Gear for every trail you love", body="Edited body."),
    })
    out = await run_evaluation(evaluation_input([edited]), deps)
    assert out.status == "partial"
    assert out.results[1].overall_score is None and out.results[1].dimension_scores.clarity is None
    assert (out.recommendation.decision, out.recommendation.rule_id) == ("inconclusive", "R0_missing_scores")
    assert "Demo fixtures cannot assess edited text." in out.limitations


async def test_demo_workflows_are_deterministic():
    first, second = await journey(), await journey()
    for a, b in zip(first[1:], second[1:]):
        assert normalized(a) == normalized(b)


class FailingQloo:
    """A live Qloo service whose every call fails (e.g. a timeout)."""

    mode = "live"

    def __init__(self, ok_terms=()):
        self.ok = demo_deps().qloo
        self.ok_terms = set(ok_terms)

    def is_configured(self) -> bool:
        return True

    async def resolve_concept(self, query: str, *, limit: int = 5) -> ResolvedConcept:
        if query in self.ok_terms:
            return await self.ok.resolve_concept(query, limit=limit)
        error = QlooError(code="QLOO_TIMEOUT", message="timed out", retryable=True)
        return ResolvedConcept(query=query, status="error", error=error, limitations=["Qloo could not be queried."])

    async def related_interests(self, seed, *, market, limit: int = 10):
        return await self.ok.related_interests(seed, market=market, limit=limit)


async def test_live_qloo_failure_fails_without_fixture_data():
    deps = WorkflowDeps(qloo=FailingQloo(), llm=LLMGateway(offline_settings()))
    out = await run_discovery(discovery_input(mode="live"), deps)
    assert out.status == "failed" and out.error.code == "PROVIDER_TIMEOUT" and out.error.retryable
    assert out.error.stage == "resolving_references"
    assert out.references == [] and out.evidence == [] and out.market_brief is None
    assert [s.status for s in out.steps] == ["failed"]


async def test_live_qloo_partial_failure_keeps_completed_parts():
    llm = LLMGateway(offline_settings(), provider=FixtureLLMProvider())  # stands in for a live model
    deps = WorkflowDeps(qloo=FailingQloo(ok_terms={"hiking"}), llm=llm)
    out = await run_discovery(discovery_input(mode="live"), deps)
    assert out.status == "partial" and out.market_brief is not None
    statuses = {r.query_term: r.match_status for r in out.references}
    assert statuses["hiking"] == "resolved" and statuses["great escape"] == "unresolved"
    assert any("could not be looked up" in note for note in out.limitations)


class FailFor(FixtureLLMProvider):
    """Fixture provider that fails one prompt version with a provider timeout."""

    def __init__(self, prompt_version: str):
        super().__init__()
        self.failing = prompt_version

    async def complete(self, request):
        if request.prompt_version == self.failing:
            raise ProviderError("timeout", transient=True, timeout=True)
        return await super().complete(request)


async def test_analysis_failure_returns_partial_with_reactions_preserved():
    deps = WorkflowDeps(qloo=demo_deps().qloo, llm=LLMGateway(offline_settings(), provider=FailFor("analyst-v1"), backoff_seconds=0))
    out = await run_rehearsal(rehearsal_input([]), deps)
    assert out.status == "partial" and out.summary is None and len(out.reactions) == 6
    assert out.dimension_results.clarity.score == 50.0
    assert (out.error.code, out.error.stage) == ("PROVIDER_TIMEOUT", "analyzing_reactions")


async def test_generation_failure_fails_the_run():
    deps = WorkflowDeps(qloo=demo_deps().qloo, llm=LLMGateway(offline_settings(), provider=FailFor("voice-adaptations-v1"), backoff_seconds=0))
    out = await run_adaptation(adaptation_input([]), deps)
    assert out.status == "failed" and out.adaptations == [] and out.error.code == "PROVIDER_TIMEOUT"
    review_down = WorkflowDeps(qloo=deps.qloo, llm=LLMGateway(offline_settings(), provider=FailFor("redteam-v1"), backoff_seconds=0))
    partial = await run_adaptation(adaptation_input([]), review_down)
    assert partial.status == "partial" and len(partial.adaptations) == 3
    assert not any(a.checks.cultural_risk_reviewed for a in partial.adaptations)
