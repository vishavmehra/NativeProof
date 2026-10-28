from datetime import datetime
from typing import Annotated, Literal
from uuid import UUID

from pydantic import Field, model_validator

from app.schemas.campaigns import CampaignContent, EvaluationCriteria
from app.schemas.common import ApiModel, Dimension, DimensionScores, Market, RiskFlag, RunMetadata
from app.schemas.evidence import EvidenceRecord
from app.schemas.runs import RunStatus

Decision = Literal["accept", "revise", "validate", "inconclusive"]


class EvaluationContext(ApiModel):
    discovery_run_id: UUID | None = None
    baseline_rehearsal_run_id: UUID | None = None


class EvaluationCreate(ApiModel):
    source_content_version_id: UUID
    candidate_adaptation_ids: Annotated[list[UUID], Field(min_length=1, max_length=3)]
    market: Market
    criteria: EvaluationCriteria
    context: EvaluationContext = EvaluationContext()

    @model_validator(mode="after")
    def _unique_candidates(self) -> "EvaluationCreate":
        if len(set(self.candidate_adaptation_ids)) != len(self.candidate_adaptation_ids):
            raise ValueError("candidate_adaptation_ids must be unique.")
        return self


class DimensionRationales(ApiModel):
    clarity: str | None = None
    brand_fidelity: str | None = None
    cultural_relevance: str | None = None
    cultural_risk: str | None = None


class CandidateResult(ApiModel):
    candidate_id: str = Field(description='"original" or the adaptation UUID.')
    candidate_type: Literal["original", "adaptation"]
    adaptation_id: UUID | None
    label: str
    content: CampaignContent
    dimension_scores: DimensionScores = Field(description="Model assessments, 0-100.")
    dimension_rationales: DimensionRationales
    overall_score: float | None = Field(description="Deterministic weighted utility; null if any dimension is missing.")
    risk_flags: list[RiskFlag]
    constraint_violations: list[str]
    strengths: list[str]
    weaknesses: list[str]
    tradeoffs: list[str]
    evidence_ids: list[UUID]


class Recommendation(ApiModel):
    decision: Decision
    candidate_id: str | None
    rationale: str
    rule_id: str = Field(description="The deterministic rule that produced the decision, e.g. R3_small_margin.")


class Comparability(ApiModel):
    same_market: bool
    same_criteria: bool
    same_source_version: bool
    same_scoring_version: bool
    same_evidence_context: bool
    same_model: bool
    notes: list[str]


class DimensionDefinition(ApiModel):
    dimension: Dimension
    label: str
    definition: str
    higher_is_better: bool


class ScoringDefinition(ApiModel):
    version: str
    scale: str
    dimensions: list[DimensionDefinition]
    aggregation: str
    recommendation_rules: list[str]


class EvaluationResult(ApiModel):
    id: UUID
    run_id: UUID
    status: RunStatus
    project_id: UUID
    campaign_id: UUID
    source_content_version_id: UUID
    market: Market
    criteria: EvaluationCriteria
    results: list[CandidateResult]
    recommendation: Recommendation | None
    comparability: Comparability
    scoring_version: str
    scoring_definition: ScoringDefinition
    evidence: list[EvidenceRecord]
    limitations: list[str]
    run_metadata: RunMetadata
    created_at: datetime
