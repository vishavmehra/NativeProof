"use client";

import { keepPreviousData, useMutation, useQuery, useQueryClient } from "@tanstack/react-query";

import { projectKeys } from "@/features/project/project-context";
import { api } from "@/lib/api/client";
import { unwrap } from "@/lib/api/errors";
import { useLatestRun } from "@/lib/api/runs";
import type { components } from "@/lib/api/schema";
import type { PopulationStudyCreate, ReactionCategory } from "@/lib/api/types";

export const PAGE = 20;
export type InterviewFilters = { group_id?: string; region?: string; reaction?: NonNullable<ReactionCategory> };
export type LandscapeFilters = { region?: string; interest?: string };

export function usePopulationStudies(studyId: string | null | undefined) {
  return useQuery({
    queryKey: ["population-studies", studyId],
    enabled: Boolean(studyId),
    queryFn: () =>
      unwrap(
        api.GET("/api/v1/studies/{study_id}/population-studies", {
          params: { path: { study_id: studyId! }, query: { limit: 20 } },
        }),
      ),
  });
}

export function useStartPopulationStudy(projectId: string) {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: ({ studyId, body }: { studyId: string; body: PopulationStudyCreate }) =>
      unwrap(api.POST("/api/v1/studies/{study_id}/population-studies", { params: { path: { study_id: studyId } }, body })),
    onSuccess: (_accepted, { studyId }) => {
      void queryClient.invalidateQueries({ queryKey: projectKeys.runs(projectId) });
      void queryClient.invalidateQueries({ queryKey: ["population-studies", studyId] });
    },
  });
}

/** The result answers 200 in any run status, so polling it while running gives honest interview counts. */
/** `runStatus` is part of the key so the run finishing triggers one fresh fetch after polling stops. */
export function usePopulationResult(id: string | null | undefined, live: boolean, runStatus?: string) {
  return useQuery({
    queryKey: ["population-study", id, runStatus],
    enabled: Boolean(id),
    refetchInterval: live ? 5000 : false,
    queryFn: () =>
      unwrap(
        api.GET("/api/v1/population-studies/{population_study_id}", { params: { path: { population_study_id: id! } } }),
      ),
  });
}

export function useInterviews(id: string | null | undefined, filters: InterviewFilters, offset: number) {
  return useQuery({
    queryKey: ["interviews", id, filters, offset],
    enabled: Boolean(id),
    placeholderData: keepPreviousData,
    queryFn: () =>
      unwrap(
        api.GET("/api/v1/population-studies/{population_study_id}/interviews", {
          params: { path: { population_study_id: id! }, query: { ...filters, limit: PAGE, offset } },
        }),
      ),
  });
}

export function usePopulation(id: string | null | undefined) {
  return useQuery({
    queryKey: ["population", id],
    enabled: Boolean(id),
    queryFn: () => unwrap(api.GET("/api/v1/populations/{population_id}", { params: { path: { population_id: id! } } })),
  });
}

export function useParticipants(populationId: string | null | undefined, groupId: string | null, offset: number) {
  return useQuery({
    queryKey: ["participants", populationId, groupId, offset],
    enabled: Boolean(populationId && groupId),
    placeholderData: keepPreviousData,
    queryFn: () =>
      unwrap(
        api.GET("/api/v1/populations/{population_id}/participants", {
          params: { path: { population_id: populationId! }, query: { group_id: groupId, limit: PAGE, offset } },
        }),
      ),
  });
}

export function useLandscape(populationId: string | null | undefined, filters: LandscapeFilters) {
  return useQuery({
    queryKey: ["landscape", populationId, filters],
    enabled: Boolean(populationId),
    placeholderData: keepPreviousData,
    queryFn: () =>
      unwrap(
        api.GET("/api/v1/populations/{population_id}/landscape", {
          params: { path: { population_id: populationId! }, query: { ...filters, limit: 150 } },
        }),
      ),
  });
}

/** Cancel stops at the next checkpoint and keeps saved work; resume continues a failed run from its checkpoint. */
export function useRunControl(projectId: string) {
  const queryClient = useQueryClient();
  const refresh = (runId: string) => {
    void queryClient.invalidateQueries({ queryKey: ["run", runId] });
    void queryClient.invalidateQueries({ queryKey: projectKeys.runs(projectId) });
  };
  const cancel = useMutation({
    mutationFn: (runId: string) => unwrap(api.POST("/api/v1/runs/{run_id}/cancel", { params: { path: { run_id: runId } } })),
    onSuccess: (run) => refresh(run.id),
  });
  const resume = useMutation({
    mutationFn: (runId: string) => unwrap(api.POST("/api/v1/runs/{run_id}/resume", { params: { path: { run_id: runId } } })),
    onSuccess: (accepted) => refresh(accepted.run_id),
  });
  return { cancel, resume };
}

/** The campaign's latest population (via its latest finished population study), for panels outside Audience. */
export function useCampaignPopulation(projectId: string, campaignId: string | null | undefined) {
  const latest = useLatestRun(campaignId ? projectId : null, { runType: "population_study", campaignId: campaignId ?? undefined });
  const run = latest.data?.run_type === "population_study" && ["completed", "partial"].includes(latest.data.status) ? latest.data : null;
  const result = usePopulationResult(run?.id, false, run?.status);
  return usePopulation(result.data?.population_id);
}

// v3.1: participant memory and follow-up questions (README §14.8). Every answer is synthetic.
type S = components["schemas"];
export type ParticipantDetail = S["ParticipantDetail"];
export type FollowUpAnswer = S["FollowUpAnswer"];
export type GroupQuestionResult = S["GroupQuestionResult"];

export function useParticipantDetail(studyId: string, participantId: string | null) {
  return useQuery({
    queryKey: ["participant", studyId, participantId],
    enabled: Boolean(participantId),
    queryFn: () =>
      unwrap(
        api.GET("/api/v1/population-studies/{population_study_id}/participants/{participant_id}", {
          params: { path: { population_study_id: studyId, participant_id: participantId! } },
        }),
      ),
  });
}

export function useFollowUps(studyId: string, participantId: string) {
  return useQuery({
    queryKey: ["follow-ups", studyId, participantId],
    queryFn: () =>
      unwrap(
        api.GET("/api/v1/population-studies/{population_study_id}/participants/{participant_id}/questions", {
          params: { path: { population_study_id: studyId, participant_id: participantId }, query: { limit: 20 } },
        }),
      ),
  });
}

export function useAskParticipant(studyId: string, participantId: string) {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: (question: string) =>
      unwrap(
        api.POST("/api/v1/population-studies/{population_study_id}/participants/{participant_id}/questions", {
          params: { path: { population_study_id: studyId, participant_id: participantId } },
          body: { question },
        }),
      ),
    onSuccess: () => {
      void queryClient.invalidateQueries({ queryKey: ["follow-ups", studyId, participantId] });
      void queryClient.invalidateQueries({ queryKey: ["participant", studyId, participantId] });
    },
  });
}

export function useGroupQuestions(studyId: string, groupId: string) {
  return useQuery({
    queryKey: ["group-questions", studyId, groupId],
    queryFn: () =>
      unwrap(
        api.GET("/api/v1/population-studies/{population_study_id}/groups/{group_id}/questions", {
          params: { path: { population_study_id: studyId, group_id: groupId }, query: { limit: 10 } },
        }),
      ),
  });
}

export function useAskGroup(studyId: string, groupId: string) {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: (body: { question: string; sample_size: number }) =>
      unwrap(
        api.POST("/api/v1/population-studies/{population_study_id}/groups/{group_id}/questions", {
          params: { path: { population_study_id: studyId, group_id: groupId } },
          body,
        }),
      ),
    onSuccess: () => void queryClient.invalidateQueries({ queryKey: ["group-questions", studyId, groupId] }),
  });
}

/** Populations in this project, for reuse: the same participants make content versions comparable (Loop). */
export function usePopulations(projectId: string) {
  return useQuery({
    queryKey: ["populations", projectId],
    queryFn: () =>
      unwrap(api.GET("/api/v1/projects/{project_id}/populations", { params: { path: { project_id: projectId }, query: { limit: 50 } } })),
  });
}
