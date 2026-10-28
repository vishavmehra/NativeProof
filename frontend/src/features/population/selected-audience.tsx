"use client";

import { ArrowRightIcon } from "lucide-react";
import Link from "next/link";

import { ClaimBadge, SyntheticBadge } from "@/components/evidence/badges";
import { EvidenceLinks } from "@/components/evidence/evidence-links";
import { buttonVariants } from "@/components/ui/button";
import { Tabs, TabsContent, TabsList, TabsTrigger } from "@/components/ui/tabs";
import type { EvidenceRecord, GroupResult, PopulationGroup, ThemeCount } from "@/lib/api/types";

import { flag, GroupImage } from "./audience-library";
import { AskGroup } from "./ask";
import { ParticipantList } from "./group-panel";
import { ReactionBar } from "./reaction-bars";

/** Top stored theme labels per region, summed over that region's groups (tallies only). */
function regionThemes(results: GroupResult[]) {
  const byRegion = new Map<string, { name: string; counts: Map<string, number> }>();
  for (const r of results) {
    const entry = byRegion.get(r.region.country_code) ?? { name: r.region.display_name, counts: new Map() };
    for (const t of r.themes) entry.counts.set(t.label, (entry.counts.get(t.label) ?? 0) + t.count);
    byRegion.set(r.region.country_code, entry);
  }
  return [...byRegion].map(([code, { name, counts }]) => ({
    code,
    name,
    top: [...counts].sort((a, b) => b[1] - a[1]).slice(0, 3),
  }));
}

function Themes({ title, items }: { title: string; items: ThemeCount[] }) {
  return (
    <div className="grid gap-1">
      <h4 className="text-sm font-semibold">{title}</h4>
      {items.length === 0 ? (
        <p className="text-xs text-ink-secondary">None recorded.</p>
      ) : (
        <ul className="grid gap-0.5 text-sm">
          {items.slice(0, 5).map((t) => (
            <li key={t.label} className="flex justify-between gap-2">
              <span>{t.label}</span>
              <span className="text-xs text-ink-secondary tabular-nums">
                {t.count} · {Math.round(t.share * 100)}%
              </span>
            </li>
          ))}
        </ul>
      )}
    </div>
  );
}

export function SelectedAudience({
  group,
  result,
  allResults,
  evidence,
  populationId,
  studyId,
  arenaHref,
}: {
  group: PopulationGroup;
  result?: GroupResult;
  allResults: GroupResult[];
  evidence: EvidenceRecord[];
  populationId: string;
  studyId: string;
  arenaHref: string;
}) {
  const regions = regionThemes(allResults);
  return (
    <section aria-labelledby="sel-h" className="grid min-w-0 grid-cols-[minmax(0,1fr)] content-start gap-4 rounded-2xl border bg-card p-4 shadow-card">
      <h2 id="sel-h" className="font-serif text-xl">
        Selected audience
      </h2>
      <div className="grid grid-cols-[auto_minmax(0,1fr)] gap-3">
        <GroupImage className="size-24" />
        <div className="grid min-w-0 grid-cols-[minmax(0,1fr)] content-start gap-1.5">
          <h3 className="font-serif text-lg leading-tight font-semibold">{group.label}</h3>
          <p className="text-xs text-ink-secondary tabular-nums">
            {flag(group.region.country_code)} {group.region.display_name} · {group.participant_count} participants
          </p>
          <ClaimBadge claim="interpreted" />
        </div>
      </div>
      <p className="text-sm">{group.description}</p>
      <SyntheticBadge />

      <Tabs defaultValue="overview">
        <div className="-mx-1 overflow-x-auto px-1">
          <TabsList>
          <TabsTrigger value="overview">Overview</TabsTrigger>
          <TabsTrigger value="insights">Interview insights</TabsTrigger>
          <TabsTrigger value="participants">Participants</TabsTrigger>
          <TabsTrigger value="ask">Ask this group</TabsTrigger>
        </TabsList>
        </div>
        <TabsContent value="overview" className="grid min-w-0 grid-cols-[minmax(0,1fr)] gap-4 pt-3">
          <div className="grid gap-1.5">
            <h4 className="text-sm font-semibold">Top interests</h4>
            {group.interests.length === 0 ? (
              <p className="text-xs text-ink-secondary">None cited.</p>
            ) : (
              <p className="text-sm">{group.interests.slice(0, 5).map((i) => i.name).join(", ")}</p>
            )}
            <p className="text-[11px] text-ink-secondary">Qloo tags and entities from the group&apos;s cited evidence.</p>
          </div>
          {result && (
            <div className="grid gap-1.5">
              <h4 className="text-sm font-semibold">Reactions</h4>
              <ReactionBar d={result.distribution} compact />
            </div>
          )}
          <div className="grid gap-1.5">
            <h4 className="text-sm font-semibold">Evidence</h4>
            <div className="[contain:inline-size]">
              <EvidenceLinks ids={group.evidence_ids} evidence={evidence} title={group.label} />
            </div>
          </div>
          {regions.length > 1 && (
            <div className="grid gap-2">
              <h4 className="text-sm font-semibold">Cultural differences by region</h4>
              <ul className="grid min-w-0 grid-cols-[minmax(0,1fr)] gap-2 sm:grid-cols-[repeat(auto-fill,minmax(9rem,1fr))]">
                {regions.map((r) => (
                  <li key={r.code} className="grid min-w-0 grid-cols-[minmax(0,1fr)] content-start gap-1 rounded-xl border bg-surface p-2.5">
                    <span className="text-sm font-medium">
                      {flag(r.code)} {r.name}
                    </span>
                    {r.top.length === 0 ? (
                      <span className="text-xs text-ink-secondary">No themes recorded.</span>
                    ) : (
                      r.top.map(([label, n]) => (
                        <span key={label} className="text-xs">
                          {label} <span className="text-ink-secondary tabular-nums">· {n}</span>
                        </span>
                      ))
                    )}
                  </li>
                ))}
              </ul>
              <p className="text-[11px] text-ink-secondary">Most frequent stored theme labels among each region&apos;s interviews.</p>
            </div>
          )}
        </TabsContent>
        <TabsContent value="insights" className="grid min-w-0 grid-cols-[minmax(0,1fr)] gap-4 pt-3">
          {result ? (
            <>
              <Themes title="Themes" items={result.themes} />
              <Themes title="Misunderstandings" items={result.misunderstandings} />
              <Themes title="Concerns" items={result.concerns} />
            </>
          ) : (
            <p className="text-sm text-ink-secondary">No interview tallies for this group yet.</p>
          )}
        </TabsContent>
        <TabsContent value="participants" className="pt-3">
          <ParticipantList populationId={populationId} groupId={group.id} studyId={studyId} />
        </TabsContent>
        <TabsContent value="ask" className="pt-3">
          <AskGroup key={group.id} studyId={studyId} groupId={group.id} />
        </TabsContent>
      </Tabs>

      <div className="grid min-w-0 grid-cols-[minmax(0,1fr)] gap-2 rounded-xl bg-accent p-3">
        <h3 className="text-sm font-semibold">Campaign testing with this audience</h3>
        <p className="text-xs text-ink-secondary">Compare campaign concepts on these synthetic participants.</p>
        <Link href={arenaHref} className={buttonVariants({ size: "sm", className: "w-fit" })}>
          Open Campaign Arena <ArrowRightIcon aria-hidden data-icon="inline-end" />
        </Link>
      </div>
    </section>
  );
}
