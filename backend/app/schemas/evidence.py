from datetime import datetime
from typing import Literal
from uuid import UUID

from pydantic import Field

from app.schemas.common import ApiModel, Page

EvidenceType = Literal[
    "qloo_source",
    "provider_result",
    "model_interpretation",
    "deterministic_calculation",
    "synthetic_response",
    "observed_outcome",
    "user_input",
]
ClaimType = Literal["observed", "derived", "interpreted", "hypothesis", "synthetic", "external_observation"]
RetrievalMode = Literal["live", "cached", "fixture", "generated", "user_input"]


class EntityRef(ApiModel):
    entity_id: str | None = Field(description="Provider identifier; null when the source returned none.")
    name: str
    entity_type: str | None


class SourceAttribute(ApiModel):
    """A returned value shown with its source meaning, never rescaled or relabeled."""

    key: str
    label: str
    value: str | float | int | bool | None
    description: str | None = Field(description="What the source value means, e.g. its scale and caveats.")


class EvidenceProvenance(ApiModel):
    request_hash: str | None
    response_hash: str | None
    normalizer_version: str | None
    fixture_origin: Literal["hand_authored", "captured_live"] | None = Field(
        description="Set only for fixture evidence: hand-written, or a sanitized capture of a real response."
    )


class EvidenceRecord(ApiModel):
    id: UUID
    project_id: UUID
    evidence_type: EvidenceType
    claim_type: ClaimType
    title: str
    summary: str
    source_provider: str = Field(description="qloo, nativeproof, fixture, a model provider id, or user.")
    source_workflow: str | None = Field(description="Verified Qloo workflow name, when Qloo-derived.")
    source_reference: str | None
    subject: EntityRef | None
    related_entity: EntityRef | None
    attributes: list[SourceAttribute]
    method: str
    retrieval_mode: RetrievalMode
    is_live_data: bool = Field(description="True only for live or cached provider data in a live-mode project.")
    source_run_id: UUID | None
    retrieved_at: datetime | None
    limitations: list[str]
    provenance: EvidenceProvenance | None
    created_at: datetime


class EvidencePage(Page[EvidenceRecord]):
    pass
