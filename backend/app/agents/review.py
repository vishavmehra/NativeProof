"""Red Team review of adaptations and the Loop judge (docs/03 A6, A7).

Both return model assessments only; deterministic checks and scores are computed in app/analytics.
"""

import random
from dataclasses import dataclass, field
from functools import lru_cache
from typing import Annotated, ClassVar
from uuid import UUID

from pydantic import Field, create_model

from app.agents._common import DROPPED_NOTE, EVIDENCE_RULES, Strict, content_dict, norm, pick, untrusted
from app.agents.audience import ReactionRiskOut
from app.analytics import DEFINITIONS
from app.llm.gateway import LLMGateway
from app.schemas.campaigns import CampaignContent
from app.schemas.common import DIMENSIONS, DimensionScores, Market, RiskFlag, StepTrace
from app.schemas.evaluations import DimensionRationales
from app.schemas.evidence import EvidenceRecord

REDTEAM_PROMPT_VERSION = "redteam-v1"
JUDGE_PROMPT_VERSION = "loop-judge-v1"


# --- Red Team -----------------------------------------------------------------------------------


class ReviewOut(Strict):
    adaptation: str = Field(description="Adaptation handle, e.g. A1.")
    risks: list[ReactionRiskOut] = Field(default=[], max_length=5)


class RiskReviewOut(Strict):
    schema_version: ClassVar[str] = "risk-review-v1"
    reviews: list[ReviewOut] = Field(max_length=3)


REDTEAM_SYSTEM = """You are the Red Team reviewer in Nativeproof. For each adapted campaign, identify possible
stereotypes, sensitivity issues, ambiguity (including idioms that may not carry over), brand inconsistency, and
unsupported claims for the target market. These are possible risks for human review, not verified violations: be
specific and conservative, never invent legal requirements, and use severity high only for issues likely to offend
or mislead. Return an empty list when you find nothing. Protected and prohibited terms were already checked in code.
Review every adaptation, keyed by its handle."""


async def review_risks(
    llm: LLMGateway, *, stage: str, source: CampaignContent, adaptations: list[tuple[str, CampaignContent]],
    market: Market, brand: dict | str,
) -> tuple[dict[int, list[RiskFlag]], StepTrace, list[str]]:
    """Returns {adaptation index: model risk flags} for reviewed adaptations only."""
    handle_of = {f"A{i}": i - 1 for i in range(1, len(adaptations) + 1)}
    rows = [{"adaptation": f"A{i}", "label": label, "content": content_dict(c)} for i, (label, c) in enumerate(adaptations, 1)]
    payload = {"adaptations": rows, "market": market.model_dump()}
    user = "\n\n".join([
        f"Target market: {market.display_name} ({market.country_code}).",
        brand if isinstance(brand, str) else untrusted("brand", brand),
        untrusted("source_campaign", content_dict(source)),
        untrusted("adaptations", rows),
    ])
    result = await llm.generate_structured(
        task="risk_analysis", stage=stage, agent="red_team", system=REDTEAM_SYSTEM, user=user, schema=RiskReviewOut,
        prompt_version=REDTEAM_PROMPT_VERSION, temperature=0.2, fixture_context=payload,
    )
    flags: dict[int, list[RiskFlag]] = {}
    dropped = 0
    for review in result.value.reviews:
        index = handle_of.get(norm(review.adaptation))
        if index is None or index in flags:
            dropped += 1
            continue
        flags[index] = [RiskFlag(**r.model_dump(), source="model_assessment") for r in review.risks]
    return flags, result.trace, [DROPPED_NOTE] if dropped else []


# --- Loop judge ---------------------------------------------------------------------------------


class ScoreOut(Strict):
    score: int = Field(ge=0, le=100)
    rationale: str = Field(max_length=400)


class _AssessmentBase(Strict):
    candidate: str = Field(description="Candidate handle, e.g. C1.")
    clarity: ScoreOut
    brand_fidelity: ScoreOut
    cultural_relevance: ScoreOut
    cultural_risk: ScoreOut
    strengths: list[str] = Field(default=[], max_length=4)
    weaknesses: list[str] = Field(default=[], max_length=4)
    risk_flags: list[ReactionRiskOut] = Field(default=[], max_length=4)
    evidence: list[str] = Field(default=[], max_length=4)


class _JudgeBase(Strict):
    schema_version: ClassVar[str] = "candidate-assessment-v1"


@lru_cache
def judge_schema(count: int) -> type[_JudgeBase]:
    return create_model(
        "CandidateAssessmentsOut", __base__=_JudgeBase,
        assessments=(Annotated[list[_AssessmentBase], Field(min_length=1, max_length=count)], ...),
    )


JUDGE_SYSTEM = f"""You are the Loop evaluator in Nativeproof. Assess every candidate text independently, with the
same criteria, for the target market. Candidates appear in arbitrary order under neutral handles; judge only the text.
Give each dimension an integer 0-100 and a one-sentence rationale. For cultural_risk, higher means more risk.
Your scores are model assessments, not consumer measurements. List concrete strengths, weaknesses, and possible risks.
{EVIDENCE_RULES}"""


@dataclass
class Assessment:
    scores: DimensionScores
    rationales: DimensionRationales
    strengths: list[str]
    weaknesses: list[str]
    risk_flags: list[RiskFlag]
    evidence_ids: list[UUID] = field(default_factory=list)


async def assess_candidates(
    llm: LLMGateway, *, stage: str, candidates: list[tuple[str, CampaignContent]], market: Market, brand: dict | str,
    evidence: list[dict], handles: dict[str, EvidenceRecord], order_seed: str,
) -> tuple[dict[str, Assessment], StepTrace, list[str]]:
    """`candidates` are (key, content). The prompt order is shuffled so the original is not identifiable by position."""
    order = list(range(len(candidates)))
    random.Random(order_seed).shuffle(order)
    key_of = {f"C{n}": candidates[i][0] for n, i in enumerate(order, 1)}
    rows = [{"candidate": f"C{n}", "content": content_dict(candidates[i][1])} for n, i in enumerate(order, 1)]
    criteria = {d: DEFINITIONS[d][1] for d in DIMENSIONS}
    payload = {"candidates": rows, "evidence": evidence, "market": market.model_dump()}
    user = "\n\n".join([
        f"Target market: {market.display_name} ({market.country_code}). Assess all {len(rows)} candidates.",
        untrusted("criteria", criteria),
        brand if isinstance(brand, str) else untrusted("brand", brand),
        untrusted("candidates", rows),
        untrusted("evidence", evidence),
    ])
    result = await llm.generate_structured(
        task="comparative_judgment", stage=stage, agent="loop", system=JUDGE_SYSTEM, user=user,
        schema=judge_schema(len(rows)), prompt_version=JUDGE_PROMPT_VERSION, temperature=0.0, seed=7,
        fixture_context=payload,
    )
    assessments: dict[str, Assessment] = {}
    dropped = 0
    for item in result.value.assessments:
        key = key_of.get(norm(item.candidate))
        if key is None or key in assessments:
            dropped += 1
            continue
        cited, lost = pick(item.evidence, handles)
        dropped += lost
        assessments[key] = Assessment(
            scores=DimensionScores(**{d: getattr(item, d).score for d in DIMENSIONS}),
            rationales=DimensionRationales(**{d: getattr(item, d).rationale for d in DIMENSIONS}),
            strengths=item.strengths, weaknesses=item.weaknesses,
            risk_flags=[RiskFlag(**r.model_dump(), source="model_assessment") for r in item.risk_flags],
            evidence_ids=[e.id for e in cited],
        )
    return assessments, result.trace, [DROPPED_NOTE] if dropped else []
