import { forceCenter, forceCollide, forceLink, forceManyBody, forceSimulation, type SimulationNodeDatum } from "d3-force";

export type LayoutKind = "force" | "hierarchical" | "region";
export type Point = { x: number; y: number };
type LayoutNode = { id: string; kind: string; region?: string | null };
type LayoutEdge = { source: string; target: string };

/** Hard cap shared by every graph view: beyond this the canvas would block rendering. */
export const MAX_NODES = 300;

/**
 * Deterministic layouts (same input → same picture), so screenshots, reviews, and repeat visits agree.
 * - force: seeded d3-force with a bounded tick budget (no animation loop on the main thread).
 * - hierarchical: one column per kind, in `kindOrder`.
 * - region: one cluster per region; nodes without a region share an "Unassigned" cluster.
 */
export function computeLayout(nodes: LayoutNode[], edges: LayoutEdge[], kind: LayoutKind, kindOrder: string[]): Map<string, Point> {
  if (kind === "hierarchical") {
    const rows = new Map<string, number>();
    const order = (k: string) => (kindOrder.indexOf(k) === -1 ? kindOrder.length : kindOrder.indexOf(k));
    const out = new Map<string, Point>();
    [...nodes]
      .sort((a, b) => order(a.kind) - order(b.kind) || a.id.localeCompare(b.id))
      .forEach((n) => {
        const row = rows.get(n.kind) ?? 0;
        rows.set(n.kind, row + 1);
        out.set(n.id, { x: order(n.kind) * 240, y: row * 96 });
      });
    return out;
  }
  if (kind === "region") {
    const groups = new Map<string, LayoutNode[]>();
    nodes.forEach((n) => groups.set(n.region ?? "Unassigned", [...(groups.get(n.region ?? "Unassigned") ?? []), n]));
    const keys = [...groups.keys()].sort();
    const cols = Math.ceil(Math.sqrt(keys.length));
    const out = new Map<string, Point>();
    keys.forEach((key, gi) => {
      const members = groups.get(key)!;
      const cx = (gi % cols) * 420;
      const cy = Math.floor(gi / cols) * 380;
      const r = members.length > 1 ? 40 + members.length * 9 : 0;
      members.forEach((n, i) => {
        const a = (2 * Math.PI * i) / members.length;
        out.set(n.id, { x: cx + r * Math.cos(a), y: cy + r * Math.sin(a) });
      });
    });
    return out;
  }
  const simNodes: (SimulationNodeDatum & { id: string })[] = nodes.map((n) => ({ id: n.id }));
  const ids = new Set(nodes.map((n) => n.id));
  const links = edges.filter((e) => ids.has(e.source) && ids.has(e.target)).map((e) => ({ source: e.source, target: e.target }));
  let seed = 7;
  const random = () => ((seed = (seed * 1664525 + 1013904223) >>> 0) / 4294967296);
  const sim = forceSimulation(simNodes)
    .randomSource(random)
    .force("link", forceLink<(typeof simNodes)[number], { source: string; target: string }>(links).id((d) => d.id).distance(130).strength(0.5))
    .force("charge", forceManyBody().strength(-340).distanceMax(700))
    .force("collide", forceCollide(56))
    .force("center", forceCenter(0, 0))
    .stop();
  for (let i = 0; i < 260; i++) sim.tick();
  return new Map(simNodes.map((d) => [d.id, { x: d.x ?? 0, y: d.y ?? 0 }]));
}
