"""Honesty and scoring invariants from contracts/README.md (§5 modes, §7 evidence, §8 scoring).

Pure functions over validated contract models. Each raises AssertionError with a precise message.
Used against contracts/fixtures (test_fixture_invariants.py) and against live API responses in the
demo journey, so both sides of the contract obey the same rules.

Where the contract is ambiguous the check is limited to what the text guarantees.
"""

from __future__ import annotations

import statistics
from collections.abc import Iterable, Mapping, Sequence
from uuid import UUID

from app.schemas.adaptations import Adaptation
from app.schemas.campaigns import CampaignContent, EvaluationCriteria
from app.schemas.common import DIMENSIONS, DimensionScores, RunMetadata
from app.schemas.discovery import BriefFinding, DiscoveryResult
from app.schemas.evaluations import CandidateResult, EvaluationResult
from app.schemas.evidence import EvidenceRecord
from app.schemas.projects import Brand
from app.schemas.reports import Report
from app.schemas.studies import Finding, RehearsalResult, Study, SyntheticReaction

DEMO_RETRIEVAL_MODES = frozenset({"fixture", "generated"})
DEMO_STEP_PROVIDERS = frozenset({"fixture", "nativeproof"})
FIXTURE_ORIGINS = frozenset({"hand_authored", "captured_live"})
# D-024: workflows verified from the official Qloo hackathon kit.
VERIFIED_QLOO_WORKFLOWS = frozenset(
    {
        "find_tags",
        "describe",
        "recommend",
        "rank",
        "where_popular",
        "compare_audiences",
        "audience_demographics",
        "entity_tags",
        "trends",
        "search_entities",  # E's adapter name for entity search (exec: describe; REST: /search), docs/04
    }
)
SCORING_VERSION = "mvp-1"
RUN_STAGES: dict[str, tuple[str, ...]] = {
    "market_discovery": ("resolving_references", "retrieving_affinities", "normalizing_evidence", "generating_brief"),
    "campaign_rehearsal": ("loading_context", "generating_reactions", "aggregating_results", "analyzing_reactions"),
    "campaign_adaptation": ("loading_context", "generating_adaptations", "checking_constraints", "reviewing_risks"),
    "campaign_evaluation": ("loading_candidates", "assessing_candidates", "scoring", "recommending"),
    # contract v2 (README §13)
    "cultural_profile": ("loading_evidence", "retrieving_context", "synthesizing_profile", "checking_evidence"),
    "market_comparison": ("discovering_markets", "assessing_evidence", "comparing_markets", "summarizing"),
    "campaign_arena": ("loading_variants", "analyzing_creatives", "generating_reactions", "scoring_variants"),
    "risk_scan": ("loading_content", "analyzing_creatives", "assessing_risks", "checking_evidence"),
    # contract v3 (README §14.1)
    "population_study": ("preparing_evidence", "constructing_population", "running_interviews", "analysing_results"),
    "social_simulation": ("building_network", "simulating_rounds", "analysing_dynamics", "summarizing"),
}
SOURCE_EVIDENCE_TYPES = frozenset({"qloo_source", "provider_result", "user_input"})
OBSERVED_CLAIM_EVIDENCE_TYPES = frozenset({"qloo_source", "provider_result", "user_input", "observed_outcome"})


# --------------------------------------------------------------------------- evidence (§5, §7)


def ui_label(record: EvidenceRecord) -> str:
    """The UI label from contracts/README.md §7: the first matching row wins."""
    if record.evidence_type == "observed_outcome":
        return "Observed outcome"
    if record.evidence_type == "synthetic_response" or record.claim_type == "synthetic":
        return "Synthetic"
    if record.evidence_type == "deterministic_calculation":
        return "Calculated"
    if record.claim_type == "hypothesis":
        return "Unverified"
    if record.evidence_type == "model_interpretation":
        return "Model interpretation"
    if record.evidence_type in SOURCE_EVIDENCE_TYPES:
        return "Source data"
    raise AssertionError(f"evidence {record.id}: no §7 label rule matches {record.evidence_type}/{record.claim_type}")


def check_evidence_semantics(record: EvidenceRecord) -> None:
    """Mode-independent honesty rules (FR-050/051, D-015)."""
    where = f"evidence {record.id} ({record.title!r})"
    ui_label(record)
    if record.claim_type == "observed":
        assert record.evidence_type in OBSERVED_CLAIM_EVIDENCE_TYPES, (
            f"{where}: claim_type 'observed' on a {record.evidence_type} record (only source data can be observed)"
        )
    if record.evidence_type == "synthetic_response":
        assert record.claim_type == "synthetic", f"{where}: synthetic responses must keep claim_type 'synthetic'"
    if record.evidence_type == "qloo_source":
        assert record.source_workflow in VERIFIED_QLOO_WORKFLOWS, (
            f"{where}: source_workflow {record.source_workflow!r} is not a verified Qloo workflow (D-024)"
        )
    if record.is_live_data:
        assert record.retrieval_mode in ("live", "cached"), f"{where}: is_live_data true with {record.retrieval_mode}"


def check_demo_evidence(records: Iterable[EvidenceRecord], project_id: UUID | None = None) -> None:
    """Every evidence record in a demo project is fixture/generated and never live (README §5, review C3)."""
    for record in records:
        where = f"evidence {record.id} ({record.title!r})"
        check_evidence_semantics(record)
        assert record.retrieval_mode in DEMO_RETRIEVAL_MODES, (
            f"{where}: demo retrieval_mode must be fixture|generated, got {record.retrieval_mode!r}"
        )
        assert record.is_live_data is False, f"{where}: demo evidence must have is_live_data false"
        assert record.evidence_type != "observed_outcome", f"{where}: a demo project has no observed outcomes"
        assert record.claim_type != "external_observation", f"{where}: a demo project has no external observations"
        if project_id is not None:
            assert record.project_id == project_id, f"{where}: project_id {record.project_id} != {project_id}"
        if record.retrieval_mode == "fixture":
            assert record.provenance is not None and record.provenance.fixture_origin in FIXTURE_ORIGINS, (
                f"{where}: fixture evidence must state provenance.fixture_origin (README §5)"
            )
        else:
            assert record.provenance is None or record.provenance.fixture_origin is None, (
                f"{where}: fixture_origin is set only for fixture evidence"
            )


def check_demo_run_metadata(metadata: RunMetadata, run_id: UUID | None = None, run_type: str | None = None) -> None:
    """Demo runs never call an external provider (README §5): steps are fixture or nativeproof only."""
    assert metadata.mode == "demo", f"run {metadata.run_id}: run_metadata.mode {metadata.mode!r} in a demo project"
    if run_id is not None:
        assert metadata.run_id == run_id, f"run_metadata.run_id {metadata.run_id} != {run_id}"
    assert metadata.steps, f"run {metadata.run_id}: no StepTrace recorded"
    for step in metadata.steps:
        if step.status == "skipped" and step.provider is None:  # nothing ran, so nothing was called
            continue
        # A stage that mixes fixture and local steps reports them joined ("fixture,nativeproof", the merge_steps).
        tokens = set((step.provider or "").split(","))
        assert tokens and tokens <= DEMO_STEP_PROVIDERS, (
            f"run {metadata.run_id} stage {step.stage}: provider {step.provider!r} in demo mode (expected fixture|nativeproof)"
        )
        assert not step.fallback_used, f"run {metadata.run_id} stage {step.stage}: fallback_used in demo mode"
    if run_type is not None:
        check_stage_order([step.stage for step in metadata.steps], run_type, f"run {metadata.run_id} steps")


def check_stage_order(stages: Sequence[str], run_type: str, where: str) -> None:
    expected = RUN_STAGES[run_type]
    unknown = [stage for stage in stages if stage not in expected]
    assert not unknown, f"{where}: stages {unknown} are not {run_type} stages {list(expected)} (README §6)"
    positions = [expected.index(stage) for stage in stages]
    assert positions == sorted(positions), f"{where}: stages {list(stages)} out of order (README §6)"


def check_refs(referenced: Iterable[UUID], available: set[UUID], where: str) -> None:
    missing = sorted({str(ref) for ref in referenced} - {str(ref) for ref in available})
    assert not missing, f"{where}: evidence ids {missing} are neither embedded nor in the project's evidence (DR-002)"


def evidence_index(records: Iterable[EvidenceRecord]) -> dict[UUID, EvidenceRecord]:
    index: dict[UUID, EvidenceRecord] = {}
    for record in records:
        assert record.id not in index, f"evidence {record.id} embedded twice"
        index[record.id] = record
    return index


def _has_qloo_observed(ids: Iterable[UUID], index: Mapping[UUID, EvidenceRecord]) -> bool:
    return any(
        (record := index.get(evidence_id)) is not None
        and record.evidence_type == "qloo_source"
        and record.claim_type == "observed"
        for evidence_id in ids
    )


def _has_source_evidence(ids: Iterable[UUID], index: Mapping[UUID, EvidenceRecord]) -> bool:
    return any((record := index.get(i)) is not None and record.evidence_type in SOURCE_EVIDENCE_TYPES for i in ids)


# --------------------------------------------------------------------------- discovery


def check_brief_finding(finding: BriefFinding, index: Mapping[UUID, EvidenceRecord], where: str) -> None:
    """§8 confidence for brief findings (D-028 cap). Brief findings have no supporting reactions."""
    where = f"{where} {finding.id}"
    qloo_observed = _has_qloo_observed(finding.evidence_ids, index)
    if finding.claim_type == "observed":
        assert qloo_observed, f"{where}: an 'observed' brief finding must cite observed Qloo evidence (FR-013)"
    if finding.claim_type == "observed" and qloo_observed:
        expected: set[str] = {"moderate"}
    elif not finding.evidence_ids:
        expected = {"insufficient"}
    elif _has_source_evidence(finding.evidence_ids, index):
        expected = {"limited"}
    else:  # only interpretations: the 'limited' and 'insufficient' rules both read on this case
        expected = {"limited", "insufficient"}
    assert finding.confidence_label in expected, f"{where}: confidence {finding.confidence_label!r}, §8 allows {sorted(expected)}"


def check_discovery(
    result: DiscoveryResult,
    *,
    demo: bool = True,
    project_id: UUID | None = None,
    run_id: UUID | None = None,
    request: Mapping[str, object] | None = None,
    project_evidence: Iterable[UUID] = (),
) -> None:
    index = evidence_index(result.evidence)
    available = set(index) | set(project_evidence)
    if run_id is not None:
        assert result.run_id == run_id, f"DiscoveryResult.run_id {result.run_id} != {run_id}"
    if project_id is not None:
        assert result.project_id == project_id
    for record in result.evidence:
        check_evidence_semantics(record)
    if demo:
        check_demo_evidence(result.evidence, project_id)
        check_demo_run_metadata(result.run_metadata, run_id, "market_discovery")
    ref_ids = [ref.id for ref in result.references]
    assert len(ref_ids) == len(set(ref_ids)), f"duplicate reference ids {ref_ids}"
    for ref in result.references:
        where = f"reference {ref.id} ({ref.query_term!r})"
        check_refs(ref.evidence_ids, available, where)
        if ref.match_status == "resolved":
            assert ref.entity_id and ref.name, f"{where}: resolved without entity_id/name"
        elif ref.match_status == "ambiguous":
            assert ref.entity_id is None, f"{where}: ambiguous references must not pick an entity (never auto-pick)"
            assert len(ref.candidates) >= 2, f"{where}: ambiguous needs at least two candidates to show"
        else:
            assert ref.entity_id is None and not ref.candidates, f"{where}: unresolved must not carry an entity"
    if result.market_brief is not None:
        for section in ("observations", "opportunities", "risks"):
            for finding in getattr(result.market_brief, section):
                check_refs(finding.evidence_ids, available, f"brief {section} {finding.id}")
                check_brief_finding(finding, index, f"brief {section}")
    if request is not None:
        terms = list(request.get("reference_terms", []))  # type: ignore[arg-type]
        assert result.reference_terms == terms, f"reference_terms {result.reference_terms} != request {terms}"
        assert result.product_category == request["product_category"]
        assert result.research_question == request["research_question"], "the user's question must be preserved (FR-010)"
        market = request["market"]
        assert result.market.country_code == market["country_code"]  # type: ignore[index]
        queried = {ref.query_term for ref in result.references}
        dropped = [term for term in terms if term not in queried]
        assert not dropped, f"requested terms {dropped} have no reference entry (silently dropped)"


def ambiguous_evidence_ids(result: DiscoveryResult) -> set[UUID]:
    return {evidence_id for ref in result.references if ref.match_status != "resolved" for evidence_id in ref.evidence_ids}


# --------------------------------------------------------------------------- rehearsal (§8 audience aggregation)


def aggregate_score(values: Sequence[int]) -> float | None:
    if not values:
        return None
    return round((statistics.fmean(values) - 1) / 4 * 100, 1)


def expected_disagreement(values: Sequence[int]) -> bool:
    n = len(values)
    if n < 3:
        return False
    spread = round(statistics.pstdev(values), 2)
    low = sum(v <= 2 for v in values) / n
    high = sum(v >= 4 for v in values) / n
    return spread >= 1.0 or (low >= 0.25 and high >= 0.25)


def ratings_for(reactions: Iterable[SyntheticReaction], dimension: str) -> list[int]:
    return [rating.value for reaction in reactions for rating in reaction.ratings if rating.dimension == dimension]


def expected_rehearsal_confidence(finding: Finding, index: Mapping[UUID, EvidenceRecord], n_reactions: int) -> str:
    support = len(set(finding.supporting_response_ids))
    share = support / n_reactions if n_reactions else 0.0
    if finding.claim_type == "synthetic" and _has_qloo_observed(finding.evidence_ids, index) and share >= 0.5:
        return "moderate"
    if support < 2 and not _has_source_evidence(finding.evidence_ids, index):
        return "insufficient"
    return "limited"


def check_rehearsal(
    result: RehearsalResult,
    *,
    demo: bool = True,
    study: Study | None = None,
    project_id: UUID | None = None,
    run_id: UUID | None = None,
    project_evidence: Iterable[UUID] = (),
    expect_grounded: bool | None = None,
) -> None:
    index = evidence_index(result.evidence)
    available = set(index) | set(project_evidence)
    reactions = result.reactions
    reaction_ids = [reaction.id for reaction in reactions]
    if run_id is not None:
        assert result.run_id == run_id
    for record in result.evidence:
        check_evidence_semantics(record)
    if demo:
        check_demo_evidence(result.evidence, project_id)
        check_demo_run_metadata(result.run_metadata, run_id, "campaign_rehearsal")

    disclosure = result.simulation_disclosure
    assert disclosure.is_synthetic is True and disclosure.independent_human_sample is False
    assert disclosure.description.strip(), "simulation disclosure needs a user-facing description"
    assert disclosure.generated_responses == len(reactions), (
        f"generated_responses {disclosure.generated_responses} != {len(reactions)} reactions returned"
    )
    if disclosure.grounded:
        assert disclosure.grounding_evidence_count > 0, "grounded without grounding evidence"
    else:
        assert disclosure.grounding_evidence_count == 0, "ungrounded run reports grounding evidence"
    if expect_grounded is not None:
        assert disclosure.grounded is expect_grounded, f"grounded {disclosure.grounded} != expected {expect_grounded}"
    if study is not None:
        assert result.study_id == study.id and result.campaign_id == study.campaign_id
        assert disclosure.requested_responses == study.simulation_config.response_count

    assert len(reaction_ids) == len(set(reaction_ids)), "duplicate reaction ids"
    segment_labels = [segment.label for segment in result.segments]
    for reaction in reactions:
        where = f"reaction {reaction.id}"
        assert reaction.is_synthetic is True, f"{where}: must be labeled synthetic"
        assert reaction.segment_label in segment_labels, f"{where}: unknown segment {reaction.segment_label!r}"
        dims = [rating.dimension for rating in reaction.ratings]
        assert len(dims) == len(set(dims)), f"{where}: a dimension is rated twice"
        if study is not None:
            assert set(dims) <= set(study.dimensions), f"{where}: rates dimensions the study did not request"
        check_refs(reaction.evidence_ids, available, where)

    assert sum(segment.response_count for segment in result.segments) == len(reactions), "segment counts != reactions"
    for segment in result.segments:
        members = [reaction for reaction in reactions if reaction.segment_label == segment.label]
        assert segment.response_count == len(members), f"segment {segment.label!r}: response_count mismatch"
        for dimension in DIMENSIONS:
            reported = getattr(segment.dimension_scores, dimension)
            expected = aggregate_score(ratings_for(members, dimension))
            assert reported == expected, f"segment {segment.label!r} {dimension}: {reported} != recomputed {expected}"

    for dimension in DIMENSIONS:
        reported = getattr(result.dimension_results, dimension)
        if study is not None and dimension not in study.dimensions:
            assert reported is None, f"dimension_results.{dimension} present but not requested"
            continue
        values = ratings_for(reactions, dimension)
        if reported is None:
            assert not values, f"dimension_results.{dimension} missing although reactions rated it"
            continue
        where = f"dimension_results.{dimension}"
        assert reported.dimension == dimension
        assert reported.n == len(values), f"{where}.n {reported.n} != {len(values)}"
        assert reported.distribution == [values.count(v) for v in range(1, 6)], f"{where}.distribution mismatch"
        assert reported.score == aggregate_score(values), f"{where}.score {reported.score} != {aggregate_score(values)}"
        spread = round(statistics.pstdev(values), 2) if values else None
        assert reported.spread == spread, f"{where}.spread {reported.spread} != {spread}"
        assert reported.disagreement == expected_disagreement(values), f"{where}.disagreement mismatch"
        assert reported.higher_is_better is (dimension != "cultural_risk"), f"{where}.higher_is_better wrong"
        assert reported.method == "deterministic_aggregation"

    if result.summary is not None:
        sections = ("key_findings", "potential_confusions", "potential_cultural_risks")
        for section in sections:
            for finding in getattr(result.summary, section):
                where = f"summary.{section} {finding.id}"
                unknown = set(map(str, finding.supporting_response_ids)) - set(map(str, reaction_ids))
                assert not unknown, f"{where}: supporting_response_ids {sorted(unknown)} are not reactions"
                check_refs(finding.evidence_ids, available, where)
                expected = expected_rehearsal_confidence(finding, index, len(reactions))
                assert finding.confidence_label == expected, (
                    f"{where}: confidence_label {finding.confidence_label!r} != §8 rule {expected!r}"
                )
        for disagreement in result.summary.disagreements:
            for cluster in disagreement.interpretations:
                unknown = set(map(str, cluster.response_ids)) - set(map(str, reaction_ids))
                assert not unknown, f"disagreement {disagreement.id}: response ids {sorted(unknown)} are not reactions"


# --------------------------------------------------------------------------- adaptation (§8 constraint checks)


def _content_text(content: CampaignContent) -> str:
    parts = [content.headline, content.body, content.call_to_action, *content.reference_terms]
    return " ".join(part for part in parts if part).casefold()


def check_adaptation(
    adaptation: Adaptation,
    *,
    brand: Brand,
    source_content: CampaignContent,
    request_protected_terms: Sequence[str] = (),
    demo: bool = True,
    project_id: UUID | None = None,
    run_id: UUID | None = None,
    project_evidence: Iterable[UUID] = (),
) -> None:
    where = f"adaptation {adaptation.id} ({adaptation.label!r})"
    index = evidence_index(adaptation.evidence)
    available = set(index) | set(project_evidence)
    for record in adaptation.evidence:
        check_evidence_semantics(record)
    if demo:
        assert adaptation.mode == "demo", f"{where}: mode {adaptation.mode!r} in a demo project"
        check_demo_evidence(adaptation.evidence, project_id)
    if project_id is not None:
        assert adaptation.project_id == project_id
    if run_id is not None:
        assert adaptation.run_id == run_id and adaptation.origin == "generated", f"{where}: not from run {run_id}"

    source_text, adapted_text = _content_text(source_content), _content_text(adaptation.content)
    protected = {term for term in [*brand.protected_terms, *request_protected_terms]}
    missing = {t.casefold() for t in protected if t.casefold() in source_text and t.casefold() not in adapted_text}
    reported_missing = {t.casefold() for t in adaptation.checks.missing_protected_terms}
    assert reported_missing == missing, f"{where}: missing_protected_terms {sorted(reported_missing)} != {sorted(missing)}"
    assert adaptation.checks.protected_terms_preserved is (not missing), f"{where}: protected_terms_preserved wrong"
    prohibited = {t.casefold() for t in brand.prohibited_terms if t.casefold() in adapted_text}
    reported_prohibited = {t.casefold() for t in adaptation.checks.prohibited_terms_found}
    assert reported_prohibited == prohibited, (
        f"{where}: prohibited_terms_found {sorted(reported_prohibited)} != {sorted(prohibited)}"
    )

    changed_fields = [change.field for change in adaptation.changes]
    assert len(changed_fields) == len(set(changed_fields)), f"{where}: a field has two change records"
    if adaptation.origin == "user_edit":  # may inherit the parent's model changes; a person's edits are user_edit
        for change in adaptation.changes:
            assert change.adapted == getattr(adaptation.content, change.field), f"{where}: 'adapted' is not the edit"
            if change.reasoning_type == "evidence_supported":
                assert change.evidence_ids, f"{where} change[{change.field}]: evidence_supported without evidence ids"
        return
    for change in adaptation.changes:
        assert change.reasoning_type != "user_edit", f"{where}: generated change typed user_edit"
        cwhere = f"{where} change[{change.field}]"
        if change.reasoning_type == "evidence_supported":
            assert change.evidence_ids, f"{cwhere}: evidence_supported without evidence ids"
        assert change.original == getattr(source_content, change.field), f"{cwhere}: 'original' is not the source text"
        assert change.adapted == getattr(adaptation.content, change.field), f"{cwhere}: 'adapted' is not the new text"
        check_refs(change.evidence_ids, available, cwhere)
    differing = {
        field
        for field in ("headline", "body", "call_to_action")
        if getattr(source_content, field) != getattr(adaptation.content, field)
    }
    unexplained = differing - set(changed_fields)
    assert not unexplained, f"{where}: changed fields {sorted(unexplained)} have no change record (07 §10.1 step 7)"

    context = adaptation.context
    if context.grounded:
        assert context.discovery_run_id is not None, f"{where}: grounded without a discovery run"
    assert context.rehearsal_informed is (context.rehearsal_run_id is not None), f"{where}: rehearsal_informed wrong"


def adaptation_has_violation(adaptation: Adaptation) -> bool:
    return bool(adaptation.checks.missing_protected_terms or adaptation.checks.prohibited_terms_found)


# --------------------------------------------------------------------------- evaluation (§8 Loop)


def exact_overall(scores: DimensionScores, criteria: EvaluationCriteria) -> float | None:
    values = {dimension: getattr(scores, dimension) for dimension in DIMENSIONS}
    if any(value is None for value in values.values()):
        return None
    utility = {d: (100 - v) if d == "cultural_risk" else v for d, v in values.items()}
    return sum(getattr(criteria, d) * utility[d] for d in DIMENSIONS)


def best_candidate(adaptations: Sequence[CandidateResult], request_order: Sequence[str]) -> CandidateResult | None:
    """Highest overall; ties → lower cultural_risk, then request order (§8)."""
    if not adaptations:
        return None
    order = {candidate_id: i for i, candidate_id in enumerate(request_order)}

    def key(candidate: CandidateResult) -> tuple[float, float, float]:
        overall = candidate.overall_score if candidate.overall_score is not None else float("-inf")
        risk = candidate.dimension_scores.cultural_risk
        return (overall, -(risk if risk is not None else float("inf")), -order.get(candidate.candidate_id, 10**6))

    return max(adaptations, key=key)


def expected_rule(original: CandidateResult, best: CandidateResult | None) -> tuple[str, str]:
    """(rule_id, decision) from rules R0-R5, first match wins."""
    if best is None or original.overall_score is None or best.overall_score is None:
        return "R0_missing_scores", "inconclusive"
    risk = best.dimension_scores.cultural_risk
    if best.constraint_violations or any(f.severity == "high" for f in best.risk_flags) or (risk is not None and risk >= 60):
        return "R1_constraint_or_risk", "revise"
    if best.overall_score < original.overall_score:
        return "R2_no_improvement", "revise"
    if best.overall_score - original.overall_score < 5:
        return "R3_small_margin", "validate"
    if best.overall_score >= 70 and risk is not None and risk < 40:
        return "R4_meets_review_threshold", "accept"
    return "R5_default", "validate"


def check_evaluation(
    evaluation: EvaluationResult,
    *,
    demo: bool = True,
    project_id: UUID | None = None,
    run_id: UUID | None = None,
    request: Mapping[str, object] | None = None,
    adaptations: Mapping[UUID, Adaptation] | None = None,
    source_content: CampaignContent | None = None,
    project_evidence: Iterable[UUID] = (),
    expect_comparable: bool = False,
) -> None:
    index = evidence_index(evaluation.evidence)
    available = set(index) | set(project_evidence)
    if run_id is not None:
        assert evaluation.run_id == run_id
    if project_id is not None:
        assert evaluation.project_id == project_id
    for record in evaluation.evidence:
        check_evidence_semantics(record)
    if demo:
        check_demo_evidence(evaluation.evidence, project_id)
        check_demo_run_metadata(evaluation.run_metadata, run_id, "campaign_evaluation")

    originals = [r for r in evaluation.results if r.candidate_type == "original"]
    candidates = [r for r in evaluation.results if r.candidate_type == "adaptation"]
    assert len(originals) == 1, f"expected exactly one original candidate, got {len(originals)}"
    original = originals[0]
    assert original.candidate_id == "original" and original.adaptation_id is None
    assert 1 <= len(candidates) <= 3, f"{len(candidates)} adaptation candidates (contract: 1-3)"
    ids = [r.candidate_id for r in evaluation.results]
    assert len(ids) == len(set(ids)), f"duplicate candidate ids {ids}"
    for candidate in candidates:
        assert candidate.adaptation_id is not None and candidate.candidate_id == str(candidate.adaptation_id)

    request_order = [str(c.adaptation_id) for c in candidates]
    if request is not None:
        request_order = [str(i) for i in request["candidate_adaptation_ids"]]  # type: ignore[union-attr]
        assert sorted(request_order) == sorted(c.candidate_id for c in candidates), "candidates != requested ids"
        criteria = request["criteria"]
        assert evaluation.criteria.model_dump() == criteria, f"criteria {evaluation.criteria} != request {criteria}"
        assert str(evaluation.source_content_version_id) == str(request["source_content_version_id"])

    for result in evaluation.results:
        where = f"candidate {result.candidate_id} ({result.label!r})"
        for dimension in DIMENSIONS:
            score = getattr(result.dimension_scores, dimension)
            if score is not None:
                assert float(score).is_integer(), f"{where}: {dimension} score {score} is not an integer 0-100 (§8)"
        exact = exact_overall(result.dimension_scores, evaluation.criteria)
        if exact is None:
            assert result.overall_score is None, f"{where}: overall must be null when a dimension is missing"
        else:
            assert result.overall_score is not None, f"{where}: overall missing although every dimension is scored"
            assert abs(result.overall_score - exact) <= 0.05 + 1e-9, (
                f"{where}: overall {result.overall_score} != round(sum(w*u), 1) of {exact:.4f} (§8)"
            )
            assert round(result.overall_score, 1) == result.overall_score, f"{where}: overall not rounded to 1 dp"
        check_refs(result.evidence_ids, available, where)
        if adaptations is not None and result.adaptation_id is not None:
            adaptation = adaptations[result.adaptation_id]
            assert result.content == adaptation.content, f"{where}: content differs from the stored adaptation"
            assert bool(result.constraint_violations) is adaptation_has_violation(adaptation), (
                f"{where}: constraint_violations disagree with the adaptation's deterministic checks"
            )
    if source_content is not None:
        assert original.content == source_content, "original candidate content differs from the source version"

    assert evaluation.scoring_version == SCORING_VERSION and evaluation.scoring_definition.version == SCORING_VERSION
    definitions = {d.dimension: d for d in evaluation.scoring_definition.dimensions}
    assert set(definitions) == set(DIMENSIONS), "scoring_definition must define all four dimensions"
    for dimension, definition in definitions.items():
        assert definition.higher_is_better is (dimension != "cultural_risk"), f"{dimension}.higher_is_better wrong"
        assert definition.definition.strip(), f"{dimension} needs a documented definition (FR-041)"

    best = best_candidate(candidates, request_order)
    rule_id, decision = expected_rule(original, best)
    recommendation = evaluation.recommendation
    if evaluation.status in ("completed", "partial"):
        assert recommendation is not None, "a completed evaluation needs a recommendation"
    if recommendation is not None:
        assert recommendation.rule_id == rule_id, f"rule_id {recommendation.rule_id} != expected {rule_id} (R0-R5)"
        assert recommendation.decision == decision, f"decision {recommendation.decision} != expected {decision}"
        assert recommendation.rationale.strip(), "recommendation needs a rationale"
        if decision in ("accept", "validate") and best is not None:
            assert recommendation.candidate_id == best.candidate_id, (
                f"recommendation.candidate_id {recommendation.candidate_id} != best {best.candidate_id}"
            )
        elif best is not None:
            assert recommendation.candidate_id in (None, best.candidate_id)
    if expect_comparable:
        c = evaluation.comparability
        assert c.same_market and c.same_criteria and c.same_source_version and c.same_scoring_version, (
            f"single-run evaluation reported non-comparable conditions: {c}"
        )


# --------------------------------------------------------------------------- report


def report_evidence_refs(report: Report) -> list[tuple[str, list[UUID]]]:
    refs: list[tuple[str, list[UUID]]] = []
    if report.discovery is not None:
        refs += [(f"report.discovery ref {r.id}", r.evidence_ids) for r in report.discovery.references]
        if report.discovery.market_brief is not None:
            for section in ("observations", "opportunities", "risks"):
                refs += [
                    (f"report.discovery brief {f.id}", f.evidence_ids)
                    for f in getattr(report.discovery.market_brief, section)
                ]
    if report.rehearsal is not None and report.rehearsal.summary is not None:
        for section in ("key_findings", "potential_confusions", "potential_cultural_risks"):
            refs += [(f"report.rehearsal {f.id}", f.evidence_ids) for f in getattr(report.rehearsal.summary, section)]
    for adaptation in report.adaptations:
        refs += [(f"report.adaptation {adaptation.id} {c.field}", c.evidence_ids) for c in adaptation.changes]
    if report.evaluation is not None:
        refs += [(f"report.evaluation {r.candidate_id}", r.evidence_ids) for r in report.evaluation.results]
    return refs


def check_report(report: Report, *, demo: bool = True, project_id: UUID | None = None, project_evidence: Iterable[UUID] = ()) -> None:
    register = evidence_index(report.evidence_register)
    available = set(register) | set(project_evidence)
    for record in report.evidence_register:
        check_evidence_semantics(record)
    if project_id is not None:
        assert report.project_id == project_id
    if demo:
        assert report.mode == "demo", f"report mode {report.mode!r} in a demo project"
        check_demo_evidence(report.evidence_register, project_id)
        for adaptation in report.adaptations:
            assert adaptation.mode == "demo"
            check_demo_evidence(adaptation.evidence, project_id)
        if report.evaluation is not None:
            check_demo_run_metadata(report.evaluation.run_metadata)
            check_demo_evidence(report.evaluation.evidence, project_id)
        for metadata in report.reproducibility.runs:
            check_demo_run_metadata(metadata)
    assert (report.status == "partial") is bool(report.missing_sections), (
        f"status {report.status!r} inconsistent with missing_sections {report.missing_sections}"
    )
    if report.rehearsal is not None:
        disclosure = report.rehearsal.simulation_disclosure
        assert disclosure.is_synthetic is True and disclosure.independent_human_sample is False
    if report.evaluation is not None:
        assert report.reproducibility.scoring_version == SCORING_VERSION
    for where, ids in report_evidence_refs(report):
        check_refs(ids, available, where)
