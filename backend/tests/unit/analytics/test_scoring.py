"""Scoring version mvp-1 against contracts/README §8 and the contract fixture numbers."""

import json
from pathlib import Path
from uuid import uuid4

import pytest

from app.analytics import (
    SCORING_DEFINITION,
    aggregate,
    best_candidate,
    brief_confidence,
    comparability,
    constraint_checks,
    finding_confidence,
    overall,
    recommend,
)
from app.schemas.campaigns import DEFAULT_EVALUATION_CRITERIA, CampaignContent
from app.schemas.common import DimensionScores, Market, RiskFlag
from app.schemas.evaluations import CandidateResult, DimensionRationales, EvaluationResult
from app.schemas.evidence import EvidenceRecord

FIXTURES = Path(__file__).resolve().parents[4] / "contracts" / "fixtures"
JP = Market(country_code="JP", display_name="Japan")
CONTENT = CampaignContent(headline="Find your next great escape")


def scores(c, b, r, k) -> DimensionScores:
    return DimensionScores(clarity=c, brand_fidelity=b, cultural_relevance=r, cultural_risk=k)


def candidate(key: str, s: DimensionScores, *, kind="adaptation", violations=(), flags=()) -> CandidateResult:
    return CandidateResult(
        candidate_id=key, candidate_type=kind, adaptation_id=None if kind == "original" else uuid4(), label=key,
        content=CONTENT, dimension_scores=s, dimension_rationales=DimensionRationales(),
        overall_score=overall(s, DEFAULT_EVALUATION_CRITERIA), risk_flags=list(flags),
        constraint_violations=list(violations), strengths=[], weaknesses=[], tradeoffs=[], evidence_ids=[],
    )


def evidence(kind="qloo_source", claim="observed") -> EvidenceRecord:
    return EvidenceRecord.model_validate(json.loads((FIXTURES / "EvidenceRecord.json").read_text())).model_copy(
        update={"evidence_type": kind, "claim_type": claim}
    )


def test_aggregation_matches_contract_story():
    result = aggregate("clarity", [4, 3, 2, 4, 2, 3])
    assert (result.score, result.spread, result.disagreement, result.n) == (50.0, 0.82, True, 6)
    assert result.distribution == [0, 2, 2, 2, 0] and result.higher_is_better


def test_aggregation_edge_cases():
    assert aggregate("clarity", []).score is None
    assert not aggregate("clarity", [3, 3, 3]).disagreement
    assert not aggregate("clarity", [1, 5]).disagreement  # n < 3
    assert aggregate("clarity", [1, 1, 5, 5]).disagreement  # spread 2.0
    assert aggregate("cultural_risk", [5, 5, 5]).higher_is_better is False


def test_overall_matches_contract_story_and_requires_every_dimension():
    assert overall(scores(55, 84, 50, 30), DEFAULT_EVALUATION_CRITERIA) == 63.0
    assert overall(scores(78, 80, 70, 20), DEFAULT_EVALUATION_CRITERIA) == 76.4
    assert overall(scores(70, 92, 58, 22), DEFAULT_EVALUATION_CRITERIA) == 73.1
    assert overall(DimensionScores(clarity=70, brand_fidelity=92, cultural_relevance=58), DEFAULT_EVALUATION_CRITERIA) is None


def test_contract_story_recommends_r4_accept():
    original = candidate("original", scores(55, 84, 50, 30), kind="original")
    clearer, brand_first = candidate("clearer", scores(78, 80, 70, 20)), candidate("brand", scores(70, 92, 58, 22))
    best = best_candidate([original, clearer, brand_first])
    assert best is clearer
    rec = recommend(original, best, JP)
    assert (rec.decision, rec.rule_id, rec.candidate_id) == ("accept", "R4_meets_review_threshold", "clearer")


def test_best_candidate_tie_breaks():
    low_risk = candidate("low-risk", scores(80, 80, 80, 20))
    high_risk = candidate("high-risk", scores(80, 80, 80, 20).model_copy(update={"cultural_risk": 20}))
    assert best_candidate([high_risk, low_risk]) is high_risk  # same overall and risk: request order
    a, b = candidate("a", scores(70, 70, 70, 40)), candidate("b", scores(76, 70, 64, 40))
    assert a.overall_score == b.overall_score
    unscored = candidate("unscored", DimensionScores())
    assert best_candidate([unscored, a]) is a
    assert best_candidate([unscored]) is unscored
    tie_lower_risk = [candidate("x", scores(70, 70, 70, 30)), candidate("y", scores(70, 70, 64, 18))]
    assert tie_lower_risk[0].overall_score == tie_lower_risk[1].overall_score
    assert best_candidate(tie_lower_risk).candidate_id == "y"


@pytest.mark.parametrize(
    ("best", "decision", "rule"),
    [
        (candidate("b", DimensionScores(clarity=90)), "inconclusive", "R0_missing_scores"),
        (candidate("b", scores(90, 90, 90, 10), violations=["Missing protected term: Northstar"]), "revise", "R1_constraint_or_risk"),
        (candidate("b", scores(90, 90, 90, 10), flags=[RiskFlag(severity="high", category="stereotype", description="x", source="model_assessment")]), "revise", "R1_constraint_or_risk"),
        (candidate("b", scores(95, 95, 95, 60)), "revise", "R1_constraint_or_risk"),
        (candidate("b", scores(50, 50, 50, 30)), "revise", "R2_no_improvement"),
        (candidate("b", scores(65, 84, 55, 30)), "validate", "R3_small_margin"),
        (candidate("b", scores(80, 84, 75, 30)), "accept", "R4_meets_review_threshold"),
        (candidate("b", scores(80, 84, 75, 45)), "validate", "R5_default"),
    ],
)
def test_recommendation_rules(best, decision, rule):
    original = candidate("original", scores(55, 84, 50, 30), kind="original")
    rec = recommend(original, best, JP)
    assert (rec.decision, rec.rule_id) == (decision, rule)


def test_missing_original_scores_and_margin_boundary():
    unscored = candidate("original", DimensionScores(), kind="original")
    assert recommend(unscored, candidate("b", scores(90, 90, 90, 10)), JP).rule_id == "R0_missing_scores"
    assert recommend(None, None, JP).rule_id == "R0_missing_scores"
    original = candidate("original", scores(60, 60, 60, 40), kind="original")  # 60.0
    exactly_five = candidate("b", scores(70, 68, 60, 40))  # 65.0: margin 5 is not "< 5"
    assert exactly_five.overall_score - original.overall_score == 5.0
    assert recommend(original, exactly_five, JP).rule_id == "R5_default"
    under = candidate("b", scores(70, 68, 60, 42))  # 64.7
    assert recommend(original, under, JP).rule_id == "R3_small_margin"


def test_constraint_checks_are_case_insensitive_and_source_relative():
    source = CampaignContent(headline="Northstar: find your next escape", body="Built for journeys.")
    missing, found, warnings = constraint_checks(source, CampaignContent(headline="A cheap escape"), ["northstar", "Trail"], ["Cheap"])
    assert missing == ["northstar"]  # "Trail" never appeared in the source, so it is not required
    assert found == ["Cheap"]
    assert [w.source for w in warnings] == ["deterministic_check"] * 2 and all(w.severity == "high" for w in warnings)
    kept = constraint_checks(source, CampaignContent(headline="NORTHSTAR, built for the trail"), ["Northstar"], ["cheap"])
    assert kept == ([], [], [])


def test_confidence_labels_follow_contract_rules():
    qloo, interp = evidence(), evidence("model_interpretation", "interpreted")
    assert brief_confidence("observed", [qloo]) == "moderate"
    assert brief_confidence("interpreted", [qloo, interp]) == "limited"  # interpreted is capped
    assert brief_confidence("observed", [interp]) == "limited"
    assert brief_confidence("hypothesis", []) == "insufficient"
    assert finding_confidence("synthetic", 3, 6, [qloo]) == "moderate"
    assert finding_confidence("synthetic", 2, 6, [qloo]) == "limited"  # under 50% support
    assert finding_confidence("hypothesis", 6, 6, [qloo]) == "limited"  # hypothesis is capped
    assert finding_confidence("synthetic", 2, 6, []) == "limited"
    assert finding_confidence("hypothesis", 1, 6, []) == "insufficient"
    assert finding_confidence("synthetic", 0, 6, [interp]) == "insufficient"


def test_scoring_definition_matches_contract_fixture():
    fixture = EvaluationResult.model_validate_json((FIXTURES / "EvaluationResult.json").read_bytes())
    assert SCORING_DEFINITION == fixture.scoring_definition


def test_comparability_flags():
    fixture = EvaluationResult.model_validate_json((FIXTURES / "EvaluationResult.json").read_bytes())
    adaptation = json.loads((FIXTURES / "Adaptation.json").read_text())
    from app.schemas.adaptations import Adaptation

    a = Adaptation.model_validate(adaptation)
    same = comparability(JP, a.source_content_version_id, [a])
    assert same.same_source_version and same.same_market and same.same_evidence_context and same.notes == fixture.comparability.notes
    other = a.model_copy(update={"source_content_version_id": uuid4(), "market": Market(country_code="KR", display_name="Korea")})
    flags = comparability(JP, a.source_content_version_id, [a, other])
    assert not flags.same_source_version and not flags.same_market and len(flags.notes) == 3
