"use client";

import { ArrowRight } from "lucide-react";
import Link from "next/link";
import { useState } from "react";

import { EmptyState, ErrorState, LoadingState } from "@/components/states";
import { RunStatusPanel } from "@/components/workflow/run-status";
import { Button, buttonVariants } from "@/components/ui/button";
import { hasResult } from "@/features/proof/api";
import { useProject } from "@/features/project/project-context";
import { FeatureHeader } from "@/components/app-shell/feature-header";
import { Panel } from "@/features/voice/field";
import { isTerminal, useLatestRun, useRun } from "@/lib/api/runs";
import type { Campaign, Project } from "@/lib/api/types";

import { useRiskScan, useStartRiskScan, type RiskScanCreate } from "./api";
import { ScanResults } from "./scan-results";
import { ScanSetup } from "./scan-setup";

export function RiskWorkspace({ runParam }: { runParam?: string }) {
  const { project, campaign } = useProject();
  const [recheck, setRecheck] = useState(0);
  return (
    <div className="grid gap-6 [&>header]:mb-0">
      <FeatureHeader
        feature="risk"
        title="Cultural Risk Radar"
        description="Review your campaign for cultural sensitivities and get actionable suggestions, with what the text says kept apart from how a model reads it."
        howItWorks={
          <ol className="grid list-decimal gap-1.5 pl-4">
            <li>Choose what to scan: a campaign version, an adaptation, or custom text, plus up to three images.</li>
            <li>Deterministic checks and a model review flag excerpts that may read badly in the market. Each finding quotes the exact text.</li>
            <li>Findings are hypotheses, not verdicts: dismiss, resolve, or reopen them with a note.</li>
            <li>Applying a suggested change saves a new adaptation for Voice. The campaign itself is never edited.</li>
          </ol>
        }
        primaryAction={
          campaign && (
            <Button size="lg" onClick={() => setRecheck((n) => n + 1)}>
              Re-check with changes
              <ArrowRight aria-hidden />
            </Button>
          )
        }
      />
      {campaign ? (
        <Workspace key={campaign.id} project={project} campaign={campaign} runParam={runParam} recheck={recheck} />
      ) : (
        <EmptyState
          title="No campaign yet"
          description="Risk Radar scans a campaign's content. Create a campaign from the project overview first."
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

function Workspace({ project, campaign, runParam, recheck }: { project: Project; campaign: Campaign; runParam?: string; recheck: number }) {
  const latestQuery = useLatestRun(project.id, { runType: "risk_scan", campaignId: campaign.id });
  const latest = latestQuery.data?.run_type === "risk_scan" ? latestQuery.data : null;
  const [startedRunId, setStartedRunId] = useState<string | null>(null);
  const [lastBody, setLastBody] = useState<RiskScanCreate | null>(null);
  const [setupOpen, setSetupOpen] = useState<boolean | null>(null);
  // The header's "Re-check with changes" opens the setup (each click bumps `recheck`).
  const [seenRecheck, setSeenRecheck] = useState(recheck);
  if (recheck !== seenRecheck) {
    setSeenRecheck(recheck);
    setSetupOpen(true);
  }

  const runId = startedRunId ?? runParam ?? latest?.id ?? null;
  const runQuery = useRun(runId);
  const run = runQuery.data;
  const scanId = run && hasResult(run) ? run.result!.ids[0] : null;
  const scanQuery = useRiskScan(scanId);
  const start = useStartRiskScan(project.id, campaign.id);
  const busy = Boolean(run && !isTerminal(run.status));

  function submit(body: RiskScanCreate) {
    setLastBody(body);
    start.mutate(body, {
      onSuccess: (accepted) => {
        setStartedRunId(accepted.run_id);
        setSetupOpen(false);
      },
    });
  }

  if (latestQuery.isPending) return <LoadingState label="Loading the latest scan…" />;
  const showSetup = setupOpen ?? !runId;

  return (
    <>
      {latestQuery.isError && <ErrorState error={latestQuery.error} onRetry={() => latestQuery.refetch()} />}
      {showSetup && (
        <Panel id="scan-setup-heading" title={runId ? "Re-check with changes" : "Scan setup"}>
          <ScanSetup
            project={project}
            campaign={campaign}
            busy={busy}
            pending={start.isPending}
            error={start.error}
            onSubmit={submit}
            onCancel={runId ? () => setSetupOpen(false) : undefined}
          />
        </Panel>
      )}

      {runQuery.isError && <ErrorState error={runQuery.error} onRetry={() => runQuery.refetch()} />}
      {run && (!hasResult(run) || run.status === "partial") && (
        <RunStatusPanel run={run} operation="Risk scan" onRetry={lastBody && run.error?.retryable ? () => submit(lastBody) : undefined} />
      )}
      {scanQuery.isPending && scanId && <LoadingState label="Loading findings…" />}
      {scanQuery.isError && <ErrorState error={scanQuery.error} onRetry={() => scanQuery.refetch()} />}
      {scanQuery.data ? (
        <ScanResults scan={scanQuery.data} projectId={project.id} />
      ) : !runId && !latestQuery.isError ? (
        <EmptyState title="No scan yet" description="Choose what to scan above. Findings appear only after the scan completes." />
      ) : null}
    </>
  );
}
