"""Deterministic analytics for scoring version mvp-1 (contracts/README §8)."""

from app.analytics.scoring import (
    DEFINITIONS,
    SCORING_DEFINITION,
    SCORING_VERSION,
    aggregate,
    best_candidate,
    brief_confidence,
    comparability,
    constraint_checks,
    finding_confidence,
    is_source_observed,
    merge_terms,
    overall,
    rating_score,
    recommend,
    tradeoff,
)

__all__ = [
    "DEFINITIONS",
    "SCORING_DEFINITION",
    "SCORING_VERSION",
    "aggregate",
    "best_candidate",
    "brief_confidence",
    "comparability",
    "constraint_checks",
    "finding_confidence",
    "is_source_observed",
    "merge_terms",
    "overall",
    "rating_score",
    "recommend",
    "tradeoff",
]
