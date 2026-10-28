"use client";

import { useState, type ReactNode } from "react";

import { ClaimBadge } from "@/components/evidence/badges";
import { LimitationList } from "@/components/evidence/limitation-list";
import { Button } from "@/components/ui/button";
import { Tabs, TabsContent, TabsList, TabsTrigger } from "@/components/ui/tabs";
import { RunProvenance } from "@/features/atlas/run-provenance";
import { ReactionMap } from "@/features/social/reaction-map";
import { SocialSimulationPanel } from "@/features/social/social-simulation";
import type { Population, PopulationStudyResult, ThemeCount } from "@/lib/api/types";

import type { InterviewFilters, LandscapeFilters } from "./api";
import { flag } from "./audience-library";
import { InterviewBrowser, InterviewCard, useExampleInterviews } from "./interviews";
import { Landscape } from "./landscape";
import { ReactionBar } from "./reaction-bars";

export type ReportTab = "overview" | "regions" | "reaction-graph" | "landscape" | "interviews" | "social" | "recommendations";

function Block({ title, aside, children }: { title: string; aside?: ReactNode; children: ReactNode }) {
  return (
    <section className="grid min-w-0 gap-3">
      <div className="flex flex-wrap items-baseline gap-x-3 gap-y-1">
        <h3 className="font-serif text-lg">{title}</h3>
        {aside}
      </div>
      {children}
    </section>
  );
}

function ThemeList({ title, items, studyId, population }: { title: string; items: ThemeCount[]; studyId: string; population?: Population }) {
  const [open, setOpen] = useState<string | null>(null);
  const opened = items.find((t) => t.label === open);
  const examples = useExampleInterviews(studyId, opened?.example_interview_ids ?? [], undefined, Boolean(opened));
  const groups = new Map((population?.groups ?? []).map((g) => [g.id, g]));
  return (
    <div className="grid min-w-0 grid-cols-[minmax(0,1fr)] content-start gap-2">
      <h4 className="text-sm font-semibold">{title}</h4>
      {items.length === 0 ? (
        <p className="text-sm text-ink-secondary">None recorded.</p>
      ) : (
        <ul className="grid gap-2">
          {items.map((t) => (
            <li key={t.label} className="grid gap-1.5">
              <div className="flex flex-wrap items-baseline justify-between gap-2">
                <span className="text-sm">{t.label}</span>
                <span className="text-xs text-ink-secondary tabular-nums">
                  {t.count} · {Math.round(t.share * 100)}%
                </span>
              </div>
              {t.example_interview_ids.length > 0 && (
                <Button variant="ghost" size="xs" className="w-fit" aria-expanded={open === t.label} onClick={() => setOpen(open === t.label ? null : t.label)}>
                  {open === t.label ? "Hide examples" : `Show ${t.example_interview_ids.length} example interviews`}
                </Button>
              )}
              {open === t.label &&
                (examples.isPending ? (
                  <p className="text-xs text-ink-secondary">Loading examples…</p>
                ) : examples.isError ? (
                  <p className="text-xs text-danger">The example interviews could not be loaded.</p>
                ) : (
                  examples.data.map((iv) => <InterviewCard key={iv.id} interview={iv} group={groups.get(iv.group_id)} level={4} />)
                ))}
            </li>
          ))}
        </ul>
      )}
    </div>
  );
}

/** The study report: every tally is deterministic over stored interviews; model text is labeled interpretation. */
export function PopulationResults({
  projectId,
  result,
  population,
  tab,
  onTab,
  interviewFilters,
  onInterviewFilters,
  onSelectGroup,
}: {
  projectId: string;
  result: PopulationStudyResult;
  population?: Population;
  tab: ReportTab;
  onTab: (tab: ReportTab) => void;
  interviewFilters: InterviewFilters;
  onInterviewFilters: (next: InterviewFilters) => void;
  onSelectGroup: (groupId: string) => void;
}) {
  const [landscapeFilters, setLandscapeFilters] = useState<LandscapeFilters>({});
  const groups = population?.groups ?? [];
  const regions = population?.regions ?? [];
  const openInterviews = (groupId: string) => {
    onInterviewFilters({ group_id: groupId });
    onTab("interviews");
  };

  return (
    <section aria-labelledby="report-h" className="grid min-w-0 grid-cols-[minmax(0,1fr)] gap-4 rounded-2xl border bg-card p-4 shadow-card md:p-6">
      <div className="flex flex-wrap items-baseline justify-between gap-2">
        <h2 id="report-h" className="font-serif text-2xl">
          Study report
        </h2>
        <p className="text-sm text-ink-secondary tabular-nums">
          {result.completed_interviews} of {result.requested_participants} interviews completed
          {result.failed_interviews > 0 && ` · ${result.failed_interviews} failed and excluded from every tally`}
        </p>
      </div>

      <Tabs value={tab} onValueChange={(value) => onTab(value as ReportTab)}>
        <div className="overflow-x-auto">
          <TabsList>
            <TabsTrigger value="overview">Overview</TabsTrigger>
            <TabsTrigger value="regions">Regional analysis</TabsTrigger>
            <TabsTrigger value="reaction-graph">Reaction graph</TabsTrigger>
            <TabsTrigger value="landscape">Landscape</TabsTrigger>
            <TabsTrigger value="interviews">Interviews</TabsTrigger>
            <TabsTrigger value="social">Social simulation</TabsTrigger>
            <TabsTrigger value="recommendations">Recommendations</TabsTrigger>
          </TabsList>
        </div>

        <TabsContent value="overview" className="grid min-w-0 grid-cols-[minmax(0,1fr)] gap-8 pt-4">
          <Block title="Reactions">
            <ReactionBar d={result.overall} />
          </Block>
          <Block title="By group">
            <ul className="grid gap-3">
              {result.by_group.map((g) => (
                <li key={g.group_id} className="grid min-w-0 grid-cols-[minmax(0,1fr)] gap-2 border-b pb-3 last:border-0 sm:grid-cols-[minmax(0,14rem)_minmax(0,1fr)] sm:gap-6">
                  <div className="grid min-w-0 grid-cols-[minmax(0,1fr)] content-start gap-1">
                    <button type="button" className="w-fit text-left text-sm font-semibold underline-offset-4 hover:underline" onClick={() => onSelectGroup(g.group_id)}>
                      {g.label}
                    </button>
                    <span className="text-xs text-ink-secondary">
                      {flag(g.region.country_code)} {g.region.display_name}
                    </span>
                    <Button variant="link" size="xs" className="h-auto w-fit px-0" onClick={() => openInterviews(g.group_id)}>
                      Open interviews
                    </Button>
                  </div>
                  <ReactionBar d={g.distribution} compact />
                </li>
              ))}
            </ul>
          </Block>
          <Block title="What came up" aside={<span className="text-xs text-ink-secondary">Counts tally labels stored on each interview.</span>}>
            <div className="grid min-w-0 grid-cols-[minmax(0,1fr)] gap-8 lg:grid-cols-3">
              <ThemeList title="Themes" items={result.themes} studyId={result.id} population={population} />
              <ThemeList title="Misunderstandings" items={result.misunderstandings} studyId={result.id} population={population} />
              <ThemeList title="Concerns" items={result.concerns} studyId={result.id} population={population} />
            </div>
          </Block>
          {result.group_differences.length > 0 && (
            <Block title="Group differences" aside={<ClaimBadge claim="interpreted" />}>
              <p className="text-xs text-ink-secondary">A model&apos;s reading of the tallies, not a measured difference between real groups.</p>
              <ul className="list-disc space-y-1 pl-5 text-sm">
                {result.group_differences.map((d) => (
                  <li key={d}>{d}</li>
                ))}
              </ul>
            </Block>
          )}
        </TabsContent>

        <TabsContent value="regions" className="pt-4">
          {result.by_region.length === 0 ? (
            <p className="text-sm text-ink-secondary">No regional tallies yet.</p>
          ) : (
            <ul className="grid min-w-0 grid-cols-[minmax(0,1fr)] gap-4 sm:grid-cols-2">
              {result.by_region.map((r) => (
                <li key={r.region.country_code} className="grid gap-1.5">
                  <h3 className="text-sm font-semibold">
                    {flag(r.region.country_code)} {r.region.display_name}
                  </h3>
                  <ReactionBar d={r.distribution} compact />
                </li>
              ))}
            </ul>
          )}
        </TabsContent>

        <TabsContent value="reaction-graph" className="pt-4">
          <ReactionMap projectId={projectId} result={result} />
        </TabsContent>

        <TabsContent value="landscape" className="pt-4">
          {population ? (
            <Landscape
              populationId={population.id}
              groups={groups}
              regions={regions}
              filters={landscapeFilters}
              onFilters={setLandscapeFilters}
              selected={[]}
              onSelect={(groupId) => onSelectGroup(groupId)}
            />
          ) : (
            <p className="text-sm text-ink-secondary">The population is still loading.</p>
          )}
        </TabsContent>

        <TabsContent value="interviews" className="pt-4">
          <InterviewBrowser
            key={JSON.stringify(interviewFilters)}
            studyId={result.id}
            groups={groups}
            regions={regions}
            filters={interviewFilters}
            onFilters={onInterviewFilters}
          />
        </TabsContent>

        <TabsContent value="social" className="pt-4">
          <SocialSimulationPanel projectId={projectId} result={result} />
        </TabsContent>

        <TabsContent value="recommendations" className="grid min-w-0 grid-cols-[minmax(0,1fr)] gap-8 pt-4">
          <Block title="Next actions" aside={<ClaimBadge claim="interpreted" />}>
            {result.next_actions.length === 0 ? (
              <p className="text-sm text-ink-secondary">None suggested.</p>
            ) : (
              <ul className="list-disc space-y-1 pl-5 text-sm">
                {result.next_actions.map((a) => (
                  <li key={a}>{a}</li>
                ))}
              </ul>
            )}
          </Block>
          <Block title="Evidence gaps">
            {result.evidence_gaps.length === 0 ? (
              <p className="text-sm text-ink-secondary">No gaps were reported.</p>
            ) : (
              <ul className="list-disc space-y-1 pl-5 text-sm">
                {result.evidence_gaps.map((g) => (
                  <li key={g}>{g}</li>
                ))}
              </ul>
            )}
          </Block>
          <LimitationList title="Study limitations" items={result.limitations} />
          <RunProvenance metadata={result.run_metadata} />
        </TabsContent>
      </Tabs>
    </section>
  );
}
