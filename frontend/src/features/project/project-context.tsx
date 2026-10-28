"use client";

import { useQuery } from "@tanstack/react-query";
import { usePathname, useRouter, useSearchParams } from "next/navigation";
import { createContext, useCallback, useContext, useMemo, type ReactNode } from "react";

import { api } from "@/lib/api/client";
import { unwrap } from "@/lib/api/errors";
import type { Campaign, Project } from "@/lib/api/types";

/** Query keys shared across features. Invalidate these after mutations. */
export const projectKeys = {
  list: ["projects"] as const,
  detail: (projectId: string) => ["project", projectId] as const,
  campaigns: (projectId: string) => ["campaigns", projectId] as const,
  /** Prefix for every runs-list query of a project (useLatestRun included). */
  runs: (projectId: string) => ["runs", projectId] as const,
  reports: (projectId: string) => ["reports", projectId] as const,
};

export function useProjectQuery(projectId: string) {
  return useQuery({
    queryKey: projectKeys.detail(projectId),
    queryFn: () => unwrap(api.GET("/api/v1/projects/{project_id}", { params: { path: { project_id: projectId } } })),
  });
}

export function useCampaignsQuery(projectId: string) {
  return useQuery({
    queryKey: projectKeys.campaigns(projectId),
    queryFn: async () => {
      const page = await unwrap(
        api.GET("/api/v1/projects/{project_id}/campaigns", { params: { path: { project_id: projectId }, query: { limit: 100 } } }),
      );
      // Newest first, independent of server ordering.
      return [...page.items].sort((a, b) => Date.parse(b.created_at) - Date.parse(a.created_at));
    },
  });
}

type ProjectContextValue = {
  project: Project;
  campaigns: Campaign[];
  /** Active campaign: the `?campaign=` search param when it matches, otherwise the newest campaign. */
  campaign: Campaign | null;
  setCampaignId(id: string): void;
};

const ProjectContext = createContext<ProjectContextValue | null>(null);

/** The loaded project and active campaign. Only available inside the project layout, which handles loading and errors. */
export function useProject(): ProjectContextValue {
  const ctx = useContext(ProjectContext);
  if (!ctx) throw new Error("useProject must be used inside /projects/[projectId] (ProjectProvider).");
  return ctx;
}

export function ProjectProvider({ project, campaigns, children }: { project: Project; campaigns: Campaign[]; children: ReactNode }) {
  const router = useRouter();
  const pathname = usePathname();
  const searchParams = useSearchParams();
  const requested = searchParams.get("campaign");

  const setCampaignId = useCallback(
    (id: string) => {
      const next = new URLSearchParams(searchParams.toString());
      next.set("campaign", id);
      router.replace(`${pathname}?${next.toString()}`, { scroll: false });
    },
    [router, pathname, searchParams],
  );

  const value = useMemo<ProjectContextValue>(
    () => ({
      project,
      campaigns,
      campaign: campaigns.find((c) => c.id === requested) ?? campaigns[0] ?? null,
      setCampaignId,
    }),
    [project, campaigns, requested, setCampaignId],
  );

  return <ProjectContext.Provider value={value}>{children}</ProjectContext.Provider>;
}
