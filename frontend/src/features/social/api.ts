"use client";

import { keepPreviousData, useMutation, useQuery, useQueryClient } from "@tanstack/react-query";

import { api } from "@/lib/api/client";
import { unwrap } from "@/lib/api/errors";
import type { SocialSimulationCreate } from "@/lib/api/types";

const LIMIT = 200;

/** Graph C. `element` and `groupId` narrow the map; the backend bounds it with `limit` (truncated=true when cut). */
export function useReactionMap(populationStudyId: string, filter: { element?: string; groupId?: string }) {
  return useQuery({
    queryKey: ["reaction-map", populationStudyId, filter],
    placeholderData: keepPreviousData,
    queryFn: () =>
      unwrap(
        api.GET("/api/v1/population-studies/{population_study_id}/reaction-map", {
          params: {
            path: { population_study_id: populationStudyId },
            query: { element: filter.element || undefined, group_id: filter.groupId || undefined, limit: LIMIT },
          },
        }),
      ),
  });
}

export function useInterviews(populationStudyId: string, filter: { groupId?: string }, enabled = true) {
  return useQuery({
    queryKey: ["interviews", populationStudyId, filter],
    enabled,
    queryFn: () =>
      unwrap(
        api.GET("/api/v1/population-studies/{population_study_id}/interviews", {
          params: { path: { population_study_id: populationStudyId }, query: { group_id: filter.groupId || undefined, limit: 20 } },
        }),
      ),
  });
}

export function usePopulations(projectId: string) {
  return useQuery({
    queryKey: ["populations", projectId],
    queryFn: () =>
      unwrap(api.GET("/api/v1/projects/{project_id}/populations", { params: { path: { project_id: projectId }, query: { limit: 100 } } })),
  });
}

/** Population studies run on one audience study (each is one campaign version shown to the same population). */
export function usePopulationStudies(studyId: string | undefined) {
  return useQuery({
    queryKey: ["population-studies", studyId],
    enabled: Boolean(studyId),
    queryFn: () =>
      unwrap(
        api.GET("/api/v1/studies/{study_id}/population-studies", { params: { path: { study_id: studyId! }, query: { limit: 100 } } }),
      ),
  });
}

/** Graph D. Needs one population and 2–4 of its population studies. */
export function useCampaignComparison(campaignId: string, populationId: string | undefined, studyIds: string[]) {
  return useQuery({
    queryKey: ["population-comparison", campaignId, populationId, studyIds],
    enabled: Boolean(populationId) && studyIds.length >= 2 && studyIds.length <= 4,
    queryFn: () =>
      unwrap(
        api.GET("/api/v1/campaigns/{campaign_id}/population-comparison", {
          params: { path: { campaign_id: campaignId }, query: { population_id: populationId!, population_study_ids: studyIds } },
        }),
      ),
  });
}

export function useSocialSimulations(populationStudyId: string) {
  return useQuery({
    queryKey: ["social-simulations", populationStudyId],
    queryFn: () =>
      unwrap(
        api.GET("/api/v1/population-studies/{population_study_id}/social-simulations", {
          params: { path: { population_study_id: populationStudyId }, query: { limit: 20 } },
        }),
      ),
  });
}

export function useSocialSimulation(simulationId: string | null) {
  return useQuery({
    queryKey: ["social-simulation", simulationId],
    enabled: Boolean(simulationId),
    queryFn: () =>
      unwrap(api.GET("/api/v1/social-simulations/{simulation_id}", { params: { path: { simulation_id: simulationId! } } })),
  });
}

export function useSocialPosts(simulationId: string, filter: { roundIndex?: number; groupId?: string; offset: number }) {
  return useQuery({
    queryKey: ["social-posts", simulationId, filter],
    placeholderData: keepPreviousData,
    queryFn: () =>
      unwrap(
        api.GET("/api/v1/social-simulations/{simulation_id}/posts", {
          params: {
            path: { simulation_id: simulationId },
            query: { round_index: filter.roundIndex, group_id: filter.groupId || undefined, limit: 20, offset: filter.offset },
          },
        }),
      ),
  });
}

export function useDiffusion(simulationId: string, roundIndex: number | undefined) {
  return useQuery({
    queryKey: ["diffusion", simulationId, roundIndex],
    placeholderData: keepPreviousData,
    queryFn: () =>
      unwrap(
        api.GET("/api/v1/social-simulations/{simulation_id}/diffusion", {
          params: { path: { simulation_id: simulationId }, query: { round_index: roundIndex, limit: LIMIT } },
        }),
      ),
  });
}

export function useStartSocialSimulation(projectId: string) {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: (body: SocialSimulationCreate) => unwrap(api.POST("/api/v1/social-simulations", { body })),
    onSuccess: () => queryClient.invalidateQueries({ queryKey: ["runs", projectId] }),
  });
}

/** Cancel stops at the next checkpoint and keeps saved work; resume continues an interrupted or failed run. */
export function useRunControl(projectId: string, runId: string | null) {
  const queryClient = useQueryClient();
  const refresh = () =>
    Promise.all([
      queryClient.invalidateQueries({ queryKey: ["run", runId] }),
      queryClient.invalidateQueries({ queryKey: ["runs", projectId] }),
    ]);
  const cancel = useMutation({
    mutationFn: () => unwrap(api.POST("/api/v1/runs/{run_id}/cancel", { params: { path: { run_id: runId! } } })),
    onSuccess: refresh,
  });
  const resume = useMutation({
    mutationFn: () => unwrap(api.POST("/api/v1/runs/{run_id}/resume", { params: { path: { run_id: runId! } } })),
    onSuccess: refresh,
  });
  return { cancel, resume };
}
