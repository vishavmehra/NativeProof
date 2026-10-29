"use client";

import { useQuery } from "@tanstack/react-query";
import { ArrowRight, Ban, CircleAlert, CircleCheck, CircleDashed, Lock, LoaderCircle, Pencil, Plus, TriangleAlert } from "lucide-react";
import Link from "next/link";
import { useState, type ComponentType } from "react";

import { CampaignContentView } from "@/components/campaign/content-view";
import { ModeBadge } from "@/components/evidence/badges";
import { marketNames } from "@/components/forms/fields";
import { EmptyState, ErrorState, LoadingState } from "@/components/states";
import { Button, buttonVariants } from "@/components/ui/button";
import { CAMPAIGN_TYPES, CampaignForm, WEIGHT_FIELDS } from "@/features/project/campaign-form";
import { projectKeys, useProject } from "@/features/project/project-context";
import { FEATURES, type FeatureKey } from "@/features/project/features";
import { RUN_TYPE_META, sectionHref } from "@/features/project/workflow";
import { api } from "@/lib/api/client";
import { unwrap } from "@/lib/api/errors";
import { useLatestRun } from "@/lib/api/runs";
import type { Campaign, Run } from "@/lib/api/types";
import { formatDateTime, formatRelative, humanize } from "@/lib/format";
import { cn } from "@/lib/utils";

// ---------- data ----------

function useRecentRuns(projectId: string) {
  return useQuery({
    queryKey: [...projectKeys.runs(projectId), "recent"],
    queryFn: () => unwrap(api.GET("/api/v1/projects/{project_id}/runs", { params: { path: { project_id: projectId }, query: { limit: 8 } } })),
  });
}

function useReports(projectId: string) {
  return useQuery({
    queryKey: projectKeys.reports(projectId),
    queryFn: () => unwrap(api.GET("/api/v1/projects/{project_id}/reports", { params: { path: { project_id: projectId }, query: { limit: 50 } } })),
  });
}

// ---------- workflow derivation ----------

type StageState = "completed" | "partial" | "running" | "failed" | "ready" | "blocked" | "loading";

type Stage = {
  /** Study verb, e.g. "Rehearse". */
  label: string;
  /** Feature name, e.g. "Audience" (matches the nav and the page title). */
  sub: string;
  step: number;
  segment: string | null;
  action: string;
  state: StageState;
  detail: string;
};

function fromRun(run: Run | null | undefined): { state: StageState; detail: string } | null {
  if (run === undefined) return { state: "loading", detail: "Checking runs…" };
  if (run === null) return null;
  const when = formatRelative(run.completed_at ?? run.created_at);
  switch (run.status) {
    case "completed":
      return { state: "completed", detail: `Completed ${when}` };
    case "partial":
      return { state: "partial", detail: `Partial result ${when}` };
    case "queued":
    case "running":
      return { state: "running", detail: run.progress?.message ?? `${humanize(run.status)}…` };
    case "failed":
      return { state: "failed", detail: run.error?.message ?? `Failed ${when}` };
    case "cancelled":
      return { state: "failed", detail: `Cancelled ${when}` };
  }
}

const done = (s: StageState) => s === "completed" || s === "partial";

// The research journey shown on the project overview (user-approved order: Compare before Adapt).
const STUDY_STEPS: Partial<Record<FeatureKey, { n: number; verb: string }>> = {
  atlas: { n: 1, verb: "Discover" },
  dna: { n: 2, verb: "Profile" },
  audience: { n: 3, verb: "Rehearse" },
  arena: { n: 4, verb: "Compare" },
  risk: { n: 5, verb: "Risk check" },
  voice: { n: 6, verb: "Adapt" },
  loop: { n: 7, verb: "Evaluate" },
  proof: { n: 8, verb: "Prove" },
};

/** The 8-step research journey, derived from real runs and reports. */
function useWorkflow(projectId: string, campaign: Campaign | null) {
  const cp = campaign ? projectId : null;
  const c = campaign?.id;
  const discovery = useLatestRun(projectId, { runType: "market_discovery" });
  const profile = useLatestRun(projectId, { runType: "cultural_profile" });
  const rehearsal = useLatestRun(cp, { runType: "campaign_rehearsal", campaignId: c });
  const arena = useLatestRun(cp, { runType: "campaign_arena", campaignId: c });
  const risk = useLatestRun(cp, { runType: "risk_scan", campaignId: c });
  const adaptation = useLatestRun(cp, { runType: "campaign_adaptation", campaignId: c });
  const evaluation = useLatestRun(cp, { runType: "campaign_evaluation", campaignId: c });
  const reports = useReports(projectId);
  const queries = [discovery, profile, rehearsal, arena, risk, adaptation, evaluation, reports];
  const error = queries.find((q) => q.error)?.error ?? null;
  // Disabled queries (no campaign) are pending but idle; only real fetches count as loading.
  const loading = queries.some((q) => q.isPending && q.fetchStatus !== "idle");

  const blocked = (detail: string) => ({ state: "blocked" as const, detail });
  const ready = (detail: string) => ({ state: "ready" as const, detail });
  const fromOr = (run: Run | null | undefined, detail: string) => fromRun(run) ?? ready(detail);
  const noCampaign = blocked("Create a campaign first.");

  const discover = fromOr(discovery.data, "Not started. Grounds later steps in cultural evidence.");
  const dna = fromOr(profile.data, "Not started. Builds on discovery evidence.");
  const rehearse = campaign ? fromOr(rehearsal.data, "Not started.") : noCampaign;
  const compare = campaign ? fromOr(arena.data, "Not started.") : noCampaign;
  const riskCheck = campaign ? fromOr(risk.data, "Not started.") : noCampaign;
  const adapt = campaign ? fromOr(adaptation.data, "Not started.") : noCampaign;
  const evaluate = !campaign
    ? noCampaign
    : (fromRun(evaluation.data) ?? (done(adapt.state) ? ready("Not started. Select adaptations to evaluate.") : blocked("Needs generated adaptations.")));
  const report = reports.data?.items.find((r) => r.campaign_id === c);
  const anyDone = [discover, dna, rehearse, compare, riskCheck, adapt, evaluate].some((s) => done(s.state));
  const prove = !campaign
    ? noCampaign
    : report
      ? { state: report.status === "partial" ? ("partial" as const) : ("completed" as const), detail: `Report “${report.title}” · ${formatRelative(report.created_at)}` }
      : anyDone
        ? ready("No report yet.")
        : blocked("Complete at least one step first.");

  const step = (key: FeatureKey, action: string, s: { state: StageState; detail: string }): Stage => {
    const f = FEATURES[key];
    const meta = STUDY_STEPS[key];
    return { label: meta?.verb ?? f.label, sub: f.label, step: meta?.n ?? 0, segment: f.segment, action, ...s };
  };
  const stages: Stage[] = [
    step("atlas", "Discover cultural signals", discover),
    step("dna", "Build the cultural profile", dna),
    step("audience", "Run campaign rehearsal", rehearse),
    step("arena", "Compare creative variants", compare),
    step("risk", "Scan for cultural risk", riskCheck),
    step("voice", "Generate adaptations", adapt),
    step("loop", "Evaluate selected versions", evaluate),
    step("proof", "Create a report", prove),
  ];
  return { stages, error, loading };
}

const STATE_UI: Record<StageState, { text: string; Icon: ComponentType<{ className?: string; "aria-hidden"?: boolean }>; className: string }> = {
  completed: { text: "Completed", Icon: CircleCheck, className: "text-success" },
  partial: { text: "Partial", Icon: TriangleAlert, className: "text-warning" },
  running: { text: "Running", Icon: LoaderCircle, className: "text-info" },
  failed: { text: "Needs attention", Icon: CircleAlert, className: "text-danger" },
  ready: { text: "Not started", Icon: CircleDashed, className: "text-ink-secondary" },
  blocked: { text: "Blocked", Icon: Ban, className: "text-ink-secondary" },
  loading: { text: "Checking", Icon: LoaderCircle, className: "text-ink-secondary" },
};

function WorkflowSequence({ stages, next, projectId, campaignId }: { stages: Stage[]; next: Stage | undefined; projectId: string; campaignId?: string }) {
  return (
    <ol className="grid gap-px overflow-hidden rounded-lg border border-border bg-border sm:grid-cols-2 lg:grid-cols-4">
      {stages.map((s) => {
        const ui = STATE_UI[s.state];
        const isNext = s === next;
        return (
          // Solid fills only: no text sits on a translucent background.
          <li key={s.label} className={cn("flex flex-col gap-2 p-3", isNext ? "bg-accent" : s.state === "blocked" ? "bg-surface-muted" : "bg-surface")}>
            <div className="flex items-center justify-between gap-2">
              <span className="text-[11px] font-medium text-ink-secondary tabular-nums">
                {String(s.step).padStart(2, "0")} · {s.sub}
              </span>
              {isNext && <span className="rounded-sm bg-primary px-1.5 py-0.5 text-[11px] font-semibold tracking-wide text-primary-foreground uppercase">Next</span>}
            </div>
            <h3 className={cn("text-[15px] font-semibold", s.state === "blocked" ? "text-ink-secondary" : "text-ink")}>{s.label}</h3>
            <p className={cn("flex items-center gap-1.5 text-xs font-medium", ui.className)}>
              <ui.Icon aria-hidden className={cn("size-3.5", (s.state === "running" || s.state === "loading") && "animate-spin")} />
              {ui.text}
            </p>
            <p className="line-clamp-3 text-xs text-ink-secondary">{s.detail}</p>
            {s.state !== "blocked" && s.state !== "loading" && (
              <Link
                href={sectionHref(projectId, s.segment, campaignId)}
                className="mt-auto inline-flex items-center gap-1 text-xs font-medium text-primary underline-offset-2 hover:underline"
              >
                {done(s.state) ? "Open results" : s.state === "running" ? "View progress" : s.state === "failed" ? "Review and retry" : s.action}
                <ArrowRight aria-hidden className="size-3" />
              </Link>
            )}
          </li>
        );
      })}
    </ol>
  );
}

// ---------- page ----------

export function ProjectOverview() {
  const { project, campaigns, campaign, setCampaignId } = useProject();
  const demo = project.mode === "demo";
  const [editor, setEditor] = useState<"closed" | "create" | "edit">("closed");
  const runs = useRecentRuns(project.id);
  const workflow = useWorkflow(project.id, campaign);
  const next = workflow.stages.find((s) => s.state === "running" || s.state === "failed" || s.state === "ready");
  const latest = runs.data?.items[0];
  const lastActivity = latest ? (latest.completed_at ?? latest.started_at ?? latest.created_at) : null;

  return (
    <div className="space-y-10">
      {/* Project header */}
      <section aria-labelledby="project-title" className="grid gap-6 border-b border-border pb-8 lg:grid-cols-[minmax(0,1fr)_320px]">
        <div className="min-w-0 space-y-3">
          <div className="flex flex-wrap items-center gap-2 text-xs text-ink-secondary">
            <span>Project</span>
            <ModeBadge mode={project.mode} />
          </div>
          <h1 id="project-title" className="font-serif text-[34px] leading-tight text-ink">
            {project.name}
          </h1>
          <dl className="flex flex-wrap gap-x-6 gap-y-1 text-[13px]">
            <div className="flex gap-1.5">
              <dt className="text-ink-secondary">Brand</dt>
              <dd className="font-medium text-ink">{project.brand.name}</dd>
            </div>
            <div className="flex gap-1.5">
              <dt className="text-ink-secondary">Markets</dt>
              <dd className="text-ink">{marketNames(project.target_markets)}</dd>
            </div>
            <div className="flex gap-1.5">
              <dt className="text-ink-secondary">Last activity</dt>
              <dd className="text-ink" title={lastActivity ? formatDateTime(lastActivity) : undefined}>
                {runs.isPending ? "…" : lastActivity ? formatRelative(lastActivity) : "No runs yet"}
              </dd>
            </div>
          </dl>
          {project.description && <p className="max-w-prose text-sm text-ink">{project.description}</p>}
          {project.objective && (
            <p className="max-w-prose text-sm text-ink">
              <span className="font-medium">Objective: </span>
              {project.objective}
            </p>
          )}
        </div>
        <aside aria-label="Brand kit" className="space-y-2 rounded-md border border-border bg-surface p-4 text-[13px]">
          <h2 className="text-[15px] font-semibold text-ink">Brand kit</h2>
          {project.brand.description && <p className="text-ink-secondary">{project.brand.description}</p>}
          <dl className="space-y-1.5">
            {(
              [
                ["Voice", project.brand.voice],
                ["Protected", project.brand.protected_terms],
                ["Prohibited", project.brand.prohibited_terms],
                ["Preferred", project.brand.preferred_terms],
              ] as const
            ).map(([label, items]) => (
              <div key={label} className="grid grid-cols-[76px_minmax(0,1fr)] gap-2">
                <dt className="text-ink-secondary">{label}</dt>
                <dd className="text-ink">{items.length ? items.join(", ") : <span className="text-ink-secondary">None</span>}</dd>
              </div>
            ))}
            {project.brand.target_audience && (
              <div className="grid grid-cols-[76px_minmax(0,1fr)] gap-2">
                <dt className="text-ink-secondary">Audience</dt>
                <dd className="text-ink">{project.brand.target_audience}</dd>
              </div>
            )}
          </dl>
        </aside>
      </section>

      {/* Next step */}
      {campaign && next && (
        <section aria-label="Next step" className="flex flex-wrap items-center justify-between gap-3 rounded-lg border border-primary/25 bg-accent px-4 py-3">
          <div className="text-sm">
            <p className="font-medium text-ink">
              Next: {next.label} · {next.state === "running" ? "in progress" : next.state === "failed" ? "the last run needs attention" : next.action.toLowerCase()}
            </p>
            <p className="text-[13px] text-ink-secondary">{next.detail}</p>
          </div>
          <Link href={sectionHref(project.id, next.segment, campaign.id)} className={buttonVariants({ size: "sm" })}>
            {next.state === "running" ? "View progress" : next.state === "failed" ? "Review" : next.action}
            <ArrowRight aria-hidden />
          </Link>
        </section>
      )}
      {campaign && !next && workflow.stages.every((s) => done(s.state)) && (
        <section aria-label="Next step" className="flex flex-wrap items-center justify-between gap-3 rounded-lg border border-primary/25 bg-accent px-4 py-3">
          <div className="text-sm">
            <p className="font-medium text-ink">Every stage has a result for this campaign.</p>
            <p className="text-[13px] text-ink-secondary">
              Review the report and its evidence register, then validate the open questions with real people before launch.
            </p>
          </div>
          <Link href={sectionHref(project.id, "proof", campaign.id)} className={buttonVariants({ size: "sm" })}>
            Open Proof
            <ArrowRight aria-hidden />
          </Link>
        </section>
      )}

      {/* Campaign */}
      <section aria-labelledby="campaign-title" className="space-y-4">
        <div className="flex flex-wrap items-center justify-between gap-3">
          <h2 id="campaign-title" className="text-xl font-semibold text-ink">
            {editor === "create" ? "New campaign" : "Current campaign"}
          </h2>
          {editor === "closed" && (
            <div className="flex flex-wrap items-center gap-2">
              {campaign && (
                <Button variant="outline" size="sm" onClick={() => setEditor("edit")}>
                  <Pencil aria-hidden />
                  Edit campaign
                </Button>
              )}
              <Button size="sm" onClick={() => setEditor("create")} disabled={demo} aria-describedby={demo ? "demo-campaign-note" : undefined}>
                <Plus aria-hidden />
                New campaign
              </Button>
            </div>
          )}
        </div>
        {demo && editor === "closed" && (
          <p id="demo-campaign-note" className="flex items-start gap-2 text-xs text-ink-secondary">
            <Lock aria-hidden className="mt-0.5 size-3.5 shrink-0" />
            Demo projects contain one seeded scenario, so new campaigns and content edits are disabled (the API returns 409). Name, objective,
            markets, and evaluation weights can still be edited.
          </p>
        )}

        {editor !== "closed" ? (
          <div className="space-y-5 rounded-xl border border-border bg-surface p-5 shadow-card">
            <CampaignForm
              key={editor === "edit" ? campaign?.id : "new"}
              projectId={project.id}
              campaign={editor === "edit" ? (campaign ?? undefined) : undefined}
              demo={demo}
              onCancel={() => setEditor("closed")}
              onDone={(saved) => {
                setEditor("closed");
                setCampaignId(saved.id);
              }}
            />
          </div>
        ) : !campaign ? (
          <EmptyState
            title="No campaign yet"
            description="Add the campaign copy you want to test: a headline, body, or call to action, plus the markets it targets. Every later stage works on a campaign."
            action={
              !demo && (
                <Button size="sm" onClick={() => setEditor("create")}>
                  <Plus aria-hidden />
                  New campaign
                </Button>
              )
            }
          />
        ) : (
          <CampaignSummary campaign={campaign} total={campaigns.length} />
        )}
      </section>

      {/* Workflow */}
      <section aria-labelledby="workflow-title" className="space-y-3">
        <div className="flex flex-wrap items-baseline justify-between gap-2">
          <h2 id="workflow-title" className="text-xl font-semibold text-ink">
            Workflow
          </h2>
          <p className="text-xs text-ink-secondary">A stage counts as done only when its run completed or returned a partial result.</p>
        </div>
        {workflow.error && <ErrorState error={workflow.error} />}
        {workflow.loading ? (
          // One skeleton for the whole strip instead of a "Checking runs…" line per step.
          <div role="status" aria-label="Checking runs" className="h-[352px] animate-pulse rounded-lg border border-border bg-surface-muted lg:h-[176px]" />
        ) : (
          <WorkflowSequence stages={workflow.stages} next={campaign ? next : undefined} projectId={project.id} campaignId={campaign?.id} />
        )}
      </section>

      {/* Recent activity */}
      <section aria-labelledby="activity-title" className="space-y-3">
        <h2 id="activity-title" className="text-xl font-semibold text-ink">
          Recent activity
        </h2>
        {runs.isPending ? (
          <LoadingState label="Loading activity…" />
        ) : runs.error ? (
          <ErrorState error={runs.error} onRetry={() => void runs.refetch()} />
        ) : runs.data.items.length === 0 ? (
          <EmptyState title="No runs yet" description="Runs appear here as soon as you start a discovery, rehearsal, adaptation, or evaluation." />
        ) : (
          <ul className="divide-y divide-border rounded-md border border-border bg-surface">
            {runs.data.items.map((run) => (
              <ActivityRow key={run.id} run={run} projectId={project.id} campaigns={campaigns} />
            ))}
          </ul>
        )}
      </section>
    </div>
  );
}

function CampaignSummary({ campaign, total }: { campaign: Campaign; total: number }) {
  const type = CAMPAIGN_TYPES.find((t) => t.value === campaign.campaign_type)?.label ?? campaign.campaign_type;
  const weightTotal = WEIGHT_FIELDS.reduce((sum, f) => sum + campaign.evaluation_criteria[f.key], 0);
  return (
    <div className="grid gap-6 rounded-md border border-border bg-surface p-5 lg:grid-cols-[minmax(0,1fr)_300px]">
      <div className="min-w-0 space-y-4">
        <div className="space-y-1">
          <h3 className="text-lg font-semibold text-ink">{campaign.name}</h3>
          <p className="text-[13px] text-ink-secondary">
            {type} · {marketNames(campaign.target_markets)} · version {campaign.current_version.version_number} · updated{" "}
            <span title={formatDateTime(campaign.updated_at)}>{formatRelative(campaign.updated_at)}</span>
            {total > 1 && ` · ${total} campaigns in this project`}
          </p>
          {campaign.objective && <p className="max-w-prose text-sm text-ink">{campaign.objective}</p>}
        </div>
        <CampaignContentView content={campaign.current_version.content} />
      </div>
      <div className="space-y-5 text-[13px]">
        <div className="space-y-2">
          <h4 className="font-semibold text-ink">Evaluation weights</h4>
          <dl className="space-y-1">
            {WEIGHT_FIELDS.map((f) => (
              <div key={f.key} className="flex justify-between gap-3">
                <dt className="text-ink-secondary">{f.label}</dt>
                <dd className="text-ink tabular-nums">{campaign.evaluation_criteria[f.key].toFixed(2)}</dd>
              </div>
            ))}
            <div className="flex justify-between gap-3 border-t border-border pt-1">
              <dt className="text-ink-secondary">Total</dt>
              <dd className="text-ink tabular-nums">{weightTotal.toFixed(2)}</dd>
            </div>
          </dl>
          <p className="text-xs text-ink-secondary">Cultural risk is inverted into utility (100 − score) when Loop computes the overall score.</p>
        </div>
        <div className="space-y-2">
          <h4 className="font-semibold text-ink">Content versions</h4>
          <ul className="space-y-1">
            {campaign.versions.map((v) => (
              <li key={v.id}>
                <details className="group rounded-sm border border-border">
                  <summary className="flex cursor-pointer items-center justify-between gap-2 px-2.5 py-1.5 select-none hover:bg-surface-muted/60">
                    <span className="font-medium text-ink">
                      Version {v.version_number}
                      {v.id === campaign.current_version.id && <span className="font-normal text-primary"> · current</span>}
                    </span>
                    <span className="text-xs text-ink-secondary" title={formatDateTime(v.created_at)}>
                      {formatRelative(v.created_at)}
                    </span>
                  </summary>
                  <div className="border-t border-border p-2.5">
                    <CampaignContentView content={v.content} />
                  </div>
                </details>
              </li>
            ))}
          </ul>
        </div>
      </div>
    </div>
  );
}

const RUN_STATUS_UI: Record<Run["status"], { Icon: ComponentType<{ className?: string; "aria-hidden"?: boolean }>; className: string }> = {
  completed: { Icon: CircleCheck, className: "text-success" },
  partial: { Icon: TriangleAlert, className: "text-warning" },
  queued: { Icon: LoaderCircle, className: "text-info" },
  running: { Icon: LoaderCircle, className: "text-info" },
  failed: { Icon: CircleAlert, className: "text-danger" },
  cancelled: { Icon: Ban, className: "text-ink-secondary" },
};

function ActivityRow({ run, projectId, campaigns }: { run: Run; projectId: string; campaigns: Campaign[] }) {
  const meta = RUN_TYPE_META[run.run_type];
  const ui = RUN_STATUS_UI[run.status];
  const when = run.completed_at ?? run.started_at ?? run.created_at;
  const campaignName = campaigns.find((c) => c.id === run.campaign_id)?.name;
  return (
    <li>
      <Link
        href={sectionHref(projectId, meta.segment, run.campaign_id)}
        className="grid gap-x-4 gap-y-0.5 px-4 py-2.5 outline-none hover:bg-surface-muted/50 sm:grid-cols-[minmax(0,1fr)_auto] sm:items-center"
      >
        <span className="flex min-w-0 items-center gap-2 text-sm">
          <ui.Icon aria-hidden className={cn("size-4 shrink-0", ui.className, (run.status === "running" || run.status === "queued") && "animate-spin")} />
          <span className="text-ink">
            {meta.label} <span className="font-medium">{run.status}</span>
          </span>
          {campaignName && <span className="truncate text-ink-secondary">· {campaignName}</span>}
        </span>
        <span className="text-xs text-ink-secondary tabular-nums sm:text-right" title={formatDateTime(when)}>
          {formatRelative(when)}
          {run.mode === "demo" && " · demo fixtures"}
        </span>
      </Link>
    </li>
  );
}
