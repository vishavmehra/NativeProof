from datetime import datetime
from typing import Annotated, Literal
from uuid import UUID

from pydantic import Field, StringConstraints, model_validator

from app.schemas.common import ApiModel, Market, MarketList, Name, Page, ShortText, Term

CampaignType = Literal["advertisement", "landing_page", "product_description", "slogan", "social_post"]
Weight = Annotated[float, Field(ge=0, le=1)]


class CampaignContent(ApiModel):
    headline: Annotated[str, StringConstraints(strip_whitespace=True, max_length=300)] | None = None
    body: Annotated[str, StringConstraints(strip_whitespace=True, max_length=5000)] | None = None
    call_to_action: Annotated[str, StringConstraints(strip_whitespace=True, max_length=200)] | None = None
    reference_terms: Annotated[list[Term], Field(max_length=20)] = []

    @model_validator(mode="after")
    def _require_copy(self) -> "CampaignContent":
        if not (self.headline or self.body):
            raise ValueError("Provide at least a headline or a body.")
        return self


class EvaluationCriteria(ApiModel):
    """Importance weights. They must sum to 1.0 (within 0.001); invalid weights are rejected, never normalized."""

    clarity: Weight
    brand_fidelity: Weight
    cultural_relevance: Weight
    cultural_risk: Weight

    @model_validator(mode="after")
    def _weights_sum_to_one(self) -> "EvaluationCriteria":
        total = self.clarity + self.brand_fidelity + self.cultural_relevance + self.cultural_risk
        if abs(total - 1.0) > 0.001:
            raise ValueError(f"Weights must sum to 1.0; got {total:.3f}.")
        return self


DEFAULT_EVALUATION_CRITERIA = EvaluationCriteria(
    clarity=0.3, brand_fidelity=0.25, cultural_relevance=0.3, cultural_risk=0.15
)


class CampaignCreate(ApiModel):
    name: Name
    campaign_type: CampaignType
    original_content: CampaignContent
    objective: ShortText | None = None
    target_markets: MarketList = []
    evaluation_criteria: EvaluationCriteria = DEFAULT_EVALUATION_CRITERIA


class CampaignUpdate(ApiModel):
    """Partial update. A changed original_content creates a new content version; earlier versions stay intact.

    Demo campaigns reject content changes with 409 CONFLICT, because their fixtures match the seeded copy.
    """

    name: Name | None = None
    objective: ShortText | None = None
    target_markets: MarketList | None = None
    evaluation_criteria: EvaluationCriteria | None = None
    original_content: CampaignContent | None = None


class ContentVersion(ApiModel):
    id: UUID
    campaign_id: UUID
    version_number: int = Field(ge=1)
    content: CampaignContent
    created_at: datetime


class Campaign(ApiModel):
    id: UUID
    project_id: UUID
    name: str
    campaign_type: CampaignType
    objective: str | None
    target_markets: list[Market]
    evaluation_criteria: EvaluationCriteria
    current_version: ContentVersion
    versions: list[ContentVersion] = Field(description="Every content version, newest first.")
    created_at: datetime
    updated_at: datetime


class CampaignPage(Page[Campaign]):
    pass
