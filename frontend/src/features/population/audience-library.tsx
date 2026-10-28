"use client";

import { SearchIcon, UsersIcon } from "lucide-react";
import { useState } from "react";

import { Checkbox } from "@/components/ui/checkbox";
import { Input } from "@/components/ui/input";
import type { GroupResult, PopulationGroup } from "@/lib/api/types";
import { cn } from "@/lib/utils";

import { REACTIONS, REACTION_LABEL } from "./reaction-bars";

/** Regional-indicator flag for an ISO 3166-1 alpha-2 code (renders as letters where the OS has no flag glyphs). */
export const flag = (code: string) => String.fromCodePoint(...[...code.toUpperCase()].map((c) => 0x1f1e6 + c.charCodeAt(0) - 65));

/** "Mostly positive (45%)": the largest stored tally, never a relevance score. */
export function leadingReaction(result: GroupResult | undefined) {
  const d = result?.distribution;
  if (!d || d.denominator === 0) return null;
  const top = REACTIONS.reduce((a, b) => ((d.counts[b] ?? 0) > (d.counts[a] ?? 0) ? b : a));
  return `Most often ${REACTION_LABEL[top].toLowerCase()} (${Math.round((d.rates[top] ?? 0) * 100)}%)`;
}

// tinted placeholder until the imagery library (`pickImagery`) lands; then render its photo with alt="".
export function GroupImage({ className }: { className?: string }) {
  return (
    <div aria-hidden className={cn("flex items-center justify-center rounded-lg bg-audience-soft text-audience", className)}>
      <UsersIcon className="size-6" />
    </div>
  );
}

export function AudienceLibrary({
  groups,
  results,
  selectedId,
  compareIds,
  onSelect,
  onCompare,
}: {
  groups: PopulationGroup[];
  results: GroupResult[];
  selectedId: string | null;
  compareIds: string[];
  onSelect: (id: string) => void;
  onCompare: (id: string) => void;
}) {
  const [q, setQ] = useState("");
  const [tab, setTab] = useState<"all" | "compare">("all");
  const needle = q.trim().toLowerCase();
  const shown = groups.filter(
    (g) =>
      (tab === "all" || compareIds.includes(g.id)) &&
      (!needle || g.label.toLowerCase().includes(needle) || g.interests.some((i) => i.name.toLowerCase().includes(needle))),
  );
  return (
    <section aria-labelledby="lib-h" className="grid min-w-0 grid-cols-[minmax(0,1fr)] content-start gap-3 rounded-2xl border bg-card p-4 shadow-card">
      <div>
        <h2 id="lib-h" className="font-serif text-xl">
          Audience library <span className="font-sans text-base text-ink-secondary tabular-nums">({groups.length})</span>
        </h2>
        <p className="text-sm text-ink-secondary">Synthetic audience groups grounded in Qloo signals.</p>
      </div>
      <div className="relative">
        <SearchIcon aria-hidden className="absolute top-2 left-2.5 size-4 text-ink-secondary" />
        <Input aria-label="Search audience groups" value={q} onChange={(e) => setQ(e.target.value)} placeholder="Search groups or interests" className="bg-surface pl-8" />
      </div>
      <div role="group" aria-label="Library view" className="flex gap-4 border-b text-sm">
        {(
          [
            ["all", "All groups"],
            ["compare", `Comparison (${compareIds.length})`],
          ] as const
        ).map(([key, label]) => (
          <button
            key={key}
            aria-pressed={tab === key}
            className={cn("-mb-px border-b-2 px-1 pb-2", tab === key ? "border-primary font-medium text-primary" : "border-transparent text-ink-secondary")}
            onClick={() => setTab(key)}
          >
            {label}
          </button>
        ))}
      </div>
      {shown.length === 0 ? (
        <p className="text-sm text-ink-secondary">{tab === "compare" ? "Tick up to two groups to compare them." : "No groups match."}</p>
      ) : (
        <ul className="grid gap-2">
          {shown.map((g) => {
            const lead = leadingReaction(results.find((r) => r.group_id === g.id));
            const active = g.id === selectedId;
            return (
              <li
                key={g.id}
                className={cn("grid grid-cols-[auto_minmax(0,1fr)] gap-3 rounded-xl border p-2.5", active ? "border-primary bg-accent" : "bg-surface")}
              >
                <div className="flex items-start gap-2">
                  <Checkbox
                    aria-label={`Compare ${g.label}`}
                    checked={compareIds.includes(g.id)}
                    disabled={!compareIds.includes(g.id) && compareIds.length >= 2}
                    onCheckedChange={() => onCompare(g.id)}
                  />
                  <GroupImage className="size-16" />
                </div>
                <div className="grid min-w-0 grid-cols-[minmax(0,1fr)] content-start gap-1">
                  <button
                    type="button"
                    aria-current={active || undefined}
                    className="w-fit text-left font-serif text-[15px] font-semibold underline-offset-4 hover:underline"
                    onClick={() => onSelect(g.id)}
                  >
                    {g.label}
                  </button>
                  <p className="text-xs text-ink-secondary tabular-nums">
                    {flag(g.region.country_code)} {g.region.display_name} · {g.participant_count} participants
                    {lead && ` · ${lead}`}
                  </p>
                  <p className="line-clamp-2 text-xs">{g.description}</p>
                  {g.interests.length > 0 && (
                    <ul className="flex flex-wrap gap-1">
                      {g.interests.slice(0, 3).map((i) => (
                        <li key={i.ref_id} className="rounded-md border px-1.5 py-0.5 text-[11px]">
                          {i.name}
                        </li>
                      ))}
                    </ul>
                  )}
                </div>
              </li>
            );
          })}
        </ul>
      )}
    </section>
  );
}
