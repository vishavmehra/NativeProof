"use client";

import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";

import { api } from "@/lib/api/client";
import { unwrap } from "@/lib/api/errors";
import type { ReportCreate, Run, RunType } from "@/lib/api/types";

export function useReports(projectId: string, campaignId: string | undefined) {
  return useQuery({
    queryKey: ["reports", projectId, campaignId],
    queryFn: () =>
      unwrap(
        api.GET("/api/v1/projects/{project_id}/reports", {
          params: { path: { project_id: projectId }, query: { campaign_id: campaignId, limit: 50 } },
        }),
      ),
  });
}

export function useReport(reportId: string) {
  return useQuery({
    queryKey: ["report", reportId],
    queryFn: () => unwrap(api.GET("/api/v1/reports/{report_id}", { params: { path: { report_id: reportId } } })),
  });
}

/** Report creation is synchronous (D-014): the response is the full report. */
export function useCreateReport(projectId: string) {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: (body: ReportCreate) =>
      unwrap(api.POST("/api/v1/projects/{project_id}/reports", { params: { path: { project_id: projectId } }, body })),
    onSuccess: (report) => {
      queryClient.setQueryData(["report", report.id], report);
      return queryClient.invalidateQueries({ queryKey: ["reports", projectId] });
    },
  });
}

export type ExportFormat = "markdown" | "json";

/** Fetch the backend export (which keeps the disclosures and labels) and save it as a file. */
export async function downloadReport(report: { id: string; title: string }, format: ExportFormat) {
  const text = await unwrap(
    api.GET("/api/v1/reports/{report_id}/export", {
      params: { path: { report_id: report.id }, query: { format } },
      parseAs: "text",
    }),
  );
  const blob = new Blob([text], { type: format === "json" ? "application/json" : "text/markdown" });
  const url = URL.createObjectURL(blob);
  const link = document.createElement("a");
  const slug = report.title.toLowerCase().replace(/[^a-z0-9]+/g, "-").replace(/^-|-$/g, "") || "report";
  link.href = url;
  link.download = `${slug}.${format === "json" ? "json" : "md"}`;
  document.body.append(link);
  link.click();
  link.remove();
  setTimeout(() => URL.revokeObjectURL(url), 1000);
}

type RunFilter = { runType?: RunType; campaignId?: string };

/** Newest-first runs of a project. Filters are applied server-side and re-checked here. */
export function useRunList(projectId: string, filter: RunFilter = {}) {
  return useQuery({
    queryKey: ["runs", projectId, "list", filter],
    queryFn: async () => {
      const page = await unwrap(
        api.GET("/api/v1/projects/{project_id}/runs", {
          params: {
            path: { project_id: projectId },
            query: { limit: 50, run_type: filter.runType, campaign_id: filter.campaignId },
          },
        }),
      );
      return page.items.filter(
        (run) =>
          (!filter.runType || run.run_type === filter.runType) &&
          (!filter.campaignId || run.campaign_id === filter.campaignId),
      );
    },
  });
}

/** A run whose result can be read: completed, or partial with a result reference. */
export const hasResult = (run: Run) => (run.status === "completed" || run.status === "partial") && Boolean(run.result);
