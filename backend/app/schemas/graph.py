"""Evidence Graph: nodes and edges built only from persisted links."""

from datetime import datetime
from typing import Literal
from uuid import UUID

from pydantic import Field

from app.schemas.common import ApiModel, ConfidenceLabel
from app.schemas.evidence import ClaimType, EvidenceType, RetrievalMode

GraphNodeKind = Literal[
    "campaign",
    "content_version",
    "source_signal",
    "evidence",
    "interpretation",
    "hypothesis",
    "synthetic_result",
    "risk_finding",
    "recommendation",
    "adaptation",
    "evaluation",
    "cultural_profile",
    "arena",
    "market_comparison",
    "report",
    "run",
    "population",
    "audience_group",
    "interview_theme",
    "social_simulation",
]
GraphRelation = Literal[
    "supports", "derived_from", "generated_by", "evaluates", "recommends", "flags", "variant_of", "references", "produced",
    "informs", "reacted_to", "motivates",
]


class GraphRef(ApiModel):
    resource: str
    id: str
    url: str | None = Field(description="API path of the underlying resource, when it has one.")


class GraphNode(ApiModel):
    id: str
    kind: GraphNodeKind
    label: str
    evidence_type: EvidenceType | None
    claim_type: ClaimType | None
    retrieval_mode: RetrievalMode | None
    is_demo: bool
    confidence_label: ConfidenceLabel | None
    created_at: datetime | None
    limitations: list[str]
    ref: GraphRef


class GraphEdge(ApiModel):
    id: str
    source: str
    target: str
    relation: GraphRelation
    provenance: str = Field(description="The persisted field that establishes this link, e.g. finding.evidence_ids.")


class EvidenceGraph(ApiModel):
    """A link that is not persisted is never inferred or drawn."""

    project_id: UUID
    campaign_id: UUID | None
    nodes: list[GraphNode]
    edges: list[GraphEdge]
    truncated: bool
    limitations: list[str]
    generated_at: datetime
