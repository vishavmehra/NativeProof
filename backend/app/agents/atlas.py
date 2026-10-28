"""Atlas market brief: synthesis from supplied Qloo evidence only (docs/03 A1)."""

import re
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import ClassVar, Literal
from uuid import uuid4

from pydantic import Field

from app.agents._common import DEMO_OUTPUT_NOTE, DROPPED_NOTE, EVIDENCE_RULES, Strict, content_dict, evidence_digest, norm, pick, untrusted
from app.analytics import brief_confidence, is_source_observed
from app.llm.gateway import LLMGateway
from app.schemas.campaigns import CampaignContent
from app.schemas.common import Market, StepTrace
from app.schemas.discovery import BriefFinding, CulturalReference, MarketBrief
from app.schemas.evidence import EvidenceRecord

PROMPT_VERSION = "atlas-brief-v2"  # v2: "observed" restricted to literal record content
INTERPRETATION_NOTE = "Model interpretation of the cited evidence; not a Qloo observation."
DEMAND_NOTE = "Cultural affinity does not establish market demand."
OVERCLAIM_NOTE = (
    "{n} finding(s) labeled observed said more than the cited records contain (a judgment such as recognition, "
    "popularity, demand, or positioning; a number that is not in the record; or no cited name) and were relabeled as "
    "interpretations."
)
# Words that judge or extrapolate beyond a record's literal fields. a lexical list, so a paraphrase that is not
# listed passes when the claim also names a cited record; extend it as live briefs show new phrasings.
INTERPRETIVE = re.compile(
    r"\b(?:recogni[sz]\w*|well[- ]known|famous|renowned|iconic|reputa\w*|popular\w*|demand\w*|"
    r"position(?:ed|ing|s)|leading|leaders?|dominan\w*|trust\w*|(?:be)?loved|favou?rite\w*|prefer\w*|trend\w*|"
    r"grow\w*|resonat\w*|appeal\w*|perceiv\w*|percept\w*|strong\w*|significant\w*|likely|suggest\w*|indicat\w*|"
    r"impl(?:y|ies)|premium|aspiration\w*|mainstream|established|loyal\w*)\b",
    re.IGNORECASE,
)
NUMBER = re.compile(r"\d+(?:\.\d+)?")


def literal_support(text: str, records: list[EvidenceRecord]) -> bool:
    """Deterministic check that an "observed" claim states only what the cited source records literally contain: it
    names a cited entity or tag, uses no judgment word outside those names, and every number it states is in a record
    (equal at the claim's precision)."""
    names = {n for e in records for n in (e.subject and e.subject.name, e.related_entity and e.related_entity.name) if n}
    rest, named = text, False
    for name in sorted(names, key=len, reverse=True):
        pattern = re.compile(re.escape(name), re.IGNORECASE)
        named = named or bool(pattern.search(rest))
        rest = pattern.sub(" ", rest)
    if not named or INTERPRETIVE.search(rest):
        return False
    pool = " ".join(f"{e.title} {e.summary} " + " ".join(str(a.value) for a in e.attributes) for e in records)
    allowed = [float(x) for x in NUMBER.findall(pool)]
    return all(any(round(v, len(t.partition(".")[2])) == float(t) for v in allowed) for t in NUMBER.findall(rest))


class BriefFindingOut(Strict):
    title: str = Field(max_length=200)
    explanation: str = Field(max_length=1000)
    claim_type: Literal["observed", "interpreted", "hypothesis"]
    evidence: list[str] = Field(default=[], max_length=8, description="Handles of evidence that supports this finding.")
    validation_question: str | None = Field(default=None, max_length=300)


class ReferenceNoteOut(Strict):
    reference: str
    relevance_explanation: str = Field(max_length=500)


class MarketBriefOut(Strict):
    schema_version: ClassVar[str] = "market-brief-v1"
    summary: str = Field(max_length=1200)
    reference_notes: list[ReferenceNoteOut] = Field(default=[], max_length=20)
    observations: list[BriefFindingOut] = Field(default=[], max_length=5)
    opportunities: list[BriefFindingOut] = Field(default=[], max_length=5)
    risks: list[BriefFindingOut] = Field(default=[], max_length=5)
    validation_questions: list[str] = Field(default=[], max_length=6)
    limitations: list[str] = Field(default=[], max_length=6)


SYSTEM = f"""You are the Atlas analyst in Nativeproof, a cultural-intelligence research tool.
Write a market brief for the stated market and product using ONLY the supplied reference lookups and evidence records.
Finding types:
- observed: states only what the cited evidence records literally contain: a resolved name and its type, a tag, a
  related entity, or an attribute value exactly as given (for example a match or affinity rank). Name the record's
  entity or tag and cite at least one evidence handle. Recognition, popularity, reputation, demand, positioning,
  trends, or any judgment about those values are not observed: label them interpreted.
- interpreted: your interpretation of the evidence; cite the handles you interpret.
- hypothesis: an untested idea (for example about an unresolved term); add a validation question.
Ambiguous references were not resolved: never treat them as evidence. Unresolved terms have no evidence.
Add one short relevance explanation per resolved reference, keyed by its reference id.
{EVIDENCE_RULES}"""


@dataclass
class BriefResult:
    brief: MarketBrief
    relevance: dict[str, str]
    new_evidence: list[EvidenceRecord]
    trace: StepTrace
    notes: list[str]


def reference_digest(
    references: list[CulturalReference], roles: dict[str, tuple[str, str | None]], handle_of: dict
) -> list[dict]:
    rows = []
    for ref in references:
        role, seed = roles.get(ref.id, ("reference_term", None))
        row = {"reference": ref.id, "role": role, "query_term": ref.query_term, "status": ref.match_status}
        if ref.match_status == "resolved":
            row |= {"name": ref.name, "entity_type": ref.entity_type, "evidence": [handle_of[i] for i in ref.evidence_ids if i in handle_of]}
            if seed:
                row["seed"] = seed
        elif ref.match_status == "ambiguous":
            row["note"] = "Several candidates matched; none was chosen. Do not use."
        rows.append(row)
    return rows


async def generate_brief(
    llm: LLMGateway,
    *,
    stage: str,
    project_id,
    run_id,
    market: Market,
    product_category: str,
    research_question: str,
    brand: dict | str,
    references: list[CulturalReference],
    roles: dict[str, tuple[str, str | None]],
    evidence: list[EvidenceRecord],
    campaign_content: CampaignContent | None,
) -> BriefResult:
    usable_ids = {i for r in references if r.match_status == "resolved" for i in r.evidence_ids}
    digest, handles = evidence_digest([e for e in evidence if e.id in usable_ids], limit=30)
    handle_of = {e.id: h for h, e in handles.items()}
    payload = {
        "market": market.model_dump(),
        "product_category": product_category,
        "research_question": research_question,
        "references": reference_digest(references, roles, handle_of),
        "evidence": digest,
    }
    user = "\n\n".join(
        [
            f"Market: {market.display_name} ({market.country_code}). Product category: {product_category}.",
            untrusted("research_question", research_question),
            brand if isinstance(brand, str) else untrusted("brand", brand),
            *([untrusted("campaign_content", content_dict(campaign_content))] if campaign_content else []),
            untrusted("references", payload["references"]),
            untrusted("evidence", digest),
        ]
    )
    result = await llm.generate_structured(
        task="research_synthesis", stage=stage, agent="atlas", system=SYSTEM, user=user, schema=MarketBriefOut,
        prompt_version=PROMPT_VERSION, temperature=0.3, fixture_context=payload,
    )
    out, trace = result.value, result.trace
    fixture = trace.provider == "fixture"
    dropped = overclaims = 0
    new_evidence: list[EvidenceRecord] = []
    now = datetime.now(UTC)

    def finding(prefix: str, index: int, item: BriefFindingOut) -> BriefFinding:
        nonlocal dropped, overclaims
        cited, lost = pick(item.evidence, handles)
        dropped += lost
        claim = item.claim_type
        sources = [e for e in cited if is_source_observed(e)]
        if claim == "observed" and not sources:
            claim = "interpreted" if cited else "hypothesis"  # "observed" needs Qloo source evidence
        elif claim == "observed" and not literal_support(f"{item.title}. {item.explanation}", sources):
            claim, overclaims = "interpreted", overclaims + 1
        if claim == "interpreted":
            record = EvidenceRecord(
                id=uuid4(), project_id=project_id, evidence_type="model_interpretation", claim_type="interpreted",
                title=f"Interpretation: {item.title}"[:200], summary=item.explanation, source_provider=trace.provider or "unknown",
                source_workflow=None, source_reference=trace.model_id, subject=None, related_entity=None, attributes=[],
                method="model_interpretation", retrieval_mode="generated", is_live_data=False, source_run_id=run_id,
                retrieved_at=None, limitations=[INTERPRETATION_NOTE] + ([DEMO_OUTPUT_NOTE] if fixture else []),
                provenance=None, created_at=now,
            )
            new_evidence.append(record)
            cited = [*cited, record]
        return BriefFinding(
            id=f"{prefix}-{index}", title=item.title, explanation=item.explanation, claim_type=claim,
            evidence_ids=[e.id for e in cited], confidence_label=brief_confidence(claim, cited),
            validation_question=item.validation_question,
        )

    observations = [finding("obs", i, f) for i, f in enumerate(out.observations, 1)]
    opportunities = [finding("opp", i, f) for i, f in enumerate(out.opportunities, 1)]
    risks = [finding("risk", i, f) for i, f in enumerate(out.risks, 1)]
    questions = list(dict.fromkeys(out.validation_questions or [f.validation_question for f in risks + opportunities if f.validation_question]))
    resolved_ids = {norm(r.id): r.id for r in references if r.match_status == "resolved"}
    relevance = {resolved_ids[norm(n.reference)]: n.relevance_explanation for n in out.reference_notes if norm(n.reference) in resolved_ids}
    limitations = list(dict.fromkeys([*out.limitations, DEMAND_NOTE] + ([DEMO_OUTPUT_NOTE] if fixture else [])))
    brief = MarketBrief(
        summary=out.summary, observations=observations, opportunities=opportunities, risks=risks,
        validation_questions=questions, limitations=limitations,
    )
    notes = ([DROPPED_NOTE] if dropped else []) + ([OVERCLAIM_NOTE.format(n=overclaims)] if overclaims else [])
    return BriefResult(brief, relevance, new_evidence, trace, notes)
