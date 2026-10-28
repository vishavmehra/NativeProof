"""Qloo result cache: canonical hashing, keys, per-workflow TTLs, and the store protocol.

The service enforces expiry; a store only saves and returns entries. D provides the
database-backed store; InMemoryQlooCache serves tests and local runs.
"""

import hashlib
import json
from datetime import datetime, timedelta
from typing import Any, Protocol

from pydantic import BaseModel

NORMALIZER_VERSION = "1"

# Tag search reads Qloo's slowly changing ontology; affinity results move faster.
CACHE_TTL: dict[str, timedelta] = {
    "find_tags": timedelta(days=7),
    "search_entities": timedelta(days=7),
    "audience_demographics": timedelta(days=7),
    "recommend": timedelta(hours=24),
    "trends": timedelta(hours=24),
}


def canonical_json(value: Any) -> str:
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False)


def sha256_hex(value: Any) -> str:
    return hashlib.sha256(canonical_json(value).encode("utf-8")).hexdigest()


def cache_key(workflow: str, request: dict[str, Any]) -> str:
    """Workflow, canonical request, and normalizer version. Requests never hold secrets."""
    return sha256_hex({"workflow": workflow, "request": request, "normalizer_version": NORMALIZER_VERSION})


class CachedEntry(BaseModel):
    key: str
    workflow: str
    request_hash: str
    response: dict[str, Any]  # the validated harness result envelope, as JSON
    response_hash: str
    retrieved_at: datetime
    expires_at: datetime


class QlooCacheStore(Protocol):
    async def get(self, key: str) -> CachedEntry | None: ...

    async def put(self, entry: CachedEntry) -> None: ...


class InMemoryQlooCache:
    def __init__(self) -> None:
        self.entries: dict[str, CachedEntry] = {}

    async def get(self, key: str) -> CachedEntry | None:
        return self.entries.get(key)

    async def put(self, entry: CachedEntry) -> None:
        self.entries[entry.key] = entry
