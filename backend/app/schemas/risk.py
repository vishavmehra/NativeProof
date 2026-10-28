"""Cultural Risk Radar: findings on campaign text and creatives, with a review workflow."""

from datetime import datetime
from typing import Annotated, Literal
from uuid import UUID

from pydantic import Field, model_validator

from app.schemas.adaptations import ContentField
from app.schemas.assets import VisionStatus, VisualObservation
from app.schemas.campaigns import CampaignContent
from app.schemas.common import (
    ApiModel,
    ConfidenceLabel,
    DataMode,
    Market,
    MediumText,
    Page,
    RiskCategory,
    RiskSeverity,
    RunMetadata,
)
from app.schemas.evidence import EvidenceRecord
from app.schemas.runs import RunStatus

RiskFindingStatus = Literal["open", "dismissed", "resolved", "applied"]
ScanSource = Literal["content_version", "adaptation", "custom"]


class RiskScanCreate(ApiModel):
    """Start a scan (run_type risk_scan). With no source given, the campaign's current version is scanned."""

    market: Market
    content_version_id: UUID | None = None
    adaptation_id: UUID | None = None
    content: CampaignContent | None = None
    asset_ids: Annotated[list[UUID], Field(max_length=3)] = []
    discovery_run_id: UUID | None = None

    @model_validator(mode="after")
    def _at_most_one_source(self) -> "RiskScanCreate":
        if sum(x is not None for x in (self.content_version_id, self.adaptation_id, self.content)) > 1:
            raise ValueError("Give at most one of content_version_id, adaptation_id, or content.")
        return self


class TextLocation(ApiModel):
    field: ContentField
    excerpt: str
    start: int | None
    end: int | None


class RiskFinding(ApiModel):
    id: UUID
    category: RiskCategory
    severity: RiskSeverity
    confidence_label: ConfidenceLabel
    source: Literal["deterministic_check", "model_assessment", "vision_model"]
    text_location: TextLocation | None
    visual_observation_id: str | None
    observation: str = Field(description="The exact text excerpt or visible element the finding concerns.")
    interpretation: str = Field(
        description="Why it may matter. A model interpretation unless source is deterministic_check."
    )
    brand_rule: str | None = Field(description="The Brand Memory rule involved, if any.")
    evidence_ids: list[UUID]
    limitations: list[str]
    suggested_alternative: str | None
    status: RiskFindingStatus
    status_note: str | None
    updated_at: datetime


class RiskFindingUpdate(ApiModel):
    status: Literal["open", "dismissed", "resolved"]
    note: MediumText | None = None


class FindingCounts(ApiModel):
    open: int
    dismissed: int
    resolved: int
    applied: int
    high: int
    medium: int
    low: int


class RiskScanSummary(ApiModel):
    id: UUID
    project_id: UUID
    campaign_id: UUID
    run_id: UUID
    status: RunStatus
    mode: DataMode
    market: Market
    source_kind: ScanSource
    source_id: UUID | None
    counts: FindingCounts
    created_at: datetime


class RiskScan(RiskScanSummary):
    content: CampaignContent
    asset_ids: list[UUID]
    visual_observations: list[VisualObservation]
    vision: VisionStatus
    findings: list[RiskFinding]
    evidence: list[EvidenceRecord]
    limitations: list[str]
    run_metadata: RunMetadata


class RiskScanPage(Page[RiskScanSummary]):
    pass
