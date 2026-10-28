"use client";

import { useQuery } from "@tanstack/react-query";
import { Bot, FileText, Layers, Lightbulb, ListChecks, MessageSquareText, Play, ShieldAlert, Signal, Sparkles, Users, Wand2 } from "lucide-react";
import { useState } from "react";

import { FeatureHeader } from "@/components/app-shell/feature-header";
import { ConfidenceBadge, EvidenceLabel, RetrievalBadge } from "@/components/evidence/badges";
import { useEvidenceInspector } from "@/components/evidence/evidence-inspector";
import { LimitationList } from "@/components/evidence/limitation-list";
import { GraphCanvas, type CanvasEdge, type CanvasNode, type LegendEntry } from "@/components/graph/graph-canvas";
import { FilterCard, FilterField, filterSelectClass } from "@/components/layout/page-parts";
import { Button } from "@/components/ui/button";
import { useProject } from "@/features/project/project-context";
import { sectionHref } from "@/features/project/workflow";
import { api } from "@/lib/api/client";
import { unwrap } from "@/lib/api/errors";
import type { components } from "@/lib/api/schema";
import { formatDateTime, humanize } from "@/lib/format";

type GraphNode = components["schemas"]["GraphNode"];
type EvidenceType = NonNullable<GraphNode["evidence_type"]>;

/** Layers (restrained multicolor): node kinds grouped by what produced them. */
const LAYERS: (LegendEntry & { kinds: string[] })[] = [
  { kind: "content", label: "Campaign elements", color: "#0f172a", Icon: FileText, kinds: ["campaign", "content_version"], description: "Campaigns and their content versions." },
  { kind: "source", label: "Cultural signals", color: "#14b8a6", Icon: Signal, kinds: ["source_signal", "evidence"], description: "Qloo source data and evidence records." },
  { kind: "audience", label: "Audience groups", color: "#4f46e5", Icon: Users, kinds: ["population", "audience_group", "synthetic_result", "arena"], description: "Synthetic populations, groups, and results." },
  { kind: "interpretation", label: "Interview findings", color: "#8b5cf6", Icon: MessageSquareText, kinds: ["interview_theme", "interpretation", "hypothesis", "cultural_profile", "market_comparison"], description: "Themes, interpretations, and hypotheses." },
  { kind: "risk", label: "Risk findings", color: "#e5484d", Icon: ShieldAlert, kinds: ["risk_finding"], description: "Risk Radar findings." },
  { kind: "adaptation", label: "Adaptations", color: "#f97316", Icon: Wand2, kinds: ["adaptation"], description: "Voice adaptations and user edits." },
  { kind: "recommendation", label: "Recommendations", color: "#10b981", Icon: Lightbulb, kinds: ["evaluation", "recommendation"], description: "Evaluations and recommendations." },
  { kind: "run", label: "Runs and reports", color: "#94a3b8", Icon: ListChecks, kinds: ["run", "report"], description: "Workflow runs and reports." },
  { kind: "other", label: "Other", color: "#a8a29e", Icon: Layers, kinds: [], description: "Kinds without a dedicated layer." },
];
const LAYER_OF = new Map(LAYERS.flatMap((l) => l.kinds.map((k) => [k, l.kind] as const)));

/** Feature page for a node's underlying resource, when one exists. */
const PAGE_OF: Record<string, string | null> = {
  campaign: null,
  content_version: null,
  adaptation: "voice",
  evaluation: "loop",
  recommendation: "loop",
  risk_finding: "risk-radar",
  cultural_profile: "cultural-dna",
  arena: "arena",
  market_comparison: "market-expansion",
  report: "proof",
  population: "audience",
  audience_group: "audience",
  interview_theme: "audience",
  synthetic_result: "audience",
};

const EVIDENCE_TYPES: EvidenceType[] = ["qloo_source", "provider_result", "model_interpretation", "deterministic_calculation", "synthetic_response", "observed_outcome", "user_input"];

export function EvidenceGraphView() {
  const { project, campaign } = useProject();
  const { inspect } = useEvidenceInspector();
  const [scope, setScope] = useState<"campaign" | "project">(campaign ? "campaign" : "project");
  const [region, setRegion] = useState("");
  const [evidenceType, setEvidenceType] = useState<EvidenceType | "">("");
  const [limit, setLimit] = useState(200); // API default; bounds 10–500

  const graph = useQuery({
    queryKey: ["evidence-graph", project.id, scope === "campaign" ? campaign?.id : null, region, evidenceType, limit],
    queryFn: () =>
      unwrap(
        api.GET("/api/v1/projects/{project_id}/evidence-graph", {
          params: {
            path: { project_id: project.id },
            query: {
              campaign_id: scope === "campaign" ? (campaign?.id ?? null) : null,
              region: region || null,
              evidence_type: evidenceType || null,
              limit,
            },
          },
        }),
      ),
  });

  const raw = new Map((graph.data?.nodes ?? []).map((n) => [n.id, n]));
  const nodes: CanvasNode[] = (graph.data?.nodes ?? []).map((n) => {
    const page = PAGE_OF[n.kind];
    return {
      id: n.id,
      label: n.label,
      kind: LAYER_OF.get(n.kind) ?? "other",
      isDemo: n.is_demo,
      isSynthetic: n.claim_type === "synthetic" || n.evidence_type === "synthetic_response",
      facts: { Kind: humanize(n.kind), Created: n.created_at ? formatDateTime(n.created_at) : null },
      href: page === undefined || page === null ? (n.kind === "campaign" ? sectionHref(project.id, null) : null) : sectionHref(project.id, page, campaign?.id),
    };
  });
  const edges: CanvasEdge[] = (graph.data?.edges ?? []).map((e) => ({ id: e.id, source: e.source, target: e.target, relation: e.relation, provenance: e.provenance }));
  const presentLayers = new Set(nodes.map((n) => n.kind));
  const legend = LAYERS.filter((l) => presentLayers.has(l.kind) || l.kind !== "other");

  async function openEvidence(n: GraphNode) {
    const record = await unwrap(api.GET("/api/v1/evidence/{evidence_id}", { params: { path: { evidence_id: n.ref.id } } })).catch(() => null);
    inspect({ title: n.label, summary: record ? undefined : "The evidence record could not be loaded.", records: record ? [record] : [], limitations: n.limitations });
  }

  const select = (id: string, value: string, onChange: (v: string) => void, options: [string, string][]) => (
    <select id={id} value={value} onChange={(e) => onChange(e.target.value)} className={filterSelectClass}>
      {options.map(([v, t]) => (
        <option key={v} value={v}>
          {t}
        </option>
      ))}
    </select>
  );

  return (
    <div className="space-y-6">
      <FeatureHeader
        feature="graph"
        className="mb-2"
        description="Only persisted links are drawn. Each connection names the stored field that establishes it."
        howItWorks={
          <div className="space-y-2">
            <p>Every node is a stored record: a campaign, a Qloo signal, an evidence record, a synthetic result, a finding, an adaptation, or a report.</p>
            <p>Edges exist only where a saved field links two records, such as a finding&apos;s evidence ids. Nothing is inferred to fill gaps.</p>
            <p>Select a node to see its provenance; evidence nodes open the full record with its labels and limitations.</p>
          </div>
        }
      />
      <GraphCanvas
        label="Evidence graph"
        isLoading={graph.isPending}
        error={graph.error}
        onRetry={() => void graph.refetch()}
        nodes={nodes}
        edges={edges}
        legend={legend}
        truncated={graph.data?.truncated}
        limitations={graph.data?.limitations ?? []}
        emptyTitle="No linked records yet"
        emptyDescription="The graph fills in as runs persist evidence, findings, adaptations, and evaluations. Start with a discovery in Atlas."
        filters={
          <FilterCard>
            {campaign && (
              <FilterField label="Scope" htmlFor="g-scope">
                {select("g-scope", scope, (v) => setScope(v as "campaign" | "project"), [
                  ["campaign", campaign.name],
                  ["project", "Whole project"],
                ])}
              </FilterField>
            )}
            <FilterField label="Region" htmlFor="g-region">
              {select("g-region", region, setRegion, [["", "All regions"], ...project.target_markets.map((m): [string, string] => [m.country_code, m.display_name])])}
            </FilterField>
            <FilterField label="Evidence type" htmlFor="g-type">
              {select("g-type", evidenceType, (v) => setEvidenceType(v as EvidenceType | ""), [["", "All types"], ...EVIDENCE_TYPES.map((t): [string, string] => [t, humanize(t)])])}
            </FilterField>
            <FilterField label="Show up to" htmlFor="g-limit">
              {select("g-limit", String(limit), (v) => setLimit(Number(v)), [10, 50, 200, 500].map((n): [string, string] => [String(n), `${n} nodes`]))}
            </FilterField>
          </FilterCard>
        }
        renderDetails={(node) => {
          const n = raw.get(node.id);
          if (!n) return null;
          return (
            <div className="space-y-3">
              <div className="flex flex-wrap gap-1.5">
                {n.evidence_type && n.claim_type && <EvidenceLabel record={{ evidence_type: n.evidence_type, claim_type: n.claim_type }} />}
                {n.retrieval_mode && <RetrievalBadge mode={n.retrieval_mode} />}
                {n.confidence_label && <ConfidenceBadge label={n.confidence_label} />}
                {node.isSynthetic && (
                  <span className="inline-flex items-center gap-1 text-[12px] text-ink-secondary">
                    <Bot aria-hidden className="size-3.5" /> Synthetic
                  </span>
                )}
              </div>
              <p className="font-mono text-[11px] break-all text-ink-secondary">
                {n.ref.resource} · {n.ref.id}
              </p>
              {(n.kind === "evidence" || n.kind === "source_signal") && (
                <Button size="sm" variant="outline" onClick={() => void openEvidence(n)}>
                  <Sparkles aria-hidden />
                  Open evidence record
                </Button>
              )}
              <LimitationList items={n.limitations} />
            </div>
          );
        }}
      />
      <p className="flex items-center gap-1.5 text-xs text-ink-secondary">
        <Play aria-hidden className="size-3" />
        {graph.data ? `${graph.data.nodes.length} nodes · ${graph.data.edges.length} edges · generated ${formatDateTime(graph.data.generated_at)}` : " "}
      </p>
    </div>
  );
}
