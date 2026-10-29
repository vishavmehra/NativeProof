"use client";

import "@xyflow/react/dist/style.css";

import { Background, Controls, Handle, MarkerType, Position, ReactFlow, ReactFlowProvider, useReactFlow, type Edge, type Node, type NodeProps } from "@xyflow/react";
import { ArrowRight, Bot, FlaskConical, type LucideIcon } from "lucide-react";
import { useRouter } from "next/navigation";
import { useEffect, useMemo, useState, type KeyboardEvent, type ReactNode } from "react";

import { computeLayout, MAX_NODES, type LayoutKind, type Point } from "@/components/graph/layout";
import { Card } from "@/components/layout/page-parts";
import { EmptyState, ErrorState, LoadingState } from "@/components/states";
import { Button } from "@/components/ui/button";
import type { components } from "@/lib/api/schema";
import { humanize } from "@/lib/format";
import { cn } from "@/lib/utils";

export type CanvasNode = {
  id: string;
  label: string;
  kind: string;
  region?: string | null;
  /** Stored facts only (every number is a stored tally). */
  facts?: Record<string, string | number | null>;
  isDemo?: boolean;
  isSynthetic?: boolean;
  /** In-app link for "Open" (feature page or resource page). */
  href?: string | null;
};
export type CanvasEdge = { id: string; source: string; target: string; relation: string; weight?: number | null; weightDefinition?: string | null; provenance: string };
export type LegendEntry = { kind: string; label: string; description?: string; color?: string; Icon?: LucideIcon };

const PALETTE = ["#4f46e5", "#e5484d", "#14b8a6", "#f97316", "#2563eb", "#8b5cf6", "#10b981", "#f59e0b", "#0ea5e9", "#475569", "#db2777"];

type GraphView = components["schemas"]["GraphView"];

/**
 * Adapter for the v3 graph views (audience_landscape, reaction_map, campaign_comparison, social_diffusion).
 * `href` maps a node's resource to a page; pass a resolver for your view.
 */
export function fromGraphView(view: GraphView, href?: (node: GraphView["nodes"][number]) => string | null) {
  return {
    nodes: view.nodes.map<CanvasNode>((n) => ({
      id: n.id,
      label: n.label,
      kind: n.kind,
      region: n.region,
      facts: n.facts,
      isDemo: n.is_demo,
      isSynthetic: n.is_synthetic,
      href: href?.(n) ?? null,
    })),
    edges: view.edges.map<CanvasEdge>((e) => ({ id: e.id, source: e.source, target: e.target, relation: e.relation, weight: e.weight, weightDefinition: e.weight_definition, provenance: e.provenance })),
    legend: view.legend.map<LegendEntry>((l) => ({ kind: l.kind, label: l.label, description: l.description })),
    truncated: view.truncated,
    limitations: view.limitations,
  };
}

type Density = "all" | "key" | "none";
type NodeData = { node: CanvasNode; color: string; Icon?: LucideIcon; showLabel: boolean; dimmed: boolean };
type FlowNode = Node<NodeData, "dot">;

function DotNode({ data, selected }: NodeProps<FlowNode>) {
  const { node, color, Icon } = data;
  return (
    <div className={cn("flex w-28 flex-col items-center gap-1.5 text-center transition-opacity", data.dimmed && "opacity-25")} title={node.label}>
      <Handle type="target" position={Position.Top} style={{ opacity: 0, width: 1, height: 1, border: 0 }} />
      <span
        className={cn("flex size-11 items-center justify-center rounded-full border-2 bg-white shadow-card", selected && "ring-4 ring-primary/25")}
        style={{ borderColor: color, color }}
      >
        {Icon ? <Icon aria-hidden className="size-5" /> : <span className="size-3 rounded-full" style={{ background: color }} />}
      </span>
      {data.showLabel && <span className="line-clamp-2 text-[11.5px] leading-tight font-medium text-ink">{node.label}</span>}
      {(node.isSynthetic || node.isDemo) && (
        <span className="text-[11px] font-semibold text-ink-secondary">{[node.isSynthetic && "Synthetic", node.isDemo && "Demo"].filter(Boolean).join(" · ")}</span>
      )}
      <Handle type="source" position={Position.Bottom} style={{ opacity: 0, width: 1, height: 1, border: 0 }} />
    </div>
  );
}
const nodeTypes = { dot: DotNode };

export type GraphCanvasProps = {
  nodes: CanvasNode[];
  edges: CanvasEdge[];
  legend: LegendEntry[];
  isLoading?: boolean;
  error?: unknown;
  onRetry?: () => void;
  truncated?: boolean;
  limitations?: string[];
  /** Caller-supplied filters that change the query (rendered above the canvas). */
  filters?: ReactNode;
  emptyTitle?: string;
  emptyDescription?: string;
  /** Extra detail content for the selected node (e.g. evidence badges). */
  renderDetails?: (node: CanvasNode) => ReactNode;
  height?: number;
  /** Accessible name of the canvas. */
  label: string;
};

/**
 * Shared graph canvas for every graph view (docs/16 §2): layer toggles from the legend, layout options, label density,
 * a node detail panel (facts, relations with weight definitions and provenance, related nodes, Open), keyboard
 * traversal (arrows move between neighbours, Enter opens), and loading / empty / partial / error states.
 *
 * Usage (v3 view):
 *   const view = useQuery(…GET /campaigns/{id}/population-comparison…);
 *   const g = view.data && fromGraphView(view.data, (n) => n.resource ? `/projects/${pid}/audience` : null);
 *   <GraphCanvas label="Reaction map" isLoading={view.isPending} error={view.error} onRetry={view.refetch}
 *     nodes={g?.nodes ?? []} edges={g?.edges ?? []} legend={g?.legend ?? []} truncated={g?.truncated} limitations={g?.limitations}
 *     filters={<FilterCard>…</FilterCard>} />
 */
export function GraphCanvas(props: GraphCanvasProps) {
  return (
    <ReactFlowProvider>
      <GraphCanvasInner {...props} />
    </ReactFlowProvider>
  );
}

function GraphCanvasInner({ nodes, edges, legend, isLoading, error, onRetry, truncated, limitations = [], filters, emptyTitle, emptyDescription, renderDetails, height = 620, label }: GraphCanvasProps) {
  const router = useRouter();
  const flow = useReactFlow();
  const [layout, setLayout] = useState<LayoutKind>("force");
  const [density, setDensity] = useState<Density>("key");
  const [hidden, setHidden] = useState<Set<string>>(new Set());
  const [selectedId, setSelectedId] = useState<string | null>(null);
  const [hoveredId, setHoveredId] = useState<string | null>(null);
  const [positions, setPositions] = useState<Map<string, Point> | null>(null);

  const capped = nodes.length > MAX_NODES;
  const colorOf = useMemo(() => {
    const m = new Map<string, { color: string; Icon?: LucideIcon }>();
    legend.forEach((l, i) => m.set(l.kind, { color: l.color ?? PALETTE[i % PALETTE.length], Icon: l.Icon }));
    return (kind: string) => m.get(kind) ?? { color: "#94a3b8" };
  }, [legend]);
  const visible = useMemo(() => nodes.slice(0, MAX_NODES).filter((n) => !hidden.has(n.kind)), [nodes, hidden]);
  const visibleIds = useMemo(() => new Set(visible.map((n) => n.id)), [visible]);
  const visibleEdges = useMemo(() => edges.filter((e) => visibleIds.has(e.source) && visibleIds.has(e.target)), [edges, visibleIds]);
  const hasRegions = nodes.some((n) => n.region);

  // Layout off the render path: compute after paint so large views never block the first frame.
  useEffect(() => {
    const id = setTimeout(() => setPositions(computeLayout(visible, visibleEdges, layout, legend.map((l) => l.kind))), 0);
    return () => clearTimeout(id);
  }, [visible, visibleEdges, layout, legend]);
  useEffect(() => {
    // Small graphs would otherwise zoom to the maximum and render giant, clipped nodes.
    if (positions) requestAnimationFrame(() => void flow.fitView({ padding: 0.2, maxZoom: 1.1, duration: 0 }));
  }, [positions, flow]);

  const degree = useMemo(() => {
    const d = new Map<string, number>();
    visibleEdges.forEach((e) => {
      d.set(e.source, (d.get(e.source) ?? 0) + 1);
      d.set(e.target, (d.get(e.target) ?? 0) + 1);
    });
    return d;
  }, [visibleEdges]);
  const keyIds = useMemo(() => new Set([...visible].sort((a, b) => (degree.get(b.id) ?? 0) - (degree.get(a.id) ?? 0)).slice(0, 12).map((n) => n.id)), [visible, degree]);
  const neighbours = (id: string) =>
    visibleEdges
      .filter((e) => e.source === id || e.target === id)
      .map((e) => (e.source === id ? e.target : e.source))
      .filter((v, i, a) => a.indexOf(v) === i)
      .map((nid) => visible.find((n) => n.id === nid)!)
      .filter(Boolean)
      .sort((a, b) => a.label.localeCompare(b.label));

  const focusId = selectedId ?? hoveredId;
  const focusNeighbours = focusId ? new Set([focusId, ...neighbours(focusId).map((n) => n.id)]) : null;

  const flowNodes: FlowNode[] = positions
    ? visible.map((n) => {
        const c = colorOf(n.kind);
        return {
          id: n.id,
          type: "dot",
          position: positions.get(n.id) ?? { x: 0, y: 0 },
          selected: n.id === selectedId,
          data: {
            node: n,
            color: c.color,
            Icon: c.Icon,
            showLabel: density === "all" || (density === "key" && (keyIds.has(n.id) || focusNeighbours?.has(n.id) === true)),
            dimmed: Boolean(focusNeighbours && !focusNeighbours.has(n.id)),
          },
        };
      })
    : [];
  const flowEdges: Edge[] = visibleEdges.map((e) => {
    const focused = Boolean(focusNeighbours?.has(e.source) && focusNeighbours.has(e.target));
    const muted = Boolean(focusNeighbours) && !focused;
    // Hex, not a CSS variable: React Flow writes the marker colour into SVG attributes.
    const color = muted ? "#e7e3dc" : focused ? PALETTE[0] : "#78716c";
    // Heavier edges carry more (a stored count or weight); log-scaled and capped so one edge never dominates.
    const width = (muted ? 1 : 1.6) + Math.min(2.4, Math.log2(1 + Math.max(0, e.weight ?? 0)));
    return {
      id: e.id,
      source: e.source,
      target: e.target,
      zIndex: focused ? 1 : 0,
      style: { stroke: color, strokeWidth: width },
      markerEnd: { type: MarkerType.ArrowClosed, width: 14, height: 14, color },
    };
  });

  function select(id: string | null) {
    setSelectedId(id);
    const p = id && positions?.get(id);
    if (p) void flow.setCenter(p.x + 56, p.y + 24, { zoom: Math.min(Math.max(flow.getZoom(), 0.8), 1.1), duration: 200 });
  }
  function onKeyDown(e: KeyboardEvent) {
    if (!visible.length) return;
    if (e.key === "Escape") return select(null);
    if (e.key === "Enter" && selectedId) {
      const href = visible.find((n) => n.id === selectedId)?.href;
      if (href) router.push(href);
      return;
    }
    if (!["ArrowRight", "ArrowLeft", "ArrowDown", "ArrowUp"].includes(e.key)) return;
    e.preventDefault();
    if (!selectedId) return select([...visible].sort((a, b) => (degree.get(b.id) ?? 0) - (degree.get(a.id) ?? 0))[0].id);
    const ns = neighbours(selectedId);
    if (!ns.length) return;
    const step = e.key === "ArrowRight" || e.key === "ArrowDown" ? 1 : -1;
    // Walk the current node's neighbours in label order; each press moves to the next neighbour.
    const anchor = hoveredId && ns.some((n) => n.id === hoveredId) ? ns.findIndex((n) => n.id === hoveredId) : -1;
    const next = ns[(anchor + step + ns.length) % ns.length];
    setHoveredId(next.id);
    select(next.id);
  }

  const shown = visible.find((n) => n.id === (selectedId ?? hoveredId));
  const shownEdges = shown ? visibleEdges.filter((e) => e.source === shown.id || e.target === shown.id) : [];
  const live = shown ? `${shown.label}, ${humanize(shown.kind)}, ${shownEdges.length} connection${shownEdges.length === 1 ? "" : "s"}` : "";
  const anySynthetic = nodes.some((n) => n.isSynthetic);
  const anyDemo = nodes.some((n) => n.isDemo);

  if (isLoading) return <LoadingState label="Loading the graph…" />;
  if (error) return <ErrorState error={error} onRetry={onRetry} />;

  return (
    <div className="grid grid-cols-[minmax(0,1fr)] gap-5 xl:grid-cols-[240px_minmax(0,1fr)_320px]">
      {/* Layers + layout */}
      <Card className="space-y-5 xl:self-start">
        <fieldset>
          <legend className="mb-2 text-[14px] font-semibold text-ink">Graph layers</legend>
          <ul className="space-y-1.5">
            {legend.map((l) => {
              const on = !hidden.has(l.kind);
              const c = colorOf(l.kind);
              return (
                <li key={l.kind}>
                  <label className="flex cursor-pointer items-center gap-2.5 text-[13.5px] text-ink-body" title={l.description}>
                    <input
                      type="checkbox"
                      checked={on}
                      onChange={() =>
                        setHidden((prev) => {
                          const next = new Set(prev);
                          if (next.has(l.kind)) next.delete(l.kind);
                          else next.add(l.kind);
                          return next;
                        })
                      }
                      className="size-4 accent-[var(--primary)]"
                    />
                    <span aria-hidden className="size-2.5 rounded-full" style={{ background: c.color }} />
                    {l.label}
                  </label>
                </li>
              );
            })}
          </ul>
        </fieldset>
        <fieldset>
          <legend className="mb-2 text-[14px] font-semibold text-ink">Layout</legend>
          {(
            [
              ["force", "Force-directed"],
              ["hierarchical", "Hierarchical"],
              ...(hasRegions ? ([["region", "By region"]] as const) : []),
            ] as const
          ).map(([k, text]) => (
            <label key={k} className="flex cursor-pointer items-center gap-2.5 py-1 text-[13.5px] text-ink-body">
              <input type="radio" name={`${label}-layout`} checked={layout === k} onChange={() => setLayout(k)} className="size-4 accent-[var(--primary)]" />
              {text}
            </label>
          ))}
        </fieldset>
        <label className="block text-[13px] text-ink-secondary">
          Labels
          <select value={density} onChange={(e) => setDensity(e.target.value as Density)} className="mt-1 h-9 w-full rounded-lg border border-border bg-surface px-2 text-[13.5px] text-ink">
            <option value="all">All labels</option>
            <option value="key">Key nodes and neighbours</option>
            <option value="none">No labels</option>
          </select>
        </label>
        {(anySynthetic || anyDemo) && (
          <div className="space-y-1.5 border-t border-border pt-3 text-[12.5px] text-ink-secondary">
            {anySynthetic && (
              <p className="flex items-start gap-1.5">
                <Bot aria-hidden className="mt-0.5 size-3.5 shrink-0" />
                Synthetic nodes are AI-generated, not real people.
              </p>
            )}
            {anyDemo && (
              <p className="flex items-start gap-1.5 text-warning">
                <FlaskConical aria-hidden className="mt-0.5 size-3.5 shrink-0" />
                Demo data: labeled fixtures, not live research.
              </p>
            )}
          </div>
        )}
      </Card>

      {/* Canvas */}
      <div className="min-w-0 space-y-3">
        {filters}
        {(truncated || capped) && (
          <div role="alert" className="rounded-card border border-warning/30 bg-warning-soft px-4 py-3 text-[13.5px] text-warning">
            <p className="font-semibold">This graph is incomplete.</p>
            {capped && <p>Showing the first {MAX_NODES} of {nodes.length} nodes to keep the canvas responsive.</p>}
            {limitations.length > 0 && (
              <ul className="mt-1 list-disc pl-5 text-ink">
                {limitations.map((l, i) => (
                  <li key={i}>{l}</li>
                ))}
              </ul>
            )}
          </div>
        )}
        {visible.length === 0 ? (
          <EmptyState title={emptyTitle ?? "Nothing to show yet"} description={emptyDescription ?? "The graph fills in as runs persist results. Turned-off layers are hidden."} />
        ) : (
          <div
            tabIndex={0}
            role="application"
            aria-label={`${label}. Arrow keys move between connected nodes, Enter opens, Escape clears.`}
            onKeyDown={onKeyDown}
            className="overflow-hidden rounded-card border border-border bg-surface shadow-card"
            style={{ height }}
          >
            {!positions ? (
              <LoadingState label="Laying out the graph…" />
            ) : (
              <ReactFlow
                nodes={flowNodes}
                edges={flowEdges}
                nodeTypes={nodeTypes}
                minZoom={0.2}
                maxZoom={1.6}
                nodesDraggable={false}
                nodesConnectable={false}
                onlyRenderVisibleElements
                onNodeClick={(_, n) => select(n.id)}
                onNodeMouseEnter={(_, n) => setHoveredId(n.id)}
                onNodeMouseLeave={() => setHoveredId(null)}
                onPaneClick={() => select(null)}
              >
                <Background gap={22} color="#efe9df" />
                <Controls showInteractive={false} />
              </ReactFlow>
            )}
          </div>
        )}
        <p aria-live="polite" className="sr-only">
          {live}
        </p>
        {!truncated && !capped && limitations.length > 0 && <p className="text-[12.5px] text-ink-secondary">{limitations.join(" ")}</p>}
      </div>

      {/* Details */}
      <Card title="Node details" className="xl:self-start">
        {!shown ? (
          <p className="text-[13.5px] text-ink-secondary">Select a node to see its facts, connections, and where it came from.</p>
        ) : (
          <div className="space-y-4">
            <div className="space-y-1">
              <p className="flex items-center gap-1.5 text-[12px] font-semibold tracking-[0.06em] text-ink-secondary uppercase">
                <span aria-hidden className="size-2.5 rounded-full" style={{ background: colorOf(shown.kind).color }} />
                {legend.find((l) => l.kind === shown.kind)?.label ?? humanize(shown.kind)}
              </p>
              <p className="font-serif text-[20px] leading-tight font-semibold text-ink">{shown.label}</p>
              {(shown.isSynthetic || shown.isDemo) && (
                <p className="text-[12.5px] text-ink-secondary">{[shown.isSynthetic && "Synthetic (AI-generated)", shown.isDemo && "Demo data"].filter(Boolean).join(" · ")}</p>
              )}
            </div>
            {shown.region && <p className="text-[13.5px] text-ink-body">Region: {shown.region}</p>}
            {shown.facts && Object.keys(shown.facts).length > 0 && (
              <dl className="divide-y divide-border rounded-xl border border-border text-[13.5px]">
                {Object.entries(shown.facts).map(([k, v]) => (
                  <div key={k} className="flex justify-between gap-3 px-3 py-2">
                    <dt className="text-ink-secondary">{humanize(k)}</dt>
                    <dd className="text-right text-ink tabular-nums">{v ?? "n/a"}</dd>
                  </div>
                ))}
              </dl>
            )}
            {renderDetails?.(shown)}
            <section className="space-y-1.5">
              <h3 className="text-[13px] font-semibold text-ink">Connected to ({shownEdges.length})</h3>
              <ul className="max-h-72 space-y-1.5 overflow-y-auto">
                {shownEdges.map((e) => {
                  const otherId = e.source === shown.id ? e.target : e.source;
                  const other = visible.find((n) => n.id === otherId);
                  return (
                    <li key={e.id} className="rounded-lg border border-border px-2.5 py-1.5 text-[12.5px]">
                      <span className="text-ink-secondary">{humanize(e.relation)} · </span>
                      <button type="button" className="text-left font-medium text-primary hover:underline" onClick={() => select(otherId)}>
                        {other?.label ?? "Node outside this view"}
                      </button>
                      {e.weight !== null && e.weight !== undefined && (
                        <span className="block text-ink-body">
                          Weight {e.weight}
                          {e.weightDefinition && <span className="text-ink-secondary">: {e.weightDefinition}</span>}
                        </span>
                      )}
                      <span className="block font-mono text-[11px] text-ink-secondary">{e.provenance}</span>
                    </li>
                  );
                })}
              </ul>
            </section>
            {shown.href && (
              <Button className="w-full" onClick={() => router.push(shown.href!)}>
                Open
                <ArrowRight aria-hidden />
              </Button>
            )}
          </div>
        )}
      </Card>
    </div>
  );
}
