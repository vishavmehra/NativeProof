"""Analyst agent: findings, disagreement clusters, and validation questions over synthetic reactions (docs/03 A4).

Every finding must reference real reaction ids; code drops unknown ids and assigns confidence labels by rule.
"""

from dataclasses import dataclass
from typing import ClassVar, Literal

from pydantic import Field

from app.agents._common import DROPPED_NOTE, EVIDENCE_RULES, Strict, content_dict, norm, pick, untrusted
from app.analytics import finding_confidence
from app.analytics.scoring import SYNTHETIC_NOTE
from app.llm.gateway import LLMGateway
from app.schemas.campaigns import CampaignContent
from app.schemas.common import Dimension, StepTrace
from app.schemas.evidence import EvidenceRecord
from app.schemas.studies import (
    DimensionResults,
    Disagreement,
    Finding,
    FindingCategory,
    InterpretationCluster,
    RehearsalSummary,
    SyntheticReaction,
)

PROMPT_VERSION = "analyst-v1"
SINGLE_REACTION_NOTE = "Raised by a single synthetic reaction."


class FindingOut(Strict):
    category: FindingCategory
    title: str = Field(max_length=200)
    summary: str = Field(max_length=800)
    supporting_reactions: list[str] = Field(max_length=24, description="Reaction handles, e.g. R1.")
    evidence: list[str] = Field(default=[], max_length=6)
    claim_type: Literal["synthetic", "interpreted", "hypothesis"]


class ClusterOut(Strict):
    label: str = Field(max_length=120)
    summary: str = Field(max_length=400)
    reactions: list[str] = Field(max_length=24)


class DisagreementOut(Strict):
    topic: str = Field(max_length=200)
    dimension: Dimension | None = None
    interpretations: list[ClusterOut] = Field(min_length=2, max_length=5)
    possible_explanations: list[str] = Field(max_length=4)
    validation_question: str = Field(max_length=300)


class AnalystOut(Strict):
    schema_version: ClassVar[str] = "rehearsal-summary-v1"
    key_findings: list[FindingOut] = Field(default=[], max_length=6)
    potential_confusions: list[FindingOut] = Field(default=[], max_length=5)
    potential_cultural_risks: list[FindingOut] = Field(default=[], max_length=5)
    disagreements: list[DisagreementOut] = Field(default=[], max_length=4)
    validation_questions: list[str] = Field(default=[], max_length=6)


SYSTEM = f"""You are the Analyst in Nativeproof. Analyze AI-generated synthetic reactions to a campaign.
They are not real people: never describe them as survey results, never infer statistical significance, and do not
hide disagreement behind averages. Every finding must cite the reaction handles (R1, R2, ...) that support it.
claim_type: synthetic = a pattern visible in the reactions; interpreted = your interpretation of it; hypothesis = a
possible cause or risk that needs validation. Possible explanations of disagreement are hypotheses. Group materially
different interpretations into clusters and propose questions for validation with real people. The deterministic
scores are already computed; do not restate or invent numbers.
{EVIDENCE_RULES}"""


@dataclass
class AnalysisResult:
    summary: RehearsalSummary
    trace: StepTrace
    notes: list[str]


async def analyze(
    llm: LLMGateway, *, stage: str, reactions: list[SyntheticReaction], dimension_results: DimensionResults,
    dimensions: list[Dimension], research_questions: list[str], content: CampaignContent,
    evidence: list[dict], handles: dict[str, EvidenceRecord],
) -> AnalysisResult:
    reaction_of = {f"R{i}": r for i, r in enumerate(reactions, 1)}
    reaction_rows = [
        {
            "reaction": handle, "segment": r.segment_label, "sentiment": r.sentiment, "interpretation": r.interpretation,
            "summary": r.reaction_summary, "ratings": {x.dimension: x.value for x in r.ratings},
            "confusion_level": r.confusion_level, "confusions": r.potential_confusions,
            "risks": [f.description for f in r.risk_flags],
        }
        for handle, r in reaction_of.items()
    ]
    scores = [
        {"dimension": d, "score": res.score, "spread": res.spread, "disagreement": res.disagreement, "n": res.n}
        for d in dimensions
        if (res := getattr(dimension_results, d)) is not None
    ]
    payload = {"reactions": reaction_rows, "scores": scores, "evidence": evidence}
    user = "\n\n".join([
        untrusted("research_questions", research_questions),
        untrusted("campaign_content", content_dict(content)),
        "Deterministic scores (0-100; spread is the SD of 1-5 ratings):",
        untrusted("scores", scores),
        untrusted("synthetic_reactions", reaction_rows),
        untrusted("evidence", evidence),
    ])
    result = await llm.generate_structured(
        task="research_synthesis", stage=stage, agent="analyst",
        system=SYSTEM, user=user, schema=AnalystOut, prompt_version=PROMPT_VERSION, temperature=0.2,
        fixture_context=payload,
    )
    out = result.value
    ids = {norm(h): r.id for h, r in reaction_of.items()}
    dropped = 0

    def findings(prefix: str, items: list[FindingOut]) -> list[Finding]:
        nonlocal dropped
        built = []
        for i, item in enumerate(items, 1):
            support, lost_r = pick(item.supporting_reactions, ids)
            cited, lost_e = pick(item.evidence, handles)
            dropped += lost_r + lost_e
            built.append(
                Finding(
                    id=f"{prefix}-{i}", category=item.category, title=item.title, summary=item.summary,
                    supporting_response_ids=support, evidence_ids=[e.id for e in cited],
                    method="synthetic_response_analysis", claim_type=item.claim_type,
                    confidence_label=finding_confidence(item.claim_type, len(support), len(reactions), cited),
                    limitations=[SYNTHETIC_NOTE] + ([SINGLE_REACTION_NOTE] if len(support) == 1 else []),
                )
            )
        return built

    disagreements = []
    for item in out.disagreements:
        clusters = []
        for c in item.interpretations:
            members, lost = pick(c.reactions, ids)
            dropped += lost
            if members:
                clusters.append(InterpretationCluster(label=c.label, summary=c.summary, response_ids=members))
        if len(clusters) < 2:  # a disagreement needs two supported readings
            dropped += 1
            continue
        dimension = item.dimension if item.dimension in dimensions else None
        result_d = getattr(dimension_results, dimension) if dimension else None
        disagreements.append(
            Disagreement(
                id=f"dg-{len(disagreements) + 1}", topic=item.topic, dimension=dimension, interpretations=clusters,
                possible_explanations=[e if e.lower().startswith("hypothesis") else f"Hypothesis: {e}" for e in item.possible_explanations],
                validation_question=item.validation_question, spread=result_d.spread if result_d else None,
            )
        )
    questions = out.validation_questions or [d.validation_question for d in disagreements]
    summary = RehearsalSummary(
        key_findings=findings("kf", out.key_findings),
        potential_confusions=findings("cf", out.potential_confusions),
        potential_cultural_risks=findings("cr", out.potential_cultural_risks),
        disagreements=disagreements,
        validation_questions=list(dict.fromkeys(questions)),
    )
    return AnalysisResult(summary, result.trace, [DROPPED_NOTE] if dropped else [])
