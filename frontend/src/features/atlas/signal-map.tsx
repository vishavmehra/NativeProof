"use client";

import type { CulturalReference } from "@/lib/api/types";
import { cn } from "@/lib/utils";

// Cluster hues from the feature palette; status is also stated in text and shape, never by color alone.
const HUES = ["bg-atlas", "bg-dna", "bg-markets", "bg-voice", "bg-trends", "bg-audience"];
const RELATED = /^related to (.+)$/i;

type Placed = { ref: CulturalReference; x: number; y: number; hue: string; outer: boolean; parent?: { x: number; y: number } };

/** Radial layout of one discovery: user terms on the inner ring, their related interests on the outer ring. */
function layout(references: CulturalReference[]): Placed[] {
  const related = references.filter((r) => RELATED.test(r.query_term));
  const primary = references.filter((r) => !RELATED.test(r.query_term));
  const placed: Placed[] = [];
  primary.forEach((ref, i) => {
    const a = -Math.PI / 2 + (2 * Math.PI * i) / Math.max(primary.length, 1);
    const p = { x: 50 + 27 * Math.cos(a), y: 50 + 30 * Math.sin(a) };
    const hue = HUES[i % HUES.length];
    placed.push({ ref, ...p, hue, outer: false });
    const kids = related.filter((r) => r.query_term.match(RELATED)?.[1]?.toLowerCase() === ref.name?.toLowerCase());
    kids.forEach((kid, k) => {
      const ka = a + (k - (kids.length - 1) / 2) * 0.42;
      placed.push({ ref: kid, x: 50 + 43 * Math.cos(ka), y: 50 + 42 * Math.sin(ka), hue, outer: true, parent: p });
    });
  });
  // Related interests whose parent is not on the map still appear, on the outer ring.
  const orphans = related.filter((r) => !placed.some((p) => p.ref.id === r.id));
  orphans.forEach((ref, i) => {
    const a = Math.PI / 2 + (2 * Math.PI * i) / Math.max(orphans.length, 1);
    placed.push({ ref, x: 50 + 43 * Math.cos(a), y: 50 + 42 * Math.sin(a), hue: HUES[(i + 3) % HUES.length], outer: true });
  });
  return placed;
}

export function SignalMap({
  center,
  references,
  selectedId,
  onSelect,
}: {
  center: string;
  references: CulturalReference[];
  selectedId: string | null;
  onSelect: (id: string) => void;
}) {
  const nodes = layout(references);
  return (
    <div className="relative h-[22rem] w-full min-w-0 sm:h-[26rem]">
      <svg aria-hidden className="absolute inset-0 size-full" viewBox="0 0 100 100" preserveAspectRatio="none">
        {nodes.map((n) => {
          const from = n.parent ?? { x: 50, y: 50 };
          return (
            <line
              key={n.ref.id}
              x1={from.x}
              y1={from.y}
              x2={n.x}
              y2={n.y}
              vectorEffect="non-scaling-stroke"
              className={cn("stroke-border", n.ref.match_status !== "resolved" && "[stroke-dasharray:4_4]")}
              strokeWidth={1.25}
            />
          );
        })}
      </svg>
      <div className="absolute top-1/2 left-1/2 grid -translate-x-1/2 -translate-y-1/2 justify-items-center gap-1 text-center">
        <span className="flex size-14 items-center justify-center rounded-full bg-primary text-sm font-semibold text-primary-foreground shadow-raised">
          {center.slice(0, 1).toUpperCase()}
        </span>
        <span className="max-w-36 font-serif text-sm leading-tight font-semibold">{center}</span>
      </div>
      {nodes.map((n) => {
        const status = n.ref.match_status;
        const label = n.ref.name ?? `“${n.ref.query_term}”`;
        return (
          <button
            key={n.ref.id}
            type="button"
            onClick={() => onSelect(n.ref.id)}
            aria-pressed={n.ref.id === selectedId}
            aria-label={`${label}: ${status}`}
            style={{ left: `${n.x}%`, top: `${n.y}%` }}
            className={cn(
              "absolute grid max-w-28 -translate-x-1/2 -translate-y-1/2 justify-items-center gap-1 rounded-lg p-1 text-center",
              n.ref.id === selectedId && "bg-accent",
            )}
          >
            <span
              aria-hidden
              className={cn(
                "rounded-full ring-4 ring-surface",
                n.outer ? "size-3.5" : "size-6",
                status === "resolved" ? n.hue : "border-2 border-dashed border-ink-secondary bg-surface",
              )}
            />
            <span className={cn("text-xs leading-tight", !n.outer && "font-serif font-semibold")}>
              {label}
              {status !== "resolved" && <span className="block text-[11px] font-normal text-ink-secondary">{status}</span>}
            </span>
          </button>
        );
      })}
    </div>
  );
}
