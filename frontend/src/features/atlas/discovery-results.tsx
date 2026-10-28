"use client";

import { ArrowRightIcon, ChevronRightIcon } from "lucide-react";
import Link from "next/link";
import { useState } from "react";

import { LimitationList } from "@/components/evidence/limitation-list";
import { Button, buttonVariants } from "@/components/ui/button";
import { useCampaignPopulation } from "@/features/population/api";
import { sectionHref } from "@/features/project/workflow";
import type { DiscoveryResult } from "@/lib/api/types";
import { formatDateTime } from "@/lib/format";
import { cn } from "@/lib/utils";

import { splitLimitations } from "./limitations";
import { BriefFindingList, MarketBrief, sectionHeading } from "./market-brief";
import { ReferenceTable, matchCounts, type ConfirmCandidate } from "./reference-table";
import { RunProvenance } from "./run-provenance";
import { SignalDetail, groupsCiting } from "./signal-detail";
import { SignalMap } from "./signal-map";

/** Audience link that carries this discovery as grounding. */
export function audienceHrefFor(result: DiscoveryResult, campaignId: string | null) {
  const linked = result.campaign_id ?? campaignId;
  return `/projects/${result.project_id}/audience?${new URLSearchParams({ ...(linked ? { campaign: linked } : {}), discovery: result.run_id })}`;
}

const card = "grid min-w-0 grid-cols-[minmax(0,1fr)] content-start gap-3 rounded-2xl border bg-card p-4 shadow-card";

export function DiscoveryResults({
  result,
  campaignId,
  onRefine,
  onConfirm,
  busy,
}: {
  result: DiscoveryResult;
  campaignId: string | null;
  onRefine: () => void;
  onConfirm: ConfirmCandidate;
  busy: boolean;
}) {
  const limits = splitLimitations(result.limitations, result.references.map((r) => r.limitations), "references");
  const references = result.references.map((r) => ({ ...r, limitations: limits.own(r.limitations) }));
  const brief = result.market_brief && { ...result.market_brief, limitations: limits.own(result.market_brief.limitations) };
  const linkedCampaign = result.campaign_id ?? campaignId;
  const audienceHref = audienceHrefFor(result, campaignId);
  const groups = useCampaignPopulation(result.project_id, linkedCampaign).data?.groups ?? [];
  const [view, setView] = useState<"map" | "list">("map");
  const [selectedId, setSelectedId] = useState<string | null>(null);
  const selected = references.find((r) => r.id === selectedId) ?? references.find((r) => r.match_status === "resolved") ?? references[0];
  const resolved = references.filter((r) => r.match_status === "resolved");
  const keyAudiences = groups.filter((g) => resolved.some((r) => groupsCiting(r, [g]).length > 0));

  return (
    <div className="grid min-w-0 grid-cols-[minmax(0,1fr)] gap-6">
      <h2 className="sr-only">Discovery results</h2>
      {result.status === "partial" && (
        <p className="text-sm text-warning">Partial result: some stages did not complete. The limitations below name what is missing.</p>
      )}

      <div className="grid min-w-0 grid-cols-[minmax(0,1fr)] gap-6 xl:grid-cols-[minmax(0,1fr)_minmax(0,24rem)]">
        <section aria-labelledby="map-h" className={card}>
          <div className="flex flex-wrap items-start justify-between gap-3">
            <div>
              <h2 id="map-h" className="font-serif text-2xl">
                Cultural signal map
              </h2>
              <p className="text-sm text-ink-secondary">
                {result.market.display_name} · {result.product_category} · {formatDateTime(result.run_metadata.completed_at)} ·{" "}
                <span className="tabular-nums">{matchCounts(references)}</span>
              </p>
            </div>
            <div role="group" aria-label="Signal view" className="flex rounded-lg border p-0.5 max-sm:hidden">
              {(["map", "list"] as const).map((v) => (
                <Button key={v} size="sm" variant={view === v ? "default" : "ghost"} aria-pressed={view === v} onClick={() => setView(v)}>
                  {v === "map" ? "Map view" : "List view"}
                </Button>
              ))}
            </div>
          </div>
          {references.length === 0 ? (
            <p className="text-sm text-ink-secondary">No cultural references were returned for these inputs.</p>
          ) : (
            <>
              {/* The radial map needs width; phones get the list. */}
              <div className={cn("max-sm:hidden", view !== "map" && "hidden")}>
                <SignalMap center={result.product_category} references={references} selectedId={selected?.id ?? null} onSelect={setSelectedId} />
                <p className="text-xs text-ink-secondary">
                  Filled nodes resolved to a Qloo tag or entity; dashed nodes are ambiguous or unresolved and are never used
                  downstream. Outer nodes are related interests returned for their inner signal.
                </p>
              </div>
              <div className={cn(view === "map" && "sm:hidden")}>
                <ReferenceTable references={references} evidence={result.evidence} onRefine={onRefine} onConfirm={onConfirm} busy={busy} />
              </div>
            </>
          )}
        </section>

        {selected && (
          <SignalDetail
            reference={selected}
            result={result}
            groups={groups}
            onSelect={setSelectedId}
            dnaHref={sectionHref(result.project_id, "cultural-dna", linkedCampaign)}
            audienceHref={audienceHref}
          />
        )}
      </div>

      <div className="grid min-w-0 grid-cols-[minmax(0,1fr)] gap-6 lg:grid-cols-3">
        <section aria-labelledby="top-h" className={card}>
          <h2 id="top-h" className="font-serif text-lg">
            Top related signals
          </h2>
          {resolved.length === 0 ? (
            <p className="text-sm text-ink-secondary">No signal resolved yet.</p>
          ) : (
            <ul className="grid gap-1">
              {resolved.slice(0, 5).map((r) => {
                const attr = r.attributes[0];
                return (
                  <li key={r.id}>
                    <button
                      type="button"
                      onClick={() => setSelectedId(r.id)}
                      className="grid w-full grid-cols-[minmax(0,1fr)_auto] items-center gap-2 rounded-lg px-2 py-1.5 text-left hover:bg-surface-muted"
                    >
                      <span className="min-w-0">
                        <span className="block truncate text-sm font-medium">{r.name}</span>
                        <span className="block text-xs text-ink-secondary">
                          {r.entity_type ?? "signal"}
                          {attr && attr.value !== null && ` · ${attr.label} ${attr.value}`}
                        </span>
                      </span>
                      <ChevronRightIcon aria-hidden className="size-4 text-ink-secondary" />
                    </button>
                  </li>
                );
              })}
            </ul>
          )}
          {resolved.some((r) => r.attributes.length > 0) && (
            <p className="text-[11px] text-ink-secondary">Attribute values are Qloo&apos;s own fields; see each signal for their meaning.</p>
          )}
        </section>

        <section aria-labelledby="aud-h" className={card}>
          <h2 id="aud-h" className="font-serif text-lg">
            Key audiences
          </h2>
          {keyAudiences.length === 0 ? (
            <p className="text-sm text-ink-secondary">
              No synthetic audience group cites these signals yet. Groups come from a population study.
            </p>
          ) : (
            <ul className="grid gap-1.5">
              {keyAudiences.slice(0, 4).map((g) => (
                <li key={g.id} className="text-sm">
                  <span className="font-medium">{g.label}</span>{" "}
                  <span className="text-xs text-ink-secondary tabular-nums">
                    {g.region.display_name} · {g.participant_count} participants
                  </span>
                </li>
              ))}
            </ul>
          )}
          <Link href={audienceHref} className={buttonVariants({ variant: "outline", size: "sm", className: "w-fit" })}>
            Open Audience Intelligence <ArrowRightIcon aria-hidden data-icon="inline-end" />
          </Link>
        </section>

        <section aria-labelledby="sum-h" className={card}>
          <h2 id="sum-h" className="font-serif text-lg">
            Market brief
          </h2>
          {brief ? (
            <>
              <p className="line-clamp-4 text-sm">{brief.summary}</p>
              <p className="text-xs text-ink-secondary tabular-nums">
                {brief.observations.length} observations · {brief.opportunities.length} opportunities · {brief.risks.length} risks
              </p>
              <a href="#brief-heading" className="w-fit text-sm font-medium text-primary underline-offset-4 hover:underline">
                Read the full brief
              </a>
            </>
          ) : (
            <p className="text-sm text-ink-secondary">No market brief was generated for this run.</p>
          )}
        </section>
      </div>

      <MarketBrief brief={brief} evidence={result.evidence} />

      {brief && (
        <div className="grid min-w-0 grid-cols-[minmax(0,1fr)] gap-8 lg:grid-cols-[minmax(0,1fr)_minmax(0,1fr)]">
          <section aria-labelledby="opportunities-heading" className="grid min-w-0 grid-cols-[minmax(0,1fr)] content-start gap-3">
            <h2 id="opportunities-heading" className={sectionHeading}>
              Opportunities
            </h2>
            <BriefFindingList findings={brief.opportunities} evidence={result.evidence} empty="No opportunities were identified." />
          </section>
          <section aria-labelledby="risks-heading" className="grid min-w-0 grid-cols-[minmax(0,1fr)] content-start gap-3">
            <h2 id="risks-heading" className={sectionHeading}>
              Risks
            </h2>
            <BriefFindingList findings={brief.risks} evidence={result.evidence} empty="No risks were identified." />
          </section>
        </div>
      )}

      <LimitationList title="Result limitations" items={limits.page} />
      <RunProvenance metadata={result.run_metadata} />

      <nav aria-label="Next steps" className="flex flex-wrap items-center justify-between gap-3 rounded-2xl bg-accent px-4 py-3">
        <p className="font-serif text-base">What would you like to do next?</p>
        <div className="flex flex-wrap gap-2">
          <Link href={sectionHref(result.project_id, "market-expansion", linkedCampaign)} className={buttonVariants({ variant: "outline" })}>
            Compare markets
          </Link>
          <Link href={audienceHref} className={buttonVariants()}>
            Interview audiences <ArrowRightIcon aria-hidden data-icon="inline-end" />
          </Link>
        </div>
      </nav>
    </div>
  );
}
