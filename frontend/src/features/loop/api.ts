"use client";

import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";

import { api } from "@/lib/api/client";
import { unwrap } from "@/lib/api/errors";
import type { EvaluationCreate } from "@/lib/api/types";

export function useEvaluation(campaignId: string | undefined, evaluationId: string | null | undefined) {
  return useQuery({
    queryKey: ["evaluation", campaignId, evaluationId],
    enabled: Boolean(campaignId && evaluationId),
    queryFn: () =>
      unwrap(
        api.GET("/api/v1/campaigns/{campaign_id}/evaluations/{evaluation_id}", {
          params: { path: { campaign_id: campaignId!, evaluation_id: evaluationId! } },
        }),
      ),
  });
}

export function useStartEvaluation(projectId: string, campaignId: string) {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: (body: EvaluationCreate) =>
      unwrap(
        api.POST("/api/v1/campaigns/{campaign_id}/evaluations", {
          params: { path: { campaign_id: campaignId } },
          body,
        }),
      ),
    onSuccess: () => queryClient.invalidateQueries({ queryKey: ["runs", projectId] }),
  });
}
