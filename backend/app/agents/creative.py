"""Arena review and Risk Radar text assessment (contracts/README §13).

All outputs are model interpretations; code verifies excerpts, handles, and brand rules before use.
"""

from typing import ClassVar

from pydantic import Field

from app.agents._common import EVIDENCE_RULES, Strict, untrusted
from app.agents.audience import ModelRiskCategory
from app.llm.gateway import LLMGateway, LLMResult
from app.schemas.adaptations import ContentField
from app.schemas.common import RiskSeverity

ARENA_PROMPT_VERSION = "arena-review-v1"
RISK_PROMPT_VERSION = "risk-scan-v2"  # v2: the alternative replaces exactly the excerpt


class ImprovementOut(Strict):
    suggestion: str = Field(max_length=300)
    rationale: str = Field(max_length=500)
    evidence: list[str] = Field(default=[], max_length=4)


class VariantReviewOut(Strict):
    variant: str = Field(description="Variant handle, e.g. V1.")
    strengths: list[str] = Field(default=[], max_length=4)
    weaknesses: list[str] = Field(default=[], max_length=4)
    improvements: list[ImprovementOut] = Field(default=[], max_length=3)


class ArenaReviewOut(Strict):
    schema_version: ClassVar[str] = "arena-review-v1"
    reviews: list[VariantReviewOut] = Field(default=[], max_length=4)


ARENA_SYSTEM = f"""You review campaign variants after a synthetic rehearsal in Nativeproof. The scores and reactions are
AI-generated, not real people. For each variant list strengths, weaknesses, and up to three concrete improvements,
grounded in the reactions, the visual observations, and the Brand Memory. Do not restate or invent scores.
{EVIDENCE_RULES}"""


async def review_variants(
    llm: LLMGateway, *, stage: str, variants: list[dict], brand: str, evidence: list[dict], market: str
) -> LLMResult[ArenaReviewOut]:
    payload = {"variants": variants, "evidence": evidence}
    user = "\n\n".join([f"Market: {market}.", brand, untrusted("variants", variants), untrusted("evidence", evidence)])
    return await llm.generate_structured(
        task="comparative_judgment", stage=stage, agent="loop", system=ARENA_SYSTEM, user=user, schema=ArenaReviewOut,
        prompt_version=ARENA_PROMPT_VERSION, temperature=0.2, fixture_context=payload,
    )


class RiskOut(Strict):
    field: ContentField | None = Field(default=None, description="Copy field of the excerpt; null for visual findings.")
    excerpt: str | None = Field(default=None, max_length=300, description="Exact quote from that field.")
    visual_observation: str | None = Field(default=None, description="Visual observation id, for visual findings.")
    category: ModelRiskCategory
    severity: RiskSeverity
    interpretation: str = Field(max_length=600)
    brand_rule: str | None = Field(default=None, description="The exact Brand Memory rule involved, if any.")
    suggested_alternative: str | None = Field(default=None, max_length=300, description="Replacement for the excerpt.")
    evidence: list[str] = Field(default=[], max_length=4)


class RiskScanOut(Strict):
    schema_version: ClassVar[str] = "risk-scan-v1"
    findings: list[RiskOut] = Field(default=[], max_length=10)


RISK_SYSTEM = f"""You are the Cultural Risk Radar in Nativeproof. Find possible stereotypes, sensitivity issues,
ambiguity, brand inconsistency, and unsupported claims in the campaign for the target market. Each text finding quotes
the exact excerpt from one field; each visual finding names a visual observation id. Keep the observation (what is
there) separate from your interpretation (why it may matter). Suggest replacement text for the excerpt when useful:
it replaces exactly the excerpt, so never repeat words from just before or after it.
Name a Brand Memory rule only by its exact text. These are possible risks for human review, not verified violations.
{EVIDENCE_RULES}"""


async def assess_risks(
    llm: LLMGateway, *, stage: str, content: dict, market: str, brand: str, observations: list[dict], evidence: list[dict]
) -> LLMResult[RiskScanOut]:
    payload = {"content": content, "observations": observations, "evidence": evidence}
    user = "\n\n".join([
        f"Target market: {market}.", brand, untrusted("campaign_content", content),
        untrusted("visual_observations", observations), untrusted("evidence", evidence),
    ])
    return await llm.generate_structured(
        task="risk_analysis", stage=stage, agent="red_team", system=RISK_SYSTEM, user=user, schema=RiskScanOut,
        prompt_version=RISK_PROMPT_VERSION, temperature=0.2, fixture_context=payload,
    )

