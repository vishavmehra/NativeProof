"""Scoring version mvp-1, exactly as contracts/README §8 defines it. Deterministic code, no model calls."""

import statistics
from collections.abc import Sequence
from uuid import UUID

from app.schemas.adaptations import Adaptation
from app.schemas.campaigns import CampaignContent, EvaluationCriteria
from app.schemas.common import DIMENSIONS, ConfidenceLabel, Dimension, DimensionScores, Market, RiskFlag
from app.schemas.evaluations import CandidateResult, Comparability, DimensionDefinition, Recommendation, ScoringDefinition
from app.schemas.evidence import EvidenceRecord
from app.schemas.studies import DimensionResult

SCORING_VERSION = "mvp-1"
SYNTHETIC_NOTE = "Derived from AI-generated reactions; not a measurement of real people."

# label, definition, higher_is_better (texts match scripts/build_contract_fixtures.py)
DEFINITIONS: dict[Dimension, tuple[str, str, bool]] = {
    "clarity": ("Clarity", "How easily the intended message is understood.", True),
    "brand_fidelity": ("Brand fidelity", "How well the content keeps the brand's voice and protected terms.", True),
    "cultural_relevance": ("Cultural relevance", "How relevant the content's references are to the target market.", True),
    "cultural_risk": (
        "Cultural risk",
        "Potential for misinterpretation, offense, or sensitivity issues. Higher means more risk.",
        False,
    ),
}

SCORING_DEFINITION = ScoringDefinition(
    version=SCORING_VERSION,
    scale="0-100 per dimension",
    dimensions=[
        DimensionDefinition(dimension=d, label=label, definition=text, higher_is_better=better)
        for d, (label, text, better) in DEFINITIONS.items()
    ],
    aggregation=(
        "overall = sum(weight_d * utility_d), where utility = score for clarity, brand_fidelity and "
        "cultural_relevance, and 100 - score for cultural_risk. Weights sum to 1. Overall is null when "
        "any dimension score is missing."
    ),
    recommendation_rules=[
        "R0_missing_scores: a score is missing for the original or the best candidate -> inconclusive",
        "R1_constraint_or_risk: best candidate has a constraint violation, a high-severity risk flag, "
        "or cultural_risk >= 60 -> revise",
        "R2_no_improvement: best candidate overall < original overall -> revise",
        "R3_small_margin: best candidate overall - original overall < 5 -> validate",
        "R4_meets_review_threshold: best candidate overall >= 70 and cultural_risk < 40 -> accept "
        "(for the next internal review, not proof of market success)",
        "R5_default: otherwise -> validate",
    ],
)


# --- Audience aggregation -------------------------------------------------------------------


def rating_score(values: Sequence[int]) -> float | None:
    return round((statistics.fmean(values) - 1) / 4 * 100, 1) if values else None


def aggregate(dimension: Dimension, values: Sequence[int]) -> DimensionResult:
    """score, distribution, spread (population SD, 1-5 scale) and the disagreement rule."""
    n = len(values)
    _, definition, higher_is_better = DEFINITIONS[dimension]
    if not n:
        return DimensionResult(
            dimension=dimension, score=None, higher_is_better=higher_is_better, n=0, distribution=[0] * 5,
            spread=None, disagreement=False, definition=definition,
            interpretation="No synthetic ratings were available.", limitations=[SYNTHETIC_NOTE],
        )
    mean = statistics.fmean(values)
    spread = statistics.pstdev(values)
    low = sum(v <= 2 for v in values) / n
    high = sum(v >= 4 for v in values) / n
    disagreement = n >= 3 and (spread >= 1.0 or (low >= 0.25 and high >= 0.25))
    note = " Ratings diverge; see the disagreement analysis." if disagreement else ""
    return DimensionResult(
        dimension=dimension, score=rating_score(values), higher_is_better=higher_is_better, n=n,
        distribution=[list(values).count(r) for r in range(1, 6)], spread=round(spread, 2),
        disagreement=disagreement, definition=definition,
        interpretation=f"Synthetic reactions averaged {mean:.2f} of 5 (n={n}).{note}",
        limitations=[SYNTHETIC_NOTE],
    )


# --- Evaluation ---------------------------------------------------------------------------------


def overall(scores: DimensionScores, criteria: EvaluationCriteria) -> float | None:
    values = [getattr(scores, d) for d in DIMENSIONS]
    if any(v is None for v in values):
        return None
    return round(
        sum(getattr(criteria, d) * (100 - v if d == "cultural_risk" else v) for d, v in zip(DIMENSIONS, values)), 1
    )


def _complete(scores: DimensionScores) -> bool:
    return all(getattr(scores, d) is not None for d in DIMENSIONS)


def best_candidate(results: Sequence[CandidateResult]) -> CandidateResult | None:
    """Highest overall among adaptations; ties: lower cultural_risk, then request order. Unscored rank last."""
    adaptations = [r for r in results if r.candidate_type == "adaptation"]
    if not adaptations:
        return None

    def key(item: tuple[int, CandidateResult]) -> tuple:
        index, r = item
        risk = r.dimension_scores.cultural_risk
        return (r.overall_score is None, -(r.overall_score or 0), float("inf") if risk is None else risk, index)

    return min(enumerate(adaptations), key=key)[1]


def recommend(original: CandidateResult | None, best: CandidateResult | None, market: Market) -> Recommendation:
    """Rules R0-R5; the first matching rule wins."""
    if original is None or best is None or not _complete(original.dimension_scores) or not _complete(best.dimension_scores):
        return Recommendation(
            decision="inconclusive", candidate_id=best.candidate_id if best else None, rule_id="R0_missing_scores",
            rationale="Required scores are missing for the original or the best candidate, so no comparison was made.",
        )
    risk = best.dimension_scores.cultural_risk
    margin = round(best.overall_score - original.overall_score, 1)
    versus = f"{best.label} scores {best.overall_score} against {original.overall_score} for the original"
    if best.constraint_violations or any(f.severity == "high" for f in best.risk_flags) or risk >= 60:
        reasons = (["a constraint violation"] if best.constraint_violations else []) + (
            ["a high-severity risk flag"] if any(f.severity == "high" for f in best.risk_flags) else []
        ) + ([f"assessed cultural risk {risk}"] if risk >= 60 else [])
        return Recommendation(
            decision="revise", candidate_id=best.candidate_id, rule_id="R1_constraint_or_risk",
            rationale=f"{best.label} has {' and '.join(reasons)}. Revise it before any further review.",
        )
    if margin < 0:
        return Recommendation(
            decision="revise", candidate_id=best.candidate_id, rule_id="R2_no_improvement",
            rationale=f"{versus}; no adaptation improved on the original under these criteria.",
        )
    if margin < 5:
        return Recommendation(
            decision="validate", candidate_id=best.candidate_id, rule_id="R3_small_margin",
            rationale=f"{versus}. Differences under 5 points are not treated as meaningful; validate with real people.",
        )
    if best.overall_score >= 70 and risk < 40:
        return Recommendation(
            decision="accept", candidate_id=best.candidate_id, rule_id="R4_meets_review_threshold",
            rationale=(
                f"{versus}, with assessed cultural risk {risk}. It meets the criteria for the next internal review; "
                f"this is not evidence of market performance. Test it with consumers in {market.display_name} before launch."
            ),
        )
    return Recommendation(
        decision="validate", candidate_id=best.candidate_id, rule_id="R5_default",
        rationale=f"{versus}, but it does not meet the review threshold (overall >= 70 and cultural risk < 40).",
    )


def tradeoff(candidate: DimensionScores, original: DimensionScores) -> str | None:
    """Deterministic score differences versus the original (model assessments, not measurements)."""
    parts = []
    for d in DIMENSIONS:
        a, b = getattr(candidate, d), getattr(original, d)
        if a is not None and b is not None and a != b:
            parts.append(f"{DEFINITIONS[d][0].lower()} {a - b:+g}")
    return f"Versus the original: {', '.join(parts)} (cultural risk: lower is better)." if parts else None


def comparability(market: Market, source_version_id: UUID, candidates: Sequence[Adaptation]) -> Comparability:
    """All candidates are assessed in one call, so criteria, model and scoring version are shared by design."""
    same_market = all(a.market.country_code == market.country_code for a in candidates)
    same_source = all(a.source_content_version_id == source_version_id for a in candidates)
    same_evidence = len({(a.context.discovery_run_id, a.context.rehearsal_run_id, a.context.grounded) for a in candidates}) <= 1
    notes = ["All candidates were assessed in one run with the same criteria, model, and scoring version."]
    if not same_market:
        notes.append("Some candidates were generated for a different market than the evaluation market.")
    if not same_source:
        notes.append("Some candidates were adapted from a different source content version.")
    if not same_evidence:
        notes.append("Candidates were generated with different evidence contexts (discovery or rehearsal runs).")
    return Comparability(
        same_market=same_market, same_criteria=True, same_source_version=same_source, same_scoring_version=True,
        same_evidence_context=same_evidence, same_model=True, notes=notes,
    )


# --- Confidence labels (not probabilities) --------------------------------------------------------


def is_source_observed(record: EvidenceRecord) -> bool:
    return record.evidence_type == "qloo_source" and record.claim_type == "observed"


def brief_confidence(claim_type: str, evidence: Sequence[EvidenceRecord]) -> ConfidenceLabel:
    if not evidence:
        return "insufficient"
    if claim_type == "observed" and any(is_source_observed(e) for e in evidence):
        return "moderate"
    return "limited"


def finding_confidence(claim_type: str, supporting: int, total: int, evidence: Sequence[EvidenceRecord]) -> ConfidenceLabel:
    has_source = any(is_source_observed(e) for e in evidence)
    if claim_type == "synthetic" and has_source and total and supporting / total >= 0.5:
        return "moderate"
    if supporting < 2 and not has_source:
        return "insufficient"
    return "limited"


# --- Deterministic constraint checks (case-insensitive) -------------------------------------------


def _copy_text(content: CampaignContent) -> str:
    return " ".join(p for p in (content.headline, content.body, content.call_to_action) if p).casefold()


def merge_terms(*groups: Sequence[str]) -> list[str]:
    seen: dict[str, str] = {}
    for group in groups:
        for term in group:
            if term.strip():
                seen.setdefault(term.strip().casefold(), term.strip())
    return list(seen.values())


def constraint_checks(
    source: CampaignContent, adapted: CampaignContent, protected_terms: Sequence[str], prohibited_terms: Sequence[str]
) -> tuple[list[str], list[str], list[RiskFlag]]:
    """(missing protected terms, prohibited terms found, deterministic warnings). Same semantics as
    app/services/adaptations.constraint_checks, so generated adaptations and user revisions agree."""
    source_text, adapted_text = _copy_text(source), _copy_text(adapted)
    missing = [t for t in protected_terms if t.casefold() in source_text and t.casefold() not in adapted_text]
    found = [t for t in prohibited_terms if t.casefold() in adapted_text]
    warnings = [
        RiskFlag(severity="high", category="constraint_violation", source="deterministic_check",
                 description=f"Protected term '{term}' from the source is missing.")
        for term in missing
    ] + [
        RiskFlag(severity="high", category="constraint_violation", source="deterministic_check",
                 description=f"Prohibited term '{term}' is present.")
        for term in found
    ]
    return missing, found, warnings
