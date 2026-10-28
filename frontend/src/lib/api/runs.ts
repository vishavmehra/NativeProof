"use client";

import { useQuery } from "@tanstack/react-query";

import { api } from "./client";
import { unwrap } from "./errors";
import type { RunStatus, RunType } from "./types";

export const TERMINAL_RUN_STATUSES: readonly RunStatus[] = ["completed", "partial", "failed", "cancelled"];

export function isTerminal(status: RunStatus) {
  return TERMINAL_RUN_STATUSES.includes(status);
}

/** Poll a run (contracts/README §6): every 1.5 s for the first 30 s, then every 5 s; stop at a terminal status. */
export function useRun(runId: string | null | undefined) {
  return useQuery({
    queryKey: ["run", runId],
    enabled: Boolean(runId),
    queryFn: () => unwrap(api.GET("/api/v1/runs/{run_id}", { params: { path: { run_id: runId! } } })),
    refetchInterval: (query) => {
      const run = query.state.data;
      if (query.state.status === "error" || (run && isTerminal(run.status))) return false;
      if (!run) return 1500;
      return Date.now() - Date.parse(run.created_at) < 30_000 ? 1500 : 5000;
    },
  });
}

type LatestRunFilter = { runType: RunType; campaignId?: string; studyId?: string; status?: RunStatus };

/** The newest run matching the filter, or null. Use it to resume a stage after a page refresh. */
export function useLatestRun(projectId: string | null | undefined, filter: LatestRunFilter) {
  return useQuery({
    queryKey: ["runs", projectId, "latest", filter],
    enabled: Boolean(projectId),
    queryFn: async () => {
      const page = await unwrap(
        api.GET("/api/v1/projects/{project_id}/runs", {
          params: {
            path: { project_id: projectId! },
            query: {
              limit: 1,
              run_type: filter.runType,
              campaign_id: filter.campaignId,
              study_id: filter.studyId,
              status: filter.status,
            },
          },
        }),
      );
      return page.items[0] ?? null;
    },
  });
}
