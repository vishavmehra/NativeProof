"""Semantic retrieval over a project's content (contracts/README §13, D-034).

Index: each source (evidence record, brand example, risk finding, profile item, adaptation) becomes
whitespace-normalized chunks with their provenance (GraphRef, evidence and claim types, retrieval
mode). Chunks are stored even when no embedding model is configured or the provider fails; they are
embedded later. Search: chunks embedded in another space (provider, model, dimensions, config
version) are re-embedded first, so spaces never mix; then cosine similarity ranks one hit per
source. Without a configured embedding model the result is `unavailable`; there is no lexical
stand-in. Similarity is a ranking signal, not a probability.
"""

import hashlib
import logging
import math
import re
from collections.abc import Sequence
from dataclasses import dataclass
from datetime import datetime
from typing import Literal
from uuid import UUID

from pydantic import BaseModel

from app.core.config import Settings
from app.llm.embeddings import EmbeddingClient
from app.llm.gateway import LLMError, LLMGateway
from app.retrieval.store import IndexedChunk, RetrievalStore
from app.schemas.adaptations import Adaptation
from app.schemas.evidence import ClaimType, EvidenceRecord, EvidenceType, RetrievalMode
from app.schemas.graph import GraphRef
from app.schemas.profiles import ProfileItem
from app.schemas.projects import Brand
from app.schemas.risk import RiskFinding
from app.schemas.search import SearchHit, SearchKind, SearchResults

log = logging.getLogger(__name__)

API = "/api/v1"
MAX_CHUNK_CHARS = 1200
SNIPPET_CHARS = 240
MAX_LIMIT = 50
# Measured floor per (model, config version): below it a hit is dropped. Qwen3-Embedding-8B with emb-v1
# (2026-10-26 evaluation): relevant hits in the top 5 never scored below 0.372, no-answer queries peaked at
# 0.275. Provisional (2 no-answer probes); models without a measured floor return unfiltered top-k.
MIN_SIMILARITY: dict[tuple[str, str], float] = {("Qwen/Qwen3-Embedding-8B", "emb-v1"): 0.33}
NOT_CONFIGURED = "Semantic search is unavailable: no embedding model is configured."
DEMO_UNAVAILABLE = "Search is not available in demo projects."
_SENTENCE_END = re.compile(r"(?<=[.!?。！？])\s+")


class SearchDocument(BaseModel):
    """One searchable source. `text` is embedded under its title."""

    kind: SearchKind
    source_id: str
    title: str
    text: str
    ref: GraphRef
    evidence_type: EvidenceType | None = None
    claim_type: ClaimType | None = None
    retrieval_mode: RetrievalMode | None = None
    created_at: datetime | None = None


@dataclass(frozen=True)
class IndexReport:
    stored: int  # sources written (new or changed)
    unchanged: int  # sources skipped because their content hash matched
    embedded: bool  # False: chunks were stored and will be embedded before the next search


def chunk_text(text: str, max_chars: int = MAX_CHUNK_CHARS) -> list[str]:
    """Pack whole sentences into chunks of at most `max_chars`; overlong sentences are split."""
    # no overlap between chunks; add a one-sentence overlap if long sources start missing hits.
    cleaned = " ".join(text.split())
    if len(cleaned) <= max_chars:
        return [cleaned] if cleaned else []
    chunks: list[str] = []
    current = ""
    for sentence in _SENTENCE_END.split(cleaned):
        for start in range(0, len(sentence), max_chars):
            piece = sentence[start : start + max_chars]
            if current and len(current) + 1 + len(piece) > max_chars:
                chunks.append(current)
                current = piece
            else:
                current = f"{current} {piece}" if current else piece
    if current:
        chunks.append(current)
    return chunks


def cosine(a: Sequence[float], b: Sequence[float]) -> float:
    # pure-Python scan of every chunk in the project; move to pgvector when projects get large.
    dot = sum(x * y for x, y in zip(a, b, strict=True))
    norm = math.sqrt(sum(x * x for x in a)) * math.sqrt(sum(y * y for y in b))
    return dot / norm if norm else 0.0


def rank_chunks(
    query_vector: Sequence[float], chunks: Sequence[IndexedChunk], space_key: str, limit: int
) -> list[tuple[float, IndexedChunk]]:
    """Best-scoring chunk per source, highest first. Chunks from other spaces are never scored."""
    best: dict[tuple[str, str], tuple[float, IndexedChunk]] = {}
    for chunk in chunks:
        if chunk.vector is None or chunk.space != space_key:
            continue
        score = cosine(query_vector, chunk.vector)
        key = (chunk.kind, chunk.source_id)
        if key not in best or score > best[key][0]:
            best[key] = (score, chunk)
    return sorted(best.values(), key=lambda pair: (-pair[0], pair[1].title))[:limit]


def _digest(document: SearchDocument) -> str:
    return hashlib.sha256(f"{document.kind}\n{document.title}\n{document.text}".encode()).hexdigest()


def _embedding_input(chunk: IndexedChunk) -> str:
    return f"{chunk.title}\n{chunk.text}"


# --- Documents for each searchable resource ---


def evidence_document(record: EvidenceRecord) -> SearchDocument:
    return SearchDocument(
        kind="evidence", source_id=str(record.id), title=record.title, text=record.summary,
        ref=GraphRef(resource="evidence", id=str(record.id), url=f"{API}/evidence/{record.id}"),
        evidence_type=record.evidence_type, claim_type=record.claim_type, retrieval_mode=record.retrieval_mode,
        created_at=record.created_at,
    )


def brand_example_documents(project_id: UUID, brand: Brand) -> list[SearchDocument]:
    ref = GraphRef(resource="brand", id=str(brand.id), url=f"{API}/projects/{project_id}/brand")
    return [
        SearchDocument(
            kind="brand_example",
            source_id=f"{brand.id}:example:{hashlib.sha256(example.text.encode()).hexdigest()[:16]}",
            title="Approved brand example", text=f"{example.text} ({example.note})" if example.note else example.text,
            ref=ref, evidence_type="user_input", retrieval_mode="user_input", created_at=brand.updated_at,
        )
        for example in brand.approved_examples
    ]


def risk_finding_document(scan_id: UUID, finding: RiskFinding, created_at: datetime | None = None) -> SearchDocument:
    deterministic = finding.source == "deterministic_check"
    text = f"Observation: {finding.observation} Interpretation: {finding.interpretation}"
    if finding.suggested_alternative:
        text += f" Suggested alternative: {finding.suggested_alternative}"
    return SearchDocument(
        kind="risk_finding", source_id=str(finding.id),
        title=f"{finding.category.replace('_', ' ').capitalize()} risk ({finding.severity})", text=text,
        ref=GraphRef(resource="risk_finding", id=str(finding.id), url=f"{API}/risk-scans/{scan_id}"),
        evidence_type="deterministic_calculation" if deterministic else "model_interpretation",
        claim_type="derived" if deterministic else "interpreted", retrieval_mode="generated", created_at=created_at,
    )


def profile_item_document(profile_id: UUID, item: ProfileItem, created_at: datetime | None = None) -> SearchDocument:
    return SearchDocument(
        kind="profile_item", source_id=f"{profile_id}:{item.id}", title=item.title, text=item.explanation,
        ref=GraphRef(resource="cultural_profile", id=str(profile_id), url=f"{API}/cultural-profiles/{profile_id}"),
        evidence_type="model_interpretation", claim_type=item.claim_type, retrieval_mode="generated",
        created_at=created_at,
    )


def adaptation_document(adaptation: Adaptation) -> SearchDocument:
    content = adaptation.content
    copy = " ".join(part for part in (content.headline, content.body, content.call_to_action) if part)
    user_edit = adaptation.origin == "user_edit"
    return SearchDocument(
        kind="adaptation", source_id=str(adaptation.id),
        title=f"{adaptation.label} ({adaptation.market.display_name})", text=f"{adaptation.strategy} {copy}",
        ref=GraphRef(resource="adaptation", id=str(adaptation.id), url=f"{API}/adaptations/{adaptation.id}"),
        evidence_type="user_input" if user_edit else "model_interpretation",
        claim_type=None if user_edit else "interpreted",
        retrieval_mode="user_input" if user_edit else "generated", created_at=adaptation.created_at,
    )


class RetrievalService:
    def __init__(
        self, embedder: EmbeddingClient | None, store: RetrievalStore, *, unavailable_message: str | None = None
    ) -> None:
        self._embedder = embedder
        self._store = store
        self._unavailable = unavailable_message  # set for demo projects: no indexing, search unavailable

    def is_configured(self) -> bool:
        return self._unavailable is None and self._embedder is not None and self._embedder.is_configured()

    # --- Indexing ---

    async def index_documents(self, project_id: UUID, documents: Sequence[SearchDocument]) -> IndexReport:
        if self._unavailable is not None or not documents:
            return IndexReport(stored=0, unchanged=0, embedded=False)
        kinds = sorted({document.kind for document in documents})
        stored = await self._store.list_chunks(project_id, kinds, vectors=False)
        stored_hashes = {(c.kind, c.source_id): c.content_hash for c in stored}
        changed: list[tuple[SearchDocument, list[IndexedChunk]]] = []
        for document in documents:
            digest = _digest(document)
            if stored_hashes.get((document.kind, document.source_id)) == digest:
                continue
            chunks = [
                IndexedChunk(
                    project_id=project_id, kind=document.kind, source_id=document.source_id, chunk_index=index,
                    title=document.title, text=piece, content_hash=digest, ref=document.ref,
                    evidence_type=document.evidence_type, claim_type=document.claim_type,
                    retrieval_mode=document.retrieval_mode, created_at=document.created_at,
                )
                for index, piece in enumerate(chunk_text(document.text) or [document.title])
            ]
            changed.append((document, chunks))
        pending = [chunk for _, chunks in changed for chunk in chunks]
        embedded = await self._embed(pending)
        by_position = iter(embedded)
        for document, chunks in changed:
            await self._store.replace_source(project_id, document.kind, document.source_id,
                                             [next(by_position) for _ in chunks])
        return IndexReport(
            stored=len(changed), unchanged=len(documents) - len(changed),
            embedded=all(chunk.vector is not None for chunk in embedded),
        )

    async def index_evidence(self, project_id: UUID, records: Sequence[EvidenceRecord]) -> IndexReport:
        return await self.index_documents(project_id, [evidence_document(record) for record in records])

    async def index_brand_examples(self, project_id: UUID, brand: Brand) -> IndexReport:
        """Brand Memory is replaced as a whole, so examples no longer present are removed."""
        documents = brand_example_documents(project_id, brand)
        if self._unavailable is None:
            current = {document.source_id for document in documents}
            for chunk in await self._store.list_chunks(project_id, ["brand_example"], vectors=False):
                if chunk.source_id not in current:
                    await self._store.replace_source(project_id, "brand_example", chunk.source_id, [])
        return await self.index_documents(project_id, documents)

    async def index_risk_findings(
        self, project_id: UUID, scan_id: UUID, findings: Sequence[RiskFinding], created_at: datetime | None = None
    ) -> IndexReport:
        return await self.index_documents(project_id, [risk_finding_document(scan_id, f, created_at) for f in findings])

    async def index_profile_items(
        self, project_id: UUID, profile_id: UUID, items: Sequence[ProfileItem], created_at: datetime | None = None
    ) -> IndexReport:
        return await self.index_documents(project_id, [profile_item_document(profile_id, i, created_at) for i in items])

    async def index_adaptations(self, project_id: UUID, adaptations: Sequence[Adaptation]) -> IndexReport:
        return await self.index_documents(project_id, [adaptation_document(adaptation) for adaptation in adaptations])

    async def remove(self, project_id: UUID, kind: SearchKind, source_id: str) -> None:
        await self._store.replace_source(project_id, kind, source_id, [])

    async def embed_pending(self, project_id: UUID) -> int:
        """Embed chunks that have no vector or belong to another space. Raises LLMError on provider failure."""
        if not self.is_configured():
            return 0
        assert self._embedder is not None and self._embedder.space is not None
        space = self._embedder.space.key
        # A chunk has a space exactly when it has a vector, so the check never loads the vectors themselves.
        chunks = await self._store.list_chunks(project_id, vectors=False)
        stale_sources = {(c.kind, c.source_id) for c in chunks if c.space != space}
        if not stale_sources:
            return 0
        to_embed = [c for c in chunks if (c.kind, c.source_id) in stale_sources]
        vectors = (await self._embedder.embed([_embedding_input(c) for c in to_embed])).vectors
        updated: dict[tuple[str, str], list[IndexedChunk]] = {}
        for chunk, vector in zip(to_embed, vectors, strict=True):
            updated.setdefault((chunk.kind, chunk.source_id), []).append(
                chunk.model_copy(update={"vector": vector, "space": space})
            )
        for (kind, source_id), source_chunks in updated.items():
            await self._store.replace_source(project_id, kind, source_id, sorted(source_chunks, key=lambda c: c.chunk_index))  # type: ignore[arg-type]
        log.info("retrieval re-embedded %d chunks for %d sources", len(to_embed), len(updated))
        return len(to_embed)

    async def _embed(self, chunks: list[IndexedChunk]) -> list[IndexedChunk]:
        """Chunks with vectors when possible; otherwise unchanged (embedded before the next search)."""
        if not chunks or not self.is_configured():
            return chunks
        assert self._embedder is not None and self._embedder.space is not None
        try:
            embeddings = await self._embedder.embed([_embedding_input(chunk) for chunk in chunks], stage="indexing")
        except LLMError as exc:
            log.warning("retrieval indexing stored %d chunks without vectors: %s", len(chunks), exc.code)
            return chunks
        return [
            chunk.model_copy(update={"vector": vector, "space": embeddings.space.key})
            for chunk, vector in zip(chunks, embeddings.vectors, strict=True)
        ]

    # --- Search ---

    async def search(
        self, project_id: UUID, query: str, kinds: Sequence[SearchKind] | None = None, limit: int = 10
    ) -> SearchResults:
        text = " ".join(query.split())
        if not self.is_configured():
            return SearchResults(query=text, status="unavailable", message=self._unavailable or NOT_CONFIGURED,
                                 embedding_model=None, hits=[])
        assert self._embedder is not None and self._embedder.space is not None
        space = self._embedder.space
        if not text:
            return SearchResults(query=text, status="ok", message=None, embedding_model=space.model, hits=[])
        try:
            await self.embed_pending(project_id)
            query_vector = (await self._embedder.embed([text], kind="query", stage="search")).vectors[0]
        except LLMError as exc:
            return SearchResults(query=text, status="unavailable", message=f"Semantic search is unavailable: {exc.message}",
                                 embedding_model=space.model, hits=[])
        chunks = await self._store.list_chunks(project_id, kinds)
        floor = MIN_SIMILARITY.get((space.model, space.config_version), -1.0)
        ranked = [
            (score, chunk)
            for score, chunk in rank_chunks(query_vector, chunks, space.key, max(1, min(limit, MAX_LIMIT)))
            if score >= floor
        ]
        hits = [
            SearchHit(
                id=chunk.source_id, kind=chunk.kind, title=chunk.title,
                snippet=chunk.text if len(chunk.text) <= SNIPPET_CHARS else chunk.text[: SNIPPET_CHARS - 1] + "…",
                similarity=round(score, 4), ref=chunk.ref, evidence_type=chunk.evidence_type,
                claim_type=chunk.claim_type, retrieval_mode=chunk.retrieval_mode, created_at=chunk.created_at,
            )
            for score, chunk in ranked
        ]
        return SearchResults(query=text, status="ok", message=None, embedding_model=space.model, hits=hits)


def get_retrieval_service(
    mode: Literal["live", "demo"], settings: Settings, store: RetrievalStore, *, http_client: object = None
) -> RetrievalService:
    """Demo projects get an unavailable service (contracts/README §13); live projects embed with EMBEDDING_*."""
    if mode == "demo":
        return RetrievalService(None, store, unavailable_message=DEMO_UNAVAILABLE)
    return RetrievalService(LLMGateway(settings, http_client=http_client).capability("embeddings"), store)
