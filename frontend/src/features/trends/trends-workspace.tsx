"use client";

import { useState, type FormEvent } from "react";

import { EmptyState, ErrorState, LoadingState } from "@/components/states";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { useDiscoveryRuns } from "@/features/atlas/api";
import { PageHeader } from "@/features/atlas/page-header";
import { useProject } from "@/features/project/project-context";
import { sectionHref } from "@/features/project/workflow";
import { formatDate, formatDateTime, shortId } from "@/lib/format";

import type { Snapshot } from "@/lib/api/types";

import { useCompareSnapshots, useCreateSnapshot, useSnapshots, useTrendComparison, useTrendComparisons } from "./api";
import { TrendBoard } from "./trend-board";
import { TrendView } from "./trend-view";

const SELECT =
  "h-8 w-full rounded-lg border border-input bg-surface px-2 text-sm outline-none focus-visible:border-ring focus-visible:ring-3 focus-visible:ring-ring/50";

function SaveSnapshot({ projectId, saved }: { projectId: string; saved: Snapshot[] }) {
  const { campaigns } = useProject();
  const runsQuery = useDiscoveryRuns(projectId);
  const create = useCreateSnapshot(projectId);
  const [runId, setRunId] = useState("");
  const [label, setLabel] = useState("");
  const runs = runsQuery.data ?? [];
  const already = new Set(saved.map((s) => s.discovery_run_id));
  // Default to the newest run that has no snapshot yet.
  const chosen = runs.find((r) => r.id === runId) ?? runs.find((r) => !already.has(r.id)) ?? runs[0];
  const defaultLabel = chosen ? `Discovery ${formatDateTime(chosen.completed_at ?? chosen.created_at)}` : "";

  function submit(event: FormEvent) {
    event.preventDefault();
    if (!chosen) return;
    create.mutate({ discovery_run_id: chosen.id, label: label.trim() || defaultLabel }, { onSuccess: () => setLabel("") });
  }

  if (runsQuery.isPending) return <LoadingState label="Loading discovery runs…" />;
  if (runsQuery.isError) return <ErrorState error={runsQuery.error} onRetry={() => runsQuery.refetch()} />;
  if (runs.length === 0)
    return <p className="text-sm text-ink-secondary">No completed discoveries to save yet. Run one in Atlas first.</p>;
  return (
    <form onSubmit={submit} className="grid gap-3">
      <div className="grid gap-1.5">
        <Label htmlFor="tw-run" className="text-xs">
          Discovery run
        </Label>
        <select id="tw-run" className={SELECT} value={chosen?.id ?? ""} onChange={(e) => setRunId(e.target.value)}>
          {runs.map((run) => (
            <option key={run.id} value={run.id}>
              {formatDateTime(run.completed_at ?? run.created_at)}
              {campaigns.find((c) => c.id === run.campaign_id) ? ` · ${campaigns.find((c) => c.id === run.campaign_id)!.name}` : ""} ·{" "}
              {shortId(run.id)}
              {already.has(run.id) ? " (saved)" : ""}
            </option>
          ))}
        </select>
      </div>
      <div className="grid gap-1.5">
        <Label htmlFor="tw-label" className="text-xs">
          Label
        </Label>
        <Input id="tw-label" value={label} maxLength={120} placeholder={defaultLabel} onChange={(e) => setLabel(e.target.value)} className="bg-surface" />
      </div>
      {Boolean(create.error) && <ErrorState error={create.error} />}
      <Button type="submit" variant="outline" disabled={create.isPending}>
        Save snapshot
      </Button>
      <p className="text-xs text-ink-secondary">A snapshot keeps that run&apos;s references and evidence as they were, dated by when the run completed.</p>
    </form>
  );
}

export function TrendsWorkspace() {
  const { project, campaign } = useProject();
  const snapshotsQuery = useSnapshots(project.id);
  const comparisonsQuery = useTrendComparisons(project.id);
  const compare = useCompareSnapshots(project.id);
  const [baseId, setBaseId] = useState("");
  const [targetId, setTargetId] = useState("");
  const [selectedId, setSelectedId] = useState<string | null>(null);

  // Oldest first, by when the underlying discovery completed; ties by when the snapshot was saved.
  const snapshots = [...(snapshotsQuery.data?.items ?? [])].sort(
    (a, b) => Date.parse(a.captured_at) - Date.parse(b.captured_at) || Date.parse(a.created_at) - Date.parse(b.created_at),
  );
  const base = snapshots.find((s) => s.id === baseId) ?? snapshots.at(-2);
  const target = snapshots.find((s) => s.id === targetId) ?? snapshots.at(-1);
  const summaries = comparisonsQuery.data?.items ?? [];
  const comparisonId = selectedId ?? summaries[0]?.id ?? null;
  const comparisonQuery = useTrendComparison(comparisonId);
  const labelOf = (id: string) => snapshots.find((s) => s.id === id)?.label ?? shortId(id);

  return (
    <div className="grid gap-8">
      <PageHeader
        feature="trends"
        title="Cultural Trend Watch"
        description="Save discovery runs as dated snapshots, then compare two of them. Comparisons are deterministic; Nativeproof never fills in history it did not record."
      />
      {snapshotsQuery.isPending ? (
        <LoadingState label="Loading snapshots…" />
      ) : snapshotsQuery.isError ? (
        <ErrorState error={snapshotsQuery.error} onRetry={() => snapshotsQuery.refetch()} />
      ) : (
        <div className="grid gap-8 lg:grid-cols-[18rem_minmax(0,1fr)] lg:items-start">
          <aside className="grid gap-6">
            <section aria-labelledby="tw-save" className="grid gap-3 rounded-lg border bg-card p-4">
              <h2 id="tw-save" className="text-[15px] font-semibold">
                Save a snapshot
              </h2>
              <SaveSnapshot projectId={project.id} saved={snapshots} />
            </section>

            <section aria-labelledby="tw-timeline" className="grid gap-3">
              <h2 id="tw-timeline" className="text-[15px] font-semibold">
                Snapshot timeline <span className="font-normal text-ink-secondary tabular-nums">{snapshots.length}</span>
              </h2>
              {snapshots.length === 0 ? (
                <p className="text-sm text-ink-secondary">No snapshots saved yet.</p>
              ) : (
                <ol className="grid border-l pl-4">
                  {snapshots.map((s) => (
                    <li key={s.id} className="relative grid gap-0.5 pb-4 last:pb-0">
                      <span aria-hidden className="absolute top-1.5 -left-[21px] size-2.5 rounded-full border-2 border-card bg-trends" />
                      <p className="text-sm font-medium">{s.label}</p>
                      <p className="text-xs text-ink-secondary tabular-nums">
                        {formatDateTime(s.captured_at)} · {s.market.display_name}
                      </p>
                      <p className="text-xs text-ink-secondary tabular-nums">
                        {s.reference_count} references · {s.evidence_count} evidence records
                        {s.mode === "demo" && " · demo fixtures"}
                      </p>
                      {s.reference_terms.length > 0 && (
                        <p className="text-xs text-ink-secondary">Terms: {s.reference_terms.join(", ")}</p>
                      )}
                    </li>
                  ))}
                </ol>
              )}
            </section>
          </aside>

          <div className="grid min-w-0 gap-6">
            {snapshots.length < 2 ? (
              <EmptyState
                title="Two snapshots are needed to compare"
                description={`You have ${snapshots.length}. Save another snapshot after a later discovery run. Trend Watch only compares snapshots that were actually saved.`}
              />
            ) : (
              <section aria-labelledby="tw-compare" className="grid gap-3 rounded-lg border bg-card p-4">
                <h2 id="tw-compare" className="text-[15px] font-semibold">
                  Compare two snapshots
                </h2>
                <form
                  className="grid gap-3 sm:grid-cols-[1fr_1fr_auto] sm:items-end"
                  onSubmit={(e) => {
                    e.preventDefault();
                    if (!base || !target || base.id === target.id) return;
                    compare.mutate(
                      { base_snapshot_id: base.id, target_snapshot_id: target.id },
                      { onSuccess: (result) => setSelectedId(result.id) },
                    );
                  }}
                >
                  {(
                    [
                      ["tw-base", "Base (earlier)", base, setBaseId],
                      ["tw-target", "Target (later)", target, setTargetId],
                    ] as const
                  ).map(([id, label, value, set]) => (
                    <div key={id} className="grid gap-1.5">
                      <Label htmlFor={id} className="text-xs">
                        {label}
                      </Label>
                      <select id={id} className={SELECT} value={value?.id ?? ""} onChange={(e) => set(e.target.value)}>
                        {snapshots.map((s) => (
                          <option key={s.id} value={s.id}>
                            {s.label} · {formatDate(s.captured_at)}
                          </option>
                        ))}
                      </select>
                    </div>
                  ))}
                  <Button type="submit" disabled={!base || !target || base.id === target.id || compare.isPending}>
                    Compare
                  </Button>
                </form>
                {base && target && base.id === target.id && <p className="text-xs text-warning">Choose two different snapshots.</p>}
                {Boolean(compare.error) && <ErrorState error={compare.error} />}
                {summaries.length > 0 && (
                  <div className="flex flex-wrap items-center gap-2 border-t pt-3">
                    <Label htmlFor="tw-history" className="text-xs">
                      Past comparisons
                    </Label>
                    <select
                      id="tw-history"
                      className={`${SELECT} w-auto max-w-full`}
                      value={comparisonId ?? ""}
                      onChange={(e) => setSelectedId(e.target.value)}
                    >
                      {summaries.map((s) => (
                        <option key={s.id} value={s.id}>
                          {labelOf(s.base_snapshot_id)} → {labelOf(s.target_snapshot_id)} · {s.change_count} changes
                          {s.comparable ? "" : " · not comparable"}
                        </option>
                      ))}
                    </select>
                  </div>
                )}
              </section>
            )}
            {comparisonsQuery.isError && <ErrorState error={comparisonsQuery.error} onRetry={() => comparisonsQuery.refetch()} />}
            {comparisonQuery.isError && <ErrorState error={comparisonQuery.error} onRetry={() => comparisonQuery.refetch()} />}
            {comparisonId && comparisonQuery.isPending && <LoadingState label="Loading comparison…" />}
            {comparisonQuery.data && (
              <>
                <TrendBoard
                  comparison={comparisonQuery.data}
                  atlasHref={sectionHref(project.id, "atlas", campaign?.id)}
                  audienceHref={sectionHref(project.id, "audience", campaign?.id)}
                />
                <TrendView comparison={comparisonQuery.data} />
              </>
            )}
          </div>
        </div>
      )}
    </div>
  );
}
