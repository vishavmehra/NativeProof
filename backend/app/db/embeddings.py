"""Embedding storage for retrieval (D-034). The retrieval module computes vectors; this module only stores them.

Vectors are compared only within one (model, dims, config_version) space, so every read is scoped to it.
"""

from dataclasses import dataclass, field
from uuid import UUID

from sqlalchemy import delete, select

from app.db import models as m
from app.db.base import utcnow
from app.db.session import read_session, session


@dataclass(frozen=True)
class EmbeddingInput:
    project_id: UUID
    source_kind: str  # evidence | brand_example | risk_finding | profile_item | adaptation
    source_id: str
    text: str
    model: str
    dims: int
    config_version: str
    vector: list[float]
    metadata: dict = field(default_factory=dict)


async def upsert_embeddings(items: list[EmbeddingInput]) -> None:
    """Insert or replace by (project, source_kind, source_id, model, config_version)."""
    if not items:
        return
    async with session() as s, s.begin():
        for item in items:
            if len(item.vector) != item.dims:
                raise ValueError(f"Vector length {len(item.vector)} does not match dims {item.dims}.")
            row = (
                await s.execute(
                    select(m.Embedding).where(
                        m.Embedding.project_id == item.project_id, m.Embedding.source_kind == item.source_kind,
                        m.Embedding.source_id == item.source_id, m.Embedding.model == item.model,
                        m.Embedding.config_version == item.config_version,
                    )
                )
            ).scalar_one_or_none()
            if row is None:
                s.add(m.Embedding(project_id=item.project_id, source_kind=item.source_kind, source_id=item.source_id,
                                  text=item.text, meta=item.metadata, model=item.model, dims=item.dims,
                                  config_version=item.config_version, vector=item.vector))
            else:
                row.text, row.meta, row.dims, row.vector, row.updated_at = (
                    item.text, item.metadata, item.dims, item.vector, utcnow()
                )


async def embeddings_in_space(
    project_id: UUID, *, model: str, dims: int, config_version: str, kinds: list[str] | None = None
) -> list[m.Embedding]:
    """Every stored embedding of one project in exactly one embedding space."""
    stmt = select(m.Embedding).where(
        m.Embedding.project_id == project_id, m.Embedding.model == model, m.Embedding.dims == dims,
        m.Embedding.config_version == config_version,
    )
    if kinds:
        stmt = stmt.where(m.Embedding.source_kind.in_(kinds))
    async with read_session() as s:
        return list((await s.execute(stmt)).scalars())


async def delete_embeddings(project_id: UUID, source_kind: str, source_id: str) -> int:
    async with session() as s, s.begin():
        result = await s.execute(
            delete(m.Embedding).where(
                m.Embedding.project_id == project_id, m.Embedding.source_kind == source_kind,
                m.Embedding.source_id == source_id,
            )
        )
    return result.rowcount  # type: ignore[attr-defined]
