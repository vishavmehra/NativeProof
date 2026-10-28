"""Cultural DNA: persistent, versioned cultural profiles grounded in discovery evidence."""

from datetime import datetime
from typing import Annotated, Literal
from uuid import UUID

from pydantic import Field, StringConstraints

from app.schemas.common import ApiModel, ConfidenceLabel, DataMode, Market, MediumText, Name, Page, RunMetadata
from app.schemas.evidence import EvidenceRecord
from app.schemas.runs import RunStatus

ProfileSubject = Literal["brand", "product", "campaign"]
ProfileItemKind = Literal["affinity", "association", "opportunity", "conflict"]


class CulturalProfileCreate(ApiModel):
    """Generate a profile from completed discoveries (run_type cultural_profile)."""

    subject: ProfileSubject
    title: Name
    campaign_id: UUID | None = None
    markets: Annotated[list[Market], Field(min_length=1, max_length=5)]
    discovery_run_ids: Annotated[list[UUID], Field(max_length=5)] = Field(
        default=[],
        description="Completed discovery runs to ground the profile; empty = latest completed discovery per market.",
    )
    focus: Annotated[str, StringConstraints(strip_whitespace=True, max_length=500)] | None = None
    based_on_profile_id: UUID | None = Field(default=None, description="Regenerate as the next version of this profile.")


class CulturalProfileUpdate(ApiModel):
    title: Name | None = None
    notes: MediumText | None = None


class ProfileItem(ApiModel):
    id: str
    kind: ProfileItemKind
    title: str
    explanation: str
    claim_type: Literal["observed", "interpreted", "hypothesis"]
    confidence_label: ConfidenceLabel
    market: Market | None
    evidence_ids: list[UUID]
    limitations: list[str]


class CulturalProfileSummary(ApiModel):
    id: UUID
    project_id: UUID
    campaign_id: UUID | None
    lineage_id: UUID = Field(description="Shared by every version of one profile.")
    version: int
    subject: ProfileSubject
    title: str
    markets: list[Market]
    status: RunStatus
    mode: DataMode
    created_at: datetime
    updated_at: datetime


class CulturalProfile(CulturalProfileSummary):
    run_id: UUID | None
    summary: str | None
    items: list[ProfileItem]
    market_context: list[str]
    missing_evidence: list[str]
    limitations: list[str]
    notes: str | None
    brand_name: str
    source_discovery_run_ids: list[UUID]
    evidence: list[EvidenceRecord]
    run_metadata: RunMetadata | None


class CulturalProfilePage(Page[CulturalProfileSummary]):
    pass
