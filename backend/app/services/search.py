"""Project search (contracts/README §13, D-034): semantic retrieval over persisted project content.

Each search first syncs the project's searchable content into the index (evidence, Brand Memory examples,
risk findings, Cultural DNA items, adaptations). Content hashing means only new or changed sources are
embedded, and removed sources leave the index. Demo projects and live projects without a configured
embedding model get `status: unavailable`; there is never a lexical stand-in.
"""

import logging
from collections.abc import Sequence
from datetime import datetime
from uuid import UUID

from pydantic import ValidationError
from sqlalchemy import delete, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import get_settings
from app.db import models as m
from app.db.base import utcnow
from app.db.session import session
from app.retrieval import IndexedChunk, RetrievalService, SearchDocument, get_retrieval_service
from app.retrieval.service import (
    adaptation_document,
    brand_example_documents,
    evidence_document,
    profile_item_document,
    risk_finding_document,
)
from app.schemas.graph import GraphRef
from app.schemas.profiles import ProfileItem
from app.schemas.risk import RiskFinding
from app.schemas.search import SearchKind, SearchResults
from app.services.common import get_project
from app.services.projects import to_brand
from app.services.results import to_adaptations, to_evidence

log = logging.getLogger(__name__)


class DbRetrievalStore:
    """RetrievalStore over the `embeddings` table. One row per chunk: `source_id` is `<source>#<chunk>`,
    chunk metadata lives in `metadata`. A chunk not yet embedded has an empty model and vector."""

    async def replace_source(self, project_id: UUID, kind: SearchKind, source_id: str, chunks: list[IndexedChunk]) -> None:
        now = utcnow()
        try:
            async with session() as s, s.begin():
                await s.execute(delete(m.Embedding).where(
                    m.Embedding.project_id == project_id, m.Embedding.source_kind == kind,
                    m.Embedding.source_id.in_(await _row_ids(s, project_id, kind, source_id)),
                ))
                for chunk in chunks:
                    model, dims, config = _space_parts(chunk.space)
                    s.add(m.Embedding(
                        project_id=project_id, source_kind=kind, source_id=f"{source_id}#{chunk.chunk_index}",
                        text=chunk.text, model=model, dims=dims, config_version=config, vector=chunk.vector or [],
                        meta={
                            "source_id": source_id, "chunk_index": chunk.chunk_index, "title": chunk.title,
                            "content_hash": chunk.content_hash, "ref": chunk.ref.model_dump(),
                            "evidence_type": chunk.evidence_type, "claim_type": chunk.claim_type,
                            "retrieval_mode": chunk.retrieval_mode, "space": chunk.space,
                            "created_at": chunk.created_at.isoformat() if chunk.created_at else None,
                        },
                        created_at=now, updated_at=now,
                    ))
        except IntegrityError:
            log.info("concurrent index write for one source; keeping the stored copy")

    async def list_chunks(self, project_id: UUID, kinds: Sequence[SearchKind] | None = None) -> list[IndexedChunk]:
        stmt = select(m.Embedding).where(m.Embedding.project_id == project_id)
        if kinds is not None:
            stmt = stmt.where(m.Embedding.source_kind.in_(list(kinds)))
        async with session() as s:
            rows = (await s.execute(stmt)).scalars().all()
        chunks = []
        for row in rows:
            meta = row.meta or {}
            created = meta.get("created_at")
            chunks.append(IndexedChunk(
                project_id=row.project_id, kind=row.source_kind, source_id=meta["source_id"],  # type: ignore[arg-type]
                chunk_index=meta["chunk_index"], title=meta["title"], text=row.text, content_hash=meta["content_hash"],
                ref=GraphRef(**meta["ref"]), evidence_type=meta.get("evidence_type"), claim_type=meta.get("claim_type"),
                retrieval_mode=meta.get("retrieval_mode"), created_at=datetime.fromisoformat(created) if created else None,
                space=meta.get("space"), vector=list(row.vector) if row.vector else None,
            ))
        return chunks


async def _row_ids(s: AsyncSession, project_id: UUID, kind: str, source_id: str) -> list[str]:
    stmt = select(m.Embedding.source_id, m.Embedding.meta).where(
        m.Embedding.project_id == project_id, m.Embedding.source_kind == kind
    )
    return [row_id for row_id, meta in (await s.execute(stmt)).all() if (meta or {}).get("source_id") == source_id]


def _space_parts(space: str | None) -> tuple[str, int, str]:
    """(model, dims, config_version) columns from an EmbeddingSpace key; empty for chunks not yet embedded."""
    if not space:
        return "", 0, ""
    provider_and_model, dims, config = space.rsplit(":", 2)
    return provider_and_model.split(":", 1)[1], int(dims), config


async def project_documents(s: AsyncSession, project_id: UUID) -> list[SearchDocument]:
    """Every searchable source currently persisted for the project."""
    documents: list[SearchDocument] = []
    evidence = (await s.execute(select(m.EvidenceRecord).where(m.EvidenceRecord.project_id == project_id))).scalars()
    documents += [evidence_document(to_evidence(row)) for row in evidence]
    brand = (await s.execute(select(m.BrandKit).where(m.BrandKit.project_id == project_id))).scalar_one_or_none()
    if brand is not None:
        documents += brand_example_documents(project_id, to_brand(brand))
    adaptations = list((await s.execute(select(m.Adaptation).where(m.Adaptation.project_id == project_id))).scalars())
    documents += [adaptation_document(adaptation) for adaptation in await to_adaptations(s, adaptations)]
    for row in (await s.execute(select(m.RiskFinding).where(m.RiskFinding.project_id == project_id))).scalars():
        try:
            finding = RiskFinding.model_validate({**row.payload, "id": row.id, "status": row.status,
                                                  "status_note": row.status_note, "updated_at": row.updated_at})
        except ValidationError:
            log.warning("risk finding %s not indexed: payload does not match the schema", row.id)
            continue
        documents.append(risk_finding_document(row.scan_id, finding, row.created_at))
    for profile in (await s.execute(select(m.CulturalProfile).where(m.CulturalProfile.project_id == project_id))).scalars():
        for item in (profile.result or {}).get("items", []):
            try:
                documents.append(profile_item_document(profile.id, ProfileItem.model_validate(item), profile.created_at))
            except ValidationError:
                log.warning("profile item in %s not indexed: does not match the schema", profile.id)
    return documents


async def sync_index(service: RetrievalService, store: DbRetrievalStore, project_id: UUID,
                     documents: list[SearchDocument]) -> None:
    await service.index_documents(project_id, documents)
    present = {(document.kind, document.source_id) for document in documents}
    stale = {(c.kind, c.source_id) for c in await store.list_chunks(project_id)} - present
    for kind, source_id in stale:
        await service.remove(project_id, kind, source_id)  # type: ignore[arg-type]


async def search(
    user_id: UUID, project_id: UUID, q: str, kinds: list[SearchKind] | None, limit: int
) -> SearchResults:
    store = DbRetrievalStore()
    async with session() as s:
        project = await get_project(s, user_id, project_id)
        documents = await project_documents(s, project_id) if project.mode == "live" else []
    service = get_retrieval_service("live" if project.mode == "live" else "demo", get_settings(), store)
    if service.is_configured():
        await sync_index(service, store, project_id, documents)
    return await service.search(project_id, q, kinds, limit)
