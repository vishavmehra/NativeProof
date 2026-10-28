"use client";

import { ArrowDownRightIcon, ArrowRightIcon, ArrowUpRightIcon, ChevronRightIcon, MinusIcon, RefreshCwIcon, SparklesIcon } from "lucide-react";
import Link from "next/link";
import { useState } from "react";

import { ClaimBadge } from "@/components/evidence/badges";
import { buttonVariants } from "@/components/ui/button";
import type { ObservationChange, TrendComparison } from "@/lib/api/types";
import { formatDate } from "@/lib/format";
import { cn } from "@/lib/utils";

/** Direction from the stored change itself: additions and numeric rises are rising; nothing is extrapolated. */
function direction(c: ObservationChange) {
  if (c.kind === "added" || (c.delta !== null && c.delta > 0)) return { label: "Rising", Icon: ArrowUpRightIcon, tone: "text-success" };
  if (c.kind === "removed" || (c.delta !== null && c.delta < 0)) return { label: "Falling", Icon: ArrowDownRightIcon, tone: "text-danger" };
  if (c.kind === "unchanged") return { label: "Stable", Icon: MinusIcon, tone: "text-ink-secondary" };
  return { label: "Changed", Icon: RefreshCwIcon, tone: "text-info" };
}

const num = (v: string | null) => (v === null || v.trim() === "" ? NaN : Number(v));
const key = (c: ObservationChange, i: number) => `${c.reference_key}|${c.attribute ?? ""}|${i}`;

/** Two-point line from the two stored snapshot values; nothing in between is drawn because nothing was recorded. */
function Spark({ c, large = false }: { c: ObservationChange; large?: boolean }) {
  const [a, b] = [num(c.before), num(c.after)];
  if (!Number.isFinite(a) || !Number.isFinite(b)) return null;
  const [lo, hi] = [Math.min(a, b), Math.max(a, b)];
  const y = (v: number) => (hi === lo ? 50 : 80 - ((v - lo) / (hi - lo)) * 60);
  return (
    <svg aria-hidden viewBox="0 0 100 100" preserveAspectRatio="none" className={large ? "h-24 w-full" : "h-8 w-20"}>
      <line x1="8" y1={y(a)} x2="92" y2={y(b)} vectorEffect="non-scaling-stroke" className="stroke-success" strokeWidth={2} />
      <circle cx="8" cy={y(a)} r="3" className="fill-success" />
      <circle cx="92" cy={y(b)} r="3" className="fill-success" />
    </svg>
  );
}

export function TrendBoard({ comparison, atlasHref, audienceHref }: { comparison: TrendComparison; atlasHref: string; audienceHref: string }) {
  const [onlyChanges, setOnlyChanges] = useState(true);
  const rows = comparison.changes.map((c, i) => ({ c, k: key(c, i) })).filter(({ c }) => !onlyChanges || c.kind !== "unchanged");
  const [selectedKey, setSelectedKey] = useState<string | null>(null);
  const selected = rows.find((r) => r.k === selectedKey) ?? rows[0];
  const implications = selected ? comparison.implications.filter((imp) => imp.based_on.includes(selected.c.reference_key)) : [];

  return (
    <div className="grid min-w-0 grid-cols-[minmax(0,1fr)] gap-6 xl:grid-cols-[minmax(0,1fr)_minmax(0,26rem)]">
      <section aria-labelledby="trends-h" className="grid min-w-0 grid-cols-[minmax(0,1fr)] content-start gap-3 rounded-2xl border bg-card p-4 shadow-card">
        <div className="flex flex-wrap items-start justify-between gap-3">
          <div>
            <h2 id="trends-h" className="font-serif text-2xl">
              Trends
            </h2>
            <p className="text-sm text-ink-secondary tabular-nums">
              Cultural signals that changed between {formatDate(comparison.base.captured_at)} and {formatDate(comparison.target.captured_at)}.
            </p>
          </div>
          <label className="flex items-center gap-2 text-sm">
            <input type="checkbox" className="size-4 accent-primary" checked={onlyChanges} onChange={(e) => setOnlyChanges(e.target.checked)} />
            Show only changes
          </label>
        </div>
        {rows.length === 0 ? (
          <p className="text-sm text-ink-secondary">No observations changed between these snapshots.</p>
        ) : (
          <ul className="grid gap-2">
            {rows.map(({ c, k }) => {
              const d = direction(c);
              const active = selected?.k === k;
              return (
                <li key={k}>
                  <button
                    type="button"
                    aria-pressed={active}
                    onClick={() => setSelectedKey(k)}
                    className={cn(
                      "grid w-full grid-cols-[auto_minmax(0,1fr)_auto_auto] items-center gap-3 rounded-xl border p-2.5 text-left",
                      active ? "border-primary bg-accent" : "bg-surface hover:bg-surface-muted",
                    )}
                  >
                    <span aria-hidden className="flex size-12 items-center justify-center rounded-lg bg-trends-soft text-trends">
                      <SparklesIcon className="size-5" />
                    </span>
                    <span className="min-w-0">
                      <span className="block truncate font-serif text-[15px] font-semibold">{c.entity?.name ?? c.reference_key}</span>
                      <span className="block truncate text-xs text-ink-secondary">
                        {c.attribute ? `${c.attribute}: ${c.before ?? "—"} → ${c.after ?? "—"}` : c.kind.replace("_", " ")}
                      </span>
                    </span>
                    <span className="max-sm:hidden">{<Spark c={c} />}</span>
                    <span className={cn("flex items-center gap-1 text-xs font-medium", d.tone)}>
                      <d.Icon aria-hidden className="size-3.5" />
                      {d.label}
                      <ChevronRightIcon aria-hidden className="size-4 text-ink-secondary" />
                    </span>
                  </button>
                </li>
              );
            })}
          </ul>
        )}
      </section>

      {selected && (
        <section aria-labelledby="trend-detail-h" className="grid min-w-0 grid-cols-[minmax(0,1fr)] content-start gap-4 rounded-2xl border bg-card p-4 shadow-card">
          <div className="grid min-w-0 grid-cols-[minmax(0,1fr)] gap-2 rounded-xl bg-trends-soft p-4">
            <span className={cn("flex w-fit items-center gap-1 rounded-full bg-surface px-2 py-0.5 text-xs font-medium", direction(selected.c).tone)}>
              {direction(selected.c).label}
            </span>
            <h2 id="trend-detail-h" className="font-serif text-3xl leading-tight">
              {selected.c.entity?.name ?? selected.c.reference_key}
            </h2>
            <p className="font-mono text-[11px] text-ink-secondary">{selected.c.reference_key}</p>
          </div>
          <div className="grid gap-1.5">
            <h3 className="font-serif text-lg">What&apos;s changing?</h3>
            <p className="text-sm">
              {selected.c.kind === "added"
                ? "This signal appears in the later snapshot and not in the earlier one."
                : selected.c.kind === "removed"
                  ? "This signal was in the earlier snapshot and is missing from the later one."
                  : selected.c.kind === "status_changed"
                    ? `Its match status changed from ${selected.c.before ?? "—"} to ${selected.c.after ?? "—"}.`
                    : selected.c.kind === "attribute_changed"
                      ? `${selected.c.attribute} moved from ${selected.c.before ?? "—"} to ${selected.c.after ?? "—"}${selected.c.delta !== null ? ` (${selected.c.delta > 0 ? "+" : ""}${selected.c.delta}, in the source's own units)` : ""}.`
                      : "No change between these snapshots."}
            </p>
            <Spark c={selected.c} large />
            <p className="text-[11px] text-ink-secondary">
              Two stored snapshots only; nothing between them was recorded, so no trend line is extrapolated.
            </p>
          </div>
          <div className="grid gap-1.5">
            <div className="flex flex-wrap items-center gap-2">
              <h3 className="font-serif text-lg">Why it might matter</h3>
              <ClaimBadge claim="hypothesis" />
            </div>
            {implications.length === 0 ? (
              <p className="text-sm text-ink-secondary">No implication was drawn from this change.</p>
            ) : (
              <ul className="grid min-w-0 grid-cols-[minmax(0,1fr)] gap-1 text-sm">
                {implications.map((imp) => (
                  <li key={imp.text}>{imp.text}</li>
                ))}
              </ul>
            )}
          </div>
          <div className="grid gap-1.5">
            <h3 className="font-serif text-lg">What we don&apos;t know</h3>
            <ul className="list-disc space-y-0.5 pl-4 text-sm">
              {(comparison.comparable ? [] : comparison.comparability_notes).concat(comparison.limitations).map((line) => (
                <li key={line}>{line}</li>
              ))}
            </ul>
          </div>
          <div className="grid min-w-0 grid-cols-[minmax(0,1fr)] gap-2 sm:grid-cols-2">
            <Link href={atlasHref} className={buttonVariants({ variant: "outline" })}>
              Explore in Atlas
            </Link>
            <Link href={audienceHref} className={buttonVariants()}>
              Test with an audience <ArrowRightIcon aria-hidden data-icon="inline-end" />
            </Link>
          </div>
        </section>
      )}
    </div>
  );
}
