"use client";

import Link from "next/link";
import { useState } from "react";

import { EmptyState, ErrorState, LoadingState } from "@/components/states";
import { RunStatusPanel } from "@/components/workflow/run-status";
import { Button, buttonVariants } from "@/components/ui/button";
import { hasResult } from "@/features/proof/api";
import { useProject } from "@/features/project/project-context";
import { FeatureHeader } from "@/components/app-shell/feature-header";
import { Tabs, TabsContent, TabsList, TabsTrigger } from "@/components/ui/tabs";
import { LoopIterations } from "@/features/social/campaign-comparison";
import { Panel } from "@/features/voice/field";
import { isTerminal, useLatestRun, useRun } from "@/lib/api/runs";
import type { Campaign, EvaluationCreate, Project } from "@/lib/api/types";

import { useEvaluation, useStartEvaluation } from "./api";
import { EvaluationResults } from "./evaluation-results";
import { EvaluationSetup } from "./evaluation-setup";
import { NEXT_STEP } from "./verdict";

type Params = { versionParam?: string; candidateIds: string[]; runParam?: string };

export function LoopWorkspace(params: Params) {
  const { project, campaign } = useProject();
  return (
    <div className="grid gap-6 [&>header]:mb-0">
      <FeatureHeader
        feature="loop"
        description="Compare versions on the same synthetic population, then evaluate candidates under one scoring version."
        howItWorks={
          <ol className="grid list-decimal gap-1.5 pl-4">
            <li>Iteration history compares reactions to each campaign version within one synthetic population. Deltas appear only when two versions were tested on the same population.</li>
            <li>Current insights scores the original and up to three candidates under one scoring version (mvp-1): a model scores each dimension, and the overall score is calculated from your weights.</li>
            <li>A documented rule turns the scores into a verdict. Differences under 5 points are not meaningful.</li>
            <li>A verdict is a reason to validate with real people, not proof of market success.</li>
          </ol>
        }
      />
      {campaign ? (
        <Workspace key={campaign.id} project={project} campaign={campaign} {...params} />
      ) : (
        <EmptyState
          title="No campaign yet"
          description="Loop compares a campaign's original content with its adaptations. Create a campaign first."
          action={
            <Link className={buttonVariants({ variant: "outline" })} href={`/projects/${project.id}`}>
              Go to overview
            </Link>
          }
        />
      )}
    </div>
  );
}

function Workspace({ project, campaign, versionParam, candidateIds, runParam }: Params & { project: Project; campaign: Campaign }) {
  const latestQuery = useLatestRun(project.id, { runType: "campaign_evaluation", campaignId: campaign.id });
  const latest = latestQuery.data?.run_type === "campaign_evaluation" ? latestQuery.data : null;
  const [startedRunId, setStartedRunId] = useState<string | null>(null);
  const [lastBody, setLastBody] = useState<EvaluationCreate | null>(null);
  // null = automatic: open when candidates were linked here or nothing has been evaluated yet.
  const [setupOpen, setSetupOpen] = useState<boolean | null>(null);
  const [tab, setTab] = useState<string | null>(null);

  const runId = startedRunId ?? runParam ?? latest?.id ?? null;
  const runQuery = useRun(runId);
  const run = runQuery.data;
  // The evaluation resource exists only once its run is completed or partial (contracts/README §6).
  const evaluationId = run && hasResult(run) ? run.result!.ids[0] : null;
  const evaluationQuery = useEvaluation(campaign.id, evaluationId);
  const start = useStartEvaluation(project.id, campaign.id);
  const busy = Boolean(run && !isTerminal(run.status));

  function submit(body: EvaluationCreate) {
    setLastBody(body);
    start.mutate(body, {
      onSuccess: (accepted) => {
        setStartedRunId(accepted.run_id);
        setSetupOpen(false);
      },
    });
  }

  if (latestQuery.isPending) return <LoadingState label="Loading the latest evaluation…" />;

  const showSetup = setupOpen ?? (candidateIds.length > 0 || !runId);
  const evaluation = evaluationQuery.data;
  const reportHref = `/projects/${project.id}/proof?${new URLSearchParams({ campaign: campaign.id, ...(evaluation ? { evaluation: evaluation.id } : {}) })}`;
  const decision = evaluation?.recommendation?.decision;
  const nextSteps = [
    decision ? NEXT_STEP[decision] : "Evaluate the latest adaptations against the original.",
    // NEXT_STEP already says "validate with real people" for every decision except revise.
    ...(decision && decision !== "revise" ? [] : ["Validate the leading version with real people in the target market before launch."]),
    "Create a report so the evidence, limitations, and disclosures travel with the decision.",
  ];
  const activeTab = tab ?? (candidateIds.length > 0 || runId ? "insights" : "history");

  return (
    <Tabs value={activeTab} onValueChange={(v) => setTab(v as string)}>
      <TabsList variant="line" className="w-full justify-start border-b border-border">
        <TabsTrigger value="history">Iteration history</TabsTrigger>
        <TabsTrigger value="insights">Current insights</TabsTrigger>
        <TabsTrigger value="plan">Action plan</TabsTrigger>
      </TabsList>
      <TabsContent value="history" className="mt-5">
        <LoopIterations projectId={project.id} campaign={campaign} nextSteps={nextSteps} />
      </TabsContent>
      <TabsContent value="plan" className="mt-5 grid gap-4">
        <ol className="grid gap-2">
          {nextSteps.map((s, i) => (
            <li key={s} className="flex gap-3 rounded-card border border-border bg-surface px-4 py-3 text-sm text-ink shadow-card">
              <span className="font-semibold text-primary tabular-nums">{i + 1}</span>
              {s}
            </li>
          ))}
        </ol>
        <div className="flex flex-wrap gap-2">
          <Link className={buttonVariants({ size: "lg" })} href={reportHref}>
            Create report
          </Link>
          <Link className={buttonVariants({ variant: "outline", size: "lg" })} href={`/projects/${project.id}/voice?campaign=${campaign.id}`}>
            Revise in Voice
          </Link>
          <Link className={buttonVariants({ variant: "outline", size: "lg" })} href={`/projects/${project.id}/arena?campaign=${campaign.id}`}>
            Compare in Arena
          </Link>
        </div>
      </TabsContent>
      <TabsContent value="insights" className="mt-5 grid gap-6">
      {latestQuery.isError && <ErrorState error={latestQuery.error} onRetry={() => latestQuery.refetch()} />}

      <Panel
        id="loop-setup-heading"
        title="Evaluation setup"
        actions={
          !showSetup && (
            <Button variant="outline" size="sm" onClick={() => setSetupOpen(true)} disabled={busy}>
              New evaluation
            </Button>
          )
        }
      >
        {showSetup ? (
          <EvaluationSetup
            project={project}
            campaign={campaign}
            versionParam={versionParam}
            candidateIds={candidateIds}
            busy={busy}
            pending={start.isPending}
            error={start.error}
            onSubmit={submit}
            onCancel={runId ? () => setSetupOpen(false) : undefined}
          />
        ) : (
          <p className="text-sm text-ink-secondary">
            Showing the latest evaluation for this campaign. Start a new one to change the candidates, market, or weights.
          </p>
        )}
      </Panel>

      {runQuery.isError && <ErrorState error={runQuery.error} onRetry={() => runQuery.refetch()} />}
      {run && (!hasResult(run) || run.status === "partial") && (
        <RunStatusPanel
          run={run}
          operation="Evaluation"
          onRetry={lastBody && run.error?.retryable ? () => submit(lastBody) : undefined}
        />
      )}

      {evaluationQuery.isPending && evaluationId && <LoadingState label="Loading evaluation results…" />}
      {evaluationQuery.isError && <ErrorState error={evaluationQuery.error} onRetry={() => evaluationQuery.refetch()} />}
      {evaluation ? (
        <EvaluationResults
          evaluation={evaluation}
          campaignName={campaign.name}
          versionNumber={campaign.versions.find((v) => v.id === evaluation.source_content_version_id)?.version_number}
          reportHref={`/projects/${project.id}/proof?${new URLSearchParams({ campaign: campaign.id, evaluation: evaluation.id })}`}
        />
      ) : !runId ? (
        <EmptyState
          title="No evaluation yet"
          description="Select candidates above and run an evaluation. Scores appear only after the evaluation run completes."
        />
      ) : null}
      </TabsContent>
    </Tabs>
  );
}
