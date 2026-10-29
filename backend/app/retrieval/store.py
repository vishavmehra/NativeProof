"""Indexed chunks and the store protocol (D-034: embeddings live in the application database).

D supplies the database repository; InMemoryRetrievalStore serves tests and the evaluation.
A chunk keeps its text, so it can be re-embedded when the embedding space changes.
"""

from collections.abc import Sequence
from datetime import datetime
from typing import Protocol
from uuid import UUID

from pydantic import BaseModel

from app.schemas.evidence import ClaimType, EvidenceType, RetrievalMode
from app.schemas.graph import GraphRef
from app.schemas.search import SearchKind


class IndexedChunk(BaseModel):
    project_id: UUID
    kind: SearchKind
    source_id: str
    chunk_index: int
    title: str
    text: str
    content_hash: str  # sha256 of the source's kind, title, and full text
    ref: GraphRef
    evidence_type: EvidenceType | None = None
    claim_type: ClaimType | None = None
    retrieval_mode: RetrievalMode | None = None
    created_at: datetime | None = None
    # Null until embedded. `space` is EmbeddingSpace.key: provider, model, dimensions, config version.
    space: str | None = None
    vector: list[float] | None = None


class RetrievalStore(Protocol):
    async def replace_source(self, project_id: UUID, kind: SearchKind, source_id: str, chunks: list[IndexedChunk]) -> None:
        """Replace every chunk of one source; an empty list deletes the source."""

    async def list_chunks(
        self, project_id: UUID, kinds: Sequence[SearchKind] | None = None, *, vectors: bool = True
    ) -> list[IndexedChunk]:
        """All chunks of a project, optionally only the given kinds. With `vectors=False` every chunk's vector is
        None but its `space` is kept, for callers that only compare hashes or spaces."""


class InMemoryRetrievalStore:
    def __init__(self) -> None:
        self.sources: dict[tuple[UUID, str, str], list[IndexedChunk]] = {}

    async def replace_source(self, project_id: UUID, kind: SearchKind, source_id: str, chunks: list[IndexedChunk]) -> None:
        if chunks:
            self.sources[(project_id, kind, source_id)] = list(chunks)
        else:
            self.sources.pop((project_id, kind, source_id), None)

    async def list_chunks(
        self, project_id: UUID, kinds: Sequence[SearchKind] | None = None, *, vectors: bool = True
    ) -> list[IndexedChunk]:
        return [
            chunk if vectors else chunk.model_copy(update={"vector": None})
            for (project, kind, _), chunks in self.sources.items()
            if project == project_id and (kinds is None or kind in kinds)
            for chunk in chunks
        ]
