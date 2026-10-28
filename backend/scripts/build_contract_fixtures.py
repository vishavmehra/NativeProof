"""Build contracts/fixtures/*.json: one consistent, schema-valid demo journey.

These are illustrative API responses for frontend development and contract tests.
Every value is a labeled demo fixture; none is live Qloo or model output. Numbers
are computed with the documented formulas (contracts/README.md), not typed in.
Regenerate after any schema change, from backend/:
    uv run python -m scripts.build_contract_fixtures
"""

import json
import statistics
from datetime import datetime, timedelta, timezone
from pathlib import Path
from uuid import NAMESPACE_URL, UUID, uuid5

from pydantic import BaseModel

from app.schemas.adaptations import Adaptation, AdaptationChecks, AdaptationContext, AdaptationPage, ContentChange
from app.schemas.campaigns import (
    DEFAULT_EVALUATION_CRITERIA,
    Campaign,
    CampaignContent,
    CampaignPage,
    ContentVersion,
    EvaluationCriteria,
)
from app.schemas.common import (
    DIMENSIONS,
    Dimension,
    DimensionScores,
    ErrorBody,
    ErrorDetail,
    ErrorResponse,
    Market,
    RiskFlag,
    RunMetadata,
    StepTrace,
)
from app.schemas.discovery import BriefFinding, CulturalReference, DiscoveryResult, MarketBrief
from app.schemas.evaluations import (
    CandidateResult,
    Comparability,
    DimensionDefinition,
    DimensionRationales,
    EvaluationResult,
    Recommendation,
    ScoringDefinition,
)
from app.schemas.evidence import EntityRef, EvidencePage, EvidenceProvenance, EvidenceRecord, SourceAttribute
from app.schemas.health import Readiness, ReadinessCapabilities, ReadinessDependencies
from app.schemas.projects import Brand, BrandExample, Project, ProjectPage, ProjectSummary
from app.schemas.reports import (
    ExecutiveSummary,
    Report,
    ReportCampaignSnapshot,
    ReportDiscoverySection,
    ReportPage,
    ReportRehearsalSection,
    ReportSummary,
    ReproducibilityInfo,
)
from app.schemas.runs import Run, RunAccepted, RunError, RunPage, RunProgress, RunResultRef
from app.schemas.studies import (
    DimensionRating,
    DimensionResult,
    DimensionResults,
    Disagreement,
    Finding,
    InterpretationCluster,
    RehearsalResult,
    RehearsalSummary,
    SegmentAssumption,
    SegmentSummary,
    SimulationConfig,
    SimulationDisclosure,
    Study,
    StudyPage,
    SyntheticReaction,
)

OUT = Path(__file__).resolve().parents[2] / "contracts" / "fixtures"
T0 = datetime(2026, 10, 25, 8, 30, tzinfo=timezone.utc)
API = "/api/v1"


def uid(name: str) -> UUID:
    return uuid5(NAMESPACE_URL, f"nativeproof-fixture:{name}")


def at(seconds: int) -> datetime:
    return T0 + timedelta(seconds=seconds)


PROJECT, BRAND, CAMPAIGN, VERSION = uid("project"), uid("brand"), uid("campaign"), uid("content-v1")
STUDY, EVALUATION, REPORT = uid("study"), uid("evaluation"), uid("report")
ADAPTATION_1, ADAPTATION_2 = uid("adaptation-1"), uid("adaptation-2")
RUN_DISCOVERY, RUN_REHEARSAL = uid("run-discovery"), uid("run-rehearsal")
RUN_ADAPTATION, RUN_EVALUATION = uid("run-adaptation"), uid("run-evaluation")
EV_HIKING, EV_CAMPING, EV_MINIMAL = uid("evidence-hiking"), uid("evidence-camping"), uid("evidence-minimal")
EV_BRIEF, EV_CLARITY = uid("evidence-brief"), uid("evidence-clarity")

MARKET = Market(country_code="JP", display_name="Japan")
FIXTURE_NOTE = "Demo fixture: hand-authored in the Qloo result format, not retrieved from Qloo."
AFFINITY_NOTE = "Aggregate affinity; not evidence of demand, purchase intent, or individual preference."
SYNTHETIC_NOTE = "Derived from AI-generated reactions; not a measurement of real people."
DEMO_OUTPUT_NOTE = "Demo fixture output, not a live model response."
SOURCE_HEADLINE = "Find your next great escape"

CONTENT_V1 = CampaignContent(
    headline=SOURCE_HEADLINE,
    body="Built for the journeys that change you.",
    call_to_action="Explore the collection",
    reference_terms=["great escape"],
)

# label, definition, higher_is_better — mirrors scoring version mvp-1.
DEFINITIONS: dict[Dimension, tuple[str, str, bool]] = {
    "clarity": ("Clarity", "How easily the intended message is understood.", True),
    "brand_fidelity": ("Brand fidelity", "How well the content keeps the brand's voice and protected terms.", True),
    "cultural_relevance": ("Cultural relevance", "How relevant the content's references are to the target market.", True),
    "cultural_risk": (
        "Cultural risk",
        "Potential for misinterpretation, offense, or sensitivity issues. Higher means more risk.",
        False,
    ),
}

SCORING = ScoringDefinition(
    version="mvp-1",
    scale="0-100 per dimension",
    dimensions=[
        DimensionDefinition(dimension=d, label=label, definition=text, higher_is_better=better)
        for d, (label, text, better) in DEFINITIONS.items()
    ],
    aggregation=(
        "overall = sum(weight_d * utility_d), where utility = score for clarity, brand_fidelity and "
        "cultural_relevance, and 100 - score for cultural_risk. Weights sum to 1. Overall is null when "
        "any dimension score is missing."
    ),
    recommendation_rules=[
        "R0_missing_scores: a score is missing for the original or the best candidate -> inconclusive",
        "R1_constraint_or_risk: best candidate has a constraint violation, a high-severity risk flag, "
        "or cultural_risk >= 60 -> revise",
        "R2_no_improvement: best candidate overall < original overall -> revise",
        "R3_small_margin: best candidate overall - original overall < 5 -> validate",
        "R4_meets_review_threshold: best candidate overall >= 70 and cultural_risk < 40 -> accept "
        "(for the next internal review, not proof of market success)",
        "R5_default: otherwise -> validate",
    ],
)


def aggregate(dimension: Dimension, values: list[int]) -> DimensionResult:
    """Audience aggregation, scoring version mvp-1."""
    n = len(values)
    mean = statistics.fmean(values)
    spread = statistics.pstdev(values)
    low = sum(v <= 2 for v in values) / n
    high = sum(v >= 4 for v in values) / n
    disagreement = n >= 3 and (spread >= 1.0 or (low >= 0.25 and high >= 0.25))
    _, definition, higher_is_better = DEFINITIONS[dimension]
    note = " Ratings diverge; see the disagreement analysis." if disagreement else ""
    return DimensionResult(
        dimension=dimension,
        score=round((mean - 1) / 4 * 100, 1),
        higher_is_better=higher_is_better,
        n=n,
        distribution=[values.count(r) for r in range(1, 6)],
        spread=round(spread, 2),
        disagreement=disagreement,
        definition=definition,
        interpretation=f"Synthetic reactions averaged {mean:.2f} of 5 (n={n}).{note}",
        limitations=[SYNTHETIC_NOTE],
    )


def overall(scores: DimensionScores, criteria: EvaluationCriteria) -> float:
    """Evaluation aggregation, scoring version mvp-1."""
    return round(
        criteria.clarity * scores.clarity
        + criteria.brand_fidelity * scores.brand_fidelity
        + criteria.cultural_relevance * scores.cultural_relevance
        + criteria.cultural_risk * (100 - scores.cultural_risk),
        1,
    )


def qloo_fixture(
    id_: UUID, title: str, summary: str, workflow: str, subject: EntityRef | None,
    related: EntityRef | None, attributes: list[SourceAttribute], second: int,
) -> EvidenceRecord:
    target = related or subject
    return EvidenceRecord(
        id=id_, project_id=PROJECT, evidence_type="qloo_source", claim_type="observed", title=title,
        summary=summary, source_provider="qloo", source_workflow=workflow,
        source_reference=target.entity_id if target else None, subject=subject, related_entity=related,
        attributes=attributes, method="provider_result", retrieval_mode="fixture", is_live_data=False,
        source_run_id=RUN_DISCOVERY, retrieved_at=at(second), limitations=[FIXTURE_NOTE, AFFINITY_NOTE],
        provenance=EvidenceProvenance(
            request_hash=None, response_hash=None, normalizer_version="1", fixture_origin="hand_authored"
        ),
        created_at=at(second),
    )


def completed_run(
    id_: UUID, run_type, started: int, completed: int, resource, ids: list[UUID], url: str,
    study: UUID | None = None,
) -> Run:
    return Run(
        id=id_, project_id=PROJECT, campaign_id=CAMPAIGN, study_id=study, run_type=run_type,
        status="completed", mode="demo",
        progress=RunProgress(stage="completed", completed_steps=4, total_steps=4, message="Complete (demo fixtures)."),
        result=RunResultRef(resource=resource, ids=ids, url=url), error=None,
        created_at=at(started - 1), started_at=at(started), completed_at=at(completed),
    )


def step(stage: str, agent: str, provider: str, prompt: str | None = None, schema: str | None = None) -> StepTrace:
    return StepTrace(
        stage=stage, agent=agent, status="completed", provider=provider, prompt_version=prompt,
        schema_version=schema, latency_ms=12,
    )


def build() -> dict[str, BaseModel]:
    # --- Project, brand, campaign -------------------------------------------------
    brand = Brand(
        id=BRAND, name="Northstar", description="A premium outdoor lifestyle brand",
        voice=["confident", "minimal", "adventurous"], target_audience="Urban professionals who hike on weekends",
        preferred_terms=["trail", "craft"], prohibited_terms=["cheap"], protected_terms=["Northstar"],
        positioning="Premium outdoor gear for people who return to the trail every weekend.",
        communication_style="Short, confident sentences. No hype and no superlatives.",
        audience_preferences="Craft and minimal design over technical jargon.",
        approved_examples=[BrandExample(text="Built for the journeys that change you.", note="Approved tagline")],
        constraints=["Never promise performance we have not tested."],
        updated_at=at(0),
    )
    project = Project(
        id=PROJECT, name="Japan Market Launch", description="Evaluate the autumn launch campaign for Japan.",
        objective="Decide whether the autumn campaign needs adaptation before a Japan launch.", mode="demo",
        status="active", brand=brand, target_markets=[MARKET], created_at=at(0), updated_at=at(900),
    )
    version = ContentVersion(id=VERSION, campaign_id=CAMPAIGN, version_number=1, content=CONTENT_V1, created_at=at(60))
    campaign = Campaign(
        id=CAMPAIGN, project_id=PROJECT, name="Autumn Launch Campaign", campaign_type="advertisement",
        objective="Evaluate cultural relevance and clarity", target_markets=[MARKET],
        evaluation_criteria=DEFAULT_EVALUATION_CRITERIA, current_version=version, versions=[version],
        created_at=at(60), updated_at=at(60),
    )

    # --- Atlas: discovery ------------------------------------------------------------
    hiking = EntityRef(entity_id="fixture:tag:hiking", name="Hiking", entity_type="tag")
    camping = EntityRef(entity_id="fixture:brand:kumo-trail", name="Kumo Trail Co. (fictional)", entity_type="brand")
    affinity = SourceAttribute(
        key="affinity", label="Affinity", value=0.71,
        description="Illustrative fixture value. The live adapter preserves Qloo's own field meaning; not a probability.",
    )
    ev_hiking = qloo_fixture(
        EV_HIKING, "Resolved tag: Hiking", "The term 'hiking' resolved to the Hiking tag (near-exact match).",
        "find_tags", hiking, None,
        [SourceAttribute(key="match_rank", label="Match rank", value=1, description="Position in the returned candidates.")],
        121,
    )
    ev_camping = qloo_fixture(
        EV_CAMPING, "Related brand: Kumo Trail Co. (fictional)",
        "A fictional demo brand standing in for a recommend result for audiences with a Hiking affinity.",
        "recommend", hiking, camping, [affinity], 122,
    )
    ev_minimal = qloo_fixture(
        EV_MINIMAL, "Ambiguous match: 'minimal design'",
        "Two plausible tags were returned; Nativeproof did not choose one.", "find_tags", None, None, [], 121,
    )
    ev_brief = EvidenceRecord(
        id=EV_BRIEF, project_id=PROJECT, evidence_type="model_interpretation", claim_type="interpreted",
        title="Interpretation: trail-focused framing",
        summary="The Hiking signal suggests framing the launch around trail use rather than escape.",
        source_provider="fixture", source_workflow=None, source_reference=None, subject=None, related_entity=None,
        attributes=[], method="model_interpretation", retrieval_mode="generated", is_live_data=False,
        source_run_id=RUN_DISCOVERY, retrieved_at=None,
        limitations=["Model interpretation of the evidence above; not a Qloo observation.", DEMO_OUTPUT_NOTE],
        provenance=None, created_at=at(123),
    )
    references = [
        CulturalReference(
            id="ref-1", query_term="hiking", match_status="resolved", name="Hiking",
            entity_id=hiking.entity_id, entity_type="tag", candidates=[], attributes=[],
            relevance_explanation="Hiking matches the campaign's journey framing and the brand's outdoor positioning.",
            evidence_ids=[EV_HIKING], limitations=[AFFINITY_NOTE],
        ),
        CulturalReference(
            id="ref-2", query_term="related to Hiking", match_status="resolved", name=camping.name,
            entity_id=camping.entity_id, entity_type="brand", candidates=[], attributes=[affinity],
            relevance_explanation="A related outdoor brand may indicate adjacent tastes; fictional demo entity.",
            evidence_ids=[EV_CAMPING], limitations=[AFFINITY_NOTE],
        ),
        CulturalReference(
            id="ref-3", query_term="minimal design", match_status="ambiguous", name=None, entity_id=None,
            entity_type=None,
            candidates=[
                EntityRef(entity_id="fixture:tag:minimalism", name="Minimalism", entity_type="tag"),
                EntityRef(entity_id="fixture:tag:minimalist-architecture", name="Minimalist architecture", entity_type="tag"),
            ],
            attributes=[], relevance_explanation=None, evidence_ids=[EV_MINIMAL],
            limitations=["Ambiguous: refine the term before relying on it."],
        ),
        CulturalReference(
            id="ref-4", query_term="great escape", match_status="unresolved", name=None, entity_id=None,
            entity_type=None, candidates=[], attributes=[], relevance_explanation=None, evidence_ids=[],
            limitations=["No usable Qloo match; any interpretation of this phrase is a hypothesis."],
        ),
    ]
    brief = MarketBrief(
        summary=(
            "Hiking is the clearest supported signal for this launch. The campaign's "
            "'great escape' phrasing did not resolve to any cultural reference and should be tested."
        ),
        observations=[
            BriefFinding(
                id="obs-1", title="Hiking resolved as a relevant tag",
                explanation="'hiking' resolved to the Hiking tag, with a related outdoor brand (fictional demo entity).",
                claim_type="observed", evidence_ids=[EV_HIKING, EV_CAMPING], confidence_label="moderate",
                validation_question=None,
            )
        ],
        opportunities=[
            BriefFinding(
                id="opp-1", title="Lead with trail-focused framing",
                explanation="Framing the launch around trail use connects the copy to the supported signals.",
                claim_type="interpreted", evidence_ids=[EV_HIKING, EV_CAMPING, EV_BRIEF], confidence_label="limited",
                validation_question="Does trail-focused copy resonate more than escape framing with weekend hikers?",
            )
        ],
        risks=[
            BriefFinding(
                id="risk-1", title="'Great escape' may not carry over",
                explanation="The phrase did not resolve; its connotation in Japan is untested.",
                claim_type="hypothesis", evidence_ids=[], confidence_label="insufficient",
                validation_question="How do Japanese consumers read 'great escape' in an outdoor-apparel ad?",
            )
        ],
        validation_questions=["How do Japanese consumers read 'great escape' in an outdoor-apparel ad?"],
        limitations=["Cultural affinity does not establish market demand.", FIXTURE_NOTE],
    )
    discovery_meta = RunMetadata(
        run_id=RUN_DISCOVERY, mode="demo", started_at=at(120), completed_at=at(124),
        steps=[
            step("resolving_references", "atlas", "fixture"),
            step("retrieving_affinities", "atlas", "fixture"),
            step("normalizing_evidence", "atlas", "nativeproof"),
            step("generating_brief", "atlas", "fixture", "atlas-brief-v1", "market-brief-v1"),
        ],
    )
    discovery = DiscoveryResult(
        run_id=RUN_DISCOVERY, status="completed", project_id=PROJECT, campaign_id=CAMPAIGN, market=MARKET,
        product_category="outdoor lifestyle apparel",
        research_question="Which cultural interests could inform this launch?",
        reference_terms=["hiking", "minimal design", "great escape"], references=references,
        market_brief=brief, evidence=[ev_hiking, ev_camping, ev_minimal, ev_brief],
        limitations=["Demo mode: every provider result in this run is a fixture."], run_metadata=discovery_meta,
    )

    # --- Audience: study and rehearsal ---------------------------------------------
    segments = [
        SegmentAssumption(label="Weekend hikers", description="Metropolitan professionals who hike one or two weekends a month."),
        SegmentAssumption(label="Design-led urban buyers", description="Style-conscious city residents who value minimal design."),
        SegmentAssumption(label="Experienced mountaineers", description="Technical climbers who judge gear on performance claims."),
    ]
    study = Study(
        id=STUDY, project_id=PROJECT, campaign_id=CAMPAIGN, name="Japan Launch Rehearsal", market=MARKET,
        research_questions=[
            "Is the main message clear?",
            "What interpretations could the headline trigger?",
            "Which references might be confusing or inappropriate?",
        ],
        dimensions=list(DIMENSIONS), segments=segments,
        simulation_config=SimulationConfig(response_count=6, segment_count=3, random_seed=42),
        latest_rehearsal_run_id=RUN_REHEARSAL, created_at=at(300), updated_at=at(410),
    )
    sensitivity = RiskFlag(
        severity="medium", category="sensitivity",
        description="Escapism framing could read as dismissive of work commitments.", source="model_assessment",
    )
    # segment, sentiment, (clarity, brand_fidelity, cultural_relevance, cultural_risk), confusion,
    # interpretation, summary, confusions, risk flags
    table = [
        ("Weekend hikers", "positive", (4, 4, 4, 2), 0.2,
         "An invitation to plan the next hiking trip with dependable gear.",
         "Feels aspirational and relevant to weekend trips.", [], []),
        ("Weekend hikers", "neutral", (3, 4, 3, 2), 0.35,
         "Reads like a travel-agency slogan rather than an apparel message.",
         "Pleasant tone, but unclear what is being sold.", ["'Escape' suggests a holiday package, not clothing."], []),
        ("Design-led urban buyers", "mixed", (2, 4, 2, 3), 0.6,
         "Suggests escaping from work and daily obligations.",
         "Stylish, but the escapism angle feels slightly off.",
         ["'Great escape' reads as leaving responsibilities behind."], [sensitivity]),
        ("Design-led urban buyers", "positive", (4, 5, 3, 1), 0.15,
         "A premium, understated brand promise.", "Minimal and confident; matches the brand.", [], []),
        ("Experienced mountaineers", "negative", (2, 3, 2, 3), 0.55,
         "Generic travel copy with no performance claim.", "Says nothing about technical quality.",
         ["No product benefit is stated."],
         [RiskFlag(severity="low", category="ambiguity",
                   description="No concrete product claim for technical buyers.", source="model_assessment")]),
        ("Experienced mountaineers", "neutral", (3, 3, 3, 2), 0.3,
         "A lifestyle message aimed at casual hikers.", "Fine for beginners; not aimed at me.", [], []),
    ]
    reactions = [
        SyntheticReaction(
            id=uid(f"reaction-{i}"), segment_label=segment, interpretation=interpretation,
            reaction_summary=summary, sentiment=sentiment,
            ratings=[DimensionRating(dimension=d, value=v, rationale=None) for d, v in zip(DIMENSIONS, ratings)],
            confusion_level=confusion, potential_confusions=confusions, risk_flags=flags,
            relevant_passage=SOURCE_HEADLINE if confusions else None,
            evidence_ids=[EV_HIKING] if segment == "Weekend hikers" else [],
        )
        for i, (segment, sentiment, ratings, confusion, interpretation, summary, confusions, flags) in enumerate(
            table, start=1
        )
    ]
    r = [reaction.id for reaction in reactions]

    def ratings_of(subset: list[SyntheticReaction], dimension: Dimension) -> list[int]:
        return [next(x.value for x in item.ratings if x.dimension == dimension) for item in subset]

    results = {d: aggregate(d, ratings_of(reactions, d)) for d in DIMENSIONS}
    clarity = results["clarity"]
    ev_clarity = EvidenceRecord(
        id=EV_CLARITY, project_id=PROJECT, evidence_type="deterministic_calculation", claim_type="derived",
        title="Clarity score from synthetic rehearsal",
        summary=f"Clarity {clarity.score} of 100 from {clarity.n} synthetic ratings; spread {clarity.spread}.",
        source_provider="nativeproof", source_workflow=None, source_reference=None, subject=None,
        related_entity=None,
        attributes=[SourceAttribute(key="spread", label="Spread (1-5 scale)", value=clarity.spread,
                                    description="Population standard deviation of the ratings.")],
        method="deterministic_aggregation", retrieval_mode="generated", is_live_data=False,
        source_run_id=RUN_REHEARSAL, retrieved_at=None, limitations=[SYNTHETIC_NOTE], provenance=None,
        created_at=at(410),
    )
    segment_summaries = [
        SegmentSummary(
            label=s.label, assumptions=s.description, source="user",
            response_count=sum(x.segment_label == s.label for x in reactions),
            dimension_scores=DimensionScores(**{
                d: aggregate(d, ratings_of([x for x in reactions if x.segment_label == s.label], d)).score
                for d in DIMENSIONS
            }),
        )
        for s in segments
    ]
    summary = RehearsalSummary(
        key_findings=[
            Finding(
                id="kf-1", category="disagreement", title="The headline splits interpretations",
                summary="Reactions diverged on what 'great escape' promises: gear for trips, a holiday, or leaving work.",
                supporting_response_ids=[r[0], r[1], r[2]], evidence_ids=[EV_CLARITY],
                method="synthetic_response_analysis", claim_type="synthetic", confidence_label="limited",
                limitations=[SYNTHETIC_NOTE],
            ),
            Finding(
                id="kf-2", category="brand_fidelity", title="The brand voice lands",
                summary="Most reactions described the tone as minimal and confident.",
                supporting_response_ids=[r[0], r[3]], evidence_ids=[], method="synthetic_response_analysis",
                claim_type="synthetic", confidence_label="limited", limitations=[SYNTHETIC_NOTE],
            ),
            Finding(
                id="kf-3", category="cultural_relevance", title="Technical buyers see no product claim",
                summary="Mountaineer perspectives found no concrete reason to choose the gear.",
                supporting_response_ids=[r[4], r[5]], evidence_ids=[], method="synthetic_response_analysis",
                claim_type="synthetic", confidence_label="limited", limitations=[SYNTHETIC_NOTE],
            ),
        ],
        potential_confusions=[
            Finding(
                id="cf-1", category="confusion", title="'Escape' read as travel or escapism",
                summary="Two reactions read the headline as a holiday offer or as leaving responsibilities.",
                supporting_response_ids=[r[1], r[2]], evidence_ids=[], method="synthetic_response_analysis",
                claim_type="synthetic", confidence_label="limited", limitations=[SYNTHETIC_NOTE],
            )
        ],
        potential_cultural_risks=[
            Finding(
                id="cr-1", category="cultural_risk", title="Escapism may feel dismissive of work",
                summary="One reaction flagged the escapism framing as a possible sensitivity.",
                supporting_response_ids=[r[2]], evidence_ids=[], method="synthetic_response_analysis",
                claim_type="hypothesis", confidence_label="insufficient",
                limitations=[SYNTHETIC_NOTE, "Raised by a single synthetic reaction."],
            )
        ],
        disagreements=[
            Disagreement(
                id="dg-1", topic="What the headline promises", dimension="clarity",
                interpretations=[
                    InterpretationCluster(label="Gear for the next trip", summary="An invitation to plan outdoor trips.",
                                          response_ids=[r[0], r[3]]),
                    InterpretationCluster(label="A holiday or travel offer", summary="Reads as travel marketing.",
                                          response_ids=[r[1], r[4]]),
                    InterpretationCluster(label="Escaping obligations", summary="Reads as leaving work behind.",
                                          response_ids=[r[2]]),
                ],
                possible_explanations=[
                    "Hypothesis: 'escape' carries a 'leaving responsibilities' connotation for some readers.",
                    "Hypothesis: the copy names no product, so readers fill the gap differently.",
                ],
                validation_question="Which reading of the headline do Japanese weekend hikers choose unprompted?",
                spread=clarity.spread,
            )
        ],
        validation_questions=[
            "Which reading of the headline do Japanese weekend hikers choose unprompted?",
            "Does naming a concrete product benefit change clarity for technical buyers?",
        ],
    )
    rehearsal_meta = RunMetadata(
        run_id=RUN_REHEARSAL, mode="demo", started_at=at(400), completed_at=at(410),
        steps=[
            step("loading_context", "audience", "nativeproof"),
            step("generating_reactions", "audience", "fixture", "audience-reactions-v1", "synthetic-reaction-v1"),
            step("aggregating_results", "analyst", "nativeproof"),
            step("analyzing_reactions", "analyst", "fixture", "analyst-v1", "rehearsal-summary-v1"),
        ],
    )
    disclosure = SimulationDisclosure(
        description="These reactions were generated by an AI model (demo fixtures) and are not responses from real people.",
        requested_responses=6, generated_responses=6, grounded=True, grounding_evidence_count=2,
    )
    rehearsal = RehearsalResult(
        run_id=RUN_REHEARSAL, status="completed", study_id=STUDY, campaign_id=CAMPAIGN, content_version_id=VERSION,
        content=CONTENT_V1, market=MARKET, simulation_disclosure=disclosure, segments=segment_summaries,
        reactions=reactions, dimension_results=DimensionResults(**results), summary=summary,
        evidence=[ev_hiking, ev_camping, ev_clarity],
        limitations=[SYNTHETIC_NOTE, "Repeated generations from one model are not independent confirmation."],
        run_metadata=rehearsal_meta,
    )

    # --- Voice: adaptations ------------------------------------------------------------
    adaptation_context = AdaptationContext(
        discovery_run_id=RUN_DISCOVERY, rehearsal_run_id=RUN_REHEARSAL, grounded=True, rehearsal_informed=True
    )
    clean_checks = AdaptationChecks(
        protected_terms_preserved=True, missing_protected_terms=[], prohibited_terms_found=[],
        brand_voice_reviewed=True, cultural_risk_reviewed=True,
    )
    voice_limits = ["Not reviewed by a native Japanese speaker or local expert.", DEMO_OUTPUT_NOTE]
    clearer = Adaptation(
        id=ADAPTATION_1, project_id=PROJECT, campaign_id=CAMPAIGN, run_id=RUN_ADAPTATION,
        source_content_version_id=VERSION, parent_adaptation_id=None, origin="generated", mode="demo",
        market=MARKET, label="Clearer message", strategy="Name the product and anchor the promise in trail use.",
        content=CampaignContent(
            headline="Gear for the trails you keep coming back to",
            body="Built for the journeys that change you, from weekend ridgelines to alpine routes.",
            call_to_action="Explore the collection", reference_terms=["trails"],
        ),
        changes=[
            ContentChange(
                field="headline", original=SOURCE_HEADLINE, adapted="Gear for the trails you keep coming back to",
                reason="Replaces the ambiguous 'great escape' with trail framing supported by the Hiking signal.",
                reasoning_type="evidence_supported", evidence_ids=[EV_HIKING],
            ),
            ContentChange(
                field="body", original="Built for the journeys that change you.",
                adapted="Built for the journeys that change you, from weekend ridgelines to alpine routes.",
                reason="Adds concrete terrain so technical buyers see a product context.",
                reasoning_type="model_interpretation", evidence_ids=[],
            ),
        ],
        checks=clean_checks, warnings=[], limitations=voice_limits, context=adaptation_context,
        evidence=[ev_hiking], created_at=at(512),
    )
    brand_first = Adaptation(
        id=ADAPTATION_2, project_id=PROJECT, campaign_id=CAMPAIGN, run_id=RUN_ADAPTATION,
        source_content_version_id=VERSION, parent_adaptation_id=None, origin="generated", mode="demo",
        market=MARKET, label="Brand-first", strategy="Lead with the brand and replace escapism with a journey metaphor.",
        content=CampaignContent(
            headline="Northstar. Built for the long way round.",
            body="Minimal gear for the journeys that change you.", call_to_action="Explore the collection",
            reference_terms=[],
        ),
        changes=[
            ContentChange(
                field="headline", original=SOURCE_HEADLINE, adapted="Northstar. Built for the long way round.",
                reason="Leads with the brand and swaps escapism for a journey metaphor.",
                reasoning_type="model_interpretation", evidence_ids=[],
            ),
            ContentChange(
                field="body", original="Built for the journeys that change you.",
                adapted="Minimal gear for the journeys that change you.",
                reason="Echoes the brand's minimal voice.", reasoning_type="model_interpretation", evidence_ids=[],
            ),
        ],
        checks=clean_checks,
        warnings=[RiskFlag(severity="low", category="ambiguity",
                           description="'The long way round' is an English idiom whose nuance may not carry over.",
                           source="model_assessment")],
        limitations=voice_limits, context=adaptation_context, evidence=[], created_at=at(512),
    )

    # --- Loop: evaluation ----------------------------------------------------------------
    criteria = DEFAULT_EVALUATION_CRITERIA

    def candidate(
        candidate_id: str, kind, adaptation_id: UUID | None, label: str, content: CampaignContent,
        scores: DimensionScores, rationales: DimensionRationales, flags: list[RiskFlag],
        strengths: list[str], weaknesses: list[str], tradeoffs: list[str], evidence_ids: list[UUID],
    ) -> CandidateResult:
        return CandidateResult(
            candidate_id=candidate_id, candidate_type=kind, adaptation_id=adaptation_id, label=label,
            content=content, dimension_scores=scores, dimension_rationales=rationales,
            overall_score=overall(scores, criteria), risk_flags=flags, constraint_violations=[],
            strengths=strengths, weaknesses=weaknesses, tradeoffs=tradeoffs, evidence_ids=evidence_ids,
        )

    original_result = candidate(
        "original", "original", None, "Original", CONTENT_V1,
        DimensionScores(clarity=55, brand_fidelity=84, cultural_relevance=50, cultural_risk=30),
        DimensionRationales(clarity="'Great escape' is open to several readings.",
                            brand_fidelity="Confident and minimal, on brand.",
                            cultural_relevance="No reference resolved to a supported local signal.",
                            cultural_risk="Escapism framing may read as dismissive of work."),
        [sensitivity], ["Distinctive, confident tone"], ["No product benefit stated", "Ambiguous headline"], [],
        [EV_CLARITY],
    )
    clearer_result = candidate(
        str(ADAPTATION_1), "adaptation", ADAPTATION_1, clearer.label, clearer.content,
        DimensionScores(clarity=78, brand_fidelity=80, cultural_relevance=70, cultural_risk=20),
        DimensionRationales(clarity="States the product and use.", brand_fidelity="Slightly less distinctive.",
                            cultural_relevance="Anchored in the Hiking signal.", cultural_risk="No sensitivity found."),
        [], ["Clear product category", "Trail framing supported by the Hiking signal"],
        ["Less distinctive than the original"], ["Gains clarity and relevance at a small cost in distinctiveness."],
        [EV_HIKING],
    )
    brand_first_result = candidate(
        str(ADAPTATION_2), "adaptation", ADAPTATION_2, brand_first.label, brand_first.content,
        DimensionScores(clarity=70, brand_fidelity=92, cultural_relevance=58, cultural_risk=22),
        DimensionRationales(clarity="Clear, but the idiom adds ambiguity.", brand_fidelity="Strongest brand presence.",
                            cultural_relevance="No supported local reference.", cultural_risk="Idiom may not carry over."),
        brand_first.warnings, ["Strongest brand presence"], ["Idiom may not translate"],
        ["Highest brand fidelity, but lower relevance than Clearer message."], [],
    )
    best = clearer_result
    evaluation = EvaluationResult(
        id=EVALUATION, run_id=RUN_EVALUATION, status="completed", project_id=PROJECT, campaign_id=CAMPAIGN,
        source_content_version_id=VERSION, market=MARKET, criteria=criteria,
        results=[original_result, clearer_result, brand_first_result],
        recommendation=Recommendation(
            decision="accept", candidate_id=best.candidate_id, rule_id="R4_meets_review_threshold",
            rationale=(
                f"Clearer message scores {best.overall_score} against {original_result.overall_score} for the "
                "original, with low assessed risk. It meets the criteria for the next internal review; this is not "
                "evidence of market performance. Test it with Japanese consumers before launch."
            ),
        ),
        comparability=Comparability(
            same_market=True, same_criteria=True, same_source_version=True, same_scoring_version=True,
            same_evidence_context=True, same_model=True,
            notes=["All candidates were assessed in one run with the same criteria, model, and scoring version."],
        ),
        scoring_version=SCORING.version, scoring_definition=SCORING, evidence=[ev_hiking, ev_clarity],
        limitations=[
            "Scores are model assessments of the text, aggregated deterministically; not consumer measurements.",
            "Differences under 5 points are treated as not meaningful.",
            DEMO_OUTPUT_NOTE,
        ],
        run_metadata=RunMetadata(
            run_id=RUN_EVALUATION, mode="demo", started_at=at(600), completed_at=at(615),
            steps=[
                step("loading_candidates", "loop", "nativeproof"),
                step("assessing_candidates", "loop", "fixture", "loop-judge-v1", "candidate-assessment-v1"),
                step("scoring", "loop", "nativeproof"),
                step("recommending", "loop", "nativeproof"),
            ],
        ),
        created_at=at(615),
    )

    # --- Runs ----------------------------------------------------------------------------
    run_discovery = completed_run(
        RUN_DISCOVERY, "market_discovery", 120, 124, "discovery", [RUN_DISCOVERY],
        f"{API}/projects/{PROJECT}/discoveries/{RUN_DISCOVERY}",
    )
    run_rehearsal = completed_run(
        RUN_REHEARSAL, "campaign_rehearsal", 400, 410, "rehearsal", [RUN_REHEARSAL],
        f"{API}/studies/{STUDY}/rehearsals/{RUN_REHEARSAL}", study=STUDY,
    )
    run_adaptation = completed_run(
        RUN_ADAPTATION, "campaign_adaptation", 500, 512, "adaptations", [ADAPTATION_1, ADAPTATION_2],
        f"{API}/campaigns/{CAMPAIGN}/adaptations?run_id={RUN_ADAPTATION}",
    )
    run_evaluation = completed_run(
        RUN_EVALUATION, "campaign_evaluation", 600, 615, "evaluation", [EVALUATION],
        f"{API}/campaigns/{CAMPAIGN}/evaluations/{EVALUATION}",
    )
    run_running = run_discovery.model_copy(update={
        "status": "running", "result": None, "completed_at": None,
        "progress": RunProgress(stage="retrieving_affinities", completed_steps=2, total_steps=4,
                                message="Retrieving related interests (demo fixtures)."),
    })
    run_failed = Run(
        id=uid("run-failed"), project_id=uid("project-live"), campaign_id=uid("campaign-live"),
        study_id=uid("study-live"), run_type="campaign_rehearsal", status="failed", mode="live",
        progress=RunProgress(stage="generating_reactions", completed_steps=1, total_steps=4,
                             message="Generating synthetic reactions."),
        result=None,
        error=RunError(code="PROVIDER_TIMEOUT", stage="generating_reactions", retryable=True,
                       message="The model provider did not respond within 60 seconds. No reactions were saved; retrying is safe."),
        created_at=at(1000), started_at=at(1001), completed_at=at(1062),
    )

    # --- Proof: report -------------------------------------------------------------------
    evidence_register = [ev_hiking, ev_camping, ev_minimal, ev_brief, ev_clarity]
    report_summary = ReportSummary(
        id=REPORT, project_id=PROJECT, campaign_id=CAMPAIGN, title="Japan Launch Cultural Review", status="completed",
        version_number=1, mode="demo", created_at=at(900),
    )
    report = Report(
        **report_summary.model_dump(),
        market=MARKET,
        executive_summary=ExecutiveSummary(
            investigated="Whether Northstar's autumn campaign 'Find your next great escape' fits the Japanese market.",
            findings=[
                "Hiking was the clearest supported cultural signal (demo fixtures).",
                "Synthetic reactions split on what the headline promises.",
            ],
            changes=["'Clearer message' replaces 'great escape' with trail-focused copy and names the product."],
            uncertainties=[
                "No real consumers were consulted; every reaction is AI-generated.",
                "'Great escape' could not be resolved to a cultural reference.",
            ],
            next_steps=[
                "Test the original and 'Clearer message' headlines with Japanese weekend hikers.",
                "Have a native-speaking copywriter review the adapted copy.",
            ],
        ),
        campaign=ReportCampaignSnapshot(
            campaign_id=CAMPAIGN, name=campaign.name, campaign_type=campaign.campaign_type, content_version_id=VERSION,
            content=CONTENT_V1,
        ),
        discovery=ReportDiscoverySection(
            run_id=RUN_DISCOVERY, market=MARKET, research_question=discovery.research_question,
            references=references, market_brief=brief,
        ),
        rehearsal=ReportRehearsalSection(
            run_id=RUN_REHEARSAL, simulation_disclosure=disclosure, dimension_results=DimensionResults(**results),
            summary=summary,
        ),
        adaptations=[clearer, brand_first],
        evaluation=evaluation,
        evidence_register=evidence_register,
        limitations=[
            "Demo mode: every provider result is a fixture.",
            "Synthetic reactions are not consumer research.",
            "Cultural affinity does not establish demand.",
        ],
        validation_steps=[
            "Run a small unmoderated test of both headlines with Japanese weekend hikers.",
            "Ask a local copywriter to review idioms and tone.",
        ],
        missing_sections=[],
        reproducibility=ReproducibilityInfo(
            runs=[discovery_meta, rehearsal_meta, evaluation.run_metadata],
            scoring_version=SCORING.version, model_ids=[],
            prompt_versions=["atlas-brief-v1", "audience-reactions-v1", "analyst-v1", "loop-judge-v1"],
            generated_at=at(900),
            notes=[
                "Demo mode: provider outputs are fixtures, so reruns reproduce identical results.",
                "Live runs can differ because model and Qloo outputs may change.",
            ],
        ),
    )

    summary_row = ProjectSummary(
        id=PROJECT, name=project.name, description=project.description, mode="demo", status="active",
        brand_name=brand.name, target_markets=[MARKET], last_activity_at=at(900), created_at=at(0),
        updated_at=at(900),
    )
    return {
        "Project.json": project,
        "ProjectPage.json": ProjectPage(items=[summary_row], limit=20, offset=0, total=1),
        "Campaign.json": campaign,
        "CampaignPage.json": CampaignPage(items=[campaign], limit=20, offset=0, total=1),
        "RunAccepted.json": RunAccepted(
            run_id=RUN_DISCOVERY, status="queued", run_type="market_discovery", status_url=f"{API}/runs/{RUN_DISCOVERY}"
        ),
        "Run.running.json": run_running,
        "Run.completed.json": run_discovery,
        "Run.failed.json": run_failed,
        "RunPage.json": RunPage(
            items=[run_evaluation, run_adaptation, run_rehearsal, run_discovery], limit=20, offset=0, total=4
        ),
        "DiscoveryResult.json": discovery,
        "Study.json": study,
        "StudyPage.json": StudyPage(items=[study], limit=20, offset=0, total=1),
        "RehearsalResult.json": rehearsal,
        "Adaptation.json": clearer,
        "AdaptationPage.json": AdaptationPage(items=[clearer, brand_first], limit=20, offset=0, total=2),
        "EvaluationResult.json": evaluation,
        "EvidenceRecord.json": ev_hiking,
        "EvidencePage.json": EvidencePage(items=evidence_register, limit=20, offset=0, total=len(evidence_register)),
        "Report.json": report,
        "ReportPage.json": ReportPage(items=[report_summary], limit=20, offset=0, total=1),
        "Readiness.json": Readiness(
            status="degraded",
            dependencies=ReadinessDependencies(database="available", llm_provider="not_configured", qloo="not_configured"),
            capabilities=ReadinessCapabilities(
                embeddings="not_configured", vision="not_configured", reranking="not_required",
            ),
            live_mode_available=False, demo_mode_available=True,
        ),
        "ErrorResponse.validation.json": ErrorResponse(error=ErrorBody(
            code="VALIDATION_ERROR", message="The supplied request is invalid.",
            details=[ErrorDetail(field="evaluation_criteria", message="Weights must sum to 1.0; got 0.950.")],
            request_id="req_fixture_validation",
        )),
        "ErrorResponse.provider_not_configured.json": ErrorResponse(error=ErrorBody(
            code="PROVIDER_NOT_CONFIGURED",
            message="Live discovery is unavailable: Qloo is not configured on the server. Use a demo project or configure Qloo.",
            details=[], request_id="req_fixture_provider",
        )),
    }


def main() -> None:
    fixtures = build()
    OUT.mkdir(parents=True, exist_ok=True)
    for stale in OUT.glob("*.json"):
        stale.unlink()
    for name, model in fixtures.items():
        (OUT / name).write_text(
            json.dumps(model.model_dump(mode="json"), indent=2) + "\n", encoding="utf-8", newline="\n"
        )
    print(f"wrote {len(fixtures)} fixtures to {OUT}")


if __name__ == "__main__":
    main()
