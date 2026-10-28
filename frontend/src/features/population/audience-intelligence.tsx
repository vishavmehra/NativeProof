"use client";

import { ArrowRightIcon, BotIcon } from "lucide-react";
import Link from "next/link";
import { useSearchParams } from "next/navigation";
import { useRef, useState } from "react";

import { WorldMap } from "@/components/data/world-map";
import { EmptyState, ErrorState, LoadingState } from "@/components/states";
import { RunStatusPanel } from "@/components/workflow/run-status";
import { Button, buttonVariants } from "@/components/ui/button";
import { Label } from "@/components/ui/label";
import { hasResult, setRunParam, useDiscoveryResult } from "@/features/atlas/api";
import { PageHeader } from "@/features/atlas/page-header";
import { useStudies } from "@/features/audience/api";
import { AudienceWorkspace } from "@/features/audience/audience-workspace";
import { useProject } from "@/features/project/project-context";
import { sectionHref } from "@/features/project/workflow";
import { isTerminal, useLatestRun, useRun } from "@/lib/api/runs";
import type { Campaign, Project } from "@/lib/api/types";
import { formatDateTime, shortId } from "@/lib/format";

import { usePopulation, usePopulationResult, usePopulationStudies, useInterviews, useRunControl, useStartPopulationStudy, type InterviewFilters } from "./api";
import { AudienceLibrary, flag } from "./audience-library";
import { GroupPanel } from "./group-panel";
import { PopulationForm } from "./population-form";
import { PopulationResults, type ReportTab } from "./population-results";
import { SelectedAudience } from "./selected-audience";

const SELECT =
  "h-9 w-full rounded-lg border border-input bg-surface px-2.5 text-sm outline-none focus-visible:border-ring";

/** /audience: population studies first; the quick rehearsal stays one click away (and opens for rehearsal links). */
export function AudienceIntelligence() {
  const { project, campaign } = useProject();
  const params = useSearchParams();
  const runParam = params.get("run");
  const linked = useRun(runParam);
  if (params.get("mode") === "quick" || linked.data?.run_type === "campaign_rehearsal") return <AudienceWorkspace />;
  if (runParam && linked.isPending) return <LoadingState label="Opening the linked run…" />;
  if (!campaign)
    return (
      <EmptyState
        title="No campaign yet"
        description="A population study interviews synthetic participants about a campaign. Add a campaign to this project first."
      />
    );
  return <PopulationView key={campaign.id} project={project} campaign={campaign} runParam={runParam} />;
}

function PopulationView({ project, campaign, runParam }: { project: Project; campaign: Campaign; runParam: string | null }) {
  const { campaigns, setCampaignId } = useProject();
  const params = useSearchParams();
  const studiesQuery = useStudies(project.id, campaign.id);
  const study = studiesQuery.data?.items[0] ?? null;
  const summariesQuery = usePopulationStudies(study?.id);
  const summaries = summariesQuery.data?.items ?? [];

  const latestQuery = useLatestRun(project.id, { runType: "population_study", campaignId: campaign.id });
  const latest = latestQuery.data?.run_type === "population_study" ? latestQuery.data : null;
  const [startedRunId, setStartedRunId] = useState<string | null>(null);
  const runId = startedRunId ?? runParam ?? latest?.id ?? null;
  const runQuery = useRun(runId);
  const run = runQuery.data;
  const active = Boolean(run && !isTerminal(run.status));
  const resultQuery = usePopulationResult(runId, active, run?.status);
  const result = resultQuery.data;
  const population = usePopulation(result?.population_id).data;

  // Grounding: the discovery passed from Atlas, else the latest completed discovery for this campaign.
  const discoveryParam = params.get("discovery");
  const latestDiscovery = useLatestRun(discoveryParam ? null : project.id, { runType: "market_discovery", campaignId: campaign.id, status: "completed" });
  const discoveryRunId = discoveryParam ?? (latestDiscovery.data?.run_type === "market_discovery" ? latestDiscovery.data.id : null);
  const discoveryQuery = useDiscoveryResult(project.id, discoveryRunId);
  const discovery = hasResult(discoveryQuery.data) ? discoveryQuery.data : undefined;

  const start = useStartPopulationStudy(project.id);
  const control = useRunControl(project.id);
  const [setupOpen, setSetupOpen] = useState(false);
  const [selectedId, setSelectedId] = useState<string | null>(null);
  const [compareIds, setCompareIds] = useState<string[]>([]);
  const [tab, setTab] = useState<ReportTab>("overview");
  const [interviewFilters, setInterviewFilters] = useState<InterviewFilters>({});
  const [region, setRegion] = useState<string>("");
  const [quoteRegion, setQuoteRegion] = useState<string | null>(null);
  const reportRef = useRef<HTMLDivElement>(null);
  const topRef = useRef<HTMLDivElement>(null);

  const groups = (population?.groups ?? []).filter((g) => !region || g.region.country_code === region);
  const selected = groups.find((g) => g.id === selectedId) ?? groups[0];
  const regions = population?.regions ?? [];
  const activeQuoteRegion = quoteRegion ?? regions[0]?.country_code ?? null;
  const quotes = useInterviews(result && hasResult(result) ? result.id : null, { region: activeQuoteRegion ?? undefined, group_id: selected?.id }, 0);
  const groupLabel = new Map((population?.groups ?? []).map((g) => [g.id, g.label]));

  function showRun(id: string) {
    setStartedRunId(id);
    setRunParam(id);
  }
  function selectGroup(id: string) {
    setSelectedId(id);
    topRef.current?.scrollIntoView({ block: "start", behavior: "smooth" });
  }
  function openReport(next: ReportTab, filters?: InterviewFilters) {
    if (filters) setInterviewFilters(filters);
    setTab(next);
    requestAnimationFrame(() => reportRef.current?.scrollIntoView({ block: "start" }));
  }

  if (studiesQuery.isPending || latestQuery.isPending) return <LoadingState label="Loading audience studies…" />;
  const showSetup = setupOpen || (!runId && Boolean(study));
  const perRegion = new Map<string, number>();
  for (const g of population?.groups ?? []) perRegion.set(g.region.country_code, (perRegion.get(g.region.country_code) ?? 0) + g.participant_count);

  return (
    <div className="grid min-w-0 grid-cols-[minmax(0,1fr)] gap-6">
      <PageHeader
        feature="audience"
        title="Audience Intelligence"
        description="Interview synthetic audience groups grounded in Qloo signals, compare how they read your campaign, and see what needs real-world validation."
        actions={
          <>
            <Link href="?mode=quick" className={buttonVariants({ variant: "outline" })}>
              Quick rehearsal
            </Link>
            {study && (
              <Button onClick={() => setSetupOpen(true)}>
                New population study <ArrowRightIcon aria-hidden data-icon="inline-end" />
              </Button>
            )}
          </>
        }
      />

      <div className="grid min-w-0 grid-cols-[minmax(0,1fr)] gap-3 rounded-2xl border bg-card p-4 shadow-card sm:grid-cols-2 lg:grid-cols-4">
        <div className="grid gap-1">
          <Label htmlFor="ai-campaign" className="text-xs text-ink-secondary">
            Campaign context
          </Label>
          <select id="ai-campaign" className={SELECT} value={campaign.id} onChange={(e) => setCampaignId(e.target.value)}>
            {campaigns.map((c) => (
              <option key={c.id} value={c.id}>
                {c.name}
              </option>
            ))}
          </select>
        </div>
        <div className="grid gap-1">
          <Label htmlFor="ai-study" className="text-xs text-ink-secondary">
            Population study
          </Label>
          <select id="ai-study" className={SELECT} value={runId ?? ""} disabled={summaries.length === 0} onChange={(e) => showRun(e.target.value)}>
            {summaries.length === 0 && <option value="">None yet</option>}
            {summaries.map((s) => (
              <option key={s.id} value={s.id}>
                {formatDateTime(s.created_at)} · {s.requested_participants} participants{s.status !== "completed" ? ` (${s.status})` : ""}
              </option>
            ))}
          </select>
        </div>
        <div className="grid gap-1">
          <Label htmlFor="ai-region" className="text-xs text-ink-secondary">
            Region
          </Label>
          <select id="ai-region" className={SELECT} value={region} disabled={regions.length < 2} onChange={(e) => setRegion(e.target.value)}>
            <option value="">All regions</option>
            {regions.map((m) => (
              <option key={m.country_code} value={m.country_code}>
                {m.display_name}
              </option>
            ))}
          </select>
        </div>
        <div className="grid content-end">
          <p className="text-xs text-ink-secondary">
            {study ? `Study: ${study.name} · ${study.market.display_name}` : "No study configured for this campaign."}
          </p>
        </div>
      </div>

      {/* A failed lookup is shown, never treated as "none yet". */}
      {latestQuery.isError && <ErrorState error={latestQuery.error} onRetry={() => latestQuery.refetch()} />}
      {summariesQuery.isError && <ErrorState error={summariesQuery.error} onRetry={() => summariesQuery.refetch()} />}
      {studiesQuery.isError && <ErrorState error={studiesQuery.error} onRetry={() => studiesQuery.refetch()} />}

      {!study && !studiesQuery.isError && (
        <EmptyState
          title="No study for this campaign"
          description="Population studies use a study's research questions and dimensions. Create one with the quick rehearsal first."
          action={
            <Link href="?mode=quick" className={buttonVariants({ variant: "outline" })}>
              Open quick rehearsal
            </Link>
          }
        />
      )}

      {study && showSetup && (
        <section aria-labelledby="setup-h" className="grid min-w-0 grid-cols-[minmax(0,1fr)] gap-4 rounded-2xl border bg-card p-4 shadow-card md:p-6">
          <div className="flex flex-wrap items-center justify-between gap-2">
            <h2 id="setup-h" className="font-serif text-xl">
              New population study
            </h2>
            {runId && (
              <Button variant="ghost" size="sm" onClick={() => setSetupOpen(false)}>
                Cancel
              </Button>
            )}
          </div>
          <PopulationForm
            project={project}
            campaign={campaign}
            study={study}
            discovery={discovery}
            busy={active}
            pending={start.isPending}
            error={start.error}
            onSubmit={(body) =>
              start.mutate(
                { studyId: study.id, body },
                {
                  onSuccess: (accepted) => {
                    showRun(accepted.run_id);
                    setSetupOpen(false);
                  },
                },
              )
            }
          />
        </section>
      )}

      {runQuery.isError && <ErrorState error={runQuery.error} onRetry={() => runQuery.refetch()} />}
      {run && !hasResult(run) && (
        <div className="grid gap-3">
          <RunStatusPanel run={run} operation="Population study" />
          {result && (
            <p className="text-sm tabular-nums">
              {result.completed_interviews} of {result.requested_participants} interviews completed
              {result.failed_interviews > 0 && ` · ${result.failed_interviews} failed`}
            </p>
          )}
          <div className="flex flex-wrap gap-2">
            {active && (
              <Button variant="outline" disabled={control.cancel.isPending} onClick={() => control.cancel.mutate(run.id)}>
                Cancel run
              </Button>
            )}
            {run.status === "failed" && (
              <Button disabled={control.resume.isPending} onClick={() => control.resume.mutate(run.id, { onSuccess: (a) => showRun(a.run_id) })}>
                Resume from last checkpoint
              </Button>
            )}
          </div>
          {active && <p className="text-xs text-ink-secondary">Cancelling stops at the next checkpoint and keeps the interviews already saved.</p>}
          {Boolean(control.cancel.error) && <ErrorState error={control.cancel.error} />}
          {Boolean(control.resume.error) && <ErrorState error={control.resume.error} />}
        </div>
      )}

      {resultQuery.isError && <ErrorState error={resultQuery.error} onRetry={() => resultQuery.refetch()} />}
      {result && hasResult(result) && (
        <>
          <aside aria-label="Simulation disclosure" className="flex items-start gap-3 rounded-2xl border border-audience/30 bg-audience-soft px-4 py-3 text-sm">
            <BotIcon aria-hidden className="mt-0.5 size-4 shrink-0" />
            <p>
              <span className="font-semibold">Synthetic participants, not real people. </span>
              {result.disclosure.description} {result.disclosure.shared_model_note}
            </p>
          </aside>

          <div ref={topRef} className="grid min-w-0 grid-cols-[minmax(0,1fr)] scroll-mt-6 gap-6 xl:grid-cols-[minmax(0,22rem)_minmax(0,1fr)_minmax(0,24rem)]">
            <AudienceLibrary
              groups={groups}
              results={result.by_group}
              selectedId={selected?.id ?? null}
              compareIds={compareIds}
              onSelect={setSelectedId}
              onCompare={(id) => setCompareIds((c) => (c.includes(id) ? c.filter((x) => x !== id) : [...c, id].slice(-2)))}
            />

            <div className="grid min-w-0 grid-cols-[minmax(0,1fr)] content-start gap-6">
              <section aria-labelledby="dist-h" className="grid min-w-0 grid-cols-[minmax(0,1fr)] gap-3 rounded-2xl border bg-card p-4 shadow-card">
                <div>
                  <h2 id="dist-h" className="font-serif text-xl">
                    Audience distribution
                  </h2>
                  <p className="text-sm text-ink-secondary">Synthetic participants per region, as configured for this study.</p>
                </div>
                <WorldMap
                  data={[...perRegion].map(([country_code, value]) => ({ country_code, value }))}
                  valueLabel="synthetic participants"
                  tone="text-audience"
                />
                <ul className="flex flex-wrap gap-x-4 gap-y-1 text-xs tabular-nums">
                  {[...perRegion].map(([code, n]) => (
                    <li key={code}>
                      {flag(code)} {regions.find((m) => m.country_code === code)?.display_name ?? code}: {n}
                    </li>
                  ))}
                </ul>
              </section>

              <section aria-labelledby="quotes-h" className="grid min-w-0 grid-cols-[minmax(0,1fr)] gap-3 rounded-2xl border bg-card p-4 shadow-card">
                <div>
                  <h2 id="quotes-h" className="font-serif text-xl">
                    Audience interviews <span className="font-sans text-base text-ink-secondary">(simulated)</span>
                  </h2>
                  <p className="text-sm text-ink-secondary">
                    AI-generated answers from {selected ? `“${selected.label}”` : "the selected group"}, grounded in its cited Qloo signals.
                  </p>
                </div>
                {regions.length > 1 && (
                  <div role="group" aria-label="Interview region" className="flex flex-wrap gap-2">
                    {regions.map((m) => {
                      const n = result.by_region.find((r) => r.region.country_code === m.country_code)?.distribution.denominator ?? 0;
                      return (
                        <Button
                          key={m.country_code}
                          variant={m.country_code === activeQuoteRegion ? "secondary" : "outline"}
                          size="sm"
                          aria-pressed={m.country_code === activeQuoteRegion}
                          onClick={() => setQuoteRegion(m.country_code)}
                        >
                          {flag(m.country_code)} {m.display_name} <span className="text-ink-secondary tabular-nums">{n}</span>
                        </Button>
                      );
                    })}
                  </div>
                )}
                {quotes.isError ? (
                  <ErrorState error={quotes.error} onRetry={() => quotes.refetch()} />
                ) : quotes.isPending ? (
                  <LoadingState label="Loading interviews…" />
                ) : (
                  <ul className="grid gap-3">
                    {quotes.data.items
                      .filter((iv) => iv.status === "completed")
                      .slice(0, 3)
                      .map((iv) => {
                        const first = iv.answers.find((a) => a.question_id === "first_impression") ?? iv.answers[0];
                        return (
                          <li key={iv.id} className="grid gap-1.5 border-b pb-3 last:border-0">
                            <p className="text-xs font-medium">
                              Participant <span className="font-mono">{shortId(iv.participant_id)}</span> · {groupLabel.get(iv.group_id)}
                            </p>
                            {first && <blockquote className="text-sm">“{first.answer}”</blockquote>}
                            {iv.themes.length > 0 && (
                              <ul className="flex flex-wrap gap-1">
                                {iv.themes.slice(0, 3).map((t) => (
                                  <li key={t} className="rounded-md border px-1.5 py-0.5 text-[11px]">
                                    {t}
                                  </li>
                                ))}
                              </ul>
                            )}
                          </li>
                        );
                      })}
                  </ul>
                )}
                <Button variant="outline" onClick={() => openReport("interviews", selected ? { group_id: selected.id } : {})}>
                  View all interviews <ArrowRightIcon aria-hidden data-icon="inline-end" />
                </Button>
              </section>
            </div>

            {selected && population ? (
              <SelectedAudience
                group={selected}
                result={result.by_group.find((r) => r.group_id === selected.id)}
                allResults={result.by_group}
                evidence={result.evidence}
                populationId={population.id}
                studyId={result.id}
                arenaHref={sectionHref(project.id, "arena", campaign.id)}
              />
            ) : (
              <LoadingState label="Loading the population…" />
            )}
          </div>

          {population && compareIds.length === 2 && (
            <GroupPanel
              groups={compareIds.map((id) => population.groups.find((g) => g.id === id)).filter((g) => g !== undefined)}
              results={result.by_group}
              evidence={result.evidence}
              populationId={population.id}
              onClose={() => setCompareIds([])}
              onOpenInterviews={(id) => openReport("interviews", { group_id: id })}
            />
          )}

          <div ref={reportRef} className="scroll-mt-6">
            <PopulationResults
              projectId={project.id}
              result={result}
              population={population}
              tab={tab}
              onTab={setTab}
              interviewFilters={interviewFilters}
              onInterviewFilters={setInterviewFilters}
              onSelectGroup={selectGroup}
            />
          </div>
        </>
      )}
    </div>
  );
}

