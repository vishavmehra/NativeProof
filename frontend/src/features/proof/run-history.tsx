"use client";

import Link from "next/link";
import type { ReactNode } from "react";

import { ModeBadge } from "@/components/evidence/badges";
import { EmptyState, ErrorState, LoadingState } from "@/components/states";
import { RUN_TYPE_META } from "@/features/project/workflow";
import { Panel } from "@/features/voice/field";
import type { Run } from "@/lib/api/types";
import { formatDateTime, humanize, shortId } from "@/lib/format";
import { cn } from "@/lib/utils";

import { useRunList } from "./api";

const COLUMNS = "md:grid-cols-[minmax(0,1.5fr)_6.5rem_6.5rem_minmax(0,1fr)_minmax(0,1fr)_minmax(0,1.6fr)]";

const STATUS_CLASS: Record<Run["status"], string> = {
  queued: "text-info",
  running: "text-info",
  completed: "text-success",
  partial: "text-warning",
  failed: "text-danger",
  cancelled: "text-ink-secondary",
};

/** Result page for a run: its section, with the run and campaign in the query. */
function runHref(projectId: string, run: Run) {
  const meta = RUN_TYPE_META[run.run_type];
  if (!meta) return null;
  const query = new URLSearchParams({ run: run.id });
  if (run.campaign_id) query.set("campaign", run.campaign_id);
  return `/projects/${projectId}/${meta.segment}?${query}`;
}

function Cell({ label, className, children }: { label: string; className?: string; children: ReactNode }) {
  return (
    <span className={cn("min-w-0", className)}>
      <span className="text-xs text-ink-secondary md:sr-only">{label}: </span>
      {children}
    </span>
  );
}

export function RunHistory({ projectId }: { projectId: string }) {
  const runs = useRunList(projectId);
  return (
    <Panel id="history-heading" title="Execution history">
      {runs.isPending ? (
        <LoadingState label="Loading runs…" />
      ) : runs.isError ? (
        <ErrorState error={runs.error} onRetry={() => runs.refetch()} />
      ) : runs.data.length === 0 ? (
        <EmptyState title="No runs yet" description="Runs appear here as you discover, rehearse, adapt, and compare." />
      ) : (
        <div className="text-sm">
          <div aria-hidden className={cn("hidden gap-3 border-b pb-2 text-xs font-medium text-ink-secondary md:grid", COLUMNS)}>
            <span>Run</span>
            <span>Status</span>
            <span>Mode</span>
            <span>Created</span>
            <span>Completed</span>
            <span>Error</span>
          </div>
          <ul className="divide-y divide-border">
            {runs.data.map((run) => {
              const href = runHref(projectId, run);
              const label = RUN_TYPE_META[run.run_type]?.label ?? humanize(run.run_type);
              return (
                <li key={run.id} className={cn("grid gap-1 py-2.5 md:items-baseline md:gap-3", COLUMNS)}>
                  <span className="min-w-0">
                    {href ? (
                      <Link href={href} className="font-medium text-ink underline-offset-2 hover:underline">
                        {label}
                      </Link>
                    ) : (
                      <span className="font-medium text-ink">{label}</span>
                    )}{" "}
                    <code className="font-mono text-xs text-ink-secondary">{shortId(run.id)}</code>
                  </span>
                  <Cell label="Status" className={cn("font-medium", STATUS_CLASS[run.status])}>
                    {humanize(run.status)}
                  </Cell>
                  <Cell label="Mode">
                    <ModeBadge mode={run.mode} />
                  </Cell>
                  <Cell label="Created" className="text-ink tabular-nums">
                    {formatDateTime(run.created_at)}
                  </Cell>
                  <Cell label="Completed" className="text-ink tabular-nums">
                    {formatDateTime(run.completed_at)}
                  </Cell>
                  <Cell label="Error" className="text-ink">
                    {run.error ? (
                      <>
                        {run.error.message} <code className="font-mono text-xs text-ink-secondary">{run.error.code}</code>
                      </>
                    ) : (
                      <span className="text-ink-secondary">None</span>
                    )}
                  </Cell>
                </li>
              );
            })}
          </ul>
        </div>
      )}
    </Panel>
  );
}
