"""Market Expansion Simulator: the Atlas pipeline run across several markets, compared honestly."""

from datetime import datetime
from typing import Annotated, Literal
from uuid import UUID

from pydantic import Field, StringConstraints, model_validator

from app.schemas.common import ApiModel, ConfidenceLabel, DataMode, Market, Page, RunMetadata, Term
from app.schemas.discovery import BriefFinding, CulturalReference
from app.schemas.evidence import EvidenceRecord
from app.schemas.runs import RunStatus


class MarketComparisonCreate(ApiModel):
    """Start a comparison of 2-5 markets (run_type market_comparison)."""

    markets: Annotated[list[Market], Field(min_length=2, max_length=5)]
    campaign_id: UUID | None = None
    product_category: Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=200)]
    research_question: Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=500)]
    reference_terms: Annotated[list[Term], Field(max_length=10)] = []

    @model_validator(mode="after")
    def _unique_markets(self) -> "MarketComparisonCreate":
        codes = [market.country_code for market in self.markets]
        if len(set(codes)) != len(codes):
            raise ValueError("markets must be unique.")
        return self


class EvidenceQuality(ApiModel):
    """Deterministic counts; the label follows the contracts/README confidence rules."""

    observed_records: int
    resolved_references: int
    ambiguous_references: int
    unresolved_references: int
    label: ConfidenceLabel
    note: str


class BrandCompatibility(ApiModel):
    assessment: str
    claim_type: Literal["interpreted", "hypothesis"]
    confidence_label: ConfidenceLabel
    brand_rules_considered: list[str]


class MarketColumn(ApiModel):
    market: Market
    status: Literal["completed", "partial", "failed", "unavailable"]
    signals: list[CulturalReference]
    opportunities: list[BriefFinding]
    risks: list[BriefFinding]
    hypotheses: list[BriefFinding]
    brand_compatibility: BrandCompatibility | None
    evidence_quality: EvidenceQuality
    gaps: list[str]
    message: str | None = Field(description="Why a market is unavailable, failed, or partial.")


class MarketComparability(ApiModel):
    market_specific_signals: bool = Field(
        description="False when the verified Qloo signals did not differ by market, so markets cannot be ranked on them."
    )
    notes: list[str]


class MarketComparisonSummary(ApiModel):
    id: UUID
    project_id: UUID
    campaign_id: UUID | None
    run_id: UUID
    status: RunStatus
    mode: DataMode
    markets: list[Market]
    created_at: datetime


class MarketComparison(MarketComparisonSummary):
    product_category: str
    research_question: str
    reference_terms: list[str]
    columns: list[MarketColumn]
    comparability: MarketComparability
    cross_market_summary: str | None = Field(
        description="Model interpretation across markets; null when evidence is insufficient."
    )
    evidence: list[EvidenceRecord]
    limitations: list[str]
    run_metadata: RunMetadata


class MarketComparisonPage(Page[MarketComparisonSummary]):
    pass
