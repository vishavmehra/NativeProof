"use client";

import { useQueryClient } from "@tanstack/react-query";
import { useEffect, useState } from "react";

import { EmptyState, ErrorState, LoadingState } from "@/components/states";
import { RunStatusPanel } from "@/components/workflow/run-status";
import { Button } from "@/components/ui/button";
import { hasResult, useRunFlow } from "@/features/atlas/api";
import { PageHeader } from "@/features/atlas/page-header";
import { useProject } from "@/features/project/project-context";
import { formatDate, humanize } from "@/lib/format";
import { cn } from "@/lib/utils";

import type { CulturalProfile, CulturalProfileCreate, CulturalProfileSummary } from "@/lib/api/types";

import { dnaKeys, useGenerateProfile, useProfile, useProfiles } from "./api";
import { ProfileForm } from "./profile-form";
import { ProfileView } from "./profile-view";

/** Versions grouped by lineage, newest version first; lineages in list order. */
function byLineage(summaries: CulturalProfileSummary[]) {
  const groups = new Map<string, CulturalProfileSummary[]>();
  for (const s of summaries) groups.set(s.lineage_id, [...(groups.get(s.lineage_id) ?? []), s]);
  return [...groups.values()].map((versions) => versions.sort((a, b) => b.version - a.version));
}

export function DnaWorkspace() {
  const { project, campaign, campaigns } = useProject();
  const queryClient = useQueryClient();
  const profilesQuery = useProfiles(project.id);
  const flow = useRunFlow(project.id, "cultural_profile");
  const generate = useGenerateProfile(project.id);
  const [selectedId, setSelectedId] = useState<string | null>(null);
  const [form, setForm] = useState<{ basedOn: CulturalProfile | null } | null>(null);
  const [lastBody, setLastBody] = useState<CulturalProfileCreate | null>(null);

  const finishedId = hasResult(flow.run) ? flow.run?.result?.ids[0] : undefined;
  useEffect(() => {
    // A finished run adds a profile (or a version) to the history.
    if (finishedId) queryClient.invalidateQueries({ queryKey: dnaKeys.list(project.id) });
  }, [finishedId, project.id, queryClient]);

  const summaries = profilesQuery.data?.items ?? [];
  const profileId = selectedId ?? finishedId ?? summaries[0]?.id ?? null;
  const profileQuery = useProfile(profileId);

  function submit(body: CulturalProfileCreate) {
    setLastBody(body);
    generate.mutate(body, {
      onSuccess: (accepted) => {
        flow.setStartedRunId(accepted.run_id);
        setSelectedId(null);
        setForm(null);
      },
    });
  }

  const header = (
    <PageHeader
      feature="dna"
      description="A versioned profile of how a brand, product, or campaign sits in each market's culture. Every item rests on discovery evidence or is labeled a hypothesis."
    />
  );
  // Errors first: a failed list must never hide behind a loading state. The resume lookup does not block the page.
  if (profilesQuery.isError) return (
      <div className="grid gap-8">
        {header}
        <ErrorState error={profilesQuery.error} onRetry={() => profilesQuery.refetch()} />
      </div>
    );
  if (profilesQuery.isPending)
    return (
      <div className="grid gap-8">
        {header}
        <LoadingState label="Loading cultural profiles…" />
      </div>
    );

  const showForm = form !== null || (summaries.length === 0 && !flow.runId);
  const lineages = byLineage(summaries);

  return (
    <div className="grid gap-8">
    {header}
    <div className="grid gap-8 lg:grid-cols-[15rem_minmax(0,1fr)] lg:items-start">
      <aside aria-labelledby="dna-history" className="grid gap-4 rounded-2xl border bg-card p-4 shadow-card lg:sticky lg:top-4">
        <div className="flex items-center justify-between gap-2">
          <h2 id="dna-history" className="font-serif text-lg">
            Profiles
          </h2>
          <Button variant="outline" size="sm" onClick={() => setForm({ basedOn: null })}>
            New profile
          </Button>
        </div>
        {lineages.length === 0 ? (
          <p className="text-sm text-ink-secondary">No profiles yet.</p>
        ) : (
          <ul className="grid gap-4">
            {lineages.map((versions) => (
              <li key={versions[0].lineage_id} className="grid gap-1">
                <p className="text-sm font-medium">{versions[0].title}</p>
                <ol aria-label={`Versions of ${versions[0].title}`} className="grid gap-0.5 border-l pl-2">
                  {versions.map((v) => (
                    <li key={v.id}>
                      <button
                        type="button"
                        aria-current={v.id === profileId || undefined}
                        onClick={() => {
                          setSelectedId(v.id);
                          setForm(null);
                        }}
                        className={cn(
                          "w-full rounded-sm px-2 py-1 text-left text-xs tabular-nums outline-none hover:bg-surface-muted focus-visible:ring-3 focus-visible:ring-ring/50",
                          v.id === profileId && "bg-surface-muted font-medium",
                        )}
                      >
                        Version {v.version} · {formatDate(v.created_at)}
                        {v.status !== "completed" && <span className="text-warning"> · {humanize(v.status)}</span>}
                      </button>
                    </li>
                  ))}
                </ol>
              </li>
            ))}
          </ul>
        )}
      </aside>

      <div className="grid min-w-0 gap-8">
        {flow.latestQuery.isError && <ErrorState error={flow.latestQuery.error} onRetry={() => flow.latestQuery.refetch()} />}
        {showForm && (
          <section aria-labelledby="dna-form" className="rounded-2xl border bg-card shadow-card">
            <h2 id="dna-form" className="border-b px-4 py-3 text-[15px] font-semibold">
              {form?.basedOn ? "Regenerate profile" : "Generate a cultural profile"}
            </h2>
            <div className="p-4 md:p-5">
              <ProfileForm
                key={form?.basedOn?.id ?? "new"}
                project={project}
                campaign={campaign}
                campaigns={campaigns}
                basedOn={form?.basedOn ?? null}
                pending={generate.isPending || flow.busy}
                error={generate.error}
                onSubmit={submit}
                onCancel={summaries.length > 0 || flow.runId ? () => setForm(null) : undefined}
              />
              {flow.busy && (
                <p className="mt-3 text-xs text-ink-secondary">A profile is being generated. You can start another when it finishes.</p>
              )}
            </div>
          </section>
        )}

        {flow.runQuery.isError && <ErrorState error={flow.runQuery.error} onRetry={() => flow.runQuery.refetch()} />}
        {flow.run && !hasResult(flow.run) && !selectedId && (
          <RunStatusPanel
            run={flow.run}
            operation="Cultural profile"
            onRetry={lastBody && flow.run.error?.retryable ? () => submit(lastBody) : undefined}
          />
        )}

        {profileQuery.isError && <ErrorState error={profileQuery.error} onRetry={() => profileQuery.refetch()} />}
        {profileId && profileQuery.isPending && <LoadingState label="Loading profile…" />}
        {profileQuery.data ? (
          <ProfileView
            key={profileQuery.data.id}
            profile={profileQuery.data}
            onRegenerate={() => setForm({ basedOn: profileQuery.data })}
          />
        ) : (
          !showForm &&
          !flow.run && (
            <EmptyState
              title="No profile selected"
              description="Generate a cultural profile from completed discoveries, or pick a version from the history."
            />
          )
        )}
      </div>
    </div>
    </div>
  );
}
