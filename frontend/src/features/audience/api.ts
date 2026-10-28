"use client";

import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";

import { projectKeys } from "@/features/project/project-context";
import { api } from "@/lib/api/client";
import { unwrap } from "@/lib/api/errors";
import type { RehearsalCreate, StudyCreate } from "@/lib/api/types";

export function useStudies(projectId: string, campaignId: string | null | undefined) {
  return useQuery({
    queryKey: ["studies", projectId, campaignId],
    enabled: Boolean(campaignId),
    queryFn: () =>
      unwrap(
        api.GET("/api/v1/projects/{project_id}/studies", {
          params: { path: { project_id: projectId }, query: { campaign_id: campaignId, limit: 100 } },
        }),
      ),
  });
}

export function useCreateStudy(projectId: string) {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: (body: StudyCreate) =>
      unwrap(api.POST("/api/v1/projects/{project_id}/studies", { params: { path: { project_id: projectId } }, body })),
    onSuccess: () => void queryClient.invalidateQueries({ queryKey: ["studies", projectId] }),
  });
}

export function useStartRehearsal(projectId: string) {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: ({ studyId, body }: { studyId: string; body: RehearsalCreate }) =>
      unwrap(api.POST("/api/v1/studies/{study_id}/rehearsals", { params: { path: { study_id: studyId } }, body })),
    onSuccess: () => void queryClient.invalidateQueries({ queryKey: projectKeys.runs(projectId) }),
  });
}

export function useRehearsalResult(studyId: string | null | undefined, runId: string | null | undefined) {
  return useQuery({
    queryKey: ["rehearsal", studyId, runId],
    enabled: Boolean(studyId && runId),
    queryFn: () =>
      unwrap(
        api.GET("/api/v1/studies/{study_id}/rehearsals/{run_id}", {
          params: { path: { study_id: studyId!, run_id: runId! } },
        }),
      ),
  });
}
