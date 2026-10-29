"use client";

import { useMutation, useQueryClient } from "@tanstack/react-query";
import Link from "next/link";
import { useRouter } from "next/navigation";

import { ModeBadge } from "@/components/evidence/badges";
import { marketNames } from "@/components/forms/fields";
import { projectKeys } from "@/features/project/project-context";
import { api } from "@/lib/api/client";
import { unwrap } from "@/lib/api/errors";
import type { ProjectSummary } from "@/lib/api/types";
import { formatDateTime, formatRelative } from "@/lib/format";

/** Creates a seeded demo project and opens it. Shared by the home dashboard and the login page. */
export function useCreateDemoProject() {
  const router = useRouter();
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: () => unwrap(api.POST("/api/v1/projects/demo")),
    onSuccess: (project) => {
      void queryClient.invalidateQueries({ queryKey: projectKeys.list });
      router.push(`/projects/${project.id}`);
    },
  });
}

/** Project rows: name, mode, brand, markets, and last activity. */
export function ProjectTable({ projects }: { projects: ProjectSummary[] }) {
  return (
    <div className="overflow-hidden rounded-xl border border-border bg-surface shadow-card">
      <div className="hidden grid-cols-[minmax(0,1fr)_200px_160px] gap-4 border-b border-border bg-surface-muted px-4 py-2 text-[11px] font-semibold tracking-[0.06em] text-ink-secondary uppercase sm:grid">
        <span>Project</span>
        <span>Target markets</span>
        <span>Last activity</span>
      </div>
      <ul className="divide-y divide-border">
        {projects.map((p) => {
          const activity = p.last_activity_at ?? p.updated_at;
          return (
            <li key={p.id}>
              <Link
                href={`/projects/${p.id}`}
                className="grid gap-1 px-4 py-3 outline-none hover:bg-surface-muted focus-visible:bg-surface-muted sm:grid-cols-[minmax(0,1fr)_200px_160px] sm:items-center sm:gap-4"
              >
                <span className="min-w-0">
                  <span className="flex flex-wrap items-center gap-2">
                    <span className="font-medium text-ink">{p.name}</span>
                    <ModeBadge mode={p.mode} />
                    {p.status === "archived" && <span className="text-xs text-ink-secondary">Archived</span>}
                  </span>
                  <span className="block truncate text-[13px] text-ink-secondary">
                    {p.brand_name}
                    {p.description && ` · ${p.description}`}
                  </span>
                </span>
                <span className="text-[13px] text-ink-body">{marketNames(p.target_markets, "No markets yet")}</span>
                <span className="text-[13px] text-ink-secondary" title={formatDateTime(activity)}>
                  {p.last_activity_at ? `Active ${formatRelative(activity)}` : `Updated ${formatRelative(activity)}`}
                </span>
              </Link>
            </li>
          );
        })}
      </ul>
    </div>
  );
}
