"""Semantic retrieval. Public interface: get_retrieval_service, RetrievalService, the store protocol."""

from app.retrieval.service import (
    IndexReport,
    RetrievalService,
    SearchDocument,
    chunk_text,
    cosine,
    get_retrieval_service,
)
from app.retrieval.store import IndexedChunk, InMemoryRetrievalStore, RetrievalStore

__all__ = [
    "InMemoryRetrievalStore",
    "IndexReport",
    "IndexedChunk",
    "RetrievalService",
    "RetrievalStore",
    "SearchDocument",
    "chunk_text",
    "cosine",
    "get_retrieval_service",
]
