"use client";

import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useState } from "react";

import { projectKeys } from "@/features/project/project-context";
import { api } from "@/lib/api/client";
import { unwrap } from "@/lib/api/errors";
import { isTerminal, useLatestRun, useRun } from "@/lib/api/runs";
import type { DiscoveryCreate, Run, RunStatus, RunType } from "@/lib/api/types";

/** A run (or result) whose result content is available: completed or partial (contracts/README §6). */
export const hasResult = (run: { status: RunStatus } | null | undefined) =>
  run?.status === "completed" || run?.status === "partial";

export function useStartDiscovery(projectId: string) {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: (body: DiscoveryCreate) =>
      unwrap(api.POST("/api/v1/projects/{project_id}/discoveries", { params: { path: { project_id: projectId } }, body })),
    onSuccess: () => void queryClient.invalidateQueries({ queryKey: projectKeys.runs(projectId) }),
  });
}

export function useDiscoveryResult(projectId: string, runId: string | null | undefined) {
  return useQuery({
    queryKey: ["discovery", projectId, runId],
    enabled: Boolean(runId),
    queryFn: () =>
      unwrap(
        api.GET("/api/v1/projects/{project_id}/discoveries/{run_id}", {
          params: { path: { project_id: projectId, run_id: runId! } },
        }),
      ),
  });
}

/** Completed or partial discovery runs, newest first: the inputs Cultural DNA and Trend Watch build on. */
export function useDiscoveryRuns(projectId: string) {
  return useQuery({
    queryKey: [...projectKeys.runs(projectId), "discoveries-finished"],
    queryFn: async () => {
      const page = await unwrap(
        api.GET("/api/v1/projects/{project_id}/runs", {
          params: { path: { project_id: projectId }, query: { run_type: "market_discovery", limit: 50 } },
        }),
      );
      const finished = (run: Run) => Date.parse(run.completed_at ?? run.created_at);
      // The list endpoint does not promise an order; newest first is what the pickers need.
      return page.items
        .filter((run) => run.run_type === "market_discovery" && hasResult(run))
        .sort((a, b) => finished(b) - finished(a));
    },
  });
}

/**
 * Resume the latest run of a type (ignoring rows of another type) or follow one started in this session.
 * Remount the caller per campaign so a started run never leaks across campaigns.
 */
export function useRunFlow(projectId: string, runType: RunType, campaignId?: string) {
  const latestQuery = useLatestRun(projectId, { runType, campaignId });
  const latest = latestQuery.data?.run_type === runType ? latestQuery.data : null;
  const [startedRunId, setStartedRunId] = useState<string | null>(null);
  const runId = startedRunId ?? latest?.id ?? null;
  const runQuery = useRun(runId);
  const run = runQuery.data;
  return { latestQuery, runQuery, run, runId, setStartedRunId, busy: Boolean(run && !isTerminal(run.status)) };
}

/** Put the run being shown into ?run= so a reload or a shared link shows the same run. */
export function setRunParam(runId: string) {
  const params = new URLSearchParams(window.location.search);
  params.set("run", runId);
  window.history.replaceState(null, "", `?${params}`);
}
