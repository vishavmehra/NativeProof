"""Shared prompt and cross-reference helpers for the agents.

Models see short handles (E1, R1, A1, C1, ref-1) instead of UUIDs: they copy them reliably, and code
maps them back. Unknown handles are dropped and counted, never trusted.
"""

import json
import re
from collections.abc import Mapping, Sequence
from typing import Any, TypeVar

from pydantic import BaseModel, ConfigDict

from app.schemas.evidence import EvidenceRecord

V = TypeVar("V")


class Strict(BaseModel):
    """Base of every model-output schema: unknown keys are invalid output (repair, then RUN_FAILED), never ignored."""

    model_config = ConfigDict(extra="forbid")

DEMO_OUTPUT_NOTE = "Demo fixture output, not a live model response."
AFFINITY_NOTE = "Aggregate affinity; not evidence of demand, purchase intent, or individual preference."
DROPPED_NOTE = "Some references in the model output did not match the supplied items and were removed."
SOURCE_EVIDENCE_TYPES = frozenset({"qloo_source", "provider_result", "user_input"})

EVIDENCE_RULES = (
    "Rules: use only the supplied evidence for factual claims and cite it by handle (for example E1). Never invent "
    "statistics, entities, sources, quotes, or handles. Qloo affinity is aggregate data, not evidence of demand, "
    "purchase intent, or individual preference. Say so when evidence is insufficient. Your interpretations are model "
    "interpretations, never Qloo observations. Avoid stereotypes and never infer sensitive traits."
)

def tagged(tag: str, name: str, data: Any) -> str:
    """Serialize `data` inside <tag name=...>, neutralizing any closing tag inside the data."""
    text = data if isinstance(data, str) else json.dumps(data, ensure_ascii=False, default=str)
    safe = re.sub(rf"</\s*{tag}", f"<\\\\/{tag}", text, flags=re.IGNORECASE)
    return f'<{tag} name="{name}">\n{safe}\n</{tag}>'


def untrusted(name: str, data: Any) -> str:
    """Wrap user- or source-supplied material so the model treats it as data (see INJECTION_GUARD)."""
    return tagged("untrusted_data", name, data)


def norm(handle: str) -> str:
    return handle.strip().upper().replace(" ", "")


def pick(handles: Sequence[str], mapping: Mapping[str, V]) -> tuple[list[V], int]:
    """Targets for valid handles (deduplicated, in order) and the number of unknown handles dropped."""
    found: list[V] = []
    dropped = 0
    for handle in handles:
        target = mapping.get(norm(handle))
        if target is None:
            dropped += 1
        elif target not in found:
            found.append(target)
    return found, dropped


def evidence_digest(
    records: Sequence[EvidenceRecord], limit: int = 20, *, sources_only: bool = False
) -> tuple[list[dict], dict[str, EvidenceRecord]]:
    """Source records first, then interpretations and calculations; at most `limit` (context selection).

    Qloo records about no entity (ambiguous or unresolved lookups) are never supplied: ambiguous candidates
    are shown to users but not used downstream. `sources_only` keeps observed source data and drops model
    interpretations, so generators are grounded in signals rather than in earlier model output."""
    usable = [
        e for e in records
        if (e.evidence_type != "qloo_source" or e.subject or e.related_entity)
        and (not sources_only or e.evidence_type in SOURCE_EVIDENCE_TYPES)
    ]
    chosen = sorted(usable, key=lambda e: e.evidence_type not in SOURCE_EVIDENCE_TYPES)[:limit]
    handles = {f"E{i}": e for i, e in enumerate(chosen, 1)}
    digest = [
        {
            "handle": handle,
            "evidence_type": e.evidence_type,
            "claim_type": e.claim_type,
            "title": e.title,
            "summary": e.summary,
            "subject": e.subject.name if e.subject else None,
            "related": e.related_entity.name if e.related_entity else None,
            "attributes": {a.label: a.value for a in e.attributes},
            "limitations": e.limitations[:2],
        }
        for handle, e in handles.items()
    ]
    return digest, handles


def content_dict(content: Any) -> dict:
    return content.model_dump(include={"headline", "body", "call_to_action", "reference_terms"})


def same_text(a: str | None, b: str | None) -> bool:
    return " ".join((a or "").split()).casefold() == " ".join((b or "").split()).casefold()
