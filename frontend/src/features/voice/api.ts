"use client";

import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";

import { api } from "@/lib/api/client";
import { unwrap } from "@/lib/api/errors";
import type { Adaptation, AdaptationCreate, AdaptationRevisionCreate } from "@/lib/api/types";

/** Every adaptation of a campaign (generated variants and user edits), oldest first. */
export function useAdaptations(campaignId: string | undefined) {
  return useQuery({
    queryKey: ["adaptations", campaignId],
    enabled: Boolean(campaignId),
    queryFn: async () => {
      const page = await unwrap(
        api.GET("/api/v1/campaigns/{campaign_id}/adaptations", {
          params: { path: { campaign_id: campaignId! }, query: { limit: 100 } },
        }),
      );
      return [...page.items].sort((a, b) => a.created_at.localeCompare(b.created_at));
    },
  });
}

export function useAdaptation(adaptationId: string | undefined) {
  return useQuery({
    queryKey: ["adaptation", adaptationId],
    enabled: Boolean(adaptationId),
    queryFn: () =>
      unwrap(api.GET("/api/v1/adaptations/{adaptation_id}", { params: { path: { adaptation_id: adaptationId! } } })),
  });
}

export function useStartAdaptation(projectId: string, campaignId: string) {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: (body: AdaptationCreate) =>
      unwrap(
        api.POST("/api/v1/campaigns/{campaign_id}/adaptations", {
          params: { path: { campaign_id: campaignId } },
          body,
        }),
      ),
    onSuccess: () => queryClient.invalidateQueries({ queryKey: ["runs", projectId] }),
  });
}

/** A user edit is stored as a new adaptation (origin user_edit); the original is never overwritten. */
export function useReviseAdaptation() {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: ({ id, body }: { id: string; body: AdaptationRevisionCreate }) =>
      unwrap(
        api.POST("/api/v1/adaptations/{adaptation_id}/revisions", {
          params: { path: { adaptation_id: id } },
          body,
        }),
      ),
    onSuccess: (adaptation: Adaptation) =>
      queryClient.invalidateQueries({ queryKey: ["adaptations", adaptation.campaign_id] }),
  });
}

/** The run's variants plus every user edit descended from them. */
export function variantsOfRun(adaptations: Adaptation[], runIds: string[]) {
  const included = new Set(runIds);
  return adaptations.filter((a) => {
    if (included.has(a.id) || (a.parent_adaptation_id && included.has(a.parent_adaptation_id))) {
      included.add(a.id);
      return true;
    }
    return false;
  });
}
