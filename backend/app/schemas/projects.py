from datetime import datetime
from typing import Annotated, Literal
from uuid import UUID

from pydantic import Field, StringConstraints

from app.schemas.common import ApiModel, DataMode, Market, MarketList, MediumText, Name, Page, ShortText, TermList

VoiceAttribute = Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=40)]
VoiceList = Annotated[list[VoiceAttribute], Field(max_length=10)]
ProjectStatus = Literal["active", "archived"]


class ProjectCreate(ApiModel):
    """Creates a live-mode project and its brand kit. Demo projects use POST /projects/demo."""

    name: Name
    description: MediumText | None = None
    objective: ShortText | None = None
    brand_name: Name
    brand_description: MediumText | None = None
    brand_voice: VoiceList = []
    target_audience: ShortText | None = None
    preferred_terms: TermList = []
    prohibited_terms: TermList = []
    protected_terms: TermList = Field(
        default=[], description="Terms that must stay verbatim in adaptations when present in the source."
    )
    target_markets: MarketList = []


class ProjectUpdate(ApiModel):
    """Partial update: omitted fields stay unchanged. Mode and ownership never change."""

    name: Name | None = None
    description: MediumText | None = None
    objective: ShortText | None = None
    brand_name: Name | None = None
    brand_description: MediumText | None = None
    brand_voice: VoiceList | None = None
    target_audience: ShortText | None = None
    preferred_terms: TermList | None = None
    prohibited_terms: TermList | None = None
    protected_terms: TermList | None = None
    target_markets: MarketList | None = None


class BrandExample(ApiModel):
    text: Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=1000)]
    note: ShortText | None = None


class BrandUpdate(ApiModel):
    """Brand Memory, replaced as a whole. Only people write it; model output never becomes a preference."""

    name: Name
    description: MediumText | None = None
    positioning: MediumText | None = None
    voice: VoiceList = []
    communication_style: MediumText | None = None
    target_audience: ShortText | None = None
    audience_preferences: MediumText | None = None
    preferred_terms: TermList = []
    prohibited_terms: TermList = []
    protected_terms: TermList = []
    approved_examples: Annotated[list[BrandExample], Field(max_length=20)] = []
    constraints: Annotated[list[ShortText], Field(max_length=20)] = Field(
        default=[], description="Explicit user rules applied to Cultural DNA, Voice, Arena, Risk Radar, and markets."
    )


class Brand(ApiModel):
    id: UUID
    name: str
    description: str | None
    positioning: str | None = None
    voice: list[str]
    communication_style: str | None = None
    target_audience: str | None
    audience_preferences: str | None = None
    preferred_terms: list[str]
    prohibited_terms: list[str]
    protected_terms: list[str]
    approved_examples: list[BrandExample] = []
    constraints: list[str] = []
    updated_at: datetime


class Project(ApiModel):
    id: UUID
    name: str
    description: str | None
    objective: str | None
    mode: DataMode = Field(description="Fixed at creation. Demo projects run on labeled fixtures only.")
    status: ProjectStatus
    brand: Brand
    target_markets: list[Market]
    created_at: datetime
    updated_at: datetime


class ProjectSummary(ApiModel):
    id: UUID
    name: str
    description: str | None
    mode: DataMode
    status: ProjectStatus
    brand_name: str
    target_markets: list[Market]
    last_activity_at: datetime | None
    created_at: datetime
    updated_at: datetime


class ProjectPage(Page[ProjectSummary]):
    pass
