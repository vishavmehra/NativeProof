from typing import Annotated, Literal
from uuid import UUID

from pydantic import Field, StringConstraints, model_validator

from app.schemas.common import ApiModel, ConfidenceLabel, Market, RunMetadata, Term
from app.schemas.evidence import EntityRef, EvidenceRecord, SourceAttribute
from app.schemas.runs import RunStatus

MatchStatus = Literal["resolved", "ambiguous", "unresolved"]


class DiscoveryOptions(ApiModel):
    max_references: int = Field(default=10, ge=1, le=20)
    include_related_interests: bool = True


class ConfirmedReference(ApiModel):
    """The person's choice among ambiguous candidates; the resolver uses it instead of guessing (README §14.2)."""

    term: Term = Field(description="Must also appear in reference_terms.")
    ref_id: Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=200)]
    ref_kind: Literal["tag", "entity"]


class DiscoveryCreate(ApiModel):
    campaign_id: UUID | None = None
    product_category: Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=200)]
    market: Market
    research_question: Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=500)]
    reference_terms: Annotated[list[Term], Field(max_length=10)] = []
    confirmed_references: Annotated[list[ConfirmedReference], Field(max_length=10)] = []
    discovery_options: DiscoveryOptions = DiscoveryOptions()

    @model_validator(mode="after")
    def _confirmed_terms_requested(self) -> "DiscoveryCreate":
        missing = {c.term.casefold() for c in self.confirmed_references} - {t.casefold() for t in self.reference_terms}
        if missing:
            raise ValueError("Every confirmed reference must name a term listed in reference_terms.")
        return self


class CulturalReference(ApiModel):
    """One looked-up concept. Ambiguous candidates are shown, never used downstream."""

    id: str = Field(description="Stable within this result, e.g. ref-1.")
    query_term: str
    match_status: MatchStatus
    name: str | None
    entity_id: str | None
    entity_type: str | None
    candidates: list[EntityRef]
    attributes: list[SourceAttribute]
    relevance_explanation: str | None = Field(description="Model interpretation of why this may matter.")
    evidence_ids: list[UUID]
    limitations: list[str]


class BriefFinding(ApiModel):
    id: str
    title: str
    explanation: str
    claim_type: Literal["observed", "interpreted", "hypothesis"]
    evidence_ids: list[UUID]
    confidence_label: ConfidenceLabel
    validation_question: str | None


class MarketBrief(ApiModel):
    summary: str
    observations: list[BriefFinding]
    opportunities: list[BriefFinding]
    risks: list[BriefFinding]
    validation_questions: list[str]
    limitations: list[str]


class DiscoveryResult(ApiModel):
    run_id: UUID
    status: RunStatus
    project_id: UUID
    campaign_id: UUID | None
    market: Market
    product_category: str
    research_question: str
    reference_terms: list[str]
    references: list[CulturalReference]
    market_brief: MarketBrief | None = Field(description="Null when the run failed before the brief was generated.")
    evidence: list[EvidenceRecord] = Field(description="Every evidence record referenced in this result.")
    limitations: list[str]
    run_metadata: RunMetadata
