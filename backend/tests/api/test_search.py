"""Project search over HTTP (contracts/README §13). Embeddings come from a deterministic fake; no provider call."""

from typing import Any

import httpx
import pytest
from sqlalchemy import select

from app.db import models as m
from app.db.session import session
from app.llm.embeddings import Embeddings, EmbeddingSpace
from app.retrieval import RetrievalService
from app.retrieval.service import DEMO_UNAVAILABLE, NOT_CONFIGURED
from app.schemas.common import StepTrace
from tests.conftest import BOB

API = "/api/v1"
VOCAB = ["trail", "sunrise", "pack", "light", "mountain", "weather", "escape", "price"]


class FakeEmbedder:
    def __init__(self) -> None:
        self.space = EmbeddingSpace("fake", "fake-embed", len(VOCAB))
        self.texts: list[str] = []

    def is_configured(self) -> bool:
        return True

    async def embed(self, texts: list[str], **kwargs: Any) -> Embeddings:
        self.texts += texts
        vectors = [[float(text.lower().count(word)) for word in VOCAB] for text in texts]
        return Embeddings(vectors=vectors, space=self.space, trace=StepTrace(stage="s", agent="a", status="completed"))


async def live_project(client: httpx.AsyncClient) -> str:
    return (await client.post(f"{API}/projects", json={"name": "P", "brand_name": "Northstar"})).json()["id"]


async def set_examples(client: httpx.AsyncClient, project_id: str, *texts: str) -> None:
    body = {"name": "Northstar", "approved_examples": [{"text": text} for text in texts]}
    response = await client.put(f"{API}/projects/{project_id}/brand", json=body)
    assert response.status_code == 200, response.text


async def test_unavailable_without_embeddings_and_in_demo_projects(client: httpx.AsyncClient) -> None:
    live = await client.get(f"{API}/projects/{await live_project(client)}/search", params={"q": "trail"})
    assert live.status_code == 200
    assert (live.json()["status"], live.json()["message"], live.json()["hits"]) == ("unavailable", NOT_CONFIGURED, [])

    demo = (await client.post(f"{API}/projects/demo")).json()
    result = (await client.get(f"{API}/projects/{demo['id']}/search", params={"q": "trail"})).json()
    assert (result["status"], result["message"], result["embedding_model"]) == ("unavailable", DEMO_UNAVAILABLE, None)


async def test_search_requires_ownership_and_a_query(client: httpx.AsyncClient) -> None:
    project_id = await live_project(client)
    assert (await client.get(f"{API}/projects/{project_id}/search", params={"q": "x"}, headers=BOB)).status_code == 404
    assert (await client.get(f"{API}/projects/{project_id}/search")).status_code == 422


async def test_search_indexes_project_content_once_and_drops_removed_sources(
    client: httpx.AsyncClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    from app.services import search as service

    embedder = FakeEmbedder()
    monkeypatch.setattr(service, "get_retrieval_service", lambda mode, settings, store: RetrievalService(embedder, store))
    project_id = await live_project(client)
    await set_examples(client, project_id, "Built for long trails and people who start before sunrise.",
                       "Layer smart. Pack light.")

    result = (await client.get(f"{API}/projects/{project_id}/search", params={"q": "trail at sunrise"})).json()
    assert result["status"] == "ok" and result["embedding_model"] == "fake-embed"
    top = result["hits"][0]
    assert (top["kind"], top["retrieval_mode"], top["ref"]["resource"]) == ("brand_example", "user_input", "brand")
    assert "sunrise" in top["snippet"] and 0 < top["similarity"] <= 1
    async with session() as s:
        rows = (await s.execute(select(m.Embedding).where(m.Embedding.project_id.is_not(None)))).scalars().all()
    assert {(row.model, row.dims, row.config_version) for row in rows} == {("fake-embed", len(VOCAB), "emb-v1")}

    embedded = len(embedder.texts)
    await client.get(f"{API}/projects/{project_id}/search", params={"q": "pack light"})
    assert len(embedder.texts) == embedded + 1  # only the query; unchanged sources are not re-embedded

    await set_examples(client, project_id, "Layer smart. Pack light.")
    result = (await client.get(f"{API}/projects/{project_id}/search", params={"q": "sunrise trail"})).json()
    assert all("sunrise" not in hit["snippet"] for hit in result["hits"])  # removed example left the index
    only_evidence = await client.get(f"{API}/projects/{project_id}/search", params={"q": "pack", "kinds": "evidence"})
    assert only_evidence.json()["hits"] == []
