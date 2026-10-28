"use client";

import { SELECT_CLASS } from "@/features/voice/field";
import type { Run, RunType } from "@/lib/api/types";
import { formatDateTime, shortId } from "@/lib/format";

import { hasResult, useRunList } from "./api";

/** Select value meaning "do not use any run". */
export const NONE = "none";

/** Runs of one type whose result can be read, newest first. */
export function useResultRuns(projectId: string, runType: RunType, campaignId?: string) {
  const query = useRunList(projectId, { runType, campaignId });
  return { runs: (query.data ?? []).filter(hasResult), isPending: query.isPending, error: query.error };
}

export function runLabel(run: Run) {
  return `${formatDateTime(run.completed_at ?? run.created_at)} · ${shortId(run.id)}${run.status === "partial" ? " (partial)" : ""}`;
}

/**
 * A run picker with an explicit "none" option. A linked id missing from `runs` stays selectable.
 * `failed` marks a list that could not load, so "None" never reads as "no runs exist".
 */
export function RunSelect({
  id,
  runs,
  value,
  onChange,
  noneLabel,
  describedBy,
  failed,
}: {
  id: string;
  runs: Run[];
  value: string;
  onChange(value: string): void;
  noneLabel: string;
  describedBy?: string;
  failed?: unknown;
}) {
  return (
    <select id={id} className={SELECT_CLASS} value={value} onChange={(e) => onChange(e.target.value)} aria-describedby={describedBy}>
      <option value={NONE}>{failed ? `${noneLabel} · past runs could not load, reload to retry` : noneLabel}</option>
      {value !== NONE && !runs.some((run) => run.id === value) && <option value={value}>Linked run · {shortId(value)}</option>}
      {runs.map((run) => (
        <option key={run.id} value={run.id}>
          {runLabel(run)}
        </option>
      ))}
    </select>
  );
}
