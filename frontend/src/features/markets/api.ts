"use client";

import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";

import { projectKeys } from "@/features/project/project-context";
import { api } from "@/lib/api/client";
import { unwrap } from "@/lib/api/errors";
import type { MarketComparisonCreate } from "@/lib/api/types";

export const marketKeys = {
  list: (projectId: string) => ["market-comparisons", projectId],
  detail: (id: string | null | undefined) => ["market-comparison", id],
};

export function useComparisons(projectId: string) {
  return useQuery({
    queryKey: marketKeys.list(projectId),
    queryFn: () =>
      unwrap(
        api.GET("/api/v1/projects/{project_id}/market-comparisons", {
          params: { path: { project_id: projectId }, query: { limit: 50 } },
        }),
      ),
  });
}

export function useComparison(comparisonId: string | null | undefined) {
  return useQuery({
    queryKey: marketKeys.detail(comparisonId),
    enabled: Boolean(comparisonId),
    queryFn: () =>
      unwrap(
        api.GET("/api/v1/market-comparisons/{comparison_id}", { params: { path: { comparison_id: comparisonId! } } }),
      ),
  });
}

export function useStartComparison(projectId: string) {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: (body: MarketComparisonCreate) =>
      unwrap(
        api.POST("/api/v1/projects/{project_id}/market-comparisons", { params: { path: { project_id: projectId } }, body }),
      ),
    onSuccess: () => void queryClient.invalidateQueries({ queryKey: projectKeys.runs(projectId) }),
  });
}
