"""Contract v2 features in demo mode, plus the v2 behaviour rules (contracts/README.md §13, D-027).

Brand Memory, Cultural DNA, Market Expansion, Trend Watch, Campaign Arena, Risk Radar, Evidence Graph, Search,
and Assets — validated against their contract models and the honesty rules.
"""

from typing import Any

import httpx

from app.schemas.adaptations import Adaptation
from app.schemas.arena import ArenaPage, ArenaResult
from app.schemas.campaigns import Campaign
from app.schemas.common import DIMENSIONS, DimensionScores
from app.schemas.graph import EvidenceGraph
from app.schemas.markets import MarketComparison, MarketComparisonPage
from app.schemas.profiles import CulturalProfile, CulturalProfilePage
from app.schemas.projects import Brand
from app.schemas.risk import RiskFinding, RiskScan, RiskScanPage
from app.schemas.search import SearchResults
from app.schemas.trends import Snapshot, SnapshotPage, TrendComparison
from tests.integration import invariants as inv
from tests.integration._support import API, detail_fields, expect_error, parse
from tests.integration.journey import DISCOVERY_REQUEST, JAPAN, Journey, discover, full_journey, project_evidence_ids
from tests.integration.v2_support import PNG, run_resource, upload

FRANCE = {"country_code": "FR", "display_name": "France"}
CUSTOM = {"headline": "Northstar trail layers, ready for the weekend", "body": "Light, warm, and quiet on the trail."}
NO_UPLOAD_ANALYSIS = "Demo projects do not analyze uploads"


def _variants(journey: Journey) -> list[dict[str, Any]]:
    return [
        {"label": "Original", "content_version_id": str(journey.version_id)},
        {"label": "Adapted", "adaptation_id": str(journey.adaptations[0].id)},
        {"label": "Custom", "content": CUSTOM},
    ]


async def _arena(client: httpx.AsyncClient, journey: Journey) -> tuple[Any, ArenaResult]:
    body = {
        "study_id": str(journey.study.id),  # type: ignore[union-attr]
        "variants": _variants(journey),
        "criteria": journey.campaign.evaluation_criteria.model_dump(),
        "discovery_run_id": str(journey.discovery_run.id),  # type: ignore[union-attr]
    }
    return await run_resource(
        client, journey.headers, f"{API}/campaigns/{journey.campaign_id}/arenas", body, "campaign_arena", "arena", ArenaResult
    )


async def _risk_scan(client: httpx.AsyncClient, journey: Journey, **extra: Any) -> tuple[Any, RiskScan]:
    body = {"market": JAPAN, **extra}
    return await run_resource(
        client, journey.headers, f"{API}/campaigns/{journey.campaign_id}/risk-scans", body, "risk_scan", "risk_scan", RiskScan
    )


async def _profile(client: httpx.AsyncClient, journey: Journey, **extra: Any) -> tuple[Any, CulturalProfile]:
    body = {
        "subject": "brand",
        "title": "Northstar in Japan",
        "markets": [JAPAN],
        "discovery_run_ids": [str(journey.discovery_run.id)],  # type: ignore[union-attr]
        **extra,
    }
    return await run_resource(
        client, journey.headers, f"{API}/projects/{journey.project_id}/cultural-profiles", body, "cultural_profile",
        "cultural_profile", CulturalProfile,
    )


# --------------------------------------------------------------------------- Brand Memory


async def test_brand_memory_is_read_only_in_demo(qa_client: httpx.AsyncClient, alice: dict[str, str]) -> None:
    journey = await full_journey(qa_client, alice, check=False)
    path = f"{API}/projects/{journey.project_id}/brand"
    brand = parse(Brand, await qa_client.get(path, headers=alice))
    assert brand.name == journey.project.brand.name
    expect_error(await qa_client.put(path, json={"name": "Hijacked"}, headers=alice), 409, "CONFLICT")
    assert parse(Brand, await qa_client.get(path, headers=alice)) == brand


async def test_only_people_write_brand_memory(qa_client: httpx.AsyncClient, alice: dict[str, str]) -> None:
    """No model output is saved into Brand Memory: every v2 workflow leaves it byte-identical."""
    journey = await full_journey(qa_client, alice, check=False)
    path = f"{API}/projects/{journey.project_id}/brand"
    before = parse(Brand, await qa_client.get(path, headers=alice))
    await _profile(qa_client, journey)
    await _arena(qa_client, journey)
    await _risk_scan(qa_client, journey)
    body = {**DISCOVERY_REQUEST, "markets": [JAPAN, FRANCE]}
    body.pop("market")
    await run_resource(
        qa_client, alice, f"{API}/projects/{journey.project_id}/market-comparisons", body, "market_comparison",
        "market_comparison", MarketComparison,
    )
    assert parse(Brand, await qa_client.get(path, headers=alice)) == before, "a workflow wrote Brand Memory"


# --------------------------------------------------------------------------- Cultural DNA


async def test_cultural_profile_is_grounded_and_versioned(qa_client: httpx.AsyncClient, alice: dict[str, str]) -> None:
    journey = await full_journey(qa_client, alice, check=False)
    run, profile = await _profile(qa_client, journey)
    assert profile.mode == "demo" and profile.version == 1 and profile.run_id == run.id
    assert profile.brand_name == journey.project.brand.name
    assert journey.discovery_run.id in profile.source_discovery_run_ids  # type: ignore[union-attr]
    inv.check_demo_evidence(profile.evidence, journey.project_id)
    assert profile.run_metadata is not None
    inv.check_demo_run_metadata(profile.run_metadata, run.id, "cultural_profile")
    index = inv.evidence_index(profile.evidence)
    available = set(index) | await project_evidence_ids(qa_client, journey)
    assert profile.items, "a grounded demo profile should have items"
    for item in profile.items:
        inv.check_refs(item.evidence_ids, available, f"profile item {item.id}")
        if not item.evidence_ids:
            assert (item.claim_type, item.confidence_label) == ("hypothesis", "insufficient"), f"ungrounded item {item.id}"
        if item.claim_type in ("interpreted", "hypothesis"):
            assert item.confidence_label != "moderate", f"item {item.id}: interpreted/hypothesis capped at limited (D-028)"
        if item.confidence_label == "moderate":
            assert inv._has_qloo_observed(item.evidence_ids, index), f"item {item.id}: moderate needs observed Qloo evidence"

    _, second = await _profile(qa_client, journey, based_on_profile_id=str(profile.id))
    assert second.id != profile.id and second.lineage_id == profile.lineage_id and second.version == 2
    again = parse(CulturalProfile, await qa_client.get(f"{API}/cultural-profiles/{profile.id}", headers=alice))
    assert again == profile, "regenerating must never overwrite an earlier version"
    patched = parse(
        CulturalProfile,
        await qa_client.patch(f"{API}/cultural-profiles/{second.id}", json={"title": "Renamed", "notes": "Checked"}, headers=alice),
    )
    assert (patched.title, patched.notes, patched.items) == ("Renamed", "Checked", second.items)
    page = parse(CulturalProfilePage, await qa_client.get(f"{API}/projects/{journey.project_id}/cultural-profiles", headers=alice))
    assert {p.id for p in page.items} == {profile.id, second.id}


# --------------------------------------------------------------------------- Market Expansion


async def test_market_comparison_never_fills_unavailable_markets(qa_client: httpx.AsyncClient, alice: dict[str, str]) -> None:
    journey = await full_journey(qa_client, alice, check=False)
    body = {**DISCOVERY_REQUEST, "markets": [JAPAN, FRANCE], "campaign_id": str(journey.campaign_id)}
    body.pop("market")
    run, comparison = await run_resource(
        qa_client, alice, f"{API}/projects/{journey.project_id}/market-comparisons", body, "market_comparison",
        "market_comparison", MarketComparison,
    )
    assert comparison.mode == "demo" and comparison.run_id == run.id
    inv.check_demo_evidence(comparison.evidence, journey.project_id)
    inv.check_demo_run_metadata(comparison.run_metadata, run.id, "market_comparison")
    assert [c.market.country_code for c in comparison.columns] == ["JP", "FR"], "one column per market, in request order"
    japan, france = comparison.columns
    assert france.status == "unavailable" and france.message, "non-JP demo columns are unavailable with a reason (§13)"
    assert not (france.signals or france.opportunities or france.risks or france.hypotheses), "insight invented for FR"
    assert france.gaps, "an unavailable market names the gap"
    assert japan.status in ("completed", "partial")
    quality = japan.evidence_quality
    statuses = [ref.match_status for ref in japan.signals]
    # `signals` may list only usable (resolved) references while the quality counts cover every lookup.
    assert quality.resolved_references == statuses.count("resolved"), "resolved count disagrees with the signals shown"
    assert quality.ambiguous_references >= statuses.count("ambiguous") and quality.unresolved_references >= statuses.count("unresolved")
    available = {e.id for e in comparison.evidence} | await project_evidence_ids(qa_client, journey)
    for finding in [*japan.opportunities, *japan.risks, *japan.hypotheses]:
        inv.check_refs(finding.evidence_ids, available, f"JP finding {finding.id}")
    for hypothesis in japan.hypotheses:
        assert hypothesis.claim_type == "hypothesis" and hypothesis.confidence_label != "moderate"
    if not comparison.comparability.market_specific_signals:
        assert comparison.comparability.notes, "say why markets cannot be ranked on these signals"
    page = parse(MarketComparisonPage, await qa_client.get(f"{API}/projects/{journey.project_id}/market-comparisons", headers=alice))
    assert [c.id for c in page.items] == [comparison.id]


# --------------------------------------------------------------------------- Trend Watch


def _trend_signature(comparison: TrendComparison) -> object:
    return (
        comparison.comparable,
        comparison.comparability_notes,
        [c.model_dump(exclude={"evidence_ids_before", "evidence_ids_after"}) for c in comparison.changes],
        [i.model_dump() for i in comparison.implications],
    )


async def test_trend_comparison_is_deterministic(qa_client: httpx.AsyncClient, alice: dict[str, str]) -> None:
    journey = await full_journey(qa_client, alice, check=False)
    first_run, first_result = journey.discovery_run, journey.discovery
    await discover(qa_client, journey, check=False)
    second_run, second_result = journey.discovery_run, journey.discovery
    snapshots = []
    for label, run, result in (("Before", first_run, first_result), ("After", second_run, second_result)):
        snapshot = parse(
            Snapshot,
            await qa_client.post(
                f"{API}/projects/{journey.project_id}/snapshots", json={"discovery_run_id": str(run.id), "label": label}, headers=alice  # type: ignore[union-attr]
            ),
            201,
        )
        assert snapshot.captured_at == run.completed_at, "captured_at is the discovery completion time"  # type: ignore[union-attr]
        assert (snapshot.reference_count, snapshot.evidence_count) == (len(result.references), len(result.evidence))  # type: ignore[union-attr]
        assert snapshot.mode == "demo" and snapshot.market.country_code == "JP"
        snapshots.append(snapshot)
    page = parse(SnapshotPage, await qa_client.get(f"{API}/projects/{journey.project_id}/snapshots", headers=alice))
    assert {s.id for s in page.items} == {s.id for s in snapshots}
    body = {"base_snapshot_id": str(snapshots[0].id), "target_snapshot_id": str(snapshots[1].id)}
    path = f"{API}/projects/{journey.project_id}/trend-comparisons"
    one = parse(TrendComparison, await qa_client.post(path, json=body, headers=alice), 201)
    two = parse(TrendComparison, await qa_client.post(path, json=body, headers=alice), 201)
    assert one.comparable is True, f"same market and terms must be comparable: {one.comparability_notes}"
    assert _trend_signature(one) == _trend_signature(two), "trend comparisons must be deterministic"
    assert one.change_count == sum(c.kind != "unchanged" for c in one.changes), "change_count counts real changes"
    keys = {c.reference_key for c in one.changes}
    for implication in one.implications:
        assert implication.claim_type == "hypothesis" and set(implication.based_on) <= keys
    assert parse(TrendComparison, await qa_client.get(f"{API}/trend-comparisons/{one.id}", headers=alice)) == one

    await discover(qa_client, journey, check=False, terms=["hiking", "great escape"])
    other = parse(
        Snapshot,
        await qa_client.post(
            f"{API}/projects/{journey.project_id}/snapshots", json={"discovery_run_id": str(journey.discovery_run.id), "label": "Other terms"}, headers=alice  # type: ignore[union-attr]
        ),
        201,
    )
    mismatch = parse(
        TrendComparison,
        await qa_client.post(path, json={"base_snapshot_id": str(snapshots[0].id), "target_snapshot_id": str(other.id)}, headers=alice),
        201,
    )
    assert mismatch.comparable is False and mismatch.comparability_notes, "different terms must be flagged not comparable"


# --------------------------------------------------------------------------- Campaign Arena


async def test_arena_scores_synthetic_ratings_honestly(qa_client: httpx.AsyncClient, alice: dict[str, str]) -> None:
    journey = await full_journey(qa_client, alice, check=False)
    run, arena = await _arena(qa_client, journey)
    assert arena.mode == "demo" and arena.run_id == run.id and arena.study_id == journey.study.id  # type: ignore[union-attr]
    disclosure = arena.simulation_disclosure
    assert disclosure.is_synthetic is True and disclosure.independent_human_sample is False
    assert arena.vision.status == "not_requested", "no image variants were given"
    inv.check_demo_evidence(arena.evidence, journey.project_id)
    inv.check_demo_run_metadata(arena.run_metadata, run.id, "campaign_arena")
    study_segments = {s.label for s in journey.study.segments}  # type: ignore[union-attr]
    by_label = {v.label: v for v in arena.variants}
    assert set(by_label) == {"Original", "Adapted", "Custom"}
    for variant in arena.variants:
        assert all(r.is_synthetic for r in variant.reactions)
        assert {s.label for s in variant.segments} <= study_segments, "variants share the study's segments"
        scores = {}
        for dimension in DIMENSIONS:
            result = getattr(variant.dimension_results, dimension)
            values = inv.ratings_for(variant.reactions, dimension)
            if result is not None and values:
                assert result.score == inv.aggregate_score(values), f"{variant.label} {dimension} score not mvp-1"
                assert result.disagreement == inv.expected_disagreement(values)
            scores[dimension] = result.score if result is not None else None
        exact = inv.exact_overall(DimensionScores(**scores), arena.criteria)
        if exact is None:
            assert variant.overall_score is None
        else:
            assert variant.overall_score is not None and abs(variant.overall_score - exact) <= 0.05 + 1e-9
    custom = by_label["Custom"]
    assert custom.source == "custom" and custom.overall_score is None, "demo custom variants have null scores (§13)"
    assert any("custom" in limitation.lower() for limitation in arena.limitations), "say why the custom variant is unscored"
    assert sorted(arena.ranking) == sorted(v.variant_id for v in arena.variants)
    scored = [by_id.overall_score for by_id in (next(v for v in arena.variants if v.variant_id == i) for i in arena.ranking)]
    present = [s for s in scored if s is not None]
    assert present == sorted(present, reverse=True) and scored[: len(present)] == present, f"ranking order {scored}"

    patched = parse(ArenaResult, await qa_client.patch(f"{API}/arenas/{arena.id}", json={"preferred_variant_id": custom.variant_id}, headers=alice))
    assert patched.preferred_variant_id == custom.variant_id and patched.variants == arena.variants
    campaign = parse(Campaign, await qa_client.get(f"{API}/campaigns/{journey.campaign_id}", headers=alice))
    assert campaign.current_version == journey.campaign.current_version, "choosing a variant is not approval"
    page = parse(ArenaPage, await qa_client.get(f"{API}/campaigns/{journey.campaign_id}/arenas", headers=alice))
    assert page.items[0].preferred_variant_id == custom.variant_id


# --------------------------------------------------------------------------- Risk Radar


def _check_finding_location(finding: RiskFinding, scan: RiskScan) -> None:
    assert finding.observation.strip() and finding.interpretation.strip()
    location = finding.text_location
    if location is not None:
        text = getattr(scan.content, location.field) or ""
        assert location.excerpt in text, f"finding {finding.id}: excerpt is not the exact text (observation vs interpretation)"
        if location.start is not None and location.end is not None:
            assert text[location.start : location.end] == location.excerpt, f"finding {finding.id}: offsets do not match"


async def test_risk_radar_findings_and_actions(qa_client: httpx.AsyncClient, alice: dict[str, str]) -> None:
    journey = await full_journey(qa_client, alice, check=False)
    run, scan = await _risk_scan(qa_client, journey)
    assert scan.mode == "demo" and scan.source_kind == "content_version" and scan.vision.status == "not_requested"
    assert scan.content == journey.campaign.current_version.content
    inv.check_demo_evidence(scan.evidence, journey.project_id)
    inv.check_demo_run_metadata(scan.run_metadata, run.id, "risk_scan")
    assert scan.findings, "the demo scan should report at least one finding"
    available = {e.id for e in scan.evidence} | await project_evidence_ids(qa_client, journey)
    for finding in scan.findings:
        _check_finding_location(finding, scan)
        inv.check_refs(finding.evidence_ids, available, f"risk finding {finding.id}")
        assert finding.source != "vision_model" and finding.status == "open"
    counts = scan.counts
    severities = [f.severity for f in scan.findings]
    assert (counts.open, counts.high, counts.medium, counts.low) == (
        len(scan.findings), severities.count("high"), severities.count("medium"), severities.count("low")
    )
    target = scan.findings[0]
    path = f"{API}/risk-scans/{scan.id}/findings/{target.id}"
    dismissed = parse(RiskFinding, await qa_client.patch(path, json={"status": "dismissed", "note": "Brand-approved idiom"}, headers=alice))
    assert (dismissed.status, dismissed.status_note) == ("dismissed", "Brand-approved idiom")
    refreshed = parse(RiskScan, await qa_client.get(f"{API}/risk-scans/{scan.id}", headers=alice))
    assert (refreshed.counts.open, refreshed.counts.dismissed) == (counts.open - 1, 1)
    assert parse(RiskFinding, await qa_client.patch(path, json={"status": "open"}, headers=alice)).status == "open"
    expect_error(await qa_client.patch(path, json={"status": "applied"}, headers=alice), 422, "VALIDATION_ERROR")

    fixable = next((f for f in scan.findings if f.suggested_alternative), None)
    assert fixable is not None, "the demo scan should offer at least one alternative"
    applied = parse(Adaptation, await qa_client.post(f"{API}/risk-scans/{scan.id}/findings/{fixable.id}/apply", headers=alice), 201)
    assert applied.origin == "user_edit" and applied.run_id is None and applied.mode == "demo"
    assert any(c.reasoning_type == "user_edit" for c in applied.changes)
    after = parse(RiskScan, await qa_client.get(f"{API}/risk-scans/{scan.id}", headers=alice))
    assert next(f for f in after.findings if f.id == fixable.id).status == "applied" and after.counts.applied == 1
    campaign = parse(Campaign, await qa_client.get(f"{API}/campaigns/{journey.campaign_id}", headers=alice))
    assert campaign.current_version == journey.campaign.current_version, "applying never edits the campaign in place"
    page = parse(RiskScanPage, await qa_client.get(f"{API}/campaigns/{journey.campaign_id}/risk-scans", headers=alice))
    assert [s.id for s in page.items] == [scan.id]


async def test_demo_uploads_are_not_analyzed(qa_client: httpx.AsyncClient, alice: dict[str, str]) -> None:
    """§13 demo rules: images get vision 'unavailable' with the stated message, and text analysis still runs."""
    journey = await full_journey(qa_client, alice, check=False)
    image = await upload(qa_client, alice, journey.project_id, kind="image", filename="pixel.png", data=PNG, content_type="image/png")
    assert image.status_code == 201, image.text
    _, scan = await _risk_scan(qa_client, journey, asset_ids=[image.json()["id"]])
    assert scan.vision.status == "unavailable" and NO_UPLOAD_ANALYSIS in (scan.vision.message or "")
    assert scan.visual_observations == [] and all(f.source != "vision_model" for f in scan.findings)
    assert scan.findings, "text analysis still runs without vision"


# --------------------------------------------------------------------------- Evidence Graph


async def test_evidence_graph_draws_only_persisted_links(qa_client: httpx.AsyncClient, alice: dict[str, str]) -> None:
    journey = await full_journey(qa_client, alice, check=False)
    graph = parse(EvidenceGraph, await qa_client.get(f"{API}/projects/{journey.project_id}/evidence-graph", params={"limit": 500}, headers=alice))
    assert not graph.truncated and graph.nodes and graph.edges
    nodes = {n.id: n for n in graph.nodes}
    assert len(nodes) == len(graph.nodes), "duplicate node ids"
    stored = {e.id: e for e in await _all_evidence(qa_client, journey)}
    for node in graph.nodes:
        assert node.is_demo, f"node {node.id} in a demo project must be marked demo"
        if node.kind == "evidence":
            record = stored.get(_uuid(node.ref.id))
            assert record is not None, f"evidence node {node.ref.id} is not a stored evidence record"
            assert (node.evidence_type, node.claim_type, node.retrieval_mode) == (record.evidence_type, record.claim_type, record.retrieval_mode)
    fetched: dict[str, str] = {}
    for edge in graph.edges:
        assert edge.source in nodes and edge.target in nodes and edge.source != edge.target, f"edge {edge.id} dangles"
        assert "." in edge.provenance, f"edge {edge.id}: provenance must name the persisted field, got {edge.provenance!r}"
        ends = [nodes[edge.source], nodes[edge.target]]
        evidence_ends = [n for n in ends if n.kind == "evidence"]
        other = [n for n in ends if n.kind != "evidence"]
        if len(evidence_ends) == 1 and other and other[0].ref.url:
            url = other[0].ref.url
            if url not in fetched:
                response = await qa_client.get(url, headers=alice)
                assert response.status_code == 200, f"node ref url {url} -> {response.status_code}"
                fetched[url] = response.text
            record = stored[_uuid(evidence_ends[0].ref.id)].model_dump_json()
            linked = evidence_ends[0].ref.id in fetched[url] or other[0].ref.id in record  # the field may live on either side
            assert linked, f"edge {edge.id} ({edge.provenance}) is not backed by a persisted field"
    small = parse(EvidenceGraph, await qa_client.get(f"{API}/projects/{journey.project_id}/evidence-graph", params={"limit": 10}, headers=alice))
    assert len(small.nodes) <= 10 and small.truncated is (len(graph.nodes) > 10)
    assert {e.source for e in small.edges} | {e.target for e in small.edges} <= {n.id for n in small.nodes}


async def _all_evidence(client: httpx.AsyncClient, journey: Journey) -> list[Any]:
    from app.schemas.evidence import EvidencePage
    from tests.integration._support import fetch_all

    return await fetch_all(client, f"{API}/projects/{journey.project_id}/evidence", journey.headers, EvidencePage)


def _uuid(value: str) -> Any:
    from uuid import UUID

    try:
        return UUID(value)
    except ValueError:
        return value


# --------------------------------------------------------------------------- Search


async def test_search_reports_unavailable_without_embeddings(qa_client: httpx.AsyncClient, alice: dict[str, str]) -> None:
    journey = await full_journey(qa_client, alice, check=False)
    path = f"{API}/projects/{journey.project_id}/search"
    results = parse(SearchResults, await qa_client.get(path, params={"q": "hiking"}, headers=alice))
    assert results.status == "unavailable" and results.hits == [] and results.message, "no lexical guesses (§13)"
    assert results.embedding_model is None and results.query == "hiking"
    for params, field in (({"q": ""}, "q"), ({"q": "x" * 301}, "q"), ({"q": "a", "limit": 26}, "limit"), ({"q": "a", "kinds": "everything"}, "kinds")):
        fields = detail_fields(expect_error(await qa_client.get(path, params=params, headers=alice), 422, "VALIDATION_ERROR"))
        assert any(f == field or (f or "").startswith(f"{field}.") for f in fields), f"{params}: {fields}"


# --------------------------------------------------------------------------- isolation


async def test_live_v2_resources_of_other_users_are_not_found(
    qa_client: httpx.AsyncClient, alice: dict[str, str], bob: dict[str, str]
) -> None:
    journey = await full_journey(qa_client, alice, check=False)
    image = await upload(qa_client, alice, journey.project_id, kind="image", filename="pixel.png", data=PNG, content_type="image/png")
    asset_id = image.json()["id"]
    run_id = str(journey.discovery_run.id)  # type: ignore[union-attr]
    snapshot = await qa_client.post(
        f"{API}/projects/{journey.project_id}/snapshots", json={"discovery_run_id": run_id, "label": "Mine"}, headers=alice
    )
    assert snapshot.status_code == 201, snapshot.text
    p = journey.project_id
    for path in (
        f"{API}/projects/{p}/brand",
        f"{API}/projects/{p}/snapshots",
        f"{API}/projects/{p}/trend-comparisons",
        f"{API}/projects/{p}/evidence-graph",
        f"{API}/projects/{p}/search?q=hiking",
        f"{API}/projects/{p}/assets",
        f"{API}/assets/{asset_id}",
        f"{API}/assets/{asset_id}/content",
    ):
        expect_error(await qa_client.get(path, headers=bob), 404, "NOT_FOUND")
    for method, path, body in (
        ("PUT", f"{API}/projects/{p}/brand", {"name": "Taken"}),
        ("POST", f"{API}/projects/{p}/snapshots", {"discovery_run_id": run_id, "label": "Theirs"}),
    ):
        expect_error(await qa_client.request(method, path, json=body, headers=bob), 404, "NOT_FOUND")


async def test_v2_resources_of_other_users_are_not_found(
    qa_client: httpx.AsyncClient, alice: dict[str, str], bob: dict[str, str]
) -> None:
    journey = await full_journey(qa_client, alice, check=False)
    _, profile = await _profile(qa_client, journey)
    _, arena = await _arena(qa_client, journey)
    _, scan = await _risk_scan(qa_client, journey)
    image = await upload(qa_client, alice, journey.project_id, kind="image", filename="pixel.png", data=PNG, content_type="image/png")
    asset_id = image.json()["id"]
    p = journey.project_id
    for path in (
        f"{API}/projects/{p}/brand",
        f"{API}/projects/{p}/cultural-profiles",
        f"{API}/cultural-profiles/{profile.id}",
        f"{API}/projects/{p}/market-comparisons",
        f"{API}/projects/{p}/snapshots",
        f"{API}/projects/{p}/trend-comparisons",
        f"{API}/campaigns/{journey.campaign_id}/arenas",
        f"{API}/arenas/{arena.id}",
        f"{API}/campaigns/{journey.campaign_id}/risk-scans",
        f"{API}/risk-scans/{scan.id}",
        f"{API}/projects/{p}/evidence-graph",
        f"{API}/projects/{p}/search?q=hiking",
        f"{API}/projects/{p}/assets",
        f"{API}/assets/{asset_id}",
        f"{API}/assets/{asset_id}/content",
    ):
        expect_error(await qa_client.get(path, headers=bob), 404, "NOT_FOUND")
    finding = scan.findings[0].id
    for method, path, body in (
        ("PUT", f"{API}/projects/{p}/brand", {"name": "Taken"}),
        ("PATCH", f"{API}/cultural-profiles/{profile.id}", {"title": "Taken"}),
        ("PATCH", f"{API}/arenas/{arena.id}", {"preferred_variant_id": None}),
        ("PATCH", f"{API}/risk-scans/{scan.id}/findings/{finding}", {"status": "dismissed"}),
        ("POST", f"{API}/risk-scans/{scan.id}/findings/{finding}/apply", None),
    ):
        expect_error(await qa_client.request(method, path, json=body, headers=bob), 404, "NOT_FOUND")
