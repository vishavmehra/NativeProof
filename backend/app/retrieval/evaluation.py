"""Retrieval evaluation (D-034): 15 labeled Nativeproof queries over a fixed demo-scenario corpus.

Usage (from backend/, with EMBEDDING_* configured; 2 embedding requests per variant):
    uv run python -m app.retrieval.evaluation [--dimensions 1024] [--no-instruction]

The corpus imitates one project's searchable content (Northstar outdoor apparel, Japan): evidence,
brand examples, risk findings, Cultural DNA items, and adaptations, with deliberate near-misses.
Labels were written before running. Precision@k is bounded by the number of relevant items per
query, so the ideal value is printed alongside it.
"""

import argparse
import asyncio
import statistics
from uuid import uuid4

from app.core.config import Settings
from app.llm.gateway import LLMGateway
from app.retrieval.service import RetrievalService, SearchDocument, rank_chunks
from app.retrieval.store import InMemoryRetrievalStore
from app.schemas.graph import GraphRef
from app.schemas.search import SearchKind

CORPUS: list[tuple[str, SearchKind, str, str]] = [
    ("ev-hiking", "evidence", "Resolved tag: Hiking", "The concept 'hiking' resolved to the Hiking tag in Qloo tag search."),
    ("ev-kumo", "evidence", "Related interest: Kumo Trail Co.",
     "Kumo Trail Co. was returned as a related brand for audiences with a Hiking affinity in Japan."),
    ("ev-minimal", "evidence", "Ambiguous match: 'minimal design'",
     "Two plausible tags were returned, Minimalism and Minimalist architecture; Nativeproof did not choose one."),
    ("ev-escape", "evidence", "Unresolved: 'great escape'",
     "Qloo returned no usable match for 'great escape'; any interpretation of the phrase is a hypothesis."),
    ("ev-trail-framing", "evidence", "Interpretation: trail-focused framing",
     "Hiking and trail-brand signals suggest framing the launch around trail use rather than escape."),
    ("ev-vague", "evidence", "Synthetic reaction: escape framing unclear",
     "Several synthetic respondents found 'Find your next great escape' vague and asked what the product does."),
    ("ev-durable", "evidence", "Synthetic reaction: durability valued",
     "Weekend-hiker respondents rated durability and light weight as the most persuasive product qualities."),
    ("ev-clarity", "evidence", "Calculated clarity score 62.5",
     "Deterministic aggregation of 12 synthetic ratings: clarity mean 3.5 of 5, spread 1.1, disagreement flagged."),
    ("ev-risk-score", "evidence", "Calculated cultural risk score 18.8",
     "Deterministic aggregation: cultural risk mean 1.75 of 5, low perceived risk in every segment."),
    ("ev-commuters", "evidence", "Synthetic reaction: urban commuters",
     "Urban commuter respondents liked the look of the jacket but doubted they needed trail-grade features."),
    ("ev-price", "evidence", "Synthetic reaction: price concerns",
     "Students in the sample worried the jacket was too expensive and asked about discounts."),
    ("ev-gift", "evidence", "Interpretation: autumn gifting",
     "Framing the jacket as a practical autumn gift may suit family shoppers; untested."),
    ("ev-length", "evidence", "Calculated headline length",
     "Deterministic check: the Japanese headline is 24 characters, within the 30-character display limit."),
    ("ev-rainy", "evidence", "Interpretation: rainy season",
     "The June rainy season (tsuyu) drives demand for waterproof shells; not relevant to the autumn launch."),
    ("ev-gorpcore", "evidence", "Interpretation: outdoor gear as city fashion",
     "Outdoor gear worn as streetwear (gorpcore) may widen the audience beyond hikers; unverified."),
    ("be-1", "brand_example", "Approved brand example",
     "Built for long trails, quiet mornings, and the people who start before sunrise."),
    ("be-2", "brand_example", "Approved brand example",
     "Gear that keeps up with you, from the first switchback to the summit hut. (approved for JP social)"),
    ("be-3", "brand_example", "Approved brand example", "Layer smart. Pack light. Leave no trace."),
    ("be-4", "brand_example", "Approved brand example",
     "Northstar jackets are tested in real mountain weather, not only in the lab."),
    ("rf-escape", "risk_finding", "Ambiguity risk (medium)",
     "Observation: 'Find your next great escape' Interpretation: A literal Japanese rendering of 'escape' can suggest "
     "running away from obligations. Suggested alternative: Find your next trail."),
    ("rf-prohibited", "risk_finding", "Constraint violation risk (high)",
     "Observation: 'cheapest jacket' Interpretation: Deterministic check: 'cheapest' is a prohibited brand term. "
     "Suggested alternative: best-value jacket."),
    ("rf-shrine", "risk_finding", "Sensitivity risk (medium)",
     "Observation: a torii gate is visible behind the product. Interpretation: Using a shrine gate as a product "
     "backdrop may be seen as disrespectful of a sacred site."),
    ("rf-zen", "risk_finding", "Stereotype risk (low)",
     "Observation: 'Zen simplicity' Interpretation: Using 'Zen' as a style label may read as a cliché about Japan."),
    ("rf-claim", "risk_finding", "Unsupported claim risk (high)",
     "Observation: 'Japan's favourite outdoor brand' Interpretation: No evidence supports market leadership; the "
     "claim could mislead."),
    ("rf-color", "risk_finding", "Brand inconsistency risk (low)",
     "Observation: a neon pink call-to-action button. Interpretation: The colour departs from Northstar's muted "
     "earth-tone palette."),
    ("rf-pack", "risk_finding", "Ambiguity risk (low)",
     "Observation: 'Pack light' Interpretation: Could be read as advice about luggage limits rather than gear weight."),
    ("pi-weekend", "profile_item", "Weekend hiking culture",
     "Day hikes near cities on weekends are a common leisure pattern for the target audience."),
    ("pi-craft", "profile_item", "Preference for craftsmanship",
     "Audiences respond to visible build quality and details more than to bold slogans (hypothesis)."),
    ("pi-seasons", "profile_item", "Seasonal awareness",
     "Seasonal references such as autumn leaves (koyo) carry positive associations; untested for this campaign."),
    ("pi-modest", "profile_item", "Understated messaging",
     "A modest, factual tone may land better than superlatives (interpretation)."),
    ("pi-group", "profile_item", "Group outings",
     "Hiking is often social: friends and hiking clubs plan trips together."),
    ("ad-clearer", "adaptation", "Clearer message (Japan)",
     "Replace the abstract escape idea with concrete trail benefits. Find your next trail. Light, durable layers for "
     "weekend hikes near the city. See the autumn collection."),
    ("ad-seasonal", "adaptation", "Seasonal (Japan)",
     "Anchor the launch in autumn leaf season. Autumn trails are calling. Warm layers for koyo hikes. Explore the "
     "collection."),
    ("ad-craft", "adaptation", "Craftsmanship (Japan)",
     "Emphasize build quality and testing. Made for real mountain weather. Every seam is tested on the trail. "
     "Discover the details."),
    ("ad-edit", "adaptation", "User edit (Japan)",
     "User revision of the clearer-message variant. Your weekend trail starts here. Light layers for the hills "
     "near home."),
    ("ev-sample", "evidence", "Calculated sample size",
     "The rehearsal generated 12 synthetic reactions across 3 segments; they are not independent human observations."),
]

QUERIES: list[tuple[str, set[str]]] = [
    ("why might 'great escape' not work in Japan", {"rf-escape", "ev-escape", "ev-vague"}),
    ("which brands are related to hiking audiences", {"ev-kumo"}),
    ("approved brand voice examples about trails", {"be-1", "be-2"}),
    ("risky imagery involving sacred sites", {"rf-shrine"}),
    ("claims we cannot back up with evidence", {"rf-claim"}),
    ("how clear was the campaign message to respondents", {"ev-clarity", "ev-vague"}),
    ("copy variant that focuses on autumn leaves", {"ad-seasonal", "pi-seasons"}),
    ("words the brand does not allow", {"rf-prohibited"}),
    ("do people hike alone or with friends", {"pi-group"}),
    ("what did price-sensitive students think", {"ev-price"}),
    ("stereotypes about Japanese culture", {"rf-zen"}),
    ("evidence about product durability and quality", {"ev-durable", "pi-craft", "ad-craft"}),
    ("unresolved or ambiguous Qloo references", {"ev-minimal", "ev-escape"}),
    ("見出しの文字数は表示制限内ですか", {"ev-length"}),
    ("colors that clash with the brand palette", {"rf-color"}),
]
NO_ANSWER = ["Brazilian football sponsorship deals", "quarterly tax filing deadlines"]
K = (1, 3, 5)


async def evaluate(settings: Settings, *, instruction: bool) -> None:
    embedder = LLMGateway(settings).capability("embeddings")  # the one gateway: deadlines, configured checks
    assert embedder is not None and embedder.space is not None, "EMBEDDING_* is not configured"
    store, project = InMemoryRetrievalStore(), uuid4()
    service = RetrievalService(embedder, store)
    documents = [
        SearchDocument(kind=kind, source_id=doc_id, title=title, text=text,
                       ref=GraphRef(resource=kind, id=doc_id, url=None))
        for doc_id, kind, title, text in CORPUS
    ]
    report = await service.index_documents(project, documents)
    assert report.embedded, "corpus was not embedded"
    queries = [query for query, _ in QUERIES] + NO_ANSWER
    result = await embedder.embed(queries, kind="query" if instruction else "document")
    chunks = await store.list_chunks(project)

    precision = {k: [] for k in K}
    ideal = {k: [] for k in K}
    recall5, reciprocal, top_relevant, top_irrelevant, relevant_scores = [], [], [], [], []
    for (query, relevant), vector in zip(QUERIES, result.vectors, strict=False):
        ranked = rank_chunks(vector, chunks, embedder.space.key, limit=max(K))
        ids = [chunk.source_id for _, chunk in ranked]
        for k in K:
            precision[k].append(len(relevant & set(ids[:k])) / k)
            ideal[k].append(min(len(relevant), k) / k)
        recall5.append(len(relevant & set(ids)) / len(relevant))
        first = next((rank for rank, doc in enumerate(ids, start=1) if doc in relevant), None)
        reciprocal.append(1 / first if first else 0.0)
        scores = {chunk.source_id: score for score, chunk in ranked}
        relevant_scores += [scores[doc] for doc in ids if doc in relevant]
        top_relevant += [scores[doc] for doc in ids[:1] if doc in relevant]
        top_irrelevant += [scores[doc] for doc in ids[:1] if doc not in relevant]
        marks = " ".join(f"{doc}{'*' if doc in relevant else ''}" for doc in ids)
        print(f"  {query[:52]:<52} {marks}")
    no_answer_top = [
        rank_chunks(vector, chunks, embedder.space.key, limit=1)[0][0] for vector in result.vectors[len(QUERIES):]
    ]
    mean = statistics.fmean
    print(f"space={embedder.space.key} instruction={instruction} documents={len(CORPUS)} queries={len(QUERIES)}")
    for k in K:
        print(f"P@{k}={mean(precision[k]):.3f} (ideal {mean(ideal[k]):.3f})", end="  ")
    print(f"R@5={mean(recall5):.3f} MRR={mean(reciprocal):.3f}")
    print(f"top-1 similarity: relevant mean {mean(top_relevant):.3f} min {min(top_relevant):.3f} (n={len(top_relevant)}), "
          f"irrelevant {[round(s, 3) for s in top_irrelevant]}, no-answer queries {[round(s, 3) for s in no_answer_top]}")
    print(f"relevant items retrieved in top {max(K)}: min similarity {min(relevant_scores):.3f} (n={len(relevant_scores)})")
    print(f"latency: query batch {result.trace.latency_ms} ms; usage {result.trace.usage}")


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--dimensions", type=int)
    parser.add_argument("--no-instruction", action="store_true")
    args = parser.parse_args()
    settings = Settings()
    if args.dimensions:
        settings = settings.model_copy(update={"embedding_dimensions": args.dimensions})
    asyncio.run(evaluate(settings, instruction=not args.no_instruction))


if __name__ == "__main__":
    main()
