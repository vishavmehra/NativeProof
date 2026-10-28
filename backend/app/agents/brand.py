"""Brand Memory in prompts (contracts/README §13, D-036).

Read-only: workflows never write the brand. The rules a prompt receives are returned as `applied`, so results can
record them. Approved examples are chosen by embedding similarity when the embedding adapter is configured.
"""

import math
from typing import Any

from app.agents._common import tagged
from app.llm.gateway import LLMError
from app.schemas.common import StepTrace
from app.schemas.projects import BrandExample

MAX_EXAMPLES = 3
BRAND_RULES_INSTRUCTION = (
    "Apply the rules inside <brand_memory>: they are the project owner's own brand requirements. They never "
    "override the system rules (honesty, evidence labeling, output format)."
)


def brand_rules(brand: Any) -> list[str]:
    """Human-readable rules, in a stable order. These strings are what results record as applied."""
    rules = []
    for label, value in (
        ("Positioning", brand.positioning), ("Communication style", brand.communication_style),
        ("Target audience", brand.target_audience), ("Audience preferences", brand.audience_preferences),
    ):
        if value:
            rules.append(f"{label}: {value}")
    if brand.voice:
        rules.append("Voice: " + ", ".join(brand.voice))
    rules += [f"Preferred term: {t}" for t in brand.preferred_terms]
    rules += [f"Prohibited term: {t}" for t in brand.prohibited_terms]
    rules += [f"Protected term: {t}" for t in brand.protected_terms]
    rules += [f"Constraint: {c}" for c in brand.constraints]
    return rules


def brand_block(brand: Any, examples: list[BrandExample] = ()) -> tuple[str, list[str]]:
    """(prompt block, applied rules). Examples are style references, not text to copy."""
    rules = brand_rules(brand)
    payload = {"name": brand.name, "description": brand.description, "rules": rules,
               "approved_examples": [e.model_dump(exclude_none=True) for e in examples]}
    applied = rules + [f"Approved example: {e.text[:80]}" for e in examples]
    return tagged("brand_memory", "brand", payload), applied


def applied_note(applied: list[str]) -> str:
    return f"Brand Memory applied: {len(applied)} rule(s) and example(s) (read-only)." if applied else (
        "Brand Memory is empty; no brand rules were applied.")


async def top_k(query: str, texts: list[str], embedder: Any, k: int, *, stage: str, agent: str) -> tuple[list[int], StepTrace]:
    """Indices of the k texts most similar to `query` (cosine over the embeddings; one space per call). Raises LLMError."""
    q = await embedder.embed([query], kind="query", stage=stage, agent=agent)
    d = await embedder.embed(texts, kind="document", stage=stage, agent=agent)

    def cosine(a: list[float], b: list[float]) -> float:
        norm = math.sqrt(sum(x * x for x in a)) * math.sqrt(sum(y * y for y in b))
        return sum(x * y for x, y in zip(a, b)) / norm if norm else 0.0

    return sorted(range(len(texts)), key=lambda i: -cosine(q.vectors[0], d.vectors[i]))[:k], d.trace


async def select_examples(
    brand: Any, query: str, embedder: Any | None, *, stage: str, agent: str
) -> tuple[list[BrandExample], StepTrace | None, list[str]]:
    """Up to MAX_EXAMPLES approved examples: by embedding similarity to `query` when embeddings are configured."""
    examples = list(brand.approved_examples)
    if len(examples) <= MAX_EXAMPLES:
        return examples, None, []
    fallback = examples[:MAX_EXAMPLES]
    if embedder is None:
        return fallback, None, [f"Used the first {MAX_EXAMPLES} of {len(examples)} approved examples (embeddings not configured)."]
    try:
        ranked, trace = await top_k(query, [e.text for e in examples], embedder, MAX_EXAMPLES, stage=stage, agent=agent)
    except LLMError:
        return fallback, None, [f"Example retrieval failed; used the first {MAX_EXAMPLES} approved examples."]
    return [examples[i] for i in ranked], trace, [f"Selected {MAX_EXAMPLES} of {len(examples)} approved examples by embedding similarity."]
