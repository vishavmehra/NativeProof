"""Semantic search over project evidence, Brand Memory examples, and results."""

from datetime import datetime
from typing import Literal

from pydantic import Field

from app.schemas.common import ApiModel
from app.schemas.evidence import ClaimType, EvidenceType, RetrievalMode
from app.schemas.graph import GraphRef

SearchKind = Literal["evidence", "brand_example", "risk_finding", "profile_item", "adaptation"]


class SearchHit(ApiModel):
    id: str
    kind: SearchKind
    title: str
    snippet: str
    similarity: float = Field(description="Cosine similarity of embeddings; a ranking signal, not a probability.")
    ref: GraphRef
    evidence_type: EvidenceType | None
    claim_type: ClaimType | None
    retrieval_mode: RetrievalMode | None
    created_at: datetime | None


class SearchResults(ApiModel):
    query: str
    status: Literal["ok", "unavailable"]
    message: str | None = Field(description="Why search is unavailable, e.g. no embedding model configured.")
    embedding_model: str | None
    hits: list[SearchHit]
