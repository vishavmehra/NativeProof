"use client";

import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";

import { projectKeys } from "@/features/project/project-context";
import { api } from "@/lib/api/client";
import { unwrap } from "@/lib/api/errors";
import type { CulturalProfileCreate, CulturalProfileUpdate } from "@/lib/api/types";

export const dnaKeys = {
  list: (projectId: string) => ["cultural-profiles", projectId],
  detail: (profileId: string | null | undefined) => ["cultural-profile", profileId],
};

export function useProfiles(projectId: string) {
  return useQuery({
    queryKey: dnaKeys.list(projectId),
    queryFn: () =>
      unwrap(
        api.GET("/api/v1/projects/{project_id}/cultural-profiles", {
          params: { path: { project_id: projectId }, query: { limit: 100 } },
        }),
      ),
  });
}

export function useProfile(profileId: string | null | undefined) {
  return useQuery({
    queryKey: dnaKeys.detail(profileId),
    enabled: Boolean(profileId),
    queryFn: () =>
      unwrap(api.GET("/api/v1/cultural-profiles/{profile_id}", { params: { path: { profile_id: profileId! } } })),
  });
}

export function useGenerateProfile(projectId: string) {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: (body: CulturalProfileCreate) =>
      unwrap(
        api.POST("/api/v1/projects/{project_id}/cultural-profiles", { params: { path: { project_id: projectId } }, body }),
      ),
    onSuccess: () => void queryClient.invalidateQueries({ queryKey: projectKeys.runs(projectId) }),
  });
}

export function useUpdateProfile(projectId: string) {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: ({ profileId, body }: { profileId: string; body: CulturalProfileUpdate }) =>
      unwrap(api.PATCH("/api/v1/cultural-profiles/{profile_id}", { params: { path: { profile_id: profileId } }, body })),
    onSuccess: (profile) => {
      queryClient.setQueryData(dnaKeys.detail(profile.id), profile);
      // Not awaited: the caller closes its editor now; the history list refreshes in the background.
      void queryClient.invalidateQueries({ queryKey: dnaKeys.list(projectId) });
    },
  });
}
