"""Test double for `app.workflows` (owned by the AI workstream), built to the agreed interface.

`install(monkeypatch)` puts a fake package in sys.modules so the run engine's lazy import finds
it. Outputs are small but complete, labeled test fixtures; knobs on the returned object switch
outcomes (completed, partial, failed, raise, block) per run type.
"""

import asyncio
import statistics
import sys
import types as pytypes
from typing import Any, Literal, Protocol
from uuid import UUID, uuid4

import pytest
from pydantic import BaseModel

from app.db.base import utcnow
from app.schemas.adaptations import Adaptation, AdaptationChecks, AdaptationContext, AdaptationCreate, ContentChange
from app.schemas.campaigns import CampaignContent, EvaluationCriteria
from app.schemas.common import DataMode, DimensionScores, Market, StepTrace
from app.schemas.discovery import BriefFinding, CulturalReference, DiscoveryCreate, MarketBrief
from app.schemas.evaluations import (
    CandidateResult,
    Comparability,
    DimensionDefinition,
    DimensionRationales,
    Recommendation,
    ScoringDefinition,
)
from app.schemas.evidence import EntityRef, EvidenceProvenance, EvidenceRecord
from app.schemas.runs import RunError
from app.schemas.studies import (
    DimensionRating,
    DimensionResult,
    DimensionResults,
    Finding,
    RehearsalSummary,
    SegmentSummary,
    SimulationConfig,
    SimulationDisclosure,
    Study,
    SyntheticReaction,
)
from app.services.runs import STAGES

OutcomeStatus = Literal["completed", "partial", "failed"]


class BrandContext(BaseModel):
    name: str
    description: str | None
    voice: list[str]
    target_audience: str | None
    preferred_terms: list[str]
    prohibited_terms: list[str]
    protected_terms: list[str]


class WorkflowContext(BaseModel):
    run_id: UUID
    project_id: UUID
    campaign_id: UUID | None
    mode: DataMode
    brand: BrandContext


class ProgressFn(Protocol):
    async def __call__(self, stage: str, completed_steps: int, total_steps: int, message: str) -> None: ...


class _Outcome(BaseModel):
    status: OutcomeStatus
    evidence: list[EvidenceRecord] = []
    limitations: list[str] = []
    steps: list[StepTrace] = []
    error: RunError | None = None


class DiscoveryInput(BaseModel):
    context: WorkflowContext
    request: DiscoveryCreate
    campaign_content: CampaignContent | None


class DiscoveryOutcome(_Outcome):
    references: list[CulturalReference] = []
    market_brief: MarketBrief | None = None


class RehearsalInput(BaseModel):
    context: WorkflowContext
    study: Study
    content_version_id: UUID
    content: CampaignContent
    simulation_config: SimulationConfig
    grounding_evidence: list[EvidenceRecord]


class RehearsalOutcome(_Outcome):
    simulation_disclosure: SimulationDisclosure
    segments: list[SegmentSummary] = []
    reactions: list[SyntheticReaction] = []
    dimension_results: DimensionResults = DimensionResults()
    summary: RehearsalSummary | None = None


class AdaptationInput(BaseModel):
    context: WorkflowContext
    source_content_version_id: UUID
    source_content: CampaignContent
    request: AdaptationCreate
    protected_terms: list[str]
    grounding_evidence: list[EvidenceRecord]
    rehearsal_summary: RehearsalSummary | None


class AdaptationOutcome(_Outcome):
    adaptations: list[Adaptation] = []


class EvaluationInput(BaseModel):
    context: WorkflowContext
    evaluation_id: UUID
    source_content_version_id: UUID
    source_content: CampaignContent
    candidates: list[Adaptation]
    criteria: EvaluationCriteria
    market: Market
    grounding_evidence: list[EvidenceRecord]
    rehearsal_summary: RehearsalSummary | None


class EvaluationOutcome(_Outcome):
    results: list[CandidateResult] = []
    recommendation: Recommendation | None = None
    comparability: Comparability
    scoring_version: str = "mvp-1"
    scoring_definition: ScoringDefinition


NOTE = "Test fixture output; not live Qloo or model data."
SCORING = ScoringDefinition(
    version="mvp-1", scale="0-100 per dimension",
    dimensions=[DimensionDefinition(dimension=d, label=d, definition=d, higher_is_better=d != "cultural_risk")
                for d in ("clarity", "brand_fidelity", "cultural_relevance", "cultural_risk")],
    aggregation="weighted utility", recommendation_rules=["R4_meets_review_threshold"],
)


class FakeWorkflows:
    def __init__(self) -> None:
        self.status: dict[str, OutcomeStatus] = {}
        self.raise_in: set[str] = set()
        self.block: asyncio.Event | None = None
        self.mislabel_live = False
        self.inputs: dict[str, Any] = {}

    # -- helpers --------------------------------------------------------------------------

    async def _stages(self, run_type: str, progress: ProgressFn) -> None:
        for index, stage in enumerate(STAGES[run_type]):
            await progress(stage, index, len(STAGES[run_type]), f"{stage} (test fixtures).")
        if self.block is not None:
            await self.block.wait()
        if run_type in self.raise_in:
            raise RuntimeError("simulated workflow bug")

    def _evidence(self, ctx: WorkflowContext, evidence_type: str, claim_type: str, title: str, **extra: Any) -> EvidenceRecord:
        live = self.mislabel_live and evidence_type == "qloo_source"
        return EvidenceRecord(
            id=uuid4(), project_id=ctx.project_id, evidence_type=evidence_type, claim_type=claim_type,  # type: ignore[arg-type]
            title=title, summary=f"{title}.", source_provider=extra.get("provider", "fixture"),
            source_workflow=extra.get("workflow"), source_reference=None, subject=None, related_entity=None,
            attributes=[], method=extra.get("method", "provider_result"),
            retrieval_mode="live" if live else extra.get("retrieval", "fixture"), is_live_data=live,
            source_run_id=ctx.run_id, retrieved_at=utcnow(), limitations=[NOTE],
            provenance=EvidenceProvenance(request_hash=None, response_hash=None, normalizer_version="1",
                                          fixture_origin="hand_authored"),
            created_at=utcnow(),
        )

    def _steps(self, run_type: str) -> list[StepTrace]:
        return [StepTrace(stage=s, agent="test", status="completed", provider="fixture", prompt_version=f"{s}-v1",
                          model_id="fixture-model") for s in STAGES[run_type]]

    def _failed(self, run_type: str) -> dict[str, Any]:
        stage = STAGES[run_type][1]
        error = RunError(code="PROVIDER_ERROR", stage=stage, retryable=True,
                         message="The provider returned an error. No results were saved; retrying is safe.")
        return {"status": "failed", "error": error, "steps": self._steps(run_type)[:1]}

    # -- workflows --------------------------------------------------------------------------

    async def run_discovery(self, inp: DiscoveryInput, deps: Any, progress: ProgressFn) -> DiscoveryOutcome:
        self.inputs["market_discovery"] = inp
        await self._stages("market_discovery", progress)
        status = self.status.get("market_discovery", "completed")
        if status == "failed":
            return DiscoveryOutcome(**self._failed("market_discovery"))
        ctx = inp.context
        observed = self._evidence(ctx, "qloo_source", "observed", "Resolved tag: Hiking", workflow="find_tags")
        interpretation = self._evidence(ctx, "model_interpretation", "interpreted", "Interpretation: trail framing",
                                        method="model_interpretation", retrieval="generated")
        references = [
            CulturalReference(id="ref-1", query_term=(inp.request.reference_terms or ["outdoor"])[0],
                              match_status="resolved", name="Hiking", entity_id="fixture:tag:hiking", entity_type="tag",
                              candidates=[], attributes=[], relevance_explanation="Matches the journey framing.",
                              evidence_ids=[observed.id], limitations=[]),
            CulturalReference(id="ref-2", query_term="minimal design", match_status="ambiguous", name=None,
                              entity_id=None, entity_type=None, attributes=[], relevance_explanation=None,
                              candidates=[EntityRef(entity_id="fixture:tag:minimalism", name="Minimalism", entity_type="tag")],
                              evidence_ids=[], limitations=["Ambiguous."]),
        ]
        brief = MarketBrief(
            summary="Trail interests are the clearest supported signal.",
            observations=[BriefFinding(id="obs-1", title="Hiking resolved", explanation="Resolved tag.",
                                       claim_type="observed", evidence_ids=[observed.id], confidence_label="moderate",
                                       validation_question=None)],
            opportunities=[BriefFinding(id="opp-1", title="Lead with trails", explanation="Interpretation.",
                                        claim_type="interpreted", evidence_ids=[observed.id, interpretation.id],
                                        confidence_label="limited", validation_question="Do trails resonate?")],
            risks=[], validation_questions=["Do trails resonate?"], limitations=["Affinity is not demand."],
        )
        partial = status == "partial"
        return DiscoveryOutcome(
            status=status, references=references, market_brief=None if partial else brief,
            evidence=[observed] if partial else [observed, interpretation],
            limitations=["The brief could not be generated."] if partial else [NOTE],
            steps=self._steps("market_discovery"),
        )

    async def run_rehearsal(self, inp: RehearsalInput, deps: Any, progress: ProgressFn) -> RehearsalOutcome:
        self.inputs["campaign_rehearsal"] = inp
        await self._stages("campaign_rehearsal", progress)
        status = self.status.get("campaign_rehearsal", "completed")
        config, grounding = inp.simulation_config, inp.grounding_evidence
        disclosure = SimulationDisclosure(
            description="These reactions were generated by an AI model (test fixtures) and are not responses from real people.",
            requested_responses=config.response_count, generated_responses=0 if status == "failed" else config.response_count,
            grounded=bool(grounding), grounding_evidence_count=len(grounding),
        )
        if status == "failed":
            return RehearsalOutcome(simulation_disclosure=disclosure, **self._failed("campaign_rehearsal"))
        labels = [s.label for s in inp.study.segments] or [f"Segment {i + 1}" for i in range(config.segment_count)]
        reactions = [
            SyntheticReaction(
                id=uuid4(), segment_label=labels[i % len(labels)], interpretation="An invitation to hike.",
                reaction_summary="Relevant.", sentiment="positive",
                ratings=[DimensionRating(dimension=d, value=2 + (i + j) % 3, rationale=None) for j, d in enumerate(inp.study.dimensions)],
                confusion_level=0.2, potential_confusions=[], risk_flags=[], relevant_passage=None,
                evidence_ids=[grounding[0].id] if grounding else [],
            )
            for i in range(config.response_count)
        ]
        results = {}
        for d in inp.study.dimensions:
            values = [r.value for x in reactions for r in x.ratings if r.dimension == d]
            results[d] = DimensionResult(
                dimension=d, score=round((statistics.fmean(values) - 1) / 4 * 100, 1), higher_is_better=d != "cultural_risk",
                n=len(values), distribution=[values.count(v) for v in range(1, 6)], spread=round(statistics.pstdev(values), 2),
                disagreement=False, definition=d, interpretation="Synthetic ratings.", limitations=[NOTE],
            )
        calc = self._evidence(inp.context, "deterministic_calculation", "derived", "Clarity score",
                              provider="nativeproof", method="deterministic_aggregation", retrieval="generated")
        summary = RehearsalSummary(
            key_findings=[Finding(id="kf-1", category="clarity", title="Mostly clear", summary="Clear.",
                                  supporting_response_ids=[r.id for r in reactions[:2]], evidence_ids=[calc.id],
                                  method="synthetic_response_analysis", claim_type="synthetic",
                                  confidence_label="limited", limitations=[NOTE])],
            potential_confusions=[], potential_cultural_risks=[], disagreements=[],
            validation_questions=["Which reading do real hikers choose?"],
        )
        return RehearsalOutcome(
            status=status, simulation_disclosure=disclosure,
            segments=[SegmentSummary(label=label, assumptions="Test assumption.", source="model",
                                     response_count=sum(r.segment_label == label for r in reactions),
                                     dimension_scores=DimensionScores()) for label in labels],
            reactions=reactions, dimension_results=DimensionResults(**results),
            summary=None if status == "partial" else summary, evidence=[calc], limitations=[NOTE],
            steps=self._steps("campaign_rehearsal"),
        )

    async def run_adaptation(self, inp: AdaptationInput, deps: Any, progress: ProgressFn) -> AdaptationOutcome:
        self.inputs["campaign_adaptation"] = inp
        await self._stages("campaign_adaptation", progress)
        status = self.status.get("campaign_adaptation", "completed")
        if status == "failed":
            return AdaptationOutcome(**self._failed("campaign_adaptation"))
        ctx, grounding = inp.context, inp.grounding_evidence
        adaptations = []
        for i in range(inp.request.variant_count):
            headline = f"Gear for the trails, take {i + 1}"
            adaptations.append(Adaptation(
                id=uuid4(), project_id=ctx.project_id, campaign_id=ctx.campaign_id,  # type: ignore[arg-type]
                run_id=ctx.run_id, source_content_version_id=inp.source_content_version_id, parent_adaptation_id=None,
                origin="generated", mode=ctx.mode, market=inp.request.market, label=f"Variant {i + 1}",
                strategy="Anchor the promise in trail use.",
                content=inp.source_content.model_copy(update={"headline": headline}),
                changes=[ContentChange(field="headline", original=inp.source_content.headline, adapted=headline,
                                       reason="Trail framing.",
                                       reasoning_type="evidence_supported" if grounding else "model_interpretation",
                                       evidence_ids=[grounding[0].id] if grounding else [])],
                checks=AdaptationChecks(protected_terms_preserved=True, missing_protected_terms=[],
                                        prohibited_terms_found=[], brand_voice_reviewed=True, cultural_risk_reviewed=True),
                warnings=[], limitations=[NOTE],
                context=AdaptationContext(discovery_run_id=inp.request.discovery_run_id,
                                          rehearsal_run_id=inp.request.rehearsal_run_id, grounded=bool(grounding),
                                          rehearsal_informed=inp.rehearsal_summary is not None),
                evidence=grounding[:1], created_at=utcnow(),
            ))
        return AdaptationOutcome(status=status, adaptations=adaptations, limitations=[NOTE], steps=self._steps("campaign_adaptation"))

    async def run_evaluation(self, inp: EvaluationInput, deps: Any, progress: ProgressFn) -> EvaluationOutcome:
        self.inputs["campaign_evaluation"] = inp
        await self._stages("campaign_evaluation", progress)
        status = self.status.get("campaign_evaluation", "completed")
        comparability = Comparability(same_market=True, same_criteria=True, same_source_version=True,
                                      same_scoring_version=True, same_evidence_context=True, same_model=True, notes=["One run."])
        if status == "failed":
            return EvaluationOutcome(comparability=comparability, scoring_definition=SCORING, **self._failed("campaign_evaluation"))
        calc = self._evidence(inp.context, "deterministic_calculation", "derived", "Overall scores",
                              provider="nativeproof", method="deterministic_aggregation", retrieval="generated")

        def result(candidate_id: str, kind: Any, adaptation: Adaptation | None, content: CampaignContent, base: int) -> CandidateResult:
            scores = DimensionScores(clarity=base, brand_fidelity=base, cultural_relevance=base, cultural_risk=20)
            c = inp.criteria
            overall = round(c.clarity * base + c.brand_fidelity * base + c.cultural_relevance * base + c.cultural_risk * 80, 1)
            return CandidateResult(
                candidate_id=candidate_id, candidate_type=kind, adaptation_id=adaptation.id if adaptation else None,
                label=adaptation.label if adaptation else "Original", content=content, dimension_scores=scores,
                dimension_rationales=DimensionRationales(), overall_score=overall, risk_flags=[], constraint_violations=[],
                strengths=[], weaknesses=[], tradeoffs=[], evidence_ids=[calc.id],
            )

        results = [result("original", "original", None, inp.source_content, 55)]
        results += [result(str(a.id), "adaptation", a, a.content, 75 + i) for i, a in enumerate(inp.candidates)]
        best = max(results[1:], key=lambda r: r.overall_score or 0)
        return EvaluationOutcome(
            status=status, results=results, comparability=comparability, scoring_definition=SCORING,
            recommendation=Recommendation(decision="accept", candidate_id=best.candidate_id,
                                          rationale="Meets the review threshold (test fixtures).",
                                          rule_id="R4_meets_review_threshold"),
            evidence=[calc], limitations=[NOTE], steps=self._steps("campaign_evaluation"),
        )

    @staticmethod
    def build_workflow_deps(mode: str, settings: Any, *, qloo_cache: Any = None) -> dict[str, Any]:
        return {"mode": mode}


def install(monkeypatch: pytest.MonkeyPatch) -> FakeWorkflows:
    fake = FakeWorkflows()
    package = pytypes.ModuleType("app.workflows")
    types_module = pytypes.ModuleType("app.workflows.types")
    for name, value in dict(globals()).items():
        if isinstance(value, type) and issubclass(value, BaseModel):
            setattr(types_module, name, value)
    for name in ("run_discovery", "run_rehearsal", "run_adaptation", "run_evaluation", "build_workflow_deps"):
        setattr(package, name, getattr(fake, name))
    package.types = types_module  # type: ignore[attr-defined]
    monkeypatch.setitem(sys.modules, "app.workflows", package)
    monkeypatch.setitem(sys.modules, "app.workflows.types", types_module)
    return fake
