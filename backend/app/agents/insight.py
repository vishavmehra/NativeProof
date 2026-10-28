"""Cultural DNA synthesis and the cross-market summary (contracts/README §13). Evidence-only synthesis;
code enforces claim types, evidence ids, and confidence labels afterwards."""

from typing import ClassVar, Literal

from pydantic import Field

from app.agents._common import EVIDENCE_RULES, Strict, untrusted
from app.llm.gateway import LLMGateway, LLMResult
from app.schemas.profiles import ProfileItemKind

PROFILE_PROMPT_VERSION = "cultural-profile-v1"
MARKETS_PROMPT_VERSION = "market-summary-v1"


class ProfileItemOut(Strict):
    kind: ProfileItemKind
    title: str = Field(max_length=200)
    explanation: str = Field(max_length=800)
    claim_type: Literal["observed", "interpreted", "hypothesis"]
    market: str | None = Field(default=None, description="ISO country code of the market, or null for all markets.")
    evidence: list[str] = Field(default=[], max_length=8)


class ProfileOut(Strict):
    schema_version: ClassVar[str] = "cultural-profile-v1"
    summary: str = Field(max_length=1200)
    items: list[ProfileItemOut] = Field(default=[], max_length=12)
    market_context: list[str] = Field(default=[], max_length=8)
    missing_evidence: list[str] = Field(default=[], max_length=8)


PROFILE_SYSTEM = f"""You build a Cultural DNA profile in Nativeproof: the cultural affinities, associations,
opportunities, and conflicts relevant to the subject in the listed markets, grounded ONLY in the supplied discovery
evidence. observed = restates what cited records show (cite at least one handle); interpreted = your interpretation of
cited records; hypothesis = an untested idea (no evidence needed). Tag each item with its market's country code, or
null when it applies to all markets. List the evidence that is missing.
{EVIDENCE_RULES}"""


async def synthesize_profile(
    llm: LLMGateway, *, stage: str, subject: str, title: str, focus: str | None, markets: list[dict], brand: str,
    evidence: list[dict], previous: list[dict],
) -> LLMResult[ProfileOut]:
    payload = {"subject": subject, "title": title, "focus": focus, "markets": markets, "evidence": evidence,
               "previous_items": previous}
    user = "\n\n".join([
        f"Subject: {subject}. Markets: {', '.join(m['country_code'] for m in markets)}.",
        untrusted("profile_request", {"title": title, "focus": focus}),
        brand,
        *([untrusted("previous_version_items", previous)] if previous else []),
        untrusted("evidence", evidence),
    ])
    return await llm.generate_structured(
        task="research_synthesis", stage=stage, agent="atlas", system=PROFILE_SYSTEM, user=user, schema=ProfileOut,
        prompt_version=PROFILE_PROMPT_VERSION, temperature=0.3, fixture_context=payload,
    )


class MarketAssessmentOut(Strict):
    market: str = Field(description="ISO country code.")
    assessment: str = Field(max_length=600, description="Brand compatibility in this market, from the evidence.")
    claim_type: Literal["interpreted", "hypothesis"]


class MarketSummaryOut(Strict):
    schema_version: ClassVar[str] = "market-summary-v1"
    cross_market_summary: str = Field(max_length=1500)
    markets: list[MarketAssessmentOut] = Field(default=[], max_length=5)


MARKETS_SYSTEM = f"""You compare markets for a launch in Nativeproof using ONLY each market's supplied Qloo signals and
brief findings. Assess brand compatibility per market against the Brand Memory. Never invent insight for a market with
no data. When the signals are identical across markets, say they cannot rank the markets. Your text is a model
interpretation, not a measurement of demand.
{EVIDENCE_RULES}"""


async def summarize_markets(
    llm: LLMGateway, *, stage: str, product_category: str, research_question: str, columns: list[dict], brand: str,
    market_specific: bool,
) -> LLMResult[MarketSummaryOut]:
    payload = {"columns": columns, "market_specific_signals": market_specific}
    user = "\n\n".join([
        f"Product category: {product_category}. Signals differ by market: {'yes' if market_specific else 'no'}.",
        untrusted("research_question", research_question),
        brand,
        untrusted("markets", columns),
    ])
    return await llm.generate_structured(
        task="research_synthesis", stage=stage, agent="atlas", system=MARKETS_SYSTEM, user=user,
        schema=MarketSummaryOut, prompt_version=MARKETS_PROMPT_VERSION, temperature=0.3, fixture_context=payload,
    )
