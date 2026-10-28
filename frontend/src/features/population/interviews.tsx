"use client";

import { useQuery } from "@tanstack/react-query";
import { ChevronDownIcon } from "lucide-react";
import { useState } from "react";

import { SyntheticBadge } from "@/components/evidence/badges";
import { ErrorState, LoadingState } from "@/components/states";
import { Button } from "@/components/ui/button";
import { Collapsible, CollapsibleContent, CollapsibleTrigger } from "@/components/ui/collapsible";
import { Label } from "@/components/ui/label";
import { api } from "@/lib/api/client";
import { unwrap } from "@/lib/api/errors";
import type { Interview, Market, PopulationGroup } from "@/lib/api/types";
import { humanize, shortId } from "@/lib/format";
import { cn } from "@/lib/utils";

import { PAGE, useInterviews, type InterviewFilters } from "./api";
import { REACTIONS, REACTION_LABEL } from "./reaction-bars";

const SELECT =
  "h-8 rounded-lg border border-input bg-surface px-2 text-sm outline-none focus-visible:border-ring focus-visible:ring-3 focus-visible:ring-ring/50";

export function InterviewCard({
  interview: iv,
  group,
  level = 3,
}: {
  interview: Interview;
  group?: PopulationGroup;
  /** Heading level that fits where the card is placed. */
  level?: 3 | 4;
}) {
  const Title = level === 4 ? "h4" : "h3";
  return (
    <article className="grid min-w-0 grid-cols-[minmax(0,1fr)] content-start gap-2 rounded-lg border bg-card p-3">
      <header className="flex flex-wrap items-baseline gap-x-2 gap-y-1">
        <Title className="text-sm font-semibold">{group?.label ?? "Group"}</Title>
        <span className="text-xs text-ink-secondary">{iv.region.display_name}</span>
        <span className="font-mono text-[11px] text-ink-secondary">{shortId(iv.participant_id)}</span>
        {iv.status === "failed" ? (
          <span className="text-xs font-medium text-danger">Interview failed; not counted</span>
        ) : (
          <>
            {iv.reaction && <span className="text-xs font-medium">{REACTION_LABEL[iv.reaction]}</span>}
            {iv.comprehension && <span className="text-xs text-ink-secondary">· {humanize(iv.comprehension)}</span>}
          </>
        )}
      </header>
      <SyntheticBadge />
      {iv.misunderstanding && (
        <p className="text-sm">
          <span className="text-ink-secondary">Misunderstanding: </span>
          {iv.misunderstanding}
        </p>
      )}
      {iv.themes.length > 0 && (
        <ul aria-label="Themes" className="flex flex-wrap gap-1">
          {iv.themes.map((t) => (
            <li key={t} className="rounded-sm border px-1.5 py-0.5 text-[11px]">
              {t}
            </li>
          ))}
        </ul>
      )}
      {iv.concerns.length > 0 && (
        <p className="text-xs">
          <span className="text-ink-secondary">Concerns: </span>
          {iv.concerns.join("; ")}
        </p>
      )}
      {iv.answers.length > 0 && (
        <Collapsible>
          <CollapsibleTrigger className="group flex items-center gap-1 rounded-sm text-xs font-medium outline-none focus-visible:ring-3 focus-visible:ring-ring/50">
            <ChevronDownIcon aria-hidden className="size-3.5 transition-transform group-data-[panel-open]:rotate-180" />
            Answers ({iv.answers.length})
          </CollapsibleTrigger>
          <CollapsibleContent>
            <dl className="mt-2 grid gap-2 text-sm">
              {iv.answers.map((a) => (
                <div key={a.question_id}>
                  <dt className="text-xs text-ink-secondary">{a.question}</dt>
                  <dd>{a.answer}</dd>
                </div>
              ))}
            </dl>
          </CollapsibleContent>
        </Collapsible>
      )}
    </article>
  );
}

/**
 * Example interviews by id. The API lists interviews only by filter, so this pages through (100 at a time) until every
 * id is found; it runs only when someone asks for examples.
 */
export function useExampleInterviews(studyId: string, ids: string[], groupId: string | undefined, enabled: boolean) {
  return useQuery({
    queryKey: ["interview-examples", studyId, groupId, ids],
    enabled: enabled && ids.length > 0,
    queryFn: async () => {
      const wanted = new Set(ids);
      const found: Interview[] = [];
      for (let offset = 0; wanted.size > 0; offset += 100) {
        const page = await unwrap(
          api.GET("/api/v1/population-studies/{population_study_id}/interviews", {
            params: { path: { population_study_id: studyId }, query: { group_id: groupId, limit: 100, offset } },
          }),
        );
        for (const iv of page.items) if (wanted.delete(iv.id)) found.push(iv);
        if (offset + 100 >= page.total) break;
      }
      return found;
    },
  });
}

export function InterviewBrowser({
  studyId,
  groups,
  regions,
  filters,
  onFilters,
}: {
  studyId: string;
  groups: PopulationGroup[];
  regions: Market[];
  filters: InterviewFilters;
  onFilters: (next: InterviewFilters) => void;
}) {
  const [offset, setOffset] = useState(0);
  const query = useInterviews(studyId, filters, offset);
  const set = (patch: InterviewFilters) => {
    setOffset(0);
    onFilters({ ...filters, ...patch });
  };
  const byId = new Map(groups.map((g) => [g.id, g]));
  const total = query.data?.total ?? 0;

  return (
    <div className="grid gap-3">
      <div className="flex flex-wrap items-end gap-x-4 gap-y-2">
        <div className="grid gap-1">
          <Label htmlFor="iv-group" className="text-xs">
            Group
          </Label>
          <select id="iv-group" className={SELECT} value={filters.group_id ?? ""} onChange={(e) => set({ group_id: e.target.value || undefined })}>
            <option value="">All groups</option>
            {groups.map((g) => (
              <option key={g.id} value={g.id}>
                {g.label}
              </option>
            ))}
          </select>
        </div>
        <div className="grid gap-1">
          <Label htmlFor="iv-region" className="text-xs">
            Region
          </Label>
          <select id="iv-region" className={SELECT} value={filters.region ?? ""} onChange={(e) => set({ region: e.target.value || undefined })}>
            <option value="">All regions</option>
            {regions.map((m) => (
              <option key={m.country_code} value={m.country_code}>
                {m.display_name}
              </option>
            ))}
          </select>
        </div>
        <div className="grid gap-1">
          <Label htmlFor="iv-reaction" className="text-xs">
            Reaction
          </Label>
          <select
            id="iv-reaction"
            className={SELECT}
            value={filters.reaction ?? ""}
            onChange={(e) => set({ reaction: (e.target.value || undefined) as InterviewFilters["reaction"] })}
          >
            <option value="">All reactions</option>
            {REACTIONS.map((r) => (
              <option key={r} value={r}>
                {REACTION_LABEL[r]}
              </option>
            ))}
          </select>
        </div>
        <p aria-live="polite" className="pb-1.5 text-xs text-ink-secondary tabular-nums">
          {query.data ? (total === 0 ? "No interviews match" : `${offset + 1}–${Math.min(offset + PAGE, total)} of ${total}`) : ""}
        </p>
      </div>

      {query.isError ? (
        <ErrorState error={query.error} onRetry={() => query.refetch()} />
      ) : query.isPending ? (
        <LoadingState label="Loading interviews…" />
      ) : (
        <ul className={cn("@container grid gap-3 @3xl:grid-cols-2", query.isPlaceholderData && "opacity-60")}>
          {query.data.items.map((iv) => (
            <li key={iv.id}>
              <InterviewCard interview={iv} group={byId.get(iv.group_id)} />
            </li>
          ))}
        </ul>
      )}

      {total > PAGE && (
        <div className="flex items-center gap-2">
          <Button variant="outline" size="sm" disabled={offset === 0} onClick={() => setOffset(Math.max(0, offset - PAGE))}>
            Previous
          </Button>
          <Button variant="outline" size="sm" disabled={offset + PAGE >= total} onClick={() => setOffset(offset + PAGE)}>
            Next
          </Button>
        </div>
      )}
    </div>
  );
}
