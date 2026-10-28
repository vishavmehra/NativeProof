"use client";

import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";

import { api } from "@/lib/api/client";
import { unwrap } from "@/lib/api/errors";
import type { SnapshotCreate, TrendComparisonCreate } from "@/lib/api/types";

export const trendKeys = {
  snapshots: (projectId: string) => ["snapshots", projectId],
  comparisons: (projectId: string) => ["trend-comparisons", projectId],
  comparison: (id: string | null | undefined) => ["trend-comparison", id],
};

export function useSnapshots(projectId: string) {
  return useQuery({
    queryKey: trendKeys.snapshots(projectId),
    queryFn: () =>
      unwrap(
        api.GET("/api/v1/projects/{project_id}/snapshots", { params: { path: { project_id: projectId }, query: { limit: 100 } } }),
      ),
  });
}

export function useCreateSnapshot(projectId: string) {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: (body: SnapshotCreate) =>
      unwrap(api.POST("/api/v1/projects/{project_id}/snapshots", { params: { path: { project_id: projectId } }, body })),
    onSuccess: () => void queryClient.invalidateQueries({ queryKey: trendKeys.snapshots(projectId) }),
  });
}

export function useTrendComparisons(projectId: string) {
  return useQuery({
    queryKey: trendKeys.comparisons(projectId),
    queryFn: () =>
      unwrap(
        api.GET("/api/v1/projects/{project_id}/trend-comparisons", {
          params: { path: { project_id: projectId }, query: { limit: 50 } },
        }),
      ),
  });
}

export function useTrendComparison(comparisonId: string | null | undefined) {
  return useQuery({
    queryKey: trendKeys.comparison(comparisonId),
    enabled: Boolean(comparisonId),
    queryFn: () =>
      unwrap(api.GET("/api/v1/trend-comparisons/{comparison_id}", { params: { path: { comparison_id: comparisonId! } } })),
  });
}

/** Synchronous and deterministic: the response is the finished comparison. */
export function useCompareSnapshots(projectId: string) {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: (body: TrendComparisonCreate) =>
      unwrap(api.POST("/api/v1/projects/{project_id}/trend-comparisons", { params: { path: { project_id: projectId } }, body })),
    onSuccess: (comparison) => {
      queryClient.setQueryData(trendKeys.comparison(comparison.id), comparison);
      // Not awaited: show the comparison now; the history list refreshes in the background.
      void queryClient.invalidateQueries({ queryKey: trendKeys.comparisons(projectId) });
    },
  });
}

/** Fetch evidence records by id (trend changes carry ids only). */
export function useEvidenceFetcher() {
  const queryClient = useQueryClient();
  return (ids: string[]) =>
    Promise.all(
      ids.map((id) =>
        queryClient.fetchQuery({
          queryKey: ["evidence", id],
          queryFn: () => unwrap(api.GET("/api/v1/evidence/{evidence_id}", { params: { path: { evidence_id: id } } })),
        }),
      ),
    );
}
