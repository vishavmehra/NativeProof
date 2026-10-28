"""Voice agent: 1-3 genuinely different market adaptations with per-field change explanations (docs/03 A5).

Code computes which fields changed; `evidence_supported` requires a cited, supplied source record.
"""

from dataclasses import dataclass
from functools import lru_cache
from typing import Annotated, ClassVar

from pydantic import Field, ValidationError, create_model

from app.agents._common import DROPPED_NOTE, EVIDENCE_RULES, SOURCE_EVIDENCE_TYPES, Strict, content_dict, pick, same_text, untrusted
from app.llm.gateway import LLMGateway
from app.schemas.adaptations import ContentChange, ContentField
from app.schemas.campaigns import CampaignContent
from app.schemas.common import Market, StepTrace
from app.schemas.evidence import EvidenceRecord
from app.schemas.studies import RehearsalSummary

PROMPT_VERSION = "voice-adaptations-v1"
FIELDS: tuple[ContentField, ...] = ("headline", "body", "call_to_action")


class ChangeOut(Strict):
    field: ContentField
    reason: str = Field(max_length=500)
    evidence: list[str] = Field(default=[], max_length=4, description="Handles that directly support this change.")


class VariantOut(Strict):
    label: str = Field(min_length=1, max_length=60, description="Short strategy label, e.g. Clearer message.")
    strategy: str = Field(min_length=1, max_length=300)
    headline: str | None = Field(default=None, max_length=300)
    body: str | None = Field(default=None, max_length=5000)
    call_to_action: str | None = Field(default=None, max_length=200)
    reference_terms: list[Annotated[str, Field(max_length=100)]] = Field(default=[], max_length=10)
    changes: list[ChangeOut] = Field(default=[], max_length=3)


class _VariantsBase(Strict):
    schema_version: ClassVar[str] = "adaptation-variants-v1"


@lru_cache
def variants_schema(count: int) -> type[_VariantsBase]:
    return create_model(
        "AdaptationVariantsOut", __base__=_VariantsBase,
        variants=(Annotated[list[VariantOut], Field(min_length=1, max_length=count)], ...),
    )


SYSTEM = f"""You are the Voice agent in Nativeproof. Adapt a campaign for the target market while preserving the
brand's intent and voice. Each variant must follow a genuinely different strategy, not a paraphrase of another.
Keep every protected term that appears in the source verbatim. Never use prohibited terms. Do not invent product
facts or claims. For each field you change, give the reason; cite evidence handles only when a record directly
supports that specific change. User instructions are requests: follow them unless they conflict with these rules.
{EVIDENCE_RULES}"""


@dataclass
class VariantDraft:
    label: str
    strategy: str
    content: CampaignContent
    changes: list[ContentChange]
    evidence: list[EvidenceRecord]


def _rehearsal_digest(summary: RehearsalSummary | None) -> dict | None:
    if summary is None:
        return None
    pick_text = lambda items: [f"{f.title}: {f.summary}" for f in items]  # noqa: E731
    return {
        "key_findings": pick_text(summary.key_findings),
        "potential_confusions": pick_text(summary.potential_confusions),
        "potential_cultural_risks": pick_text(summary.potential_cultural_risks),
        "disagreements": [d.topic for d in summary.disagreements],
        "note": "Findings from AI-generated synthetic reactions, not real people.",
    }


async def generate_variants(
    llm: LLMGateway, *, stage: str, source: CampaignContent, market: Market, brand: dict | str, protected_terms: list[str],
    variant_count: int, instructions: str | None, evidence: list[dict], handles: dict[str, EvidenceRecord],
    rehearsal_summary: RehearsalSummary | None,
) -> tuple[list[VariantDraft], StepTrace, list[str], int]:
    rehearsal = _rehearsal_digest(rehearsal_summary)
    payload = {
        "variant_count": variant_count, "source": content_dict(source), "market": market.model_dump(),
        "protected_terms": protected_terms, "evidence": evidence, "rehearsal": rehearsal,
    }
    user = "\n\n".join([
        f"Target market: {market.display_name} ({market.country_code}). Write {variant_count} variant(s).",
        untrusted("source_campaign", content_dict(source)),
        brand if isinstance(brand, str) else untrusted("brand", brand),
        untrusted("protected_terms", protected_terms),
        *([untrusted("user_instructions", instructions)] if instructions else []),
        *([untrusted("rehearsal_findings", rehearsal)] if rehearsal else []),
        untrusted("evidence", evidence),
    ])
    result = await llm.generate_structured(
        task="creative_adaptation", stage=stage, agent="voice", system=SYSTEM, user=user,
        schema=variants_schema(variant_count), prompt_version=PROMPT_VERSION, temperature=0.7, fixture_context=payload,
    )
    drafts: list[VariantDraft] = []
    notes: list[str] = []
    dropped = 0
    for item in result.value.variants[:variant_count]:
        try:
            content = CampaignContent(
                headline=item.headline, body=item.body, call_to_action=item.call_to_action,
                reference_terms=item.reference_terms,
            )
        except ValidationError:
            notes.append(f"Variant '{item.label}' was discarded: it had neither a headline nor a body.")
            continue
        if any(all(same_text(getattr(content, f), getattr(o, f)) for f in FIELDS) for o in [source, *(d.content for d in drafts)]):
            notes.append(f"Variant '{item.label}' was discarded: it repeated the source or another variant.")
            continue
        reasons: dict[str, ChangeOut] = {}
        for change in item.changes:
            reasons.setdefault(change.field, change)
        changes, cited_all = [], []
        for field in FIELDS:
            original, adapted = getattr(source, field), getattr(content, field)
            if same_text(original, adapted):
                continue
            explained = reasons.get(field)
            cited, lost = pick(explained.evidence, handles) if explained else ([], 0)
            dropped += lost
            supported = any(e.evidence_type in SOURCE_EVIDENCE_TYPES for e in cited)
            changes.append(
                ContentChange(
                    field=field, original=original, adapted=adapted,
                    reason=explained.reason if explained else "The model did not explain this change.",
                    reasoning_type="evidence_supported" if supported else "model_interpretation",
                    evidence_ids=[e.id for e in cited],
                )
            )
            cited_all += [e for e in cited if e not in cited_all]
        drafts.append(VariantDraft(item.label, item.strategy, content, changes, cited_all))
    discarded = len(result.value.variants[:variant_count]) - len(drafts)  # invalid or repeated output, never saved
    return drafts, result.trace, notes + ([DROPPED_NOTE] if dropped else []), discarded
