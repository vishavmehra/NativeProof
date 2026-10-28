"use client";

import { useQueryClient } from "@tanstack/react-query";
import { ArrowRight } from "lucide-react";
import Link from "next/link";
import { useEffect, useState, type ReactNode } from "react";

import { EmptyState, ErrorState, LoadingState } from "@/components/states";
import { RunStatusPanel } from "@/components/workflow/run-status";
import { Button, buttonVariants } from "@/components/ui/button";
import { hasResult } from "@/features/proof/api";
import { useProject } from "@/features/project/project-context";
import { isTerminal, useLatestRun, useRun } from "@/lib/api/runs";
import type { Adaptation, AdaptationCreate, Campaign, Project } from "@/lib/api/types";
import { formatDateTime } from "@/lib/format";

import { AdaptationForm, VOICE_FORM_ID } from "./adaptation-form";
import { useAdaptation, useAdaptations, useStartAdaptation, variantsOfRun } from "./api";
import { ComparisonEditor } from "./comparison-editor";
import { FeatureHeader } from "@/components/app-shell/feature-header";

/** `adaptationParam` opens one adaptation directly, e.g. an alternative applied from Risk Radar. */
type Params = { discoveryParam?: string; rehearsalParam?: string; runParam?: string; adaptationParam?: string };

export function VoiceWorkspace(params: Params) {
  const { project, campaign } = useProject();
  return (
    <div className="grid gap-6 [&>header]:mb-0">
      {campaign ? (
        // Remount per campaign so a run started for one campaign never shows under another.
        <Workspace key={campaign.id} project={project} campaign={campaign} {...params} />
      ) : (
        <>
          <VoiceHeader />
          <EmptyState
            title="No campaign yet"
            description="Voice adapts a campaign's content. Create a campaign from the project overview first."
            action={
              <Link className={buttonVariants({ variant: "outline" })} href={`/projects/${project.id}`}>
                Go to overview
              </Link>
            }
          />
        </>
      )}
    </div>
  );
}

function VoiceHeader({ action }: { action?: ReactNode }) {
  return (
    <FeatureHeader
      feature="voice"
      description="Every change shows what it replaces, why, and whether evidence or model reasoning supports it."
      howItWorks={
        <ol className="grid list-decimal gap-1.5 pl-4">
          <li>Pick a market and a source version. Discovery evidence grounds changes in Qloo signals; rehearsal findings point at what to fix. Both are optional.</li>
          <li>A model drafts up to three variants and records, for every change, what it replaces and why.</li>
          <li>Protected terms and constraints are checked deterministically after generation.</li>
          <li>Select versions to evaluate in Loop. Nothing is scored here, and selecting is not approval.</li>
        </ol>
      }
      primaryAction={action}
    />
  );
}

function Workspace({ project, campaign, discoveryParam, rehearsalParam, runParam, adaptationParam }: Params & { project: Project; campaign: Campaign }) {
  const queryClient = useQueryClient();
  const latestQuery = useLatestRun(project.id, { runType: "campaign_adaptation", campaignId: campaign.id });
  // Guard: only resume a run of this type, whatever the list endpoint returns.
  const latest = latestQuery.data?.run_type === "campaign_adaptation" ? latestQuery.data : null;
  const [startedRunId, setStartedRunId] = useState<string | null>(null);
  const [lastBody, setLastBody] = useState<AdaptationCreate | null>(null);
  const [formOpen, setFormOpen] = useState(false);
  // Revisions saved in this session, kept until the list refetch includes them.
  const [revisions, setRevisions] = useState<Adaptation[]>([]);

  const runId = startedRunId ?? runParam ?? latest?.id ?? null;
  const runQuery = useRun(runId);
  const run = runQuery.data;
  const done = Boolean(run && hasResult(run));
  const adaptationsQuery = useAdaptations(campaign.id);
  const linkedQuery = useAdaptation(adaptationParam);
  const start = useStartAdaptation(project.id, campaign.id);
  const busy = Boolean(run && !isTerminal(run.status));

  // A run started here finished: refetch so its new variants are listed.
  useEffect(() => {
    if (done && startedRunId) queryClient.invalidateQueries({ queryKey: ["adaptations", campaign.id] });
  }, [done, startedRunId, campaign.id, queryClient]);

  function submit(body: AdaptationCreate) {
    setLastBody(body);
    start.mutate(body, {
      onSuccess: (accepted) => {
        setStartedRunId(accepted.run_id);
        setFormOpen(false);
      },
    });
  }

  function openForm() {
    setFormOpen(true);
    requestAnimationFrame(() => document.getElementById("voice-content")?.scrollIntoView({ block: "start" }));
  }

  if (latestQuery.isPending)
    return (
      <>
        <VoiceHeader />
        <LoadingState label="Loading the latest adaptation run…" />
      </>
    );

  const listed = adaptationsQuery.data ?? [];
  const known = new Set(listed.map((a) => a.id));
  const all = [...listed, ...revisions.filter((r) => !known.has(r.id))];
  const runVariants = done && run?.result ? variantsOfRun(all, run.result.ids) : [];
  const linked = linkedQuery.data?.campaign_id === campaign.id ? linkedQuery.data : undefined;
  const variants = linked && !runVariants.some((v) => v.id === linked.id) ? [...runVariants, linked] : runVariants;
  const showForm = !runId || formOpen;
  const first = variants[0];

  const source = campaign.versions.find((v) => v.id === (first?.source_content_version_id ?? campaign.current_version.id)) ?? campaign.current_version;
  const contentColumn = (
    <div id="voice-content" className="grid scroll-mt-24 gap-4">
      <div className="grid gap-1 rounded-lg border border-border bg-surface-muted/50 p-3 text-sm text-ink">
        <span className="text-[11px] font-medium tracking-wide text-ink-secondary uppercase">Version {source.version_number}</span>
        {source.content.headline && <p className="font-medium">{source.content.headline}</p>}
        {source.content.body && <p className="text-ink-secondary">{source.content.body}</p>}
        {source.content.call_to_action && <p className="text-xs text-ink-secondary">CTA: {source.content.call_to_action}</p>}
      </div>
      {!showForm && (
        <Button variant="outline" onClick={openForm} disabled={busy}>
          New adaptations
        </Button>
      )}
      {showForm ? (
          <AdaptationForm
            project={project}
            campaign={campaign}
            discoveryParam={discoveryParam}
            rehearsalParam={rehearsalParam}
            busy={busy}
            pending={start.isPending}
            error={start.error}
            onSubmit={submit}
            onCancel={runId ? () => setFormOpen(false) : undefined}
          />
      ) : first ? (
        <dl className="grid grid-cols-[auto_minmax(0,1fr)] gap-x-4 gap-y-1.5 text-sm">
          <dt className="text-ink-secondary">Market</dt>
          <dd>{first.market.display_name}</dd>
          <dt className="text-ink-secondary">Evidence</dt>
          <dd>{first.context.grounded ? "Grounded" : "Ungrounded"}</dd>
          <dt className="text-ink-secondary">Rehearsal</dt>
          <dd>{first.context.rehearsal_informed ? "Used" : "Not used"}</dd>
          <dt className="text-ink-secondary">Generated</dt>
          <dd>{formatDateTime(run?.completed_at ?? first.created_at)}</dd>
        </dl>
      ) : null}
    </div>
  );

  return (
    <>
      <VoiceHeader
        action={
          showForm ? (
            <Button size="lg" type="submit" form={VOICE_FORM_ID} disabled={busy || start.isPending}>
              {start.isPending ? "Starting…" : "Generate adaptations"}
              <ArrowRight aria-hidden />
            </Button>
          ) : (
            <Button size="lg" onClick={openForm} disabled={busy}>
              New adaptations
              <ArrowRight aria-hidden />
            </Button>
          )
        }
      />
      {latestQuery.isError && <ErrorState error={latestQuery.error} onRetry={() => latestQuery.refetch()} />}
      {runQuery.isError && <ErrorState error={runQuery.error} onRetry={() => runQuery.refetch()} />}
      {run && (!done || run.status === "partial") && (
        <RunStatusPanel
          run={run}
          operation="Adaptation"
          onRetry={lastBody && run.error?.retryable ? () => submit(lastBody) : undefined}
        />
      )}

      {adaptationsQuery.isError && <ErrorState error={adaptationsQuery.error} onRetry={() => adaptationsQuery.refetch()} />}
      {done && adaptationsQuery.isSuccess && variants.length === 0 && (
        <EmptyState title="This run produced no adaptations" description="The run finished without saving variants. Check its limitations above, then generate again." />
      )}
      <ComparisonEditor
        projectId={project.id}
        project={project}
        campaign={campaign}
        variants={variants}
        initialSelectedId={linked?.id}
        onRevised={(revision) => setRevisions((current) => [...current, revision])}
        contentColumn={contentColumn}
        onGenerateMore={busy ? undefined : openForm}
        emptyNote={
          latestQuery.isError || runQuery.isError || adaptationsQuery.isError
            ? "Adaptations can't be loaded right now; see the error above."
            : (runId && runQuery.isPending) || (done && adaptationsQuery.isPending)
              ? "Loading adaptations…"
              : busy
                ? "Generating adaptations…"
                : undefined
        }
      />
    </>
  );
}
