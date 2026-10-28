"use client";

import { BotIcon } from "lucide-react";
import Link from "next/link";
import { useSearchParams } from "next/navigation";
import { useRef, useState } from "react";

import { CampaignContentView } from "@/components/campaign/content-view";
import { EmptyState, ErrorState, LoadingState } from "@/components/states";
import { RunStatusPanel } from "@/components/workflow/run-status";
import { Button, buttonVariants } from "@/components/ui/button";
import { Label } from "@/components/ui/label";
import { hasResult, setRunParam, useDiscoveryResult } from "@/features/atlas/api";
import { PageHeader } from "@/features/atlas/page-header";
import { useProject } from "@/features/project/project-context";
import { isTerminal, useLatestRun, useRun } from "@/lib/api/runs";
import type { Campaign, Project, RehearsalCreate, Study } from "@/lib/api/types";
import { formatDateTime, humanize } from "@/lib/format";

import { useCreateStudy, useRehearsalResult, useStartRehearsal, useStudies } from "./api";
import { DIMENSION_LABEL } from "./dimensions";
import { RehearsalResults } from "./rehearsal-results";
import { StudyForm } from "./study-form";

export function AudienceWorkspace() {
  const { project, campaign } = useProject();
  return (
    <div className="grid gap-8">
      <PageHeader
        feature="audience"
        title="Quick rehearsal"
        actions={
          <Link href={campaign ? `?campaign=${campaign.id}` : "?"} className={buttonVariants({ variant: "outline" })}>
            Back to Audience Intelligence
          </Link>
        }
        description="Explore how synthetic audience perspectives might read the campaign. A hypothesis-generation tool, not a replacement for research with real people."
      />
      {campaign ? (
        // Remount per campaign so a run started for one campaign never shows under another.
        <Workspace key={campaign.id} project={project} campaign={campaign} />
      ) : (
        <EmptyState
          title="No campaign yet"
          description="A rehearsal tests a campaign's content. Add a campaign to this project first."
          action={
            <Link href={`/projects/${project.id}`} className={buttonVariants({ variant: "outline" })}>
              Go to overview
            </Link>
          }
        />
      )}
    </div>
  );
}

function StudyDetails({ study }: { study: Study }) {
  const { simulation_config: config } = study;
  return (
    <dl className="grid gap-x-6 gap-y-2 text-sm sm:grid-cols-[8.5rem_minmax(0,1fr)]">
      <dt className="text-muted-foreground">Market</dt>
      <dd>
        {study.market.display_name} <span className="font-mono text-xs text-muted-foreground">{study.market.country_code}</span>
      </dd>
      <dt className="text-muted-foreground">Research questions</dt>
      <dd>
        <ol className="list-decimal space-y-0.5 pl-4">
          {study.research_questions.map((q) => (
            <li key={q}>{q}</li>
          ))}
        </ol>
      </dd>
      <dt className="text-muted-foreground">Dimensions</dt>
      <dd>{study.dimensions.map((d) => DIMENSION_LABEL[d]).join(", ")}</dd>
      <dt className="text-muted-foreground">Segments</dt>
      <dd>
        {study.segments.length === 0 ? (
          "None defined; the model proposes segment assumptions, labeled as model-generated."
        ) : (
          <>
            <ul className="space-y-0.5">
              {study.segments.map((s) => (
                <li key={s.label}>
                  <span className="font-medium">{s.label}</span>
                  <span className="text-muted-foreground"> — {s.description}</span>
                </li>
              ))}
            </ul>
            <p className="mt-1 text-xs text-muted-foreground">Audience hypotheses, not verified demographic facts.</p>
          </>
        )}
      </dd>
      <dt className="text-muted-foreground">Simulation</dt>
      <dd className="tabular-nums">
        {config.response_count} reactions requested (a generation target, not a sample size) · {config.segment_count}{" "}
        {config.segment_count === 1 ? "segment" : "segments"} · seed {config.random_seed ?? "not fixed"}
      </dd>
    </dl>
  );
}

function Workspace({ project, campaign }: { project: Project; campaign: Campaign }) {
  const isDemo = project.mode === "demo";
  const searchParams = useSearchParams();
  const discoveryParam = searchParams.get("discovery");
  // A run linked with ?run= (e.g. from Proof's run history) wins over the latest one.
  const runParam = searchParams.get("run");
  const studiesQuery = useStudies(project.id, campaign.id);
  const latestQuery = useLatestRun(project.id, { runType: "campaign_rehearsal", campaignId: campaign.id });
  const latest = latestQuery.data?.run_type === "campaign_rehearsal" ? latestQuery.data : null;
  // Grounding: the discovery passed from Atlas, else the latest completed one for this campaign.
  const latestDiscoveryQuery = useLatestRun(discoveryParam ? null : project.id, {
    runType: "market_discovery",
    campaignId: campaign.id,
    status: "completed",
  });
  const latestDiscovery =
    latestDiscoveryQuery.data?.run_type === "market_discovery" && latestDiscoveryQuery.data.status === "completed"
      ? latestDiscoveryQuery.data
      : null;
  const discoveryRunId = discoveryParam ?? latestDiscovery?.id ?? null;
  const discoveryQuery = useDiscoveryResult(project.id, discoveryRunId);
  const discovery = hasResult(discoveryQuery.data) ? discoveryQuery.data : undefined;

  const [studyId, setStudyId] = useState<string | null>(null);
  const [creating, setCreating] = useState(false);
  const [ungrounded, setUngrounded] = useState(false);
  const [setupOpen, setSetupOpen] = useState(false);
  const [startedRunId, setStartedRunId] = useState<string | null>(null);
  const [lastRequest, setLastRequest] = useState<{ studyId: string; body: RehearsalCreate } | null>(null);
  const setupRef = useRef<HTMLElement>(null);

  const studies = studiesQuery.data?.items ?? [];
  const study = studies.find((s) => s.id === studyId) ?? studies.find((s) => s.id === latest?.study_id) ?? studies[0] ?? null;
  const runId = startedRunId ?? runParam ?? latest?.id ?? null;
  const runQuery = useRun(runId);
  const run = runQuery.data;
  const wrongType = run && run.run_type !== "campaign_rehearsal";
  const resultQuery = useRehearsalResult(run?.study_id, hasResult(run) && !wrongType ? runId : null);
  const createStudy = useCreateStudy(project.id);
  const start = useStartRehearsal(project.id);
  const busy = Boolean(run && !isTerminal(run.status));
  const grounded = Boolean(discovery) && !ungrounded;

  function runRehearsal(request: { studyId: string; body: RehearsalCreate }) {
    setLastRequest(request);
    start.mutate(request, {
      onSuccess: (accepted) => {
        setStartedRunId(accepted.run_id);
        setRunParam(accepted.run_id);
        setSetupOpen(false);
      },
    });
  }

  if (studiesQuery.isPending || latestQuery.isPending) return <LoadingState label="Loading studies and the latest rehearsal…" />;
  if (studiesQuery.isError) return <ErrorState error={studiesQuery.error} onRetry={() => studiesQuery.refetch()} />;

  const showSetup = !runId || setupOpen;
  const resultStudy = studies.find((s) => s.id === run?.study_id) ?? null;
  const marketMismatch = discovery && study && discovery.market.country_code !== study.market.country_code;

  return (
    <>
      {latestQuery.isError && <ErrorState error={latestQuery.error} onRetry={() => latestQuery.refetch()} />}

      <section ref={setupRef} aria-labelledby="setup-heading" className="scroll-mt-4 rounded-lg border bg-card">
        <div className="flex flex-wrap items-center justify-between gap-2 border-b px-4 py-3">
          <h2 id="setup-heading" className="text-[15px] font-semibold">
            Study configuration
          </h2>
          {!showSetup && (
            <Button
              variant="outline"
              size="sm"
              onClick={() => {
                setSetupOpen(true);
                setupRef.current?.scrollIntoView({ block: "start" });
              }}
            >
              New rehearsal
            </Button>
          )}
        </div>

        {!showSetup ? (
          <p className="px-4 py-3 text-sm md:px-5">
            {resultStudy ? (
              <>
                <span className="font-medium">{resultStudy.name}</span> · {resultStudy.market.display_name} ·{" "}
                {resultStudy.simulation_config.response_count} reactions requested
              </>
            ) : (
              "Showing the latest rehearsal for this campaign."
            )}
          </p>
        ) : (
          <div className="grid gap-6 p-4 md:p-5 lg:grid-cols-[minmax(0,3fr)_minmax(0,2fr)] lg:gap-8">
            <div className="grid content-start gap-5">
              {studies.length === 0 && isDemo ? (
                <EmptyState
                  title="No study found"
                  description="Demo projects include one seeded study, and creating studies is disabled in demo projects. Reload the page, or create a new demo project."
                />
              ) : creating || studies.length === 0 ? (
                <div className="grid gap-3">
                  <h3 className="text-[15px] font-semibold">Create a study</h3>
                  <StudyForm
                    project={project}
                    campaign={campaign}
                    pending={createStudy.isPending}
                    error={createStudy.error}
                    onSubmit={(body) =>
                      createStudy.mutate(body, {
                        onSuccess: (created) => {
                          setStudyId(created.id);
                          setCreating(false);
                        },
                      })
                    }
                    onCancel={studies.length > 0 ? () => setCreating(false) : undefined}
                  />
                </div>
              ) : (
                study && (
                  <div className="grid gap-4">
                    <div className="flex flex-wrap items-end justify-between gap-3">
                      {studies.length > 1 ? (
                        <div className="grid gap-1">
                          <Label htmlFor="study-select" className="text-xs">
                            Study
                          </Label>
                          <select
                            id="study-select"
                            value={study.id}
                            onChange={(e) => setStudyId(e.target.value)}
                            className="h-8 rounded-lg border border-input bg-transparent px-2 text-sm outline-none focus-visible:border-ring focus-visible:ring-3 focus-visible:ring-ring/50"
                          >
                            {studies.map((s) => (
                              <option key={s.id} value={s.id}>
                                {s.name}
                              </option>
                            ))}
                          </select>
                        </div>
                      ) : (
                        <h3 className="text-[15px] font-semibold">{study.name}</h3>
                      )}
                      {!isDemo && (
                        <Button variant="outline" size="sm" onClick={() => setCreating(true)}>
                          Create study
                        </Button>
                      )}
                    </div>
                    {isDemo && (
                      <p className="text-xs text-muted-foreground">
                        Demo projects use their seeded study. Creating studies is disabled because the demo fixtures
                        describe only that scenario.
                      </p>
                    )}
                    <StudyDetails study={study} />
                  </div>
                )
              )}

              {study && !creating && (
                <fieldset className="grid gap-2 border-t pt-4">
                  <legend className="mb-1.5 text-sm font-medium">Grounding evidence</legend>
                  {discoveryRunId && discoveryQuery.isPending ? (
                    <LoadingState label="Loading discovery evidence…" />
                  ) : discovery ? (
                    <>
                      <Label className="items-start font-normal">
                        <input
                          type="radio"
                          name="grounding"
                          className="mt-0.5 size-4 accent-primary"
                          checked={!ungrounded}
                          onChange={() => setUngrounded(false)}
                        />
                        <span className="leading-snug">
                          Use discovery evidence from {formatDateTime(discovery.run_metadata.completed_at)} (
                          {discovery.market.display_name}, {discovery.evidence.length} evidence records,{" "}
                          {discoveryParam ? "passed from Atlas" : "latest for this campaign"})
                        </span>
                      </Label>
                      <Label className="items-start font-normal">
                        <input
                          type="radio"
                          name="grounding"
                          className="mt-0.5 size-4 accent-primary"
                          checked={ungrounded}
                          onChange={() => setUngrounded(true)}
                        />
                        Run without discovery evidence (ungrounded)
                      </Label>
                      {marketMismatch && (
                        <p className="text-xs font-medium text-warning">
                          This discovery covers {discovery.market.display_name}, but the study targets{" "}
                          {study.market.display_name}.
                        </p>
                      )}
                      {ungrounded && (
                        <p className="text-xs text-muted-foreground">
                          The generator gets no cultural evidence, and the result is labeled ungrounded.
                        </p>
                      )}
                    </>
                  ) : (
                    <p className="text-sm text-muted-foreground">
                      {discoveryQuery.isError
                        ? "The linked discovery could not be loaded, so the rehearsal will run ungrounded. "
                        : "No completed discovery for this campaign, so the rehearsal will run ungrounded and the result will say so. "}
                      <Link href={`/projects/${project.id}/atlas?campaign=${campaign.id}`} className="underline underline-offset-2">
                        Run a discovery in Atlas
                      </Link>
                    </p>
                  )}
                </fieldset>
              )}
            </div>

            <div className="grid content-start gap-4">
              <div className="grid gap-2">
                <p className="text-xs font-medium tracking-wide text-muted-foreground uppercase">
                  Content rehearsed · version {campaign.current_version.version_number}
                </p>
                <div className="rounded-md border bg-background px-3 py-3">
                  <CampaignContentView content={campaign.current_version.content} />
                </div>
              </div>
              {study && !creating && (
                <>
                  <div className="grid gap-1.5 rounded-md border border-dashed border-ink-secondary/50 bg-surface-muted px-3 py-2.5 text-sm">
                    <p className="flex items-center gap-2 font-medium">
                      <BotIcon aria-hidden className="size-4" />
                      Before you run
                    </p>
                    <p>
                      Reactions are AI-generated and are not responses from real people. The{" "}
                      <span className="tabular-nums">{study.simulation_config.response_count}</span> requested reactions
                      are a generation target, not a sample size, and repeated generations from one model are not
                      independent confirmation.
                    </p>
                    {isDemo && (
                      <p className="text-xs text-muted-foreground">
                        Demo project: reactions come from labeled fixtures. If fewer exist than requested, the result
                        reports the true count.
                      </p>
                    )}
                  </div>
                  {Boolean(start.error) && <ErrorState error={start.error} />}
                  <Button
                    size="lg"
                    disabled={busy || start.isPending}
                    aria-busy={start.isPending || undefined}
                    onClick={() =>
                      runRehearsal({
                        studyId: study.id,
                        body: {
                          content_version_id: campaign.current_version.id,
                          ...(grounded && discovery ? { discovery_run_id: discovery.run_id } : {}),
                        },
                      })
                    }
                  >
                    Run campaign rehearsal
                  </Button>
                  {busy && (
                    <p className="text-xs text-muted-foreground">
                      A rehearsal is running. You can start another when it finishes.
                    </p>
                  )}
                </>
              )}
            </div>
          </div>
        )}
      </section>

      {runQuery.isError && <ErrorState error={runQuery.error} onRetry={() => runQuery.refetch()} />}
      {wrongType && (
        <EmptyState
          title="This link does not point to a rehearsal"
          description={`Run ${run.id} is a ${humanize(run.run_type).toLowerCase()} run. Open it from its own section, or start a rehearsal here.`}
        />
      )}
      {run && !wrongType && !hasResult(run) && (
        <RunStatusPanel
          run={run}
          operation="Campaign rehearsal"
          onRetry={lastRequest && run.error?.retryable ? () => runRehearsal(lastRequest) : undefined}
        />
      )}
      {resultQuery.isPending && hasResult(run) && <LoadingState label="Loading rehearsal results…" />}
      {resultQuery.isError && <ErrorState error={resultQuery.error} onRetry={() => resultQuery.refetch()} />}
      {resultQuery.data && <RehearsalResults result={resultQuery.data} study={resultStudy} projectId={project.id} />}
    </>
  );
}
