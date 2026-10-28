"use client";

import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";

import { api } from "@/lib/api/client";
import { unwrap } from "@/lib/api/errors";
import type { RiskFindingUpdate, RiskScanCreate } from "@/lib/api/types";

export type { RiskFinding, RiskScan, RiskScanCreate } from "@/lib/api/types";

export function useRiskScan(scanId: string | null | undefined) {
  return useQuery({
    queryKey: ["risk-scan", scanId],
    enabled: Boolean(scanId),
    queryFn: () => unwrap(api.GET("/api/v1/risk-scans/{scan_id}", { params: { path: { scan_id: scanId! } } })),
  });
}

export function useStartRiskScan(projectId: string, campaignId: string) {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: (body: RiskScanCreate) =>
      unwrap(api.POST("/api/v1/campaigns/{campaign_id}/risk-scans", { params: { path: { campaign_id: campaignId } }, body })),
    onSuccess: () => queryClient.invalidateQueries({ queryKey: ["runs", projectId] }),
  });
}

/** Dismiss, resolve, or reopen a finding, with an optional note. */
export function useUpdateFinding(scanId: string) {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: ({ findingId, body }: { findingId: string; body: RiskFindingUpdate }) =>
      unwrap(
        api.PATCH("/api/v1/risk-scans/{scan_id}/findings/{finding_id}", {
          params: { path: { scan_id: scanId, finding_id: findingId } },
          body,
        }),
      ),
    onSuccess: () => queryClient.invalidateQueries({ queryKey: ["risk-scan", scanId] }),
  });
}

/** Applies the suggested alternative as a new user-edit adaptation. The campaign is never edited in place. */
export function useApplyAlternative(scanId: string) {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: (findingId: string) =>
      unwrap(
        api.POST("/api/v1/risk-scans/{scan_id}/findings/{finding_id}/apply", {
          params: { path: { scan_id: scanId, finding_id: findingId } },
        }),
      ),
    onSuccess: (adaptation) =>
      Promise.all([
        queryClient.invalidateQueries({ queryKey: ["risk-scan", scanId] }),
        queryClient.invalidateQueries({ queryKey: ["adaptations", adaptation.campaign_id] }),
      ]),
  });
}
