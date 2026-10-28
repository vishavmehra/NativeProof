"use client";

import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";

import { api } from "@/lib/api/client";
import { unwrap } from "@/lib/api/errors";
import type { ArenaCreate } from "@/lib/api/types";

export type { ArenaCreate, ArenaResult, ArenaVariantInput, ArenaVariantResult, VisionStatus } from "@/lib/api/types";

export function useStudies(projectId: string, campaignId: string) {
  return useQuery({
    queryKey: ["studies", projectId, campaignId],
    queryFn: async () => {
      const page = await unwrap(
        api.GET("/api/v1/projects/{project_id}/studies", {
          params: { path: { project_id: projectId }, query: { campaign_id: campaignId, limit: 100 } },
        }),
      );
      return page.items.filter((s) => s.campaign_id === campaignId);
    },
  });
}

export function useArena(arenaId: string | null | undefined) {
  return useQuery({
    queryKey: ["arena", arenaId],
    enabled: Boolean(arenaId),
    queryFn: () => unwrap(api.GET("/api/v1/arenas/{arena_id}", { params: { path: { arena_id: arenaId! } } })),
  });
}

export function useStartArena(projectId: string, campaignId: string) {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: (body: ArenaCreate) =>
      unwrap(api.POST("/api/v1/campaigns/{campaign_id}/arenas", { params: { path: { campaign_id: campaignId } }, body })),
    onSuccess: () => queryClient.invalidateQueries({ queryKey: ["runs", projectId] }),
  });
}

/** Records the user's preferred variant. Selection is not approval. */
export function usePreferVariant(arenaId: string) {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: (variantId: string | null) =>
      unwrap(
        api.PATCH("/api/v1/arenas/{arena_id}", {
          params: { path: { arena_id: arenaId } },
          body: { preferred_variant_id: variantId },
        }),
      ),
    onSuccess: (arena) => queryClient.setQueryData(["arena", arena.id], arena),
  });
}
