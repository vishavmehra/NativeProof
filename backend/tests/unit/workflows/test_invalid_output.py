"""Defects #5 and #1: invalid model output is never half-persisted; missing Arena dimensions are explicit."""

from uuid import uuid4

import pytest

from app.fixtures.demo_llm import VARIANTS
from app.llm.fixture import FixtureLLMProvider
from app.llm.gateway import Completion, LLMError, LLMGateway
from app.llm.smoke import SmokeOut
from app.schemas.campaigns import DEFAULT_EVALUATION_CRITERIA, CampaignContent
from app.workflows import (
    ArenaInput,
    ArenaVariantSpec,
    EvaluationInput,
    RiskScanInput,
    WorkflowDeps,
    run_adaptation,
    run_arena,
    run_evaluation,
    run_rehearsal,
    run_risk_scan,
)
from tests.unit.workflows.scenario import (
    CONTENT,
    JP,
    STUDY,
    VERSION_ID,
    adaptation_input,
    context,
    demo_deps,
    offline_settings,
    rehearsal_input,
)

EMPTY, MALFORMED, SCHEMA_INVALID = "", '{"sentiment": "positive",', '{"sentiment": "unsure", "score": "high"}'


class Raw(FixtureLLMProvider):
    """Fixture provider whose answer for one prompt version is replaced by raw model text."""

    def __init__(self, prompt_version: str, text: str):
        super().__init__()
        self.prompt_version, self.text, self.calls = prompt_version, text, 0

    async def complete(self, request):
        if request.prompt_version == self.prompt_version:
            self.calls += 1
            return Completion(text=self.text)
        return await super().complete(request)


def deps_with(provider) -> WorkflowDeps:
    return WorkflowDeps(qloo=demo_deps().qloo, llm=LLMGateway(offline_settings(), provider=provider, backoff_seconds=0))


@pytest.mark.parametrize("text", [EMPTY, MALFORMED, SCHEMA_INVALID], ids=["empty", "malformed", "schema_invalid"])
async def test_gateway_rejects_invalid_output_after_one_repair(text):
    provider = Raw("p", text)
    with pytest.raises(LLMError) as caught:
        await LLMGateway(offline_settings(), provider=provider).generate_structured(
            task="extraction", stage="s", agent="a", system="s", user="u", schema=SmokeOut, prompt_version="p")
    assert caught.value.code == "RUN_FAILED" and caught.value.trace.status == "failed"
    assert provider.calls == 2  # the answer plus one constrained repair; never a transport retry


@pytest.mark.parametrize("text", [EMPTY, MALFORMED, SCHEMA_INVALID], ids=["empty", "malformed", "schema_invalid"])
async def test_invalid_analysis_keeps_valid_parts_and_reports_the_failure(text):
    out = await run_rehearsal(rehearsal_input([]), deps_with(Raw("analyst-v1", text)))
    assert out.status == "partial" and out.summary is None
    assert (out.error.code, out.error.stage) == ("RUN_FAILED", "analyzing_reactions")
    assert len(out.reactions) == 6 and out.dimension_results.clarity.score == 50.0


@pytest.mark.parametrize("text", [EMPTY, MALFORMED, SCHEMA_INVALID], ids=["empty", "malformed", "schema_invalid"])
async def test_invalid_generation_saves_nothing(text):
    adaptation = await run_adaptation(adaptation_input([]), deps_with(Raw("voice-adaptations-v1", text)))
    assert adaptation.status == "failed" and adaptation.adaptations == [] and adaptation.error.code == "RUN_FAILED"
    candidate = (await run_adaptation(adaptation_input([]), demo_deps())).adaptations[0]
    evaluation = await run_evaluation(EvaluationInput(
        context=context(), evaluation_id=uuid4(), source_content_version_id=VERSION_ID, source_content=CONTENT,
        candidates=[candidate], criteria=DEFAULT_EVALUATION_CRITERIA, market=JP,
    ), deps_with(Raw("loop-judge-v1", text)))
    assert evaluation.status == "failed" and evaluation.results == [] and evaluation.recommendation is None


async def test_partially_invalid_variants_are_not_saved_and_the_outcome_says_so():
    good = {"label": "Valid", "strategy": "s", "headline": "Trails await", "body": None, "call_to_action": None, "changes": []}
    bad = {"label": "No copy", "strategy": "s", "headline": None, "body": None, "call_to_action": None, "changes": []}
    provider = FixtureLLMProvider({**FixtureLLMProvider()._responders, "voice-adaptations-v1": lambda ctx: {"variants": [good, bad]}})
    out = await run_adaptation(adaptation_input([], variant_count=2), deps_with(provider))
    assert out.status == "partial" and [a.label for a in out.adaptations] == ["Valid"]
    assert out.error.code == "RUN_FAILED" and "1 generated variant(s) were invalid" in out.error.message


async def test_risk_findings_with_invented_excerpts_are_not_saved():
    invented = {"field": "headline", "excerpt": "free shipping", "category": "unsupported_claim", "severity": "high",
                "interpretation": "x"}
    provider = FixtureLLMProvider({**FixtureLLMProvider()._responders, "risk-scan-v2": lambda ctx: {"findings": [invented]}})
    out = await run_risk_scan(RiskScanInput(context=context(), scan_id=uuid4(), market=JP, source_kind="content_version",
                                            content=CONTENT), deps_with(provider))
    assert out.findings == [] and out.status == "partial" and out.error.code == "RUN_FAILED"


async def test_arena_missing_dimensions_give_null_overall_with_an_explicit_limitation():
    study = STUDY.model_copy(update={"dimensions": ["clarity", "cultural_risk"]})
    specs = [ArenaVariantSpec(variant_id="v0", label="Original", source="content_version", content=CONTENT),
             ArenaVariantSpec(variant_id="v1", label=VARIANTS[0]["label"], source="adaptation",
                              content=CampaignContent(headline=VARIANTS[0]["headline"], body=VARIANTS[0]["body"],
                                                      call_to_action=VARIANTS[0]["call_to_action"]))]
    out = await run_arena(ArenaInput(context=context(), arena_id=uuid4(), study=study, variants=specs,
                                     criteria=DEFAULT_EVALUATION_CRITERIA), demo_deps())
    assert [v.overall_score for v in out.variants] == [None, None]  # never renormalized over the scored dimensions
    assert all(v.dimension_results.clarity.score is not None for v in out.variants)
    assert out.ranking == ["v0", "v1"]  # all unscored: request order
    for label in ("Original", "Clearer message"):
        assert f"'{label}' has no overall score: no synthetic score for brand fidelity, cultural relevance. " \
               "Scores are never renormalized; unscored variants rank last." in out.limitations


def test_risk_alternative_replaces_exactly_the_excerpt():
    """the bug: applying 'next trail' to the excerpt 'great escape' gave 'Find your next next trail'."""
    from app.workflows.risk import fit_alternative

    text = "Find your next great escape"
    start = text.index("great escape")
    end = start + len("great escape")
    for suggestion in ("next trail", "your next trail", "trail"):
        fitted = fit_alternative(text, start, end, suggestion)
        assert text[:start] + fitted + text[end:] == "Find your next trail"
    body = "Built for the journeys that change you."
    s = body.index("journeys")
    assert fit_alternative(body, s, s + len("journeys"), "adventures that change") == "adventures"
    assert fit_alternative(text, start, end, "next") == "next"  # never trims the alternative to nothing
    assert fit_alternative(text, start, end, "   ") is None


async def test_risk_scan_stores_the_fitted_alternative():
    risky = {"field": "headline", "excerpt": "great escape", "category": "ambiguity", "severity": "medium",
             "interpretation": "Reads as a holiday.", "suggested_alternative": "next trail"}
    provider = FixtureLLMProvider({**FixtureLLMProvider()._responders, "risk-scan-v2": lambda ctx: {"findings": [risky]}})
    out = await run_risk_scan(RiskScanInput(context=context(), scan_id=uuid4(), market=JP, source_kind="content_version",
                                            content=CONTENT), deps_with(provider))
    assert [f.suggested_alternative for f in out.findings] == ["trail"]
