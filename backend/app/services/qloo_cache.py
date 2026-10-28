"""Database-backed QlooCacheStore (app.integrations.qloo.cache) over the qloo_cache table.

The Qloo service decides freshness and only caches live results; this store saves and returns entries.
"""

from sqlalchemy import select
from sqlalchemy.exc import IntegrityError

from app.db import models as m
from app.db.base import utcnow
from app.db.session import read_session, session
from app.integrations.qloo import CachedEntry


class DbQlooCache:
    async def get(self, key: str) -> CachedEntry | None:
        async with read_session() as s:
            row = (await s.execute(select(m.QlooCacheEntry).where(m.QlooCacheEntry.cache_key == key))).scalar_one_or_none()
        if row is None or row.expires_at is None:
            return None
        return CachedEntry(
            key=row.cache_key, workflow=row.workflow_name, request_hash=row.request_hash, response=row.response_data,
            response_hash=row.response_hash or "", retrieved_at=row.retrieved_at, expires_at=row.expires_at,
        )

    async def put(self, entry: CachedEntry) -> None:
        values = {
            "workflow_name": entry.workflow, "request_hash": entry.request_hash, "response_data": entry.response,
            "response_hash": entry.response_hash, "retrieval_mode": "live", "retrieved_at": entry.retrieved_at,
            "expires_at": entry.expires_at,
        }
        try:
            async with session() as s, s.begin():
                row = (
                    await s.execute(select(m.QlooCacheEntry).where(m.QlooCacheEntry.cache_key == entry.key))
                ).scalar_one_or_none()
                if row is None:
                    s.add(m.QlooCacheEntry(cache_key=entry.key, created_at=utcnow(), **values))
                else:
                    for name, value in values.items():
                        setattr(row, name, value)
        except IntegrityError:
            pass  # a concurrent miss stored the same key first; either copy is valid
