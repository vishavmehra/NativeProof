from datetime import datetime
from typing import Annotated, Literal
from uuid import UUID

from pydantic import Field, StringConstraints

from app.schemas.adaptations import Adaptation
from app.schemas.campaigns import CampaignContent, CampaignType
from app.schemas.common import ApiModel, DataMode, Market, Page, RunMetadata
from app.schemas.discovery import CulturalReference, MarketBrief
from app.schemas.evaluations import EvaluationResult
from app.schemas.evidence import EvidenceRecord
from app.schemas.studies import DimensionResults, RehearsalSummary, SimulationDisclosure

ReportStatus = Literal["completed", "partial"]


class ReportCreate(ApiModel):
    """All referenced resources must belong to the project. The report is a persisted snapshot; no LLM call."""

    campaign_id: UUID
    title: Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=200)]
    discovery_run_id: UUID | None = None
    rehearsal_run_id: UUID | None = None
    adaptation_ids: Annotated[list[UUID], Field(max_length=3)] = []
    evaluation_id: UUID | None = None


class ExecutiveSummary(ApiModel):
    investigated: str
    findings: list[str]
    changes: list[str]
    uncertainties: list[str]
    next_steps: list[str]


class ReportCampaignSnapshot(ApiModel):
    campaign_id: UUID
    name: str
    campaign_type: CampaignType
    content_version_id: UUID
    content: CampaignContent


class ReportDiscoverySection(ApiModel):
    run_id: UUID
    market: Market
    research_question: str
    references: list[CulturalReference]
    market_brief: MarketBrief | None


class ReportRehearsalSection(ApiModel):
    run_id: UUID
    simulation_disclosure: SimulationDisclosure
    dimension_results: DimensionResults
    summary: RehearsalSummary | None


class ReproducibilityInfo(ApiModel):
    runs: list[RunMetadata]
    scoring_version: str | None
    model_ids: list[str]
    prompt_versions: list[str]
    generated_at: datetime
    notes: list[str]


class ReportSummary(ApiModel):
    id: UUID
    project_id: UUID
    campaign_id: UUID
    title: str
    status: ReportStatus = Field(description="partial when a referenced stage is missing or failed.")
    version_number: int
    mode: DataMode
    created_at: datetime


class Report(ReportSummary):
    market: Market | None
    executive_summary: ExecutiveSummary
    campaign: ReportCampaignSnapshot
    discovery: ReportDiscoverySection | None
    rehearsal: ReportRehearsalSection | None
    adaptations: list[Adaptation]
    evaluation: EvaluationResult | None
    evidence_register: list[EvidenceRecord]
    limitations: list[str]
    validation_steps: list[str]
    missing_sections: list[str] = Field(description="Sections omitted because their stage is missing or failed.")
    reproducibility: ReproducibilityInfo


class ReportPage(Page[ReportSummary]):
    pass
