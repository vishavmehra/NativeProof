"""Evidence Graph: nodes and edges drawn only from persisted links (README section 13).

Every edge names the stored field that establishes it (`provenance`). Nothing is inferred.
"""

from typing import Any
from uuid import UUID

from sqlalchemy import select

from app.db import models as m
from app.db.base import utcnow
from app.db.session import read_session
from app.schemas.graph import EvidenceGraph, GraphEdge, GraphNode, GraphRef
from app.services.common import conflict, get_owned, get_project

API = "/api/v1"
LIMITATIONS = [
    "Only persisted links are drawn; links the system did not record are never inferred.",
    "Discovery references and rehearsal findings appear through their runs and evidence records, not as separate nodes.",
]


def _markets(request: dict) -> set:
    """Country codes named by a stored request's `market` or `markets`."""
    codes = {(request.get("market") or {}).get("country_code")}
    codes |= {m.get("country_code") for m in request.get("markets") or []}
    return codes - {None}


def _evidence_kind(e: m.EvidenceRecord) -> str:
    if e.evidence_type == "synthetic_response" or e.claim_type == "synthetic":
        return "synthetic_result"
    if e.claim_type == "hypothesis":
        return "hypothesis"
    return {"qloo_source": "source_signal", "model_interpretation": "interpretation"}.get(e.evidence_type, "evidence")


class _Builder:
    def __init__(self, demo: bool) -> None:
        self.demo = demo
        self.nodes: dict[str, GraphNode] = {}
        self.edges: list[tuple[str, str, str, str]] = []

    def node(self, node_id: str, kind: str, label: str, resource: str, rid: Any, url: str | None, created_at: Any,
             **extra: Any) -> None:
        self.nodes.setdefault(node_id, GraphNode(
            id=node_id, kind=kind, label=label[:160], evidence_type=extra.get("evidence_type"),  # type: ignore[arg-type]
            claim_type=extra.get("claim_type"), retrieval_mode=extra.get("retrieval_mode"), is_demo=self.demo,
            confidence_label=extra.get("confidence_label"), created_at=created_at,
            limitations=extra.get("limitations", []), ref=GraphRef(resource=resource, id=str(rid), url=url),
        ))

    def edge(self, source: str, target: str, relation: str, provenance: str) -> None:
        self.edges.append((source, target, relation, provenance))


async def evidence_graph(
    user_id: UUID, project_id: UUID, campaign_id: UUID | None, limit: int, *, region: str | None = None,
    evidence_type: str | None = None, population_study_id: UUID | None = None,
) -> EvidenceGraph:
    async with read_session() as s:
        project = await get_project(s, user_id, project_id)
        if campaign_id is not None:
            campaign, _ = await get_owned(s, m.Campaign, campaign_id, user_id, "Campaign", "campaign_id")
            if campaign.project_id != project_id:
                raise conflict("campaign_id", "The campaign belongs to another project.")

        async def rows(model: Any, *conditions: Any) -> list[Any]:
            stmt = select(model).where(model.project_id == project_id, *conditions)
            return list((await s.execute(stmt.order_by(model.created_at))).scalars())

        def scoped(model: Any) -> list[Any]:
            return [] if campaign_id is None else [model.campaign_id == campaign_id]

        campaigns = await rows(m.Campaign, *([m.Campaign.id == campaign_id] if campaign_id else []))
        versions = await rows(m.CampaignVersion, *scoped(m.CampaignVersion))
        runs = await rows(m.AgentRun, *scoped(m.AgentRun))
        adaptations = await rows(m.Adaptation, *scoped(m.Adaptation))
        evaluations = await rows(m.Evaluation, *scoped(m.Evaluation))
        scans = await rows(m.RiskScan, *scoped(m.RiskScan))
        findings = await rows(m.RiskFinding, m.RiskFinding.scan_id.in_([x.id for x in scans])) if scans else []
        profiles = await rows(m.CulturalProfile, *scoped(m.CulturalProfile))
        arenas = await rows(m.Arena, *scoped(m.Arena))
        comparisons = await rows(m.MarketComparison, *scoped(m.MarketComparison))
        reports = await rows(m.Report, *scoped(m.Report))
        studies = await rows(m.Study) if region is not None else []
        run_ids = {r.id for r in runs}
        referenced = {
            UUID(str(i))
            for holder in (*adaptations, *evaluations)
            for i in holder.evidence_ids
        } | {UUID(str(i)) for f in findings for i in f.payload.get("evidence_ids", [])} | {
            UUID(str(i)) for x in (*profiles, *comparisons, *arenas) for i in (x.result or {}).get("evidence_ids", [])
        }
        evidence = await rows(m.EvidenceRecord) if campaign_id is None else [
            e for e in await rows(m.EvidenceRecord) if e.source_run_id in run_ids or e.id in referenced
        ]

    g = _Builder(project.mode == "demo")
    for c in campaigns:
        g.node(f"campaign:{c.id}", "campaign", c.name, "campaign", c.id, f"{API}/campaigns/{c.id}", c.created_at)
    for v in versions:
        g.node(f"version:{v.id}", "content_version", f"Content version {v.version_number}", "content_version", v.id,
               f"{API}/campaigns/{v.campaign_id}", v.created_at)
        g.edge(f"version:{v.id}", f"campaign:{v.campaign_id}", "variant_of", "campaign_versions.campaign_id")
    for a in adaptations:
        node = f"adaptation:{a.id}"
        g.node(node, "adaptation", a.label, "adaptation", a.id, f"{API}/adaptations/{a.id}", a.created_at,
               limitations=a.limitations)
        g.edge(node, f"version:{a.source_content_version_id}", "derived_from", "adaptations.source_content_version_id")
        if a.parent_adaptation_id:
            g.edge(node, f"adaptation:{a.parent_adaptation_id}", "variant_of", "adaptations.parent_adaptation_id")
        if a.run_id:
            g.edge(node, f"run:{a.run_id}", "generated_by", "adaptations.run_id")
        for i in a.evidence_ids:
            g.edge(f"evidence:{i}", node, "supports", "adaptations.evidence_ids")
    for e in evaluations:
        node = f"evaluation:{e.id}"
        g.node(node, "evaluation", "Evaluation", "evaluation", e.id, f"{API}/campaigns/{e.campaign_id}/evaluations/{e.id}",
               e.created_at, limitations=e.limitations)
        g.edge(node, f"version:{e.source_content_version_id}", "evaluates", "evaluations.source_content_version_id")
        for result in e.results:
            if result.get("adaptation_id"):
                g.edge(node, f"adaptation:{result['adaptation_id']}", "evaluates", "evaluations.results[].adaptation_id")
        candidate = (e.recommendation or {}).get("candidate_id")
        if candidate and candidate != "original":
            g.edge(node, f"adaptation:{candidate}", "recommends", "evaluations.recommendation.candidate_id")
        g.edge(node, f"run:{e.run_id}", "generated_by", "evaluations.run_id")
        for i in e.evidence_ids:
            g.edge(f"evidence:{i}", node, "supports", "evaluations.evidence_ids")
    scan_by_id = {x.id: x for x in scans}
    for f in findings:
        node, scan = f"finding:{f.id}", scan_by_id[f.scan_id]
        g.node(node, "risk_finding", f.payload.get("observation", "Risk finding"), "risk_finding", f.id,
               f"{API}/risk-scans/{scan.id}", f.created_at, confidence_label=f.payload.get("confidence_label"),
               limitations=f.payload.get("limitations", []))
        target = {"content_version": "version", "adaptation": "adaptation"}.get(scan.source_kind)
        if target and scan.source_id:
            g.edge(node, f"{target}:{scan.source_id}", "flags", "risk_scans.source_id")
        g.edge(node, f"run:{scan.run_id}", "generated_by", "risk_scans.run_id")
        for i in f.payload.get("evidence_ids", []):
            g.edge(f"evidence:{i}", node, "supports", "risk_findings.evidence_ids")
    for p in profiles:
        node = f"profile:{p.id}"
        g.node(node, "cultural_profile", f"{p.title} v{p.version}", "cultural_profile", p.id,
               f"{API}/cultural-profiles/{p.id}", p.created_at)
        if p.run_id:
            g.edge(node, f"run:{p.run_id}", "generated_by", "cultural_profiles.run_id")
        for run_id in p.source_discovery_run_ids:
            g.edge(node, f"run:{run_id}", "derived_from", "cultural_profiles.source_discovery_run_ids")
        for item in (p.result or {}).get("items", []):
            for i in item.get("evidence_ids", []):
                g.edge(f"evidence:{i}", node, "supports", "cultural_profiles.items[].evidence_ids")
    for a in arenas:
        node = f"arena:{a.id}"
        g.node(node, "arena", "Campaign Arena", "arena", a.id, f"{API}/arenas/{a.id}", a.created_at)
        g.edge(node, f"run:{a.run_id}", "generated_by", "arenas.run_id")
        for variant in a.variants:
            target = {"content_version": "version", "adaptation": "adaptation"}.get(variant.get("source", ""))
            if target and variant.get("source_id"):
                g.edge(node, f"{target}:{variant['source_id']}", "evaluates", "arenas.variants[].source_id")
    for c in comparisons:
        node = f"comparison:{c.id}"
        g.node(node, "market_comparison", "Market comparison", "market_comparison", c.id,
               f"{API}/market-comparisons/{c.id}", c.created_at)
        g.edge(node, f"run:{c.run_id}", "generated_by", "market_comparisons.run_id")
        for i in (c.result or {}).get("evidence_ids", []):
            g.edge(f"evidence:{i}", node, "supports", "market_comparisons.evidence_ids")
    for r in reports:
        node, content = f"report:{r.id}", r.content
        g.node(node, "report", f"{r.title} v{r.version_number}", "report", r.id, f"{API}/reports/{r.id}", r.created_at)
        if content.get("evaluation"):
            g.edge(node, f"evaluation:{content['evaluation']['id']}", "references", "reports.evaluation.id")
        for a in content.get("adaptations", []):
            g.edge(node, f"adaptation:{a['id']}", "references", "reports.adaptations[].id")
        for section in ("discovery", "rehearsal"):
            if content.get(section):
                g.edge(node, f"run:{content[section]['run_id']}", "references", f"reports.{section}.run_id")
    for run in runs:
        node = f"run:{run.id}"
        g.node(node, "run", f"{run.run_type} ({run.status})", "run", run.id, f"{API}/runs/{run.id}", run.created_at)
        if run.campaign_id:
            g.edge(node, f"campaign:{run.campaign_id}", "references", "agent_runs.campaign_id")
    for e in evidence:
        node = f"evidence:{e.id}"
        g.node(node, _evidence_kind(e), e.title, "evidence", e.id, f"{API}/evidence/{e.id}", e.created_at,
               evidence_type=e.evidence_type, claim_type=e.claim_type, retrieval_mode=e.retrieval_mode,
               limitations=e.limitations)
        if e.source_run_id:
            g.edge(f"run:{e.source_run_id}", node, "produced", "evidence_records.source_run_id")

    filters: list[str] = []
    if region is not None:
        study_market = {st.id: st.market.get("country_code") for st in studies}
        run_markets = {run.id: _markets(run.inputs.get("request", {})) | (
            {study_market.get(run.study_id)} if run.study_id else set()) for run in runs}
        tagged: dict[str, set] = {f"run:{run.id}": codes for run, codes in ((r, run_markets[r.id]) for r in runs)}
        tagged |= {f"evidence:{e.id}": run_markets.get(e.source_run_id, set()) for e in evidence}
        tagged |= {f"adaptation:{a.id}": _markets({"market": a.market}) for a in adaptations}
        tagged |= {f"evaluation:{e.id}": _markets({"market": e.market}) for e in evaluations}
        tagged |= {f"finding:{f.id}": _markets({"market": scan_by_id[f.scan_id].market}) for f in findings}
        tagged |= {f"profile:{p.id}": _markets({"markets": p.markets}) for p in profiles}
        tagged |= {f"arena:{a.id}": {study_market.get(a.study_id)} for a in arenas}
        tagged |= {f"comparison:{c.id}": _markets({"markets": c.markets}) for c in comparisons}
        tagged |= {f"report:{r.id}": _markets({"market": r.content.get("market") or {}}) for r in reports}
        for node_id, codes in tagged.items():
            if (codes - {None}) and region not in codes:
                g.nodes.pop(node_id, None)
        filters.append(f"Filtered to region {region}: records tied to other markets are hidden; campaign and version "
                       "nodes, and records without a market, stay.")
    if evidence_type is not None:
        for node_id in [n.id for n in g.nodes.values() if n.evidence_type is not None and n.evidence_type != evidence_type]:
            g.nodes.pop(node_id)
        filters.append(f"Evidence filtered to type {evidence_type}; other node kinds are unaffected.")
    if population_study_id is not None:
        filters.append("Population studies have their own graph views: reaction map, audience landscape, and social diffusion.")

    # Links whose two ends are both in this view; a node cap then also drops the links touching cut nodes.
    links = list(dict.fromkeys(e for e in g.edges if e[0] in g.nodes and e[1] in g.nodes))
    kept = dict(list(g.nodes.items())[:limit])
    edges = [
        GraphEdge(id=f"e{index + 1}", source=source, target=target, relation=relation, provenance=provenance)  # type: ignore[arg-type]
        for index, (source, target, relation, provenance) in enumerate(
            e for e in links if e[0] in kept and e[1] in kept)
    ]
    truncated = len(kept) < len(g.nodes) or len(edges) < len(links)
    note = (f"Capped at {limit} nodes: showing {len(kept)} of {len(g.nodes)} nodes and {len(edges)} of "
            f"{len(links)} links. Raise the limit to see the rest.")
    return EvidenceGraph(
        project_id=project_id, campaign_id=campaign_id, nodes=list(kept.values()), edges=edges, truncated=truncated,
        limitations=LIMITATIONS + filters + ([note] if truncated else []), generated_at=utcnow(),
    )
