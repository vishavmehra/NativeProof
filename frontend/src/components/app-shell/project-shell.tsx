"use client";

import { ChevronDown } from "lucide-react";
import { useParams, useSelectedLayoutSegment } from "next/navigation";
import type { ReactNode } from "react";

import { AppShell, type Crumb } from "@/components/app-shell/app-shell";
import { ModeBadge } from "@/components/evidence/badges";
import { ErrorState, LoadingState } from "@/components/states";
import { featureBySegment } from "@/features/project/features";
import { ProjectProvider, useCampaignsQuery, useProject, useProjectQuery } from "@/features/project/project-context";
import type { Project } from "@/lib/api/types";

function CampaignSwitcher() {
  const { campaigns, campaign, setCampaignId } = useProject();
  if (!campaign) return <p className="px-1 text-xs text-ink-secondary">No campaign yet</p>;
  return (
    <label className="block">
      <span className="sr-only">Campaign</span>
      <span className="relative block">
        <select
          value={campaign.id}
          onChange={(e) => setCampaignId(e.target.value)}
          className="h-8 w-full appearance-none truncate rounded-lg border border-border bg-surface-muted pr-7 pl-2 text-xs text-ink"
        >
          {campaigns.map((c) => (
            <option key={c.id} value={c.id}>
              {c.name}
            </option>
          ))}
        </select>
        <ChevronDown aria-hidden className="pointer-events-none absolute top-1/2 right-2 size-3.5 -translate-y-1/2 text-ink-secondary" />
      </span>
    </label>
  );
}

const summary = (p: Project) => ({
  id: p.id,
  name: p.name,
  mode: p.mode,
  status: p.status,
  description: p.description,
  brand_name: p.brand.name,
  target_markets: p.target_markets,
  created_at: p.created_at,
  updated_at: p.updated_at,
  last_activity_at: null,
});

/** Project workspace: loads the project and campaigns, then renders the reference app shell around the page. */
export function ProjectShell({ children }: { children: ReactNode }) {
  const { projectId } = useParams<{ projectId: string }>();
  const segment = useSelectedLayoutSegment();
  const project = useProjectQuery(projectId);
  const campaigns = useCampaignsQuery(projectId);
  const error = project.error ?? campaigns.error;
  const feature = featureBySegment(segment);

  const crumbs: Crumb[] = [{ label: "Projects", href: "/projects" }];
  if (project.data) crumbs.push({ label: project.data.name, href: `/projects/${projectId}` });
  if (segment) crumbs.push({ label: feature.label });

  if (error || !project.data || !campaigns.data) {
    return (
      <AppShell current={null} crumbs={crumbs}>
        {error ? (
          <ErrorState
            error={error}
            onRetry={() => {
              void project.refetch();
              void campaigns.refetch();
            }}
          />
        ) : (
          <LoadingState label="Loading project…" />
        )}
      </AppShell>
    );
  }
  return (
    <ProjectProvider project={project.data} campaigns={campaigns.data}>
      <AppShell current={summary(project.data)} crumbs={crumbs} badge={<ModeBadge mode={project.data.mode} />} campaignSlot={<CampaignSwitcher />}>
        {children}
      </AppShell>
    </ProjectProvider>
  );
}

/** Static fallback while route params resolve (Cache Components prerender). */
export function ProjectShellFallback() {
  return (
    <div className="min-h-dvh bg-canvas lg:pl-[256px]">
      <div className="h-16 lg:h-[72px]" />
      <div className="px-4 sm:px-6 lg:px-10">
        <LoadingState label="Loading project…" />
      </div>
    </div>
  );
}
