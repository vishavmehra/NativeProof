"use client";

import Link from "next/link";

import { ModeBadge } from "@/components/evidence/badges";
import { EmptyState, ErrorState, LoadingState } from "@/components/states";
import { Panel } from "@/features/voice/field";
import { formatDateTime } from "@/lib/format";
import { cn } from "@/lib/utils";

import { useReports } from "./api";

export function ReportList({ projectId, campaignId }: { projectId: string; campaignId: string }) {
  const reports = useReports(projectId, campaignId);
  return (
    <Panel id="reports-heading" title="Reports">
      {reports.isPending ? (
        <LoadingState label="Loading reports…" />
      ) : reports.isError ? (
        <ErrorState error={reports.error} onRetry={() => reports.refetch()} />
      ) : reports.data.items.length === 0 ? (
        <EmptyState
          title="No report yet"
          description="Create a report below. It snapshots the selected discovery, rehearsal, adaptations, and evaluation with their evidence and limitations."
        />
      ) : (
        <ul className="divide-y divide-border">
          {reports.data.items.map((r) => (
            <li key={r.id} className="flex flex-wrap items-center justify-between gap-x-4 gap-y-1 py-3">
              <div className="grid gap-0.5">
                <Link href={`/projects/${projectId}/proof/${r.id}`} className="font-serif text-lg text-ink underline-offset-2 hover:underline">
                  {r.title}
                </Link>
                <span className="text-xs text-ink-secondary tabular-nums">
                  Version {r.version_number} · {formatDateTime(r.created_at)}
                </span>
              </div>
              <div className="flex items-center gap-2">
                <span className={cn("text-xs font-medium", r.status === "partial" ? "text-warning" : "text-ink-secondary")}>
                  {r.status === "partial" ? "Partial" : "Complete"}
                </span>
                <ModeBadge mode={r.mode} />
              </div>
            </li>
          ))}
        </ul>
      )}
    </Panel>
  );
}
