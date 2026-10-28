"use client";

import { ArrowRight, Check, FileText } from "lucide-react";
import Link from "next/link";
import { useState } from "react";

import { FeatureHeader } from "@/components/app-shell/feature-header";
import { NextStepBar } from "@/components/layout/page-parts";
import { EmptyState, ErrorState, LoadingState } from "@/components/states";
import { RunStatusPanel } from "@/components/workflow/run-status";
import { Button, buttonVariants } from "@/components/ui/button";
import { hasResult } from "@/features/proof/api";
import { useProject } from "@/features/project/project-context";
import { isTerminal, useLatestRun, useRun } from "@/lib/api/runs";
import type { Campaign, Project } from "@/lib/api/types";
import { cn } from "@/lib/utils";

import { useArena, useStartArena, type ArenaCreate } from "./api";
import { ArenaResults } from "./arena-results";
import { ARENA_FORM_ID, ArenaSetup } from "./arena-setup";

const STEPS = [
  ["Campaign concepts", "Create 2–4 variants"],
  ["Audience & criteria", "Confirm audience and goals"],
  ["Run evaluation", "Get comparative results"],
  ["Review & refine", "Explore insights and next steps"],
] as const;

function Stepper({ current }: { current: number }) {
  return (
    <ol className="grid grid-cols-[minmax(0,1fr)] gap-2 rounded-card border border-border bg-surface px-4 py-3 shadow-card sm:grid-cols-2 xl:grid-cols-4" aria-label="Arena steps">
      {STEPS.map(([title, hint], i) => {
        const state = i < current ? "done" : i === current ? "current" : "todo";
        return (
          <li key={title} className="flex items-center gap-3" aria-current={state === "current" ? "step" : undefined}>
            <span
              className={cn(
                "flex size-8 shrink-0 items-center justify-center rounded-full border text-sm font-semibold tabular-nums",
                state === "current" ? "border-primary bg-primary text-primary-foreground" : state === "done" ? "border-primary/40 bg-accent text-primary" : "border-border bg-surface text-ink-secondary",
              )}
            >
              {state === "done" ? <Check aria-hidden className="size-4" /> : i + 1}
            </span>
            <span className="grid min-w-0">
              <span className="truncate text-sm font-medium text-ink">{title}</span>
              <span className="truncate text-xs text-ink-secondary">{hint}</span>
            </span>
          </li>
        );
      })}
    </ol>
  );
}

const HOW_IT_WORKS = (
  <ol className="grid list-decimal gap-1.5 pl-4">
    <li>Pick 2–4 concepts: the current version, adaptations from Voice, or your own text and creatives.</li>
    <li>Every concept gets the same study: one market, its segments, and the same weighted criteria.</li>
    <li>Synthetic respondents react, and a model scores each concept per dimension. The overall score is calculated from the weights.</li>
    <li>Differences under 5 points are not meaningful. Setting a focus is not approval; validate with real people.</li>
  </ol>
);

export function ArenaWorkspace({ runParam }: { runParam?: string }) {
  const { project, campaign } = useProject();
  return (
    <div className="grid gap-5 [&>header]:mb-0">
      {campaign ? (
        <Workspace key={campaign.id} project={project} campaign={campaign} runParam={runParam} />
      ) : (
        <>
          <FeatureHeader feature="arena" howItWorks={HOW_IT_WORKS} />
          <EmptyState
            title="No campaign yet"
            description="Arena compares a campaign's creatives. Create a campaign from the project overview first."
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

function Workspace({ project, campaign, runParam }: { project: Project; campaign: Campaign; runParam?: string }) {
  const latestQuery = useLatestRun(project.id, { runType: "campaign_arena", campaignId: campaign.id });
  const latest = latestQuery.data?.run_type === "campaign_arena" ? latestQuery.data : null;
  const [startedRunId, setStartedRunId] = useState<string | null>(null);
  const [lastBody, setLastBody] = useState<ArenaCreate | null>(null);
  const [formReady, setFormReady] = useState(false);

  const runId = startedRunId ?? runParam ?? latest?.id ?? null;
  const runQuery = useRun(runId);
  const run = runQuery.data;
  const arenaId = run && hasResult(run) ? run.result!.ids[0] : null;
  const arenaQuery = useArena(arenaId);
  const start = useStartArena(project.id, campaign.id);
  const busy = Boolean(run && !isTerminal(run.status));
  const arena = arenaQuery.data;
  const step = busy ? 2 : arena ? 3 : 0;

  function submit(body: ArenaCreate) {
    setLastBody(body);
    start.mutate(body, { onSuccess: (accepted) => setStartedRunId(accepted.run_id) });
  }

  const preferred = arena?.variants.find((v) => v.variant_id === arena.preferred_variant_id);
  const refineHref =
    preferred?.source === "adaptation" && preferred.source_id
      ? `/projects/${project.id}/voice?campaign=${campaign.id}&adaptation=${preferred.source_id}`
      : `/projects/${project.id}/voice?campaign=${campaign.id}`;

  return (
    <>
      <FeatureHeader
        feature="arena"
        description="See what resonates, why, and what to watch for, with one study's segments and criteria for every concept."
        howItWorks={HOW_IT_WORKS}
        // Only while the setup form exists: without it these controls would do nothing.
        actions={
          formReady && (
            <a className={buttonVariants({ variant: "outline", size: "lg" })} href="#arena-audience">
              Edit audience
            </a>
          )
        }
        primaryAction={
          formReady && (
            <Button size="lg" type="submit" form={ARENA_FORM_ID} disabled={busy || start.isPending}>
              {start.isPending ? "Starting…" : "Run evaluation"}
              <ArrowRight aria-hidden />
            </Button>
          )
        }
      />
      <Stepper current={step} />
      {latestQuery.isPending ? (
        <LoadingState label="Loading the latest arena…" />
      ) : (
        <>
          {latestQuery.isError && <ErrorState error={latestQuery.error} onRetry={() => latestQuery.refetch()} />}
          <ArenaSetup project={project} campaign={campaign} busy={busy} pending={start.isPending} error={start.error} onSubmit={submit} preferredId={arena?.preferred_variant_id ?? null} onFormMount={setFormReady} />
          {runQuery.isError && <ErrorState error={runQuery.error} onRetry={() => runQuery.refetch()} />}
          {run && (!hasResult(run) || run.status === "partial") && (
            <RunStatusPanel run={run} operation="Campaign arena" onRetry={lastBody && run.error?.retryable ? () => submit(lastBody) : undefined} />
          )}
          {arenaQuery.isPending && arenaId && <LoadingState label="Loading arena results…" />}
          {arenaQuery.isError && <ErrorState error={arenaQuery.error} onRetry={() => arenaQuery.refetch()} />}
          {arena && (
            <>
              <ArenaResults arena={arena} projectId={project.id} />
              <NextStepBar
                actions={[
                  ...(preferred ? [{ label: "Refine selected concept", href: refineHref }] : []),
                  { label: "Send to Voice", href: `/projects/${project.id}/voice?campaign=${campaign.id}` },
                  { label: "Export to Proof", href: `/projects/${project.id}/proof?campaign=${campaign.id}`, Icon: FileText, primary: true },
                ]}
              />
            </>
          )}
        </>
      )}
    </>
  );
}
