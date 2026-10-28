"use client";

import { useQuery } from "@tanstack/react-query";

import { api } from "@/lib/api/client";
import { unwrap } from "@/lib/api/errors";
import type { DiscoveryResult, ProjectSummary, Run } from "@/lib/api/types";

export type ActivityItem = { project: ProjectSummary; run: Run };
export type DiscoveryItem = { project: ProjectSummary; run: Run; result: DiscoveryResult };

const when = (run: Run) => Date.parse(run.completed_at ?? run.started_at ?? run.created_at);

// fans out per project (runs) and per discovery (results), capped at 6 projects and 10 discoveries.
// A cross-project summary endpoint would replace this if dashboards need more history.
export function useResearchOverview(projects: ProjectSummary[]) {
  const ids = projects.map((p) => p.id);
  return useQuery({
    queryKey: ["home-research", ids],
    enabled: projects.length > 0,
    staleTime: 2 * 60_000,
    queryFn: async () => {
      let failed = 0;
      const perProject = await Promise.all(
        projects.map(async (project) => {
          try {
            const page = await unwrap(api.GET("/api/v1/projects/{project_id}/runs", { params: { path: { project_id: project.id }, query: { limit: 20 } } }));
            return page.items.map((run) => ({ project, run }));
          } catch {
            failed += 1;
            return [];
          }
        }),
      );
      const all = perProject.flat().sort((a, b) => when(b.run) - when(a.run));
      const discoveryRuns = all
        .filter(({ run }) => run.run_type === "market_discovery" && (run.status === "completed" || run.status === "partial"))
        .slice(0, 10);
      const discoveries = (
        await Promise.all(
          discoveryRuns.map(async ({ project, run }) => {
            try {
              const result = await unwrap(
                api.GET("/api/v1/projects/{project_id}/discoveries/{run_id}", { params: { path: { project_id: project.id, run_id: run.id } } }),
              );
              return { project, run, result };
            } catch {
              failed += 1;
              return null;
            }
          }),
        )
      ).filter((d): d is DiscoveryItem => d !== null);
      return { activity: all.slice(0, 8) as ActivityItem[], discoveries, failed };
    },
  });
}

/** Evidence records per market from completed discoveries, kept separate for live and demo projects. */
export function evidenceByMarket(discoveries: DiscoveryItem[], mode: "live" | "demo") {
  const totals = new Map<string, { value: number; discoveries: number }>();
  for (const d of discoveries) {
    if (d.project.mode !== mode) continue;
    const code = d.result.market.country_code.toUpperCase();
    const t = totals.get(code) ?? { value: 0, discoveries: 0 };
    t.value += d.result.evidence.length;
    t.discoveries += 1;
    totals.set(code, t);
  }
  return [...totals.entries()].map(([country_code, t]) => ({ country_code, ...t }));
}
