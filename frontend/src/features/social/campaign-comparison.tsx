"use client";

import { CircleCheck, Plus, TriangleAlert } from "lucide-react";
import Link from "next/link";
import { useState, type ReactNode } from "react";

import { LimitationList } from "@/components/evidence/limitation-list";
import { GraphCanvas, fromGraphView } from "@/components/graph/graph-canvas";
import { EmptyState, ErrorState, LoadingState } from "@/components/states";
import { buttonVariants } from "@/components/ui/button";
import { Checkbox } from "@/components/ui/checkbox";
import { sectionHref } from "@/features/project/workflow";
import { SELECT_CLASS } from "@/features/voice/field";
import type { Campaign, CampaignComparison, PopulationStudySummary, ReactionDistribution } from "@/lib/api/types";
import { formatDate, shortId } from "@/lib/format";
import { cn } from "@/lib/utils";

import { useCampaignComparison, usePopulationStudies, usePopulations } from "./api";
import { DistributionBar } from "./distribution";

const MAX = 4;
const FIELDS = [
  ["headline", "Headline"],
  ["body", "Body"],
  ["call_to_action", "Call to action"],
] as const;

/** Tracked reactions: `better` says which direction is an improvement. */
const METRICS = [
  { key: "positive", label: "Positive reaction", better: "up", color: "var(--color-success)" },
  { key: "confused", label: "Confusion", better: "down", color: "var(--color-warning)" },
  { key: "negative", label: "Negative reaction", better: "down", color: "var(--color-danger)" },
  { key: "mixed", label: "Mixed reaction", better: null, color: "var(--color-info)" },
] as const;

/** Default: the newest usable study per content version, up to four; with only one version, its newest studies. */
function defaultPick(studies: PopulationStudySummary[]) {
  const newest = [...studies].sort((a, b) => b.created_at.localeCompare(a.created_at));
  const seen = new Set<string>();
  const perVersion = newest.filter((s) => !seen.has(s.content_version_id) && Boolean(seen.add(s.content_version_id)));
  return (perVersion.length >= 2 ? perVersion : newest).slice(0, MAX).map((s) => s.id);
}

/** All groups of one study summed: rates over the study's completed interviews. */
function totals(data: CampaignComparison, studyId: string): ReactionDistribution {
  const cells = data.results.filter((r) => r.population_study_id === studyId);
  const counts: Record<string, number> = {};
  let denominator = 0;
  let failed = 0;
  for (const c of cells) {
    denominator += c.distribution.denominator;
    failed += c.distribution.failed;
    for (const [k, n] of Object.entries(c.distribution.counts)) counts[k] = (counts[k] ?? 0) + n;
  }
  const rates = Object.fromEntries(Object.entries(counts).map(([k, n]) => [k, denominator ? n / denominator : 0]));
  return { counts, rates, denominator, failed };
}

const pts = (d: number) => `${d > 0 ? "+" : d < 0 ? "−" : "±"}${Math.abs(Math.round(d * 100))} pts`;

function Card({ title, actions, children, className }: { title: string; actions?: ReactNode; children: ReactNode; className?: string }) {
  return (
    <section aria-label={title} className={cn("grid content-start gap-4 rounded-card border border-border bg-surface p-5 shadow-card", className)}>
      <div className="flex flex-wrap items-center justify-between gap-2">
        <h2 className="font-serif text-lg text-ink">{title}</h2>
        {actions}
      </div>
      {children}
    </section>
  );
}

/** Rates per version as lines; the table underneath is the exact text equivalent. */
function TrendChart({ labels, series }: { labels: string[]; series: { label: string; color: string; values: number[] }[] }) {
  const W = 560;
  const H = 200;
  const pad = { l: 36, r: 12, t: 12, b: 28 };
  const x = (i: number) => pad.l + (labels.length === 1 ? 0 : (i * (W - pad.l - pad.r)) / (labels.length - 1));
  const y = (v: number) => pad.t + (1 - v) * (H - pad.t - pad.b);
  return (
    <figure className="grid gap-2">
      <svg viewBox={`0 0 ${W} ${H}`} className="w-full" role="img" aria-label="Reaction rates by campaign version; values are listed in the table below">
        {[0, 0.25, 0.5, 0.75, 1].map((t) => (
          <g key={t}>
            <line x1={pad.l} x2={W - pad.r} y1={y(t)} y2={y(t)} stroke="var(--color-border)" strokeDasharray={t ? "3 4" : undefined} />
            <text x={pad.l - 6} y={y(t) + 4} textAnchor="end" fontSize="10" fill="var(--color-ink-secondary)">
              {t * 100}%
            </text>
          </g>
        ))}
        {labels.map((l, i) => (
          <text key={l} x={x(i)} y={H - 8} textAnchor="middle" fontSize="10" fill="var(--color-ink-secondary)">
            {l}
          </text>
        ))}
        {series.map((s) => (
          <g key={s.label}>
            <polyline fill="none" stroke={s.color} strokeWidth="2" points={s.values.map((v, i) => `${x(i)},${y(v)}`).join(" ")} />
            {s.values.map((v, i) => (
              <circle key={i} cx={x(i)} cy={y(v)} r="3.5" fill={s.color} />
            ))}
          </g>
        ))}
      </svg>
      <figcaption className="flex flex-wrap gap-x-4 gap-y-1 text-xs text-ink-secondary">
        {series.map((s) => (
          <span key={s.label} className="flex items-center gap-1.5">
            <span aria-hidden className="h-0.5 w-4 rounded-full" style={{ background: s.color }} />
            {s.label}
          </span>
        ))}
      </figcaption>
      <table className="sr-only">
        <caption>Reaction rates by version</caption>
        <thead>
          <tr>
            <th scope="col">Reaction</th>
            {labels.map((l) => (
              <th key={l} scope="col">
                {l}
              </th>
            ))}
          </tr>
        </thead>
        <tbody>
          {series.map((s) => (
            <tr key={s.label}>
              <th scope="row">{s.label}</th>
              {s.values.map((v, i) => (
                <td key={i}>{Math.round(v * 100)}%</td>
              ))}
            </tr>
          ))}
        </tbody>
      </table>
    </figure>
  );
}

/**
 * Loop's iteration history: campaign versions, and the change in synthetic reactions between versions shown to the
 * same population (Graph D). Deltas exist only when two or more such studies exist; nothing is estimated.
 */
export function LoopIterations({ projectId, campaign, nextSteps }: { projectId: string; campaign: Campaign; nextSteps: string[] }) {
  const populations = usePopulations(projectId);
  const [populationId, setPopulationId] = useState<string>();
  const [picked, setPicked] = useState<string[]>();
  const all = populations.data?.items ?? [];
  const population = all.find((p) => p.id === populationId) ?? all[0];
  const studies = usePopulationStudies(population?.study_id);
  const usable = (studies.data?.items ?? []).filter(
    (s) => s.population_id === population?.id && s.campaign_id === campaign.id && (s.status === "completed" || s.status === "partial"),
  );
  // Two studies of one version measure run-to-run variability, not improvement.
  const versionsTested = new Set(usable.map((s) => s.content_version_id)).size;
  const chosen = picked ?? defaultPick(usable);
  const comparison = useCampaignComparison(campaign.id, population?.id, chosen);
  const versionOf = (id: string) => campaign.versions.find((v) => v.id === id)?.version_number;
  const data = comparison.data;
  const ordered = data ? [...data.studies].sort((a, b) => (versionOf(a.content_version_id) ?? 0) - (versionOf(b.content_version_id) ?? 0)) : [];
  // Repeated versions get the study id, so two studies of one version stay distinguishable.
  const repeated = new Set(ordered.map((s) => s.content_version_id)).size < ordered.length;
  const versionLabel = (s: PopulationStudySummary) =>
    `Version ${versionOf(s.content_version_id) ?? shortId(s.content_version_id)}${repeated ? ` · ${shortId(s.id)}` : ""}`;
  const versionsDesc = [...campaign.versions].sort((a, b) => b.version_number - a.version_number);

  const keyChanges = versionsDesc.slice(0, 2).length === 2
    ? FIELDS.flatMap(([f, label]) => {
        const [newer, older] = versionsDesc;
        return newer.content[f] !== older.content[f] ? [`${label}: “${older.content[f] ?? "—"}” → “${newer.content[f] ?? "—"}”`] : [];
      })
    : [];

  // Unknown is not "none": a failed or pending lookup must never read as "no population study".
  const lookupFailed = populations.isError || studies.isError;
  const checking = populations.isPending || Boolean(population && studies.isPending);

  let impact: ReactNode;
  if (checking) impact = <LoadingState label="Loading population studies…" />;
  else if (lookupFailed)
    impact = (
      <ErrorState
        error={populations.error ?? studies.error}
        onRetry={() => (populations.isError ? populations.refetch() : studies.refetch())}
      />
    );
  else if (!population || versionsTested < 2)
    impact = (
      <EmptyState
        title="Needs two versions on the same population"
        description={`Improvement deltas come only from population studies of one synthetic population on different campaign versions. ${population ? `This population has ${usable.length} finished ${usable.length === 1 ? "study" : "studies"} for this campaign, on ${versionsTested} ${versionsTested === 1 ? "version" : "versions"}.` : "No population exists yet."}`}
        action={
          <Link className={buttonVariants({ variant: "outline" })} href={sectionHref(projectId, "audience", campaign.id)}>
            Run a population study in Audience
          </Link>
        }
      />
    );
  else if (comparison.isPending) impact = <LoadingState label="Comparing versions…" />;
  else if (comparison.isError) impact = <ErrorState error={comparison.error} onRetry={() => comparison.refetch()} />;
  else if (data && ordered.length >= 2 && ordered[0].content_version_id === ordered[ordered.length - 1].content_version_id)
    impact = (
      <p className="text-sm text-ink-secondary">
        The selected studies start and end on the same version, so their differences show run-to-run variability, not improvement. Select studies of
        two different versions below.
      </p>
    );
  else if (data && ordered.length >= 2) {
    const first = totals(data, ordered[0].id);
    const last = totals(data, ordered[ordered.length - 1].id);
    impact = (
      <>
        <ul className="grid grid-cols-[minmax(0,1fr)] gap-3 sm:grid-cols-2 xl:grid-cols-4">
          {METRICS.map((m) => {
            const d = (last.rates[m.key] ?? 0) - (first.rates[m.key] ?? 0);
            const good = m.better === null || d === 0 ? null : (m.better === "up") === d > 0;
            return (
              <li key={m.key} className="grid gap-1 rounded-xl border border-border bg-surface p-3">
                <span className="text-xs text-ink-secondary">{m.label}</span>
                <span className={cn("text-2xl font-semibold tabular-nums", good === null ? "text-ink" : good ? "text-success" : "text-danger")}>{pts(d)}</span>
                <span className="text-[11px] text-ink-secondary tabular-nums">
                  {Math.round((first.rates[m.key] ?? 0) * 100)}% → {Math.round((last.rates[m.key] ?? 0) * 100)}%
                  {good !== null && (good ? " · better" : " · worse")}
                </span>
              </li>
            );
          })}
        </ul>
        <p className="text-xs text-ink-secondary">
          {versionLabel(ordered[0])} → {versionLabel(ordered[ordered.length - 1])}, same {population.size}-participant synthetic population. {data.variability_note} No
          statistical significance is claimed.
        </p>
        <TrendChart
          labels={ordered.map(versionLabel)}
          series={METRICS.slice(0, 3).map((m) => ({ label: m.label, color: m.color, values: ordered.map((s) => totals(data, s.id).rates[m.key] ?? 0) }))}
        />
      </>
    );
  }

  return (
    <div className="grid grid-cols-[minmax(0,1fr)] gap-5 xl:grid-cols-[minmax(0,18rem)_minmax(0,1fr)]">
      <Card title="Campaign iterations">
        <ul className="grid gap-2">
          {versionsDesc.map((v) => {
            const study = usable.find((s) => s.content_version_id === v.id);
            return (
              <li key={v.id} className={cn("grid gap-0.5 rounded-xl border p-3", v.id === campaign.current_version.id ? "border-primary/40 bg-accent/60" : "border-border")}>
                <span className="flex items-center gap-2 font-serif text-base text-ink">
                  Version {v.version_number}
                  {v.id === campaign.current_version.id && <span className="rounded-md bg-success-soft px-1.5 py-0.5 font-sans text-[11px] font-medium text-success">Current</span>}
                </span>
                <span className="text-xs text-ink-secondary">{formatDate(v.created_at)}</span>
                <span className="text-[11px] text-ink-secondary">
                  {lookupFailed
                    ? "Population study status unavailable"
                    : checking
                      ? "Checking population studies…"
                      : study
                        ? `Population study · ${study.completed_interviews} interviews`
                        : "No population study yet"}
                </span>
              </li>
            );
          })}
        </ul>
        <Link className={buttonVariants({ variant: "outline" })} href={sectionHref(projectId, "voice", campaign.id)}>
          <Plus aria-hidden />
          Create new iteration
        </Link>
      </Card>

      <div className="grid content-start gap-5">
        <Card
          title="Improvement impact"
          actions={
            all.length > 1 ? (
              <select
                aria-label="Population"
                className={cn(SELECT_CLASS, "w-auto")}
                value={population?.id}
                onChange={(e) => {
                  setPopulationId(e.target.value);
                  setPicked(undefined);
                }}
              >
                {all.map((p) => (
                  <option key={p.id} value={p.id}>
                    {p.size} participants · {p.group_count} groups · {formatDate(p.created_at)}
                  </option>
                ))}
              </select>
            ) : undefined
          }
        >
          {impact}
        </Card>

        <div className="grid grid-cols-[minmax(0,1fr)] gap-5 lg:grid-cols-2">
          <Card title="Key changes">
            {keyChanges.length === 0 ? (
              <p className="text-sm text-ink-secondary">{campaign.versions.length < 2 ? "Only one campaign version exists." : "The latest two versions have the same copy."}</p>
            ) : (
              <ul className="grid gap-2 text-[13px] text-ink">
                {keyChanges.map((c) => (
                  <li key={c} className="flex gap-2">
                    <CircleCheck aria-hidden className="mt-0.5 size-3.5 shrink-0 text-success" />
                    {c}
                  </li>
                ))}
              </ul>
            )}
          </Card>
          <Card title="Next steps">
            <ol className="grid gap-2 text-[13px] text-ink">
              {nextSteps.map((s, i) => (
                <li key={s} className="flex gap-2 rounded-lg bg-surface-muted/60 px-3 py-2">
                  <span className="font-semibold text-primary tabular-nums">{i + 1}</span>
                  {s}
                </li>
              ))}
            </ol>
          </Card>
        </div>

        {data && usable.length >= 2 && (
          <Card title="Groups × versions">
            <fieldset className="grid gap-2">
              <legend className="mb-1 text-sm font-medium text-ink">
                Studies compared <span className="font-normal text-ink-secondary">(2 to {MAX}, same population)</span>
              </legend>
              <ul className="flex flex-wrap gap-2">
                {usable.map((s) => {
                  const checked = chosen.includes(s.id);
                  return (
                    <li key={s.id}>
                      <label className="flex items-center gap-2 rounded-lg border border-border px-3 py-1.5 text-sm">
                        <Checkbox
                          checked={checked}
                          disabled={!checked && chosen.length >= MAX}
                          onCheckedChange={(next) => setPicked(next ? [...chosen, s.id] : chosen.filter((id) => id !== s.id))}
                        />
                        {versionLabel(s)} <span className="text-xs text-ink-secondary">{formatDate(s.created_at)}</span>
                      </label>
                    </li>
                  );
                })}
              </ul>
            </fieldset>
            <ul className="grid gap-2 sm:grid-cols-2">
              {[
                [data.consistent_population, "Same population (identical participants)"],
                [data.consistent_protocol, "Same interview protocol and depth"],
              ].map(([ok, label]) => (
                <li
                  key={String(label)}
                  className={cn("flex items-center gap-2 rounded-lg border px-3 py-2 text-sm text-ink", ok ? "border-border" : "border-warning/40 bg-warning-soft")}
                >
                  {ok ? <CircleCheck aria-hidden className="size-4 text-success" /> : <TriangleAlert aria-hidden className="size-4 text-warning" />}
                  <span className="flex-1">{label}</span>
                  <span className="text-xs font-medium">{ok ? "Yes" : "Differs"}</span>
                </li>
              ))}
            </ul>
            <div className="grid gap-3">
              {[...new Set(data.results.map((r) => r.group_id))].map((g) => (
                <section key={g} aria-label={`Group ${g}`} className="grid gap-2 rounded-lg border border-border p-3 md:grid-cols-[minmax(0,10rem)_minmax(0,1fr)]">
                  <h3 className="text-[13px] font-semibold text-ink">
                    {data.graph.nodes.find((n) => n.kind === "audience_group" && n.group_id === g)?.label ?? shortId(g)}
                  </h3>
                  <div className="grid gap-2">
                    {ordered.map((s) => {
                      const cell = data.results.find((r) => r.group_id === g && r.population_study_id === s.id);
                      return (
                        <div key={s.id} className="grid gap-0.5">
                          <span className="text-xs text-ink-secondary">{versionLabel(s)}</span>
                          {cell ? <DistributionBar distribution={cell.distribution} compact /> : <span className="text-xs text-ink-secondary">No data</span>}
                        </div>
                      );
                    })}
                  </div>
                </section>
              ))}
            </div>
            <GraphCanvas label="Campaign comparison: audience groups by campaign version" height={480} {...fromGraphView(data.graph)} />
            <LimitationList items={data.limitations} title="Comparison limitations" />
          </Card>
        )}
      </div>
    </div>
  );
}
