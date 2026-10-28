"use client";

import { ArrowRightIcon, CircleCheckIcon, CircleHelpIcon, CircleSlashIcon, TargetIcon } from "lucide-react";
import Link from "next/link";

import { ClaimBadge, ConfidenceBadge } from "@/components/evidence/badges";
import { EvidenceLinks } from "@/components/evidence/evidence-links";
import { Badge } from "@/components/ui/badge";
import { buttonVariants } from "@/components/ui/button";
import { Tabs, TabsContent, TabsList, TabsTrigger } from "@/components/ui/tabs";
import type { CulturalReference, DiscoveryResult, PopulationGroup } from "@/lib/api/types";
import { cn } from "@/lib/utils";

const STATUS = {
  resolved: { label: "Resolved", Icon: CircleCheckIcon, tone: "text-success" },
  ambiguous: { label: "Ambiguous", Icon: CircleHelpIcon, tone: "text-warning" },
  unresolved: { label: "Unresolved", Icon: CircleSlashIcon, tone: "text-ink-secondary" },
} as const;

export const relatedTo = (ref: CulturalReference, all: CulturalReference[]) =>
  all.filter(
    (r) =>
      r.id !== ref.id &&
      ((ref.name && r.query_term.toLowerCase() === `related to ${ref.name.toLowerCase()}`) ||
        (r.name && ref.query_term.toLowerCase() === `related to ${r.name.toLowerCase()}`)),
  );

/** Groups whose cited interests include this signal's Qloo id. */
export const groupsCiting = (ref: CulturalReference, groups: PopulationGroup[]) =>
  ref.entity_id ? groups.filter((g) => g.interests.some((i) => i.ref_id === ref.entity_id)) : [];

export function SignalDetail({
  reference: ref,
  result,
  groups,
  onSelect,
  dnaHref,
  audienceHref,
}: {
  reference: CulturalReference;
  result: DiscoveryResult;
  groups: PopulationGroup[];
  onSelect: (id: string) => void;
  dnaHref: string;
  audienceHref: string;
}) {
  const { label, Icon, tone } = STATUS[ref.match_status];
  const related = relatedTo(ref, result.references);
  const citing = groupsCiting(ref, groups);
  const brief = result.market_brief;
  // Findings linked to this signal through shared evidence records.
  const insights = brief
    ? [...brief.observations, ...brief.opportunities, ...brief.risks].filter((f) => f.evidence_ids.some((id) => ref.evidence_ids.includes(id)))
    : [];
  return (
    <section aria-labelledby="signal-h" className="grid min-w-0 grid-cols-[minmax(0,1fr)] content-start gap-4 rounded-2xl border bg-card p-4 shadow-card">
      <div aria-hidden className="flex h-28 items-center justify-center rounded-xl bg-atlas-soft text-atlas">
        <TargetIcon className="size-8" />
      </div>
      <div className="grid gap-1.5">
        <div className="flex flex-wrap items-center gap-2">
          <h2 id="signal-h" className="font-serif text-2xl leading-tight">
            {ref.name ?? `“${ref.query_term}”`}
          </h2>
          <span className={cn("inline-flex items-center gap-1 rounded-full border px-2 py-0.5 text-xs font-medium", tone)}>
            <Icon aria-hidden className="size-3.5" />
            {label}
          </span>
        </div>
        <p className="flex flex-wrap gap-1.5 text-xs">
          {ref.entity_type && <span className="rounded-full border px-2 py-0.5">{ref.entity_type}</span>}
          {ref.name && <span className="rounded-full border px-2 py-0.5">from “{ref.query_term}”</span>}
          {ref.entity_id && <span className="rounded-full border px-2 py-0.5 font-mono text-[11px]">{ref.entity_id}</span>}
        </p>
      </div>

      <Tabs defaultValue="overview">
        <div className="-mx-1 overflow-x-auto px-1">
          <TabsList>
          <TabsTrigger value="overview">Overview</TabsTrigger>
          <TabsTrigger value="evidence">Evidence ({ref.evidence_ids.length})</TabsTrigger>
          <TabsTrigger value="related">Related ({related.length})</TabsTrigger>
          <TabsTrigger value="audiences">Audiences ({citing.length})</TabsTrigger>
        </TabsList>
        </div>
        <TabsContent value="overview" className="grid min-w-0 grid-cols-[minmax(0,1fr)] gap-4 pt-3">
          <div className="grid gap-1.5">
            <div className="flex flex-wrap items-center gap-2">
              <h3 className="font-serif text-base">About this signal</h3>
              {ref.relevance_explanation && <Badge variant="outline">Model interpretation</Badge>}
            </div>
            <p className="text-sm">
              {ref.relevance_explanation ??
                (ref.match_status === "resolved" ? "No interpretation was recorded for this signal." : "No usable match yet, so nothing is inferred from it.")}
            </p>
          </div>
          {ref.attributes.length > 0 && (
            <dl className="grid gap-1.5 rounded-xl bg-surface-muted p-3 text-sm">
              {ref.attributes.map((a) => (
                <div key={a.key}>
                  <dt className="inline font-medium">{a.label}: </dt>
                  <dd className="inline tabular-nums">{a.value === null ? "Not returned" : String(a.value)}</dd>
                  {a.description && <p className="text-xs text-ink-secondary">{a.description}</p>}
                </div>
              ))}
            </dl>
          )}
          <div className="grid gap-2">
            <h3 className="font-serif text-base">Key insights</h3>
            {insights.length === 0 ? (
              <p className="text-sm text-ink-secondary">No brief finding cites this signal&apos;s evidence.</p>
            ) : (
              <ul className="grid gap-2">
                {insights.map((f) => (
                  <li key={f.id} className="grid gap-1">
                    <span className="text-sm">{f.title}</span>
                    <span className="flex flex-wrap gap-1.5">
                      <ClaimBadge claim={f.claim_type} />
                      <ConfidenceBadge label={f.confidence_label} />
                    </span>
                  </li>
                ))}
              </ul>
            )}
          </div>
        </TabsContent>
        <TabsContent value="evidence" className="pt-3">
          <div className="[contain:inline-size]">
            <EvidenceLinks ids={ref.evidence_ids} evidence={result.evidence} title={ref.name ?? ref.query_term} />
          </div>
        </TabsContent>
        <TabsContent value="related" className="pt-3">
          {related.length === 0 ? (
            <p className="text-sm text-ink-secondary">No related interests were returned for this signal.</p>
          ) : (
            <ul className="grid gap-1">
              {related.map((r) => (
                <li key={r.id}>
                  <button type="button" className="text-left text-sm underline-offset-4 hover:underline" onClick={() => onSelect(r.id)}>
                    {r.name ?? r.query_term}
                  </button>
                </li>
              ))}
            </ul>
          )}
        </TabsContent>
        <TabsContent value="audiences" className="pt-3">
          {citing.length === 0 ? (
            <p className="text-sm text-ink-secondary">
              No synthetic audience group cites this signal yet. Groups come from a population study in Audience Intelligence.
            </p>
          ) : (
            <ul className="grid gap-1.5">
              {citing.map((g) => (
                <li key={g.id} className="text-sm">
                  <span className="font-medium">{g.label}</span>{" "}
                  <span className="text-xs text-ink-secondary tabular-nums">
                    {g.region.display_name} · {g.participant_count} participants
                  </span>
                </li>
              ))}
            </ul>
          )}
        </TabsContent>
      </Tabs>

      <div className="grid min-w-0 grid-cols-[minmax(0,1fr)] gap-2 sm:grid-cols-2">
        <Link href={dnaHref} className={buttonVariants({ variant: "outline" })}>
          Explore in Cultural DNA <ArrowRightIcon aria-hidden data-icon="inline-end" />
        </Link>
        <Link href={audienceHref} className={buttonVariants()}>
          Continue to Audience <ArrowRightIcon aria-hidden data-icon="inline-end" />
        </Link>
      </div>
    </section>
  );
}
