"""Campaign Arena: 2-4 variants compared under the same synthetic segments and criteria."""

from datetime import datetime
from typing import Annotated, Literal
from uuid import UUID

from pydantic import Field, model_validator

from app.schemas.assets import VisionStatus, VisualObservation
from app.schemas.campaigns import CampaignContent, EvaluationCriteria
from app.schemas.common import ApiModel, DataMode, Label, Page, RiskFlag, RunMetadata
from app.schemas.evaluations import ScoringDefinition
from app.schemas.evidence import EvidenceRecord
from app.schemas.runs import RunStatus
from app.schemas.studies import DimensionResults, SegmentSummary, SimulationDisclosure, SyntheticReaction

VariantSource = Literal["content_version", "adaptation", "custom"]


class ArenaVariantInput(ApiModel):
    label: Label
    content_version_id: UUID | None = None
    adaptation_id: UUID | None = None
    content: CampaignContent | None = None
    asset_id: UUID | None = Field(
        default=None, description="Optional image creative, analyzed only by a verified vision model."
    )

    @model_validator(mode="after")
    def _one_source(self) -> "ArenaVariantInput":
        if sum(x is not None for x in (self.content_version_id, self.adaptation_id, self.content)) != 1:
            raise ValueError("Give exactly one of content_version_id, adaptation_id, or content.")
        return self


class ArenaCreate(ApiModel):
    """Start an arena (run_type campaign_arena)."""

    study_id: UUID = Field(description="Supplies the market, segments, and dimensions shared by every variant.")
    variants: Annotated[list[ArenaVariantInput], Field(min_length=2, max_length=4)]
    criteria: EvaluationCriteria
    discovery_run_id: UUID | None = None
    responses_per_variant: int = Field(default=6, ge=3, le=12)


class ArenaUpdate(ApiModel):
    preferred_variant_id: str | None = Field(description="The user's choice. Selection is not approval.")


class Improvement(ApiModel):
    variant_id: str
    suggestion: str
    rationale: str
    claim_type: Literal["interpreted", "hypothesis"]
    evidence_ids: list[UUID]


class ArenaVariantResult(ApiModel):
    variant_id: str
    label: str
    source: VariantSource
    source_id: UUID | None
    content: CampaignContent
    asset_id: UUID | None
    visual_observations: list[VisualObservation]
    dimension_results: DimensionResults
    segments: list[SegmentSummary]
    overall_score: float | None = Field(
        description="mvp-1 weighted utility of the synthetic dimension scores; null if any score is missing."
    )
    strengths: list[str]
    weaknesses: list[str]
    risk_flags: list[RiskFlag]
    reactions: list[SyntheticReaction]
    evidence_ids: list[UUID]


class ArenaSummary(ApiModel):
    id: UUID
    project_id: UUID
    campaign_id: UUID
    study_id: UUID
    run_id: UUID
    status: RunStatus
    mode: DataMode
    variant_labels: list[str]
    preferred_variant_id: str | None
    created_at: datetime


class ArenaResult(ArenaSummary):
    criteria: EvaluationCriteria
    variants: list[ArenaVariantResult]
    ranking: list[str] = Field(description="Variant ids by overall score, highest first; ties keep request order.")
    segment_differences: list[str]
    tradeoffs: list[str]
    recommended_improvements: list[Improvement]
    simulation_disclosure: SimulationDisclosure
    vision: VisionStatus
    scoring_definition: ScoringDefinition
    evidence: list[EvidenceRecord]
    limitations: list[str]
    run_metadata: RunMetadata


class ArenaPage(Page[ArenaSummary]):
    pass
