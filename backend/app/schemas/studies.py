from datetime import datetime
from typing import Annotated, Literal
from uuid import UUID

from pydantic import Field, model_validator

from app.schemas.campaigns import CampaignContent
from app.schemas.common import (
    DIMENSIONS,
    ApiModel,
    ConfidenceLabel,
    Dimension,
    DimensionScores,
    Label,
    Market,
    Name,
    Page,
    RiskFlag,
    RunMetadata,
    Score,
    ShortText,
)
from app.schemas.evidence import EvidenceRecord
from app.schemas.runs import RunStatus

Sentiment = Literal["positive", "neutral", "negative", "mixed"]
FindingCategory = Literal[
    "clarity", "brand_fidelity", "cultural_relevance", "cultural_risk", "confusion", "disagreement", "other"
]


class SegmentAssumption(ApiModel):
    """An explicit audience hypothesis. Not a verified demographic fact."""

    label: Label
    description: ShortText


class SimulationConfig(ApiModel):
    response_count: int = Field(default=12, ge=3, le=24, description="Generation target, not a human sample size.")
    segment_count: int = Field(default=3, ge=1, le=4)
    random_seed: int | None = Field(default=42, ge=0)

    @model_validator(mode="after")
    def _segments_fit(self) -> "SimulationConfig":
        if self.segment_count > self.response_count:
            raise ValueError("segment_count cannot exceed response_count.")
        return self


class StudyCreate(ApiModel):
    campaign_id: UUID
    name: Name
    market: Market
    research_questions: Annotated[list[ShortText], Field(min_length=1, max_length=5)]
    dimensions: Annotated[list[Dimension], Field(min_length=1, max_length=4)] = list(DIMENSIONS)
    segments: Annotated[list[SegmentAssumption], Field(max_length=4)] = Field(
        default=[], description="Optional. When omitted, segment assumptions are model-generated and labeled so."
    )
    simulation_config: SimulationConfig = SimulationConfig()

    @model_validator(mode="after")
    def _consistent(self) -> "StudyCreate":
        if len(set(self.dimensions)) != len(self.dimensions):
            raise ValueError("dimensions must be unique.")
        if self.segments and len(self.segments) != self.simulation_config.segment_count:
            raise ValueError("simulation_config.segment_count must equal the number of segments provided.")
        return self


class Study(ApiModel):
    id: UUID
    project_id: UUID
    campaign_id: UUID
    name: str
    market: Market
    research_questions: list[str]
    dimensions: list[Dimension]
    segments: list[SegmentAssumption]
    simulation_config: SimulationConfig
    latest_rehearsal_run_id: UUID | None
    created_at: datetime
    updated_at: datetime


class StudyPage(Page[Study]):
    pass


class RehearsalCreate(ApiModel):
    content_version_id: UUID | None = Field(default=None, description="Defaults to the campaign's current version.")
    discovery_run_id: UUID | None = Field(default=None, description="Omit for an ungrounded rehearsal; it is disclosed.")
    simulation_config: SimulationConfig | None = Field(default=None, description="Defaults to the study's config.")


class DimensionRating(ApiModel):
    dimension: Dimension
    value: int = Field(ge=1, le=5, description="1-5. For cultural_risk, 5 means the most perceived risk.")
    rationale: str | None


class SyntheticReaction(ApiModel):
    """One AI-generated reaction. Never a real participant response."""

    id: UUID
    segment_label: str
    is_synthetic: Literal[True] = True
    interpretation: str
    reaction_summary: str
    sentiment: Sentiment
    ratings: list[DimensionRating]
    confusion_level: float = Field(ge=0, le=1, description="0 = fully understood, 1 = message not understood.")
    potential_confusions: list[str]
    risk_flags: list[RiskFlag]
    relevant_passage: str | None
    evidence_ids: list[UUID]


class DimensionResult(ApiModel):
    dimension: Dimension
    score: Score | None = Field(description="round((mean_rating - 1) / 4 * 100, 1); null when no ratings.")
    higher_is_better: bool
    n: int
    distribution: Annotated[list[int], Field(min_length=5, max_length=5)] = Field(
        description="Counts of ratings 1..5 (index 0 = rating 1)."
    )
    spread: float | None = Field(description="Population standard deviation of the 1-5 ratings.")
    disagreement: bool
    method: Literal["deterministic_aggregation"] = "deterministic_aggregation"
    definition: str
    interpretation: str
    limitations: list[str]


class DimensionResults(ApiModel):
    """Keyed by dimension; null for dimensions the study did not request."""

    clarity: DimensionResult | None = None
    brand_fidelity: DimensionResult | None = None
    cultural_relevance: DimensionResult | None = None
    cultural_risk: DimensionResult | None = None


class Finding(ApiModel):
    id: str
    category: FindingCategory
    title: str
    summary: str
    supporting_response_ids: list[UUID]
    evidence_ids: list[UUID]
    method: Literal["synthetic_response_analysis", "deterministic_aggregation"]
    claim_type: Literal["synthetic", "interpreted", "derived", "hypothesis"]
    confidence_label: ConfidenceLabel
    limitations: list[str]


class InterpretationCluster(ApiModel):
    label: str
    summary: str
    response_ids: list[UUID]


class Disagreement(ApiModel):
    id: str
    topic: str
    dimension: Dimension | None
    interpretations: Annotated[list[InterpretationCluster], Field(min_length=2)]
    possible_explanations: list[str] = Field(description="Hypotheses, not established causes.")
    validation_question: str
    spread: float | None


class RehearsalSummary(ApiModel):
    key_findings: list[Finding]
    potential_confusions: list[Finding]
    potential_cultural_risks: list[Finding]
    disagreements: list[Disagreement]
    validation_questions: list[str]


class SimulationDisclosure(ApiModel):
    is_synthetic: Literal[True] = True
    independent_human_sample: Literal[False] = False
    description: str
    requested_responses: int
    generated_responses: int
    grounded: bool = Field(description="True only when discovery evidence was supplied to the generator.")
    grounding_evidence_count: int


class SegmentSummary(ApiModel):
    label: str
    assumptions: str
    source: Literal["user", "model"]
    response_count: int
    dimension_scores: DimensionScores


class RehearsalResult(ApiModel):
    run_id: UUID
    status: RunStatus
    study_id: UUID
    campaign_id: UUID
    content_version_id: UUID
    content: CampaignContent = Field(description="Snapshot of the exact content version rehearsed.")
    market: Market
    simulation_disclosure: SimulationDisclosure
    segments: list[SegmentSummary]
    reactions: list[SyntheticReaction]
    dimension_results: DimensionResults
    summary: RehearsalSummary | None
    evidence: list[EvidenceRecord]
    limitations: list[str]
    run_metadata: RunMetadata
