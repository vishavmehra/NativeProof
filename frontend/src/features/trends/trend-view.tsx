"use client";

import { useState } from "react";

import { ClaimBadge } from "@/components/evidence/badges";
import { useEvidenceInspector } from "@/components/evidence/evidence-inspector";
import { LimitationList } from "@/components/evidence/limitation-list";
import { Button } from "@/components/ui/button";
import { Checkbox } from "@/components/ui/checkbox";
import { Label } from "@/components/ui/label";
import type { ClaimType, ObservationChange, Snapshot, TrendComparison } from "@/lib/api/types";
import { CLAIM_LABEL } from "@/lib/evidence";
import { formatDate, formatDateTime, humanize } from "@/lib/format";
import { cn } from "@/lib/utils";

import { useEvidenceFetcher } from "./api";

const KIND_TONE: Record<ObservationChange["kind"], string> = {
  added: "text-success",
  removed: "text-danger",
  status_changed: "text-warning",
  attribute_changed: "text-info",
  unchanged: "text-ink-secondary",
};
// Stacks each row into labeled lines below md, so the table never scrolls sideways on phones.
const CELL =
  "py-2 pr-3 align-top max-md:grid max-md:grid-cols-[6.5rem_minmax(0,1fr)] max-md:gap-2 max-md:py-0 max-md:pr-0 max-md:before:text-xs max-md:before:text-ink-secondary max-md:before:content-[attr(data-label)]";

const num = (value: string | null) => (value === null || value.trim() === "" ? NaN : Number(value));

/** Two-point slope chart per attribute: drawn only from numeric source values that changed. */
function SlopeChart({ attribute, changes, base, target }: { attribute: string; changes: ObservationChange[]; base: Snapshot; target: Snapshot }) {
  const rows = changes.map((c) => ({ label: c.entity?.name ?? c.reference_key, before: num(c.before), after: num(c.after) }));
  let min = Math.min(...rows.flatMap((r) => [r.before, r.after]));
  let max = Math.max(...rows.flatMap((r) => [r.before, r.after]));
  if (min === max) [min, max] = [min - 1, max + 1];
  const y = (v: number) => 14 + (1 - (v - min) / (max - min)) * 112;
  const [x0, x1] = [70, 250];
  const text = rows.map((r) => `${r.label}: ${r.before} to ${r.after}`).join("; ");
  return (
    <figure className="grid gap-1 rounded-md border bg-card p-3">
      <figcaption className="text-sm font-medium">{humanize(attribute)}</figcaption>
      <svg viewBox="0 0 400 160" role="img" aria-label={`${humanize(attribute)}, source units: ${text}`} className="w-full max-w-md">
        {[x0, x1].map((x) => (
          <line key={x} x1={x} x2={x} y1={8} y2={132} className="stroke-border" strokeWidth={1} />
        ))}
        {rows.map((r) => (
          <g key={r.label} className="text-ink">
            <line x1={x0} y1={y(r.before)} x2={x1} y2={y(r.after)} className="stroke-current" strokeWidth={1.5} />
            <circle cx={x0} cy={y(r.before)} r={3} className="fill-current" />
            <circle cx={x1} cy={y(r.after)} r={3} className="fill-current" />
            <text x={x0 - 8} y={y(r.before) + 4} textAnchor="end" className="fill-ink-secondary text-[11px] tabular-nums">
              {r.before}
            </text>
            <text x={x1 + 8} y={y(r.after) + 4} className="fill-ink text-[11px] tabular-nums">
              {r.after} {r.label.length > 18 ? `${r.label.slice(0, 17)}…` : r.label}
            </text>
          </g>
        ))}
        <text x={x0} y={152} textAnchor="middle" className="fill-ink-secondary text-[11px]">
          {formatDate(base.captured_at)}
        </text>
        <text x={x1} y={152} textAnchor="middle" className="fill-ink-secondary text-[11px]">
          {formatDate(target.captured_at)}
        </text>
      </svg>
      <p className="text-[11px] text-ink-secondary">Source values in the provider&apos;s own units, at the two snapshot dates. Only changed numeric values are drawn.</p>
    </figure>
  );
}

export function TrendView({ comparison }: { comparison: TrendComparison }) {
  const { inspect } = useEvidenceInspector();
  const fetchEvidence = useEvidenceFetcher();
  const [showUnchanged, setShowUnchanged] = useState(false);
  const { base, target } = comparison;

  const unchanged = comparison.changes.filter((c) => c.kind === "unchanged").length;
  const rows = showUnchanged ? comparison.changes : comparison.changes.filter((c) => c.kind !== "unchanged");
  const numeric = comparison.changes.filter(
    (c) => c.kind === "attribute_changed" && c.delta !== null && Number.isFinite(num(c.before)) && Number.isFinite(num(c.after)),
  );
  const byAttribute = Object.entries(
    numeric.reduce<Record<string, ObservationChange[]>>((acc, c) => {
      (acc[c.attribute ?? "value"] ??= []).push(c);
      return acc;
    }, {}),
  );

  async function openEvidence(title: string, ids: string[]) {
    try {
      inspect({ title, records: await fetchEvidence(ids) });
    } catch {
      inspect({ title, records: [], limitations: ["The evidence records could not be loaded. Try again."] });
    }
  }

  return (
    <div className="grid gap-8">
      <div className="grid gap-1 border-b pb-4">
        <h2 className="text-2xl font-semibold tracking-tight">
          {base.label} → {target.label}
        </h2>
        <p className="text-sm text-ink-secondary tabular-nums">
          {base.market.display_name} · captured {formatDateTime(base.captured_at)} and {formatDateTime(target.captured_at)} ·{" "}
          {comparison.change_count} {comparison.change_count === 1 ? "change" : "changes"} · deterministic comparison, no model
          call
        </p>
      </div>

      {!comparison.comparable && (
        <div role="note" className="grid gap-1 rounded-md border border-warning/40 bg-warning-soft px-4 py-3 text-sm">
          <p className="font-semibold text-warning">These snapshots are not directly comparable</p>
          <p>Differences below may come from changed inputs rather than changes in the market.</p>
          <ul className="list-disc pl-5 text-xs">
            {comparison.comparability_notes.map((note) => (
              <li key={note}>{note}</li>
            ))}
          </ul>
        </div>
      )}
      {comparison.comparable && comparison.comparability_notes.length > 0 && (
        <p className="text-xs text-ink-secondary">{comparison.comparability_notes.join(" ")}</p>
      )}

      <section aria-labelledby="tw-changes" className="grid gap-3">
        <div className="flex flex-wrap items-center justify-between gap-2">
          <h3 id="tw-changes" className="text-xl font-semibold tracking-tight">
            Changes
          </h3>
          {unchanged > 0 && (
            <Label className="text-xs font-normal">
              <Checkbox checked={showUnchanged} onCheckedChange={(next) => setShowUnchanged(next)} />
              Show {unchanged} unchanged
            </Label>
          )}
        </div>
        {rows.length === 0 ? (
          <p className="text-sm text-ink-secondary">No observations changed between these snapshots.</p>
        ) : (
          <table className="w-full text-sm">
            <thead className="border-b text-left text-xs text-ink-secondary max-md:sr-only">
              <tr>
                <th className="py-2 pr-3 font-medium">Change</th>
                <th className="py-2 pr-3 font-medium">Reference</th>
                <th className="py-2 pr-3 font-medium">Attribute</th>
                <th className="py-2 pr-3 font-medium">Before</th>
                <th className="py-2 pr-3 font-medium">After</th>
                <th className="py-2 pr-3 text-right font-medium">Δ</th>
                <th className="py-2 font-medium">Evidence</th>
              </tr>
            </thead>
            <tbody className="max-md:grid max-md:gap-2">
              {rows.map((c, i) => (
                <tr key={`${c.reference_key}-${c.attribute}-${i}`} className="border-b max-md:grid max-md:gap-1 max-md:rounded-md max-md:border max-md:p-3">
                  <td data-label="Change" className={cn(CELL, "font-medium", KIND_TONE[c.kind])}>
                    {humanize(c.kind)}
                  </td>
                  <td data-label="Reference" className={CELL}>
                    <span>
                      {c.entity?.name ?? c.reference_key}
                      {c.entity?.name && <span className="block font-mono text-[11px] text-ink-secondary">{c.reference_key}</span>}
                    </span>
                  </td>
                  <td data-label="Attribute" className={CELL}>
                    {c.attribute ?? "—"}
                  </td>
                  <td data-label="Before" className={cn(CELL, "tabular-nums")}>
                    {c.before ?? "—"}
                  </td>
                  <td data-label="After" className={cn(CELL, "tabular-nums")}>
                    {c.after ?? "—"}
                  </td>
                  <td data-label="Δ" className={cn(CELL, "tabular-nums md:text-right")}>
                    {c.delta === null ? "—" : `${c.delta > 0 ? "+" : ""}${c.delta}`}
                  </td>
                  <td data-label="Evidence" className={cn(CELL, "pr-0")}>
                    <span className="flex flex-wrap gap-1">
                      {c.evidence_ids_before.length > 0 && (
                        <Button variant="outline" size="xs" onClick={() => openEvidence(`${c.reference_key} — before`, c.evidence_ids_before)}>
                          Before ({c.evidence_ids_before.length})
                        </Button>
                      )}
                      {c.evidence_ids_after.length > 0 && (
                        <Button variant="outline" size="xs" onClick={() => openEvidence(`${c.reference_key} — after`, c.evidence_ids_after)}>
                          After ({c.evidence_ids_after.length})
                        </Button>
                      )}
                      {c.evidence_ids_before.length + c.evidence_ids_after.length === 0 && (
                        <span className="text-xs text-ink-secondary">None</span>
                      )}
                    </span>
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        )}
      </section>

      {byAttribute.length > 0 && (
        <section aria-labelledby="tw-series" className="grid gap-3">
          <h3 id="tw-series" className="text-xl font-semibold tracking-tight">
            Numeric changes over time
          </h3>
          <div className="grid gap-3 md:grid-cols-2">
            {byAttribute.map(([attribute, changes]) => (
              <SlopeChart key={attribute} attribute={attribute} changes={changes} base={base} target={target} />
            ))}
          </div>
        </section>
      )}

      <section aria-labelledby="tw-implications" className="grid gap-3">
        <h3 id="tw-implications" className="text-xl font-semibold tracking-tight">
          Possible implications
        </h3>
        {comparison.implications.length === 0 ? (
          <p className="text-sm text-ink-secondary">No implications were drawn.</p>
        ) : (
          <ul className="grid gap-3">
            {comparison.implications.map((imp) => (
              <li key={imp.text} className="grid gap-1">
                <div className="flex flex-wrap items-center gap-2">
                  {imp.claim_type in CLAIM_LABEL ? (
                    <ClaimBadge claim={imp.claim_type as ClaimType} />
                  ) : (
                    <span className="text-xs text-ink-secondary">{humanize(imp.claim_type)}</span>
                  )}
                  <span className="text-sm">{imp.text}</span>
                </div>
                {imp.based_on.length > 0 && <p className="text-xs text-ink-secondary">Based on: {imp.based_on.join(", ")}</p>}
              </li>
            ))}
          </ul>
        )}
        <p className="text-xs text-ink-secondary">Implications are hypotheses to validate, not findings.</p>
      </section>

      <LimitationList title="Comparison limitations" items={comparison.limitations} />
    </div>
  );
}
