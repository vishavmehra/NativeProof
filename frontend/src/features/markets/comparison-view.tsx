"use client";

import { CircleAlertIcon, CircleCheckIcon, CircleDashedIcon, CircleSlashIcon, ScaleIcon } from "lucide-react";
import { useState, type CSSProperties, type ReactNode } from "react";

import { ClaimBadge, ConfidenceBadge, ModeBadge } from "@/components/evidence/badges";
import { WorldMap } from "@/components/data/world-map";
import { LimitationList } from "@/components/evidence/limitation-list";
import { Badge } from "@/components/ui/badge";
import { Button, buttonVariants } from "@/components/ui/button";
import { Tabs, TabsContent, TabsList, TabsTrigger } from "@/components/ui/tabs";
import { BriefFindingList } from "@/features/atlas/market-brief";
import { SignalList } from "@/features/atlas/reference-table";
import { RunProvenance } from "@/features/atlas/run-provenance";
import { flag } from "@/features/population/audience-library";
import type { MarketColumn, MarketComparison } from "@/lib/api/types";
import { formatDateTime } from "@/lib/format";
import { cn } from "@/lib/utils";


const STATUS = {
  completed: { label: "Completed", Icon: CircleCheckIcon, tone: "text-success" },
  partial: { label: "Partial", Icon: CircleDashedIcon, tone: "text-warning" },
  failed: { label: "Failed", Icon: CircleAlertIcon, tone: "text-danger" },
  unavailable: { label: "Unavailable", Icon: CircleSlashIcon, tone: "text-ink-secondary" },
} as const;

/** Row labels; every column renders one cell per row so rows align across markets (CSS subgrid). */
const ROWS = ["Evidence quality", "Signals", "Opportunities", "Risks", "Hypotheses", "Brand compatibility", "Gaps"];

function Cell({ label, children }: { label: string; children: ReactNode }) {
  return (
    <div className="grid min-w-0 grid-cols-[minmax(0,1fr)] content-start gap-1.5 border-t pt-3">
      <h4 className="text-xs font-medium tracking-wide text-ink-secondary uppercase">{label}</h4>
      {children}
    </div>
  );
}

const NotAvailable = () => <p className="text-sm text-ink-secondary">Not available for this market.</p>;

function Column({ column, evidence }: { column: MarketColumn; evidence: MarketComparison["evidence"] }) {
  const { label, Icon, tone } = STATUS[column.status];
  const hasData = column.status === "completed" || column.status === "partial";
  const q = column.evidence_quality;
  const bc = column.brand_compatibility;
  // The status message is already shown under the market name; do not repeat it as a gap.
  const gaps = column.gaps.filter((gap) => gap !== column.message);
  return (
    <section
      aria-labelledby={`mx-${column.market.country_code}`}
      className="grid gap-y-3 rounded-lg border bg-card p-4 lg:row-span-8 lg:grid-rows-subgrid"
    >
      <div className="grid min-w-0 grid-cols-[minmax(0,1fr)] content-start gap-1">
        <h3 id={`mx-${column.market.country_code}`} className="flex items-baseline gap-2 text-lg font-semibold tracking-tight">
          {column.market.display_name}
          <span className="font-mono text-xs font-normal text-ink-secondary">{column.market.country_code}</span>
        </h3>
        <p className={cn("flex items-center gap-1 text-xs font-medium", tone)}>
          <Icon aria-hidden className="size-3.5" />
          {label}
        </p>
        {column.message && <p className="text-xs text-ink-secondary">{column.message}</p>}
      </div>

      <Cell label={ROWS[0]}>
        <div className="flex flex-wrap items-center gap-2">
          <ConfidenceBadge label={q.label} />
          <span className="text-[11px] text-ink-secondary">Deterministic count</span>
        </div>
        <dl className="grid grid-cols-[1fr_auto] gap-x-3 text-xs tabular-nums">
          <dt className="text-ink-secondary">Resolved references</dt>
          <dd>{q.resolved_references}</dd>
          <dt className="text-ink-secondary">Ambiguous</dt>
          <dd>{q.ambiguous_references}</dd>
          <dt className="text-ink-secondary">Unresolved</dt>
          <dd>{q.unresolved_references}</dd>
          <dt className="text-ink-secondary">Observed records</dt>
          <dd>{q.observed_records}</dd>
        </dl>
        {q.note && <p className="text-xs text-ink-secondary">{q.note}</p>}
      </Cell>
      <Cell label={ROWS[1]}>{hasData ? <SignalList references={column.signals} evidence={evidence} /> : <NotAvailable />}</Cell>
      <Cell label={ROWS[2]}>
        {hasData ? <BriefFindingList findings={column.opportunities} evidence={evidence} empty="None identified." /> : <NotAvailable />}
      </Cell>
      <Cell label={ROWS[3]}>
        {hasData ? <BriefFindingList findings={column.risks} evidence={evidence} empty="None identified." /> : <NotAvailable />}
      </Cell>
      <Cell label={ROWS[4]}>
        {hasData ? <BriefFindingList findings={column.hypotheses} evidence={evidence} empty="None proposed." /> : <NotAvailable />}
      </Cell>
      <Cell label={ROWS[5]}>
        {bc ? (
          <>
            <div className="flex flex-wrap items-center gap-1.5">
              <ClaimBadge claim={bc.claim_type} />
              <ConfidenceBadge label={bc.confidence_label} />
            </div>
            <p className="text-sm">{bc.assessment}</p>
            {bc.brand_rules_considered.length > 0 && (
              <p className="text-xs text-ink-secondary">Brand rules considered: {bc.brand_rules_considered.join("; ")}</p>
            )}
          </>
        ) : (
          <p className="text-sm text-ink-secondary">Not assessed for this market.</p>
        )}
      </Cell>
      <Cell label={ROWS[6]}>
        {gaps.length === 0 ? (
          <p className="text-sm text-ink-secondary">No gaps reported.</p>
        ) : (
          <ul className="list-disc space-y-0.5 pl-4 text-sm">
            {gaps.map((gap) => (
              <li key={gap}>{gap}</li>
            ))}
          </ul>
        )}
      </Cell>
    </section>
  );
}

type Metric = "observed" | "resolved" | "opportunities";
const METRICS: [Metric, string, string][] = [
  ["observed", "Observed evidence", "observed evidence records"],
  ["resolved", "Resolved signals", "resolved references"],
  ["opportunities", "Opportunities", "opportunities found"],
];
const metricOf = (c: MarketColumn, m: Metric) =>
  m === "observed" ? c.evidence_quality.observed_records : m === "resolved" ? c.evidence_quality.resolved_references : c.opportunities.length;
const withData = (c: MarketColumn) => c.status === "completed" || c.status === "partial";
const card = "grid min-w-0 grid-cols-[minmax(0,1fr)] content-start gap-3 rounded-2xl border bg-card p-4 shadow-card";

function Tally({ label, value, max }: { label: string; value: number; max: number }) {
  return (
    <div className="grid grid-cols-[minmax(0,1fr)_auto] items-center gap-x-2 text-xs tabular-nums">
      <span className="text-ink-secondary">{label}</span>
      <span>{value}</span>
      <div className="col-span-2 h-1 overflow-hidden rounded-full bg-surface-muted">
        <div className="h-full rounded-full bg-markets" style={{ width: `${(value / max) * 100}%` }} />
      </div>
    </div>
  );
}

function MarketDetail({ column: c, evidence }: { column: MarketColumn; evidence: MarketComparison["evidence"] }) {
  const { label, Icon, tone } = STATUS[c.status];
  const q = c.evidence_quality;
  const total = Math.max(1, q.resolved_references + q.ambiguous_references + q.unresolved_references);
  const gaps = c.gaps.filter((gap) => gap !== c.message);
  return (
    <section aria-labelledby="mx-detail-h" className={card}>
      <div aria-hidden className="flex h-28 items-center justify-center rounded-xl bg-markets-soft text-3xl">
        {flag(c.market.country_code)}
      </div>
      <div className="flex flex-wrap items-center gap-2">
        <h2 id="mx-detail-h" className="font-serif text-2xl">
          {flag(c.market.country_code)} {c.market.display_name}
        </h2>
        <span className={cn("inline-flex items-center gap-1 rounded-full border px-2 py-0.5 text-xs font-medium", tone)}>
          <Icon aria-hidden className="size-3.5" />
          {label}
        </span>
      </div>
      {c.message && <p className="text-sm text-ink-secondary">{c.message}</p>}
      {withData(c) ? (
        <Tabs defaultValue="overview">
          <div className="-mx-1 overflow-x-auto px-1">
            <TabsList>
            <TabsTrigger value="overview">Overview</TabsTrigger>
            <TabsTrigger value="signals">Signals</TabsTrigger>
            <TabsTrigger value="opportunities">Opportunities</TabsTrigger>
            <TabsTrigger value="risks">Risks</TabsTrigger>
          </TabsList>
          </div>
          <TabsContent value="overview" className="grid min-w-0 grid-cols-[minmax(0,1fr)] gap-4 pt-3">
            <div className="grid gap-1.5">
              <h3 className="font-serif text-base">Evidence coverage</h3>
              <div role="img" aria-label={`${q.resolved_references} resolved, ${q.ambiguous_references} ambiguous, ${q.unresolved_references} unresolved references`} className="flex h-2 overflow-hidden rounded-full bg-surface-muted">
                <div className="bg-success" style={{ width: `${(q.resolved_references / total) * 100}%` }} />
                <div className="bg-warning" style={{ width: `${(q.ambiguous_references / total) * 100}%` }} />
                <div className="bg-ink-secondary/40" style={{ width: `${(q.unresolved_references / total) * 100}%` }} />
              </div>
              <p className="text-xs text-ink-secondary tabular-nums">
                {q.resolved_references} resolved · {q.ambiguous_references} ambiguous · {q.unresolved_references} unresolved ·{" "}
                {q.observed_records} observed records
              </p>
              <div className="flex flex-wrap items-center gap-2">
                <ConfidenceBadge label={q.label} />
                <span className="text-[11px] text-ink-secondary">Deterministic count</span>
              </div>
              {q.note && <p className="text-xs text-ink-secondary">{q.note}</p>}
            </div>
            <div className="grid gap-1.5">
              <h3 className="font-serif text-base">Brand compatibility</h3>
              {c.brand_compatibility ? (
                <>
                  <span className="flex flex-wrap gap-1.5">
                    <ClaimBadge claim={c.brand_compatibility.claim_type} />
                    <ConfidenceBadge label={c.brand_compatibility.confidence_label} />
                  </span>
                  <p className="text-sm">{c.brand_compatibility.assessment}</p>
                </>
              ) : (
                <p className="text-sm text-ink-secondary">Not assessed for this market.</p>
              )}
            </div>
            {gaps.length > 0 && (
              <div className="grid gap-1">
                <h3 className="font-serif text-base">Gaps</h3>
                <ul className="list-disc space-y-0.5 pl-4 text-sm">
                  {gaps.map((gap) => (
                    <li key={gap}>{gap}</li>
                  ))}
                </ul>
              </div>
            )}
          </TabsContent>
          <TabsContent value="signals" className="pt-3">
            <SignalList references={c.signals} evidence={evidence} />
          </TabsContent>
          <TabsContent value="opportunities" className="grid min-w-0 grid-cols-[minmax(0,1fr)] gap-4 pt-3">
            <BriefFindingList findings={c.opportunities} evidence={evidence} empty="None identified." />
            {c.hypotheses.length > 0 && (
              <div className="grid gap-2">
                <h3 className="font-serif text-base">Hypotheses</h3>
                <BriefFindingList findings={c.hypotheses} evidence={evidence} empty="None proposed." />
              </div>
            )}
          </TabsContent>
          <TabsContent value="risks" className="pt-3">
            <BriefFindingList findings={c.risks} evidence={evidence} empty="None identified." />
          </TabsContent>
        </Tabs>
      ) : (
        gaps.length > 0 && (
          <ul className="list-disc space-y-0.5 pl-4 text-sm">
            {gaps.map((gap) => (
              <li key={gap}>{gap}</li>
            ))}
          </ul>
        )
      )}
    </section>
  );
}

export function ComparisonView({ comparison }: { comparison: MarketComparison }) {
  const { comparability } = comparison;
  const [metric, setMetric] = useState<Metric>("observed");
  const [code, setCode] = useState<string | null>(null);
  const selected =
    comparison.columns.find((c) => c.market.country_code === code) ?? comparison.columns.find(withData) ?? comparison.columns[0];
  const max = (m: Metric) => Math.max(1, ...comparison.columns.map((c) => metricOf(c, m)));
  const unit = METRICS.find(([m]) => m === metric)![2];
  return (
    <div className="grid min-w-0 grid-cols-[minmax(0,1fr)] gap-6">
      <p className="flex flex-wrap items-center gap-x-2 gap-y-1 text-sm text-ink-secondary">
        <span>{comparison.product_category}</span>·<span className="tabular-nums">{formatDateTime(comparison.created_at)}</span>
        {comparison.status !== "completed" && <span className="font-medium text-warning">· {comparison.status}</span>}
        <ModeBadge mode={comparison.mode} />
        <span className="basis-full text-ink">{comparison.research_question}</span>
      </p>

      {comparability.market_specific_signals ? (
        <p className="flex items-start gap-2 text-xs text-ink-secondary">
          <ScaleIcon aria-hidden className="mt-0.5 size-3.5 shrink-0" />
          Markets keep the order you chose. This view does not rank them; compare the evidence.
          {comparability.notes.length > 0 && ` ${comparability.notes.join(" ")}`}
        </p>
      ) : (
        <div role="note" className="grid min-w-0 grid-cols-[minmax(0,1fr)] gap-1 rounded-2xl border bg-surface-muted px-4 py-3 text-sm">
          <p className="flex items-center gap-2 font-semibold">
            <ScaleIcon aria-hidden className="size-4" />
            These markets cannot be ranked on these signals
          </p>
          <p>The verified Qloo signals did not differ by market, so a ranking would be meaningless. Read each market for what was and was not found.</p>
          {comparability.notes.length > 0 && (
            <ul className="list-disc pl-5 text-xs">
              {comparability.notes.map((note) => (
                <li key={note}>{note}</li>
              ))}
            </ul>
          )}
        </div>
      )}

      <div className="grid min-w-0 grid-cols-[minmax(0,1fr)] gap-6 xl:grid-cols-[minmax(0,1fr)_minmax(0,24rem)]">
        <div className="grid min-w-0 grid-cols-[minmax(0,1fr)] content-start gap-6">
          <section aria-labelledby="mx-map-h" className={card}>
            <div className="flex flex-wrap items-start justify-between gap-3">
              <div>
                <h2 id="mx-map-h" className="font-serif text-2xl">
                  Market opportunity map
                </h2>
                <p className="text-sm text-ink-secondary">Shading counts stored evidence per market; it is not demand or a ranking.</p>
              </div>
              <div role="group" aria-label="Map shading" className="flex flex-wrap rounded-lg border p-0.5">
                {METRICS.map(([m, label]) => (
                  <Button key={m} size="sm" variant={metric === m ? "default" : "ghost"} aria-pressed={metric === m} onClick={() => setMetric(m)}>
                    {label}
                  </Button>
                ))}
              </div>
            </div>
            <WorldMap
              data={comparison.columns.filter(withData).map((c) => ({ country_code: c.market.country_code, value: metricOf(c, metric) }))}
              valueLabel={unit}
              tone="text-markets"
            />
            <p className="text-xs text-ink-secondary">Markets without data stay unshaded.</p>
          </section>

          <section aria-labelledby="mx-cards-h" className={card}>
            <div>
              <h2 id="mx-cards-h" className="font-serif text-2xl">
                Compare markets
              </h2>
              <p className="text-sm text-ink-secondary">Select a market for its details. Bars compare stored counts across these markets.</p>
            </div>
            <ul className="grid min-w-0 grid-cols-[minmax(0,1fr)] gap-3 sm:grid-cols-[repeat(auto-fill,minmax(11rem,1fr))]">
              {comparison.columns.map((c) => {
                const { label, tone } = STATUS[c.status];
                const active = c.market.country_code === selected?.market.country_code;
                const line = c.message ?? c.opportunities[0]?.title ?? c.gaps[0] ?? null;
                return (
                  <li key={c.market.country_code} className={cn("grid min-w-0 grid-cols-[minmax(0,1fr)] content-start gap-2 rounded-xl border p-3", active ? "border-primary bg-accent" : "bg-surface")}>
                    <span aria-hidden className="flex h-14 items-center justify-center rounded-lg bg-markets-soft text-2xl">
                      {flag(c.market.country_code)}
                    </span>
                    <span className="text-sm font-semibold">
                      {flag(c.market.country_code)} {c.market.display_name}
                    </span>
                    <span className="flex flex-wrap gap-1">
                      <span className={cn("rounded-full border px-1.5 py-0.5 text-[11px] font-medium", tone)}>{label}</span>
                      {withData(c) && <ConfidenceBadge label={c.evidence_quality.label} />}
                    </span>
                    {line && <p className="line-clamp-2 text-xs text-ink-secondary">{line}</p>}
                    {withData(c) && (
                      <div className="grid gap-1.5">
                        <Tally label="Resolved signals" value={c.evidence_quality.resolved_references} max={max("resolved")} />
                        <Tally label="Opportunities" value={c.opportunities.length} max={max("opportunities")} />
                        <Tally label="Risks" value={c.risks.length} max={Math.max(1, ...comparison.columns.map((x) => x.risks.length))} />
                      </div>
                    )}
                    <Button variant="outline" size="sm" aria-pressed={active} onClick={() => setCode(c.market.country_code)}>
                      View details
                    </Button>
                  </li>
                );
              })}
            </ul>
          </section>
        </div>
        {selected && <MarketDetail column={selected} evidence={comparison.evidence} />}
      </div>

      <section aria-label="Cross-market summary" className={card}>
        {comparison.cross_market_summary ? (
          <>
            <Badge variant="outline">Model interpretation across markets</Badge>
            <p className="max-w-prose text-base leading-relaxed">{comparison.cross_market_summary}</p>
          </>
        ) : (
          <p className="text-sm text-ink-secondary">No cross-market summary: the evidence was not sufficient for one.</p>
        )}
      </section>

      <section id="mx-detail" aria-labelledby="mx-grid-h" className="grid min-w-0 grid-cols-[minmax(0,1fr)] scroll-mt-6 gap-3">
        <h2 id="mx-grid-h" className="font-serif text-2xl">
          Detailed comparison
        </h2>
        <div
          className="grid min-w-0 grid-cols-[minmax(0,1fr)] gap-4 lg:grid-cols-[repeat(var(--cols),minmax(0,1fr))] lg:gap-y-0"
          style={{ "--cols": comparison.columns.length } as CSSProperties}
        >
          {comparison.columns.map((column) => (
            <Column key={column.market.country_code} column={column} evidence={comparison.evidence} />
          ))}
        </div>
      </section>

      <LimitationList title="Comparison limitations" items={comparison.limitations} />
      <RunProvenance metadata={comparison.run_metadata} />

      <nav aria-label="Next steps" className="flex flex-wrap items-center justify-between gap-3 rounded-2xl bg-accent px-4 py-3">
        <div>
          <p className="font-serif text-base">Compare and plan your expansion strategy</p>
          <p className="text-xs text-ink-secondary">Read every market side by side, row by row.</p>
        </div>
        <a href="#mx-detail" className={buttonVariants()}>
          See the detailed comparison
        </a>
      </nav>
    </div>
  );
}
