from datetime import datetime
from typing import Annotated, Literal
from uuid import UUID

from pydantic import Field, StringConstraints

from app.schemas.campaigns import CampaignContent
from app.schemas.common import ApiModel, DataMode, Market, Page, RiskFlag, TermList
from app.schemas.evidence import EvidenceRecord

ContentField = Literal["headline", "body", "call_to_action"]


class AdaptationCreate(ApiModel):
    source_content_version_id: UUID | None = Field(default=None, description="Defaults to the current version.")
    market: Market
    discovery_run_id: UUID | None = None
    rehearsal_run_id: UUID | None = None
    variant_count: int = Field(default=3, ge=1, le=3)
    instructions: Annotated[str, StringConstraints(strip_whitespace=True, max_length=1000)] | None = None
    protected_terms: TermList = Field(default=[], description="Merged with the brand kit's protected terms.")


class AdaptationRevisionCreate(ApiModel):
    """A user edit. Stored as a new adaptation (origin user_edit); deterministic checks rerun, no LLM call."""

    content: CampaignContent
    note: Annotated[str, StringConstraints(strip_whitespace=True, max_length=500)] | None = None


class ContentChange(ApiModel):
    field: ContentField
    original: str | None
    adapted: str | None
    reason: str
    reasoning_type: Literal["evidence_supported", "model_interpretation", "user_edit"] = Field(
        description=(
            "evidence_supported requires at least one evidence id that directly supports the change; "
            "user_edit marks a change a person made in a revision."
        )
    )
    evidence_ids: list[UUID]


class AdaptationChecks(ApiModel):
    """Deterministic checks computed in code, not model claims."""

    protected_terms_preserved: bool
    missing_protected_terms: list[str]
    prohibited_terms_found: list[str]
    brand_voice_reviewed: bool
    cultural_risk_reviewed: bool


class AdaptationContext(ApiModel):
    discovery_run_id: UUID | None
    rehearsal_run_id: UUID | None
    grounded: bool = Field(description="True only when Qloo evidence was supplied to the generator.")
    rehearsal_informed: bool


class Adaptation(ApiModel):
    id: UUID
    project_id: UUID
    campaign_id: UUID
    run_id: UUID | None = Field(description="Generating run; null for user edits.")
    source_content_version_id: UUID
    parent_adaptation_id: UUID | None
    origin: Literal["generated", "user_edit"]
    mode: DataMode
    market: Market
    label: str = Field(description="Short strategy label, e.g. Clearer message.")
    strategy: str
    content: CampaignContent
    changes: list[ContentChange]
    checks: AdaptationChecks
    warnings: list[RiskFlag]
    limitations: list[str]
    context: AdaptationContext
    evidence: list[EvidenceRecord]
    created_at: datetime


class AdaptationPage(Page[Adaptation]):
    pass
