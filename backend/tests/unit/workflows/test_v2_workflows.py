"""Contract v2 workflows in demo mode (fixture Qloo + fixture LLM), plus Brand Memory."""

from uuid import uuid4

from app.schemas.campaigns import DEFAULT_EVALUATION_CRITERIA, CampaignContent
from app.schemas.common import Market
from app.schemas.markets import MarketComparisonCreate
from app.schemas.profiles import CulturalProfileCreate
from app.schemas.projects import BrandExample
from app.workflows import (
    ArenaInput,
    ArenaVariantSpec,
    AssetBlob,
    CulturalProfileInput,
    DiscoverySource,
    MarketComparisonInput,
    RiskScanInput,
    run_arena,
    run_cultural_profile,
    run_discovery,
    run_market_comparison,
    run_risk_scan,
)
from app.workflows._common import DEMO_UPLOADS_MESSAGE, STAGES
from app.fixtures.demo_llm import VARIANTS
from tests.unit.workflows.scenario import BRAND, CONTENT, JP, STUDY, TERMS, Progress, context, demo_deps, discovery_input

KR = Market(country_code="KR", display_name="South Korea")


def variant(spec: dict) -> CampaignContent:
    return CampaignContent(headline=spec["headline"], body=spec["body"], call_to_action=spec["call_to_action"])


async def discovery_source(deps):
    out = await run_discovery(discovery_input(), deps)
    return DiscoverySource(run_id=uuid4(), market=JP, references=out.references, market_brief=out.market_brief, evidence=out.evidence)


async def test_cultural_profile_demo_grounds_every_item():
    deps, progress = demo_deps(), Progress()
    source = await discovery_source(deps)
    request = CulturalProfileCreate(subject="brand", title="Northstar in Japan", markets=[JP, KR])
    out = await run_cultural_profile(CulturalProfileInput(context=context(), profile_id=uuid4(), request=request,
                                                          discoveries=[source]), deps, progress)
    assert out.status == "completed" and [c[0] for c in progress.calls] == list(STAGES["cultural_profile"])
    labels = {(i.kind, i.claim_type, i.confidence_label) for i in out.items}
    assert ("affinity", "observed", "moderate") in labels and ("association", "observed", "moderate") in labels
    assert ("opportunity", "interpreted", "limited") in labels and ("conflict", "hypothesis", "insufficient") in labels
    ids = {e.id for e in source.evidence}
    assert all(set(i.evidence_ids) <= ids for i in out.items)
    assert all(i.claim_type == "hypothesis" for i in out.items if not i.evidence_ids)
    assert "No completed discovery for South Korea." in out.missing_evidence
    assert any("minimal design" in m for m in out.missing_evidence)
    assert "Protected term: Northstar" in out.brand_rules_applied


async def test_market_comparison_demo_marks_other_markets_unavailable():
    deps, progress = demo_deps(), Progress()
    request = MarketComparisonCreate(markets=[JP, KR], product_category="outdoor lifestyle apparel",
                                     research_question="Where should we launch first?", reference_terms=TERMS)
    out = await run_market_comparison(MarketComparisonInput(context=context(), comparison_id=uuid4(), request=request),
                                      deps, progress)
    assert [c[0] for c in progress.calls] == list(STAGES["market_comparison"])
    jp, kr = out.columns
    assert jp.status == "completed" and "Hiking" in {r.name for r in jp.signals} and len(jp.signals) == 2
    assert jp.evidence_quality.label == "moderate" and jp.evidence_quality.observed_records == 2
    assert jp.brand_compatibility.confidence_label == "limited" and jp.brand_compatibility.brand_rules_considered
    assert kr.status == "unavailable" and kr.signals == [] and kr.brand_compatibility is None and kr.message
    assert out.comparability.market_specific_signals is False
    assert out.cross_market_summary and out.status == "partial"


async def test_arena_demo_scores_fixture_variants_and_nulls_custom_text():
    deps, progress = demo_deps(), Progress()
    specs = [ArenaVariantSpec(variant_id="v0", label="Original", source="content_version", content=CONTENT)] + [
        ArenaVariantSpec(variant_id=f"v{i}", label=v["label"], source="adaptation", content=variant(v)) for i, v in enumerate(VARIANTS, 1)
    ] + [ArenaVariantSpec(variant_id="custom", label="Custom", source="custom", content=CampaignContent(headline="Made by us"),
                          asset=AssetBlob(asset_id=uuid4(), media_type="image/png", data=b"\x89PNG"))]
    out = await run_arena(ArenaInput(context=context(), arena_id=uuid4(), study=STUDY, variants=specs[:4] + specs[4:],
                                     criteria=DEFAULT_EVALUATION_CRITERIA), deps, progress)
    assert [c[0] for c in progress.calls] == list(STAGES["campaign_arena"])
    scores = {v.variant_id: v.overall_score for v in out.variants}
    assert scores["custom"] is None and all(scores[f"v{i}"] is not None for i in range(4))
    assert out.ranking[0] == "v1" and out.ranking[-1] == "custom"  # Clearer message first; unscored last
    assert "Demo fixtures cannot assess custom variants; their scores are null." in out.limitations
    assert out.vision.status == "unavailable" and out.vision.message == DEMO_UPLOADS_MESSAGE
    assert out.simulation_disclosure.generated_responses == 24 and out.status == "partial"
    assert all(i.claim_type in ("interpreted", "hypothesis") for i in out.recommended_improvements)
    assert out.segment_differences and out.tradeoffs and out.brand_rules_applied


async def test_risk_scan_demo_keeps_observation_separate_and_verifies_excerpts():
    deps, progress = demo_deps(), Progress()
    out = await run_risk_scan(RiskScanInput(context=context(), scan_id=uuid4(), market=JP, source_kind="content_version",
                                            content=CONTENT), deps, progress)
    assert out.status == "completed" and [c[0] for c in progress.calls] == list(STAGES["risk_scan"])
    assert len(out.findings) == 3 and all(f.source == "model_assessment" and f.status == "open" for f in out.findings)
    for f in out.findings:
        text = getattr(CONTENT, f.text_location.field)
        assert text[f.text_location.start:f.text_location.end] == f.text_location.excerpt == f.observation
        assert f.interpretation != f.observation
    custom = CONTENT.model_copy(update={"body": "A cheap escape for everyone."})
    gap = await run_risk_scan(RiskScanInput(context=context(), scan_id=uuid4(), market=JP, source_kind="custom", content=custom), deps)
    assert gap.status == "partial" and [f.source for f in gap.findings] == ["deterministic_check"]
    assert gap.findings[0].observation == "cheap" and gap.findings[0].brand_rule == "Prohibited term: cheap"
    assert "Demo fixtures cannot assess custom text; only deterministic brand checks ran." in gap.limitations


async def test_brand_memory_is_applied_read_only_and_recorded():
    brand = BRAND.model_copy(update={"constraints": ["Never mention price."], "positioning": "Premium trail gear",
                                     "approved_examples": [BrandExample(text=f"Example {i}") for i in range(5)]})
    before = brand.model_dump()
    deps = demo_deps()
    ctx = context().model_copy(update={"brand": brand})
    out = await run_risk_scan(RiskScanInput(context=ctx, scan_id=uuid4(), market=JP, source_kind="content_version",
                                            content=CONTENT), deps)
    assert "Constraint: Never mention price." in out.brand_rules_applied and "Positioning: Premium trail gear" in out.brand_rules_applied
    assert brand.model_dump() == before
