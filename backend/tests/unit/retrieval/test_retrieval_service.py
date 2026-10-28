"""RetrievalService with a deterministic bag-of-words embedder: chunking, indexing, spaces, search."""

from datetime import UTC, datetime
from uuid import uuid4

import pytest

from app.core.config import Settings
from app.llm.embeddings import EmbeddingSpace, Embeddings
from app.llm.gateway import LLMError
from app.retrieval import InMemoryRetrievalStore, RetrievalService, SearchDocument, chunk_text, cosine, get_retrieval_service
from app.retrieval.service import DEMO_UNAVAILABLE, NOT_CONFIGURED, adaptation_document, risk_finding_document
from app.schemas.common import StepTrace
from app.schemas.graph import GraphRef
from app.schemas.projects import Brand, BrandExample

VOCAB = ["hiking", "trail", "escape", "japan", "risk", "brand", "price", "autumn", "color", "jacket"]
PROJECT = uuid4()


class FakeEmbedder:
    def __init__(self, model: str = "fake-embed", *, fail: bool = False) -> None:
        self.space = EmbeddingSpace("fake", model, len(VOCAB))
        self.fail = fail
        self.calls: list[tuple[str, list[str]]] = []

    def is_configured(self) -> bool:
        return True

    async def embed(self, texts: list[str], *, kind: str = "document", stage: str = "embedding",
                    agent: str = "retrieval") -> Embeddings:
        self.calls.append((kind, list(texts)))
        if self.fail:
            raise LLMError("PROVIDER_ERROR", "The model provider is temporarily unavailable.", retryable=True,
                           trace=StepTrace(stage=stage, agent=agent, status="failed"))
        vectors = [[float(text.lower().count(word)) for word in VOCAB] for text in texts]
        return Embeddings(vectors=vectors, space=self.space, trace=StepTrace(stage=stage, agent=agent, status="completed"))


def doc(source_id: str, text: str, kind: str = "evidence", title: str = "Item") -> SearchDocument:
    return SearchDocument(kind=kind, source_id=source_id, title=title, text=text,  # type: ignore[arg-type]
                          ref=GraphRef(resource=kind, id=source_id, url=f"/api/v1/{kind}/{source_id}"),
                          evidence_type="qloo_source", claim_type="observed", retrieval_mode="live")


def service(embedder: FakeEmbedder | None = None) -> tuple[RetrievalService, InMemoryRetrievalStore, FakeEmbedder]:
    store, embedder = InMemoryRetrievalStore(), embedder or FakeEmbedder()
    return RetrievalService(embedder, store), store, embedder  # type: ignore[arg-type]


def test_chunk_text_packs_sentences_and_splits_overlong_ones() -> None:
    assert chunk_text("  short   text ") == ["short text"]
    assert chunk_text("") == []
    long_text = " ".join(f"Sentence number {i} about trails." for i in range(80))
    chunks = chunk_text(long_text, max_chars=200)
    assert len(chunks) > 1 and all(len(c) <= 200 for c in chunks)
    assert all(c.endswith(".") for c in chunks)  # whole sentences
    assert " ".join(chunks) == " ".join(long_text.split())
    assert all(len(c) <= 50 for c in chunk_text("x" * 120, max_chars=50))


def test_cosine() -> None:
    assert cosine([1, 0], [2, 0]) == pytest.approx(1.0)
    assert cosine([1, 0], [0, 3]) == 0.0
    assert cosine([0, 0], [1, 1]) == 0.0


async def test_search_ranks_one_hit_per_source_with_provenance() -> None:
    svc, _, _ = service()
    long_trail = "Hiking trail notes. " * 120  # several chunks, still one hit
    await svc.index_documents(PROJECT, [
        doc("ev-1", "Hiking in Japan on autumn trails."), doc("ev-2", "Price of the jacket."),
        doc("ev-3", long_trail), doc("rf-1", "Escape risk in Japan.", kind="risk_finding"),
    ])
    results = await svc.search(PROJECT, "hiking trail japan")
    assert results.status == "ok" and results.embedding_model == "fake-embed"
    ids = [hit.id for hit in results.hits]
    assert ids[:2] == ["ev-1", "ev-3"] and len(ids) == len(set(ids))  # cosine 0.866 vs 0.816
    top, long_hit = results.hits[0], results.hits[1]
    assert (top.kind, top.ref.url, top.evidence_type, top.claim_type, top.retrieval_mode) == (
        "evidence", "/api/v1/evidence/ev-1", "qloo_source", "observed", "live")
    assert top.similarity == pytest.approx(0.866, abs=1e-3)
    assert len(long_hit.snippet) == 240 and long_hit.snippet.endswith("…")

    only_risks = await svc.search(PROJECT, "escape risk", kinds=["risk_finding"])
    assert [hit.id for hit in only_risks.hits] == ["rf-1"]
    assert len((await svc.search(PROJECT, "hiking", limit=1)).hits) == 1


async def test_unchanged_sources_are_not_re_embedded() -> None:
    svc, _, embedder = service()
    first = await svc.index_documents(PROJECT, [doc("ev-1", "Hiking trail.")])
    second = await svc.index_documents(PROJECT, [doc("ev-1", "Hiking trail.")])
    third = await svc.index_documents(PROJECT, [doc("ev-1", "Hiking trail in autumn.")])
    assert (first.stored, second.stored, second.unchanged, third.stored) == (1, 0, 1, 1)
    assert len(embedder.calls) == 2


async def test_a_new_embedding_space_triggers_re_embedding_and_spaces_never_mix() -> None:
    svc, store, _ = service()
    await svc.index_documents(PROJECT, [doc("ev-1", "Hiking trail."), doc("ev-2", "Brand color.")])
    new_embedder = FakeEmbedder(model="fake-embed-v2")
    svc2 = RetrievalService(new_embedder, store)  # type: ignore[arg-type]
    results = await svc2.search(PROJECT, "hiking")
    assert results.hits[0].id == "ev-1"
    assert new_embedder.calls[0][0] == "document" and len(new_embedder.calls[0][1]) == 2  # re-embedded first
    assert {chunk.space for chunk in await store.list_chunks(PROJECT)} == {new_embedder.space.key}


async def test_provider_failure_while_indexing_stores_chunks_for_later() -> None:
    store = InMemoryRetrievalStore()
    failing = RetrievalService(FakeEmbedder(fail=True), store)  # type: ignore[arg-type]
    report = await failing.index_documents(PROJECT, [doc("ev-1", "Hiking trail.")])
    assert report.stored == 1 and not report.embedded
    assert [chunk.vector for chunk in await store.list_chunks(PROJECT)] == [None]
    assert (await failing.search(PROJECT, "hiking")).status == "unavailable"

    healthy = RetrievalService(FakeEmbedder(), store)  # type: ignore[arg-type]
    assert [hit.id for hit in (await healthy.search(PROJECT, "hiking")).hits] == ["ev-1"]


async def test_unavailable_without_embeddings_or_in_demo_projects() -> None:
    store = InMemoryRetrievalStore()
    live = get_retrieval_service("live", Settings(_env_file=None, embedding_model=None), store)
    demo = get_retrieval_service("demo", Settings(_env_file=None), store)
    for svc, message in ((live, NOT_CONFIGURED), (demo, DEMO_UNAVAILABLE)):
        assert not svc.is_configured()
        results = await svc.search(PROJECT, "hiking")
        assert (results.status, results.message, results.hits, results.embedding_model) == ("unavailable", message, [], None)
    assert (await demo.index_documents(PROJECT, [doc("ev-1", "Hiking")])).stored == 0


async def test_similarity_floor_applies_to_the_measured_model() -> None:
    svc, _, _ = service(FakeEmbedder(model="Qwen/Qwen3-Embedding-8B"))
    documents = [doc("ev-1", "hiking hiking hiking trail"), doc("ev-2", "price jacket color brand hiking")]
    await svc.index_documents(PROJECT, documents)
    hits = (await svc.search(PROJECT, "hiking trail")).hits
    assert [hit.id for hit in hits] == ["ev-1"]  # ev-2 scores 0.316, below the 0.33 floor
    unfiltered, _, _ = service()
    await unfiltered.index_documents(PROJECT, documents)
    assert len((await unfiltered.search(PROJECT, "hiking trail")).hits) == 2


async def test_brand_examples_are_replaced_as_a_whole() -> None:
    svc, store, _ = service()
    brand = Brand(id=uuid4(), name="Northstar", description=None, voice=[], target_audience=None, preferred_terms=[],
                  prohibited_terms=[], protected_terms=[], updated_at=datetime(2026, 10, 26, tzinfo=UTC),
                  approved_examples=[BrandExample(text="Built for long trails."), BrandExample(text="Pack light.")])
    await svc.index_brand_examples(PROJECT, brand)
    await svc.index_brand_examples(PROJECT, brand.model_copy(update={"approved_examples": [BrandExample(text="Pack light.")]}))
    chunks = await store.list_chunks(PROJECT, ["brand_example"])
    assert [c.text for c in chunks] == ["Pack light."]
    assert chunks[0].retrieval_mode == "user_input" and chunks[0].ref.url == f"/api/v1/projects/{PROJECT}/brand"


def test_documents_carry_honest_labels() -> None:
    from app.schemas.risk import RiskFinding

    finding = RiskFinding.model_validate({
        "id": str(uuid4()), "category": "constraint_violation", "severity": "high", "confidence_label": "moderate",
        "source": "deterministic_check", "text_location": None, "visual_observation_id": None,
        "observation": "cheapest jacket", "interpretation": "'cheapest' is a prohibited term.", "brand_rule": "cheapest",
        "evidence_ids": [], "limitations": [], "suggested_alternative": "best-value jacket", "status": "open",
        "status_note": None, "updated_at": "2026-10-26T00:00:00Z",
    })
    risk = risk_finding_document(uuid4(), finding)
    assert (risk.evidence_type, risk.claim_type, risk.retrieval_mode) == ("deterministic_calculation", "derived", "generated")
    assert "Suggested alternative: best-value jacket" in risk.text
    assert risk_finding_document(uuid4(), finding.model_copy(update={"source": "model_assessment"})).claim_type == "interpreted"
    assert adaptation_document is not None
