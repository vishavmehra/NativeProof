"use client";

import { ArrowRight, Check, Gauge, Heart, Lightbulb, Scale, ShieldAlert, Target, TriangleAlert, Users } from "lucide-react";
import Link from "next/link";
import { useState, type ReactNode } from "react";

import { CampaignContentView } from "@/components/campaign/content-view";
import { ClaimBadge, SyntheticBadge } from "@/components/evidence/badges";
import { EvidenceLinks } from "@/components/evidence/evidence-links";
import { LimitationList } from "@/components/evidence/limitation-list";
import { Pill } from "@/components/data/pills";
import { ScoreBar } from "@/components/data/score-bar";
import { ErrorState } from "@/components/states";
import { Button, buttonVariants } from "@/components/ui/button";
import { ApiError } from "@/lib/api/errors";
import { MEANINGFUL_DIFFERENCE, formatScore, signedDelta } from "@/features/loop/comparison-table";
import { DIMENSION_LABEL } from "@/features/loop/criteria-editor";
import { Panel, SELECT_CLASS } from "@/features/voice/field";
import { RiskFlagList } from "@/features/voice/risk-flags";
import { humanize } from "@/lib/format";
import { cn } from "@/lib/utils";

import { usePreferVariant, type ArenaResult, type ArenaVariantResult } from "./api";
import { AssetImage } from "./asset-image";
import { VisionBanner } from "./vision-banner";

const SOURCE_LABEL = { content_version: "Content version", adaptation: "Adaptation", custom: "Custom text" } as const;
const DIMENSIONS = ["clarity", "brand_fidelity", "cultural_relevance", "cultural_risk"] as const;

/** Says why an overall score is null (mvp-1 needs every dimension score), instead of showing 0 or a blank. */
function NotScored({ v }: { v: ArenaVariantResult }) {
  const missing = DIMENSIONS.filter((d) => v.dimension_results[d]?.score == null).map((d) => humanize(d).toLowerCase());
  return (
    <span className="text-[13px] font-normal text-ink-secondary">
      Not assessed:{" "}
      {missing.length ? `no ${missing.join(", ")} score${missing.length > 1 ? "s" : ""}, and the overall needs every dimension.` : "the overall score was not computed."}
    </span>
  );
}
const COLUMNS: Record<number, string> = { 2: "md:grid-cols-2", 3: "md:grid-cols-2 xl:grid-cols-3", 4: "md:grid-cols-2 xl:grid-cols-4" };

function Block({ title, children }: { title: string; children: ReactNode }) {
  return (
    <div className="grid gap-1.5">
      <h4 className="text-xs font-semibold text-ink">{title}</h4>
      {children}
    </div>
  );
}

function Bullets({ items }: { items: string[] }) {
  if (items.length === 0) return <p className="text-xs text-ink-secondary">None stated.</p>;
  return (
    <ul className="list-disc space-y-0.5 pl-4 text-[13px] leading-snug text-ink">
      {items.map((item, i) => (
        <li key={i}>{item}</li>
      ))}
    </ul>
  );
}

function VariantColumn({ v, rank, arena }: { v: ArenaVariantResult; rank: number; arena: ArenaResult }) {
  const dimensions = Object.values(v.dimension_results).flatMap((d) => (d ? [d] : []));
  return (
    <section aria-label={v.label} className="grid content-start gap-4 rounded-card border border-border bg-surface shadow-card p-4">
      <header className="grid gap-1">
        <div className="flex flex-wrap items-center gap-2">
          <span className="text-xs font-semibold text-ink-secondary tabular-nums">#{rank}</span>
          <h3 className="text-[15px] font-semibold text-ink">{v.label}</h3>
          {arena.preferred_variant_id === v.variant_id && (
            <Pill tone="indigo">Current focus</Pill>
          )}
        </div>
        <span className="text-xs text-ink-secondary">{SOURCE_LABEL[v.source]}</span>
      </header>
      {v.asset_id && <AssetImage assetId={v.asset_id} alt={`${v.label} image creative`} className="aspect-4/3 w-full" />}
      <CampaignContentView content={v.content} />
      <Block title="Overall (calculated)">
        <p className="text-2xl font-semibold text-ink tabular-nums">
          {v.overall_score === null ? <NotScored v={v} /> : formatScore(v.overall_score)}
        </p>
      </Block>
      <Block title="Dimension scores from synthetic ratings">
        {dimensions.length === 0 ? (
          <p className="text-xs text-ink-secondary">No dimension scores.</p>
        ) : (
          <div className="grid gap-3">
            {dimensions.map((d) => (
              <ScoreBar
                key={d.dimension}
                label={humanize(d.dimension)}
                value={d.score}
                higherIsBetter={d.higher_is_better}
                note={`${d.n} synthetic ratings · spread ${d.spread ?? "n/a"}${d.disagreement ? " · disagreement" : ""}`}
              />
            ))}
          </div>
        )}
      </Block>
      <Block title="Strengths">
        <Bullets items={v.strengths} />
      </Block>
      <Block title="Weaknesses">
        <Bullets items={v.weaknesses} />
      </Block>
      <Block title="Risk flags">
        <RiskFlagList flags={v.risk_flags} empty="None raised." />
      </Block>
      {v.visual_observations.length > 0 && (
        <Block title="Visible in the image (vision model)">
          <ul className="space-y-1 text-[13px] text-ink">
            {v.visual_observations.map((o) => (
              <li key={o.id}>
                {o.description}
                <span className="text-xs text-ink-secondary">
                  {" "}
                  · {humanize(o.kind)}
                  {o.location && ` · ${o.location}`}
                </span>
              </li>
            ))}
          </ul>
        </Block>
      )}
      <Block title="Segments">
        {v.segments.length === 0 ? (
          <p className="text-xs text-ink-secondary">No segment breakdown.</p>
        ) : (
          <ul className="divide-y divide-border text-[13px]">
            {v.segments.map((s) => (
              <li key={s.label} className="grid gap-0.5 py-1.5">
                <span className="text-ink">
                  {s.label}{" "}
                  <span className="text-xs text-ink-secondary">
                    {s.response_count} reactions · {s.source === "model" ? "model-generated assumption" : "your assumption"}
                  </span>
                </span>
                <span className="text-xs text-ink-secondary tabular-nums">
                  {Object.entries(s.dimension_scores)
                    .map(([k, val]) => `${humanize(k)} ${val === null ? "n/a" : formatScore(val)}`)
                    .join(" · ")}
                </span>
              </li>
            ))}
          </ul>
        )}
      </Block>
      <Block title="Evidence">
        <EvidenceLinks ids={v.evidence_ids} evidence={arena.evidence} title={v.label} />
      </Block>
      {v.reactions.length > 0 && (
        <details className="text-[13px]">
          <summary className="cursor-pointer text-ink-secondary select-none hover:text-ink">{v.reactions.length} synthetic reactions</summary>
          <ul className="mt-2 grid gap-2">
            {v.reactions.map((r) => (
              <li key={r.id} className="grid gap-0.5 border-l-2 border-dashed border-ink-secondary/40 pl-2">
                <span className="text-xs text-ink-secondary">
                  {r.segment_label} · {humanize(r.sentiment)}
                </span>
                <span className="text-ink">{r.reaction_summary}</span>
              </li>
            ))}
          </ul>
        </details>
      )}
    </section>
  );
}

const DIMS = ["cultural_relevance", "brand_fidelity", "clarity", "cultural_risk"] as const;
const DIM_ICON = { clarity: Gauge, brand_fidelity: Heart, cultural_relevance: Target, cultural_risk: ShieldAlert } as const;

export function ArenaResults({ arena, projectId }: { arena: ArenaResult; projectId: string }) {
  const prefer = usePreferVariant(arena.id);
  const [sortKey, setSortKey] = useState<"overall" | (typeof DIMS)[number]>("overall");
  const byId = new Map(arena.variants.map((v) => [v.variant_id, v]));
  const ranked = [...arena.ranking.flatMap((id) => byId.get(id) ?? []), ...arena.variants.filter((v) => !arena.ranking.includes(v.variant_id))];
  const top = ranked[0]?.overall_score ?? null;
  const adaptationIds = arena.variants.flatMap((v) => (v.source === "adaptation" && v.source_id ? [v.source_id] : []));
  const campaignQuery = `campaign=${arena.campaign_id}`;

  const letter = (id: string) => "ABCD"[arena.variants.findIndex((v) => v.variant_id === id)] ?? "?";
  const sorted = sortKey === "overall" ? ranked : [...ranked].sort((a, b) => (b.dimension_results[sortKey]?.score ?? -1) - (a.dimension_results[sortKey]?.score ?? -1));
  const insights = [
    ...arena.segment_differences.slice(0, 2).map((text) => ({ Icon: Users, text, kind: "Segment difference" })),
    ...arena.tradeoffs.slice(0, 1).map((text) => ({ Icon: Scale, text, kind: "Trade-off" })),
    ...arena.recommended_improvements.slice(0, 2).map((imp) => ({ Icon: Lightbulb, text: `${byId.get(imp.variant_id)?.label ?? "Concept"}: ${imp.suggestion}`, kind: "Improvement (model interpretation)" })),
  ];

  return (
    <div className="grid gap-5">
      <div className="grid grid-cols-[minmax(0,1fr)] gap-5 xl:grid-cols-[minmax(0,1fr)_minmax(0,21rem)]">
        <section aria-labelledby="arena-results-heading" className="grid content-start gap-4 rounded-card border border-border bg-surface p-5 shadow-card">
          <div className="flex flex-wrap items-start justify-between gap-3">
            <div className="grid gap-0.5">
              <h2 id="arena-results-heading" className="font-serif text-2xl text-ink">
                Comparison results
              </h2>
              <p className="text-sm text-ink-secondary">Synthetic audience evaluation based on your selected criteria.</p>
            </div>
            <div className="flex flex-wrap items-center gap-2">
              <select aria-label="Sort concepts by" className={cn(SELECT_CLASS, "w-auto")} value={sortKey} onChange={(e) => setSortKey(e.target.value as typeof sortKey)}>
                <option value="overall">Overall performance</option>
                {DIMS.map((d) => (
                  <option key={d} value={d}>
                    {DIMENSION_LABEL[d]}
                  </option>
                ))}
              </select>
              <a className={buttonVariants({ variant: "outline" })} href="#arena-details">
                See detailed analysis
                <ArrowRight aria-hidden />
              </a>
            </div>
          </div>
          <p className="flex flex-wrap items-center gap-2 text-xs text-ink-secondary tabular-nums">
            <SyntheticBadge />
            {arena.simulation_disclosure.generated_responses} of {arena.simulation_disclosure.requested_responses} responses generated · not an
            independent human sample · {arena.simulation_disclosure.grounded ? "grounded in discovery evidence" : "ungrounded"}
          </p>
          <VisionBanner vision={arena.vision} />
          <ul className="grid grid-cols-[minmax(0,1fr)] gap-4 md:grid-cols-2 2xl:grid-cols-3">
            {sorted.map((v) => {
              const rank = ranked.indexOf(v);
              const gap = rank > 0 && top !== null && v.overall_score !== null ? Math.round((v.overall_score - top) * 10) / 10 : null;
              const focus = arena.preferred_variant_id === v.variant_id;
              return (
                <li key={v.variant_id} className={cn("grid content-start gap-3 rounded-xl border bg-surface p-4", focus ? "border-primary/50 ring-1 ring-primary/20" : "border-border")}>
                  <div className="flex items-start justify-between gap-3">
                    <div className="flex min-w-0 items-center gap-2">
                      <span className="flex size-9 shrink-0 items-center justify-center rounded-full bg-accent font-semibold text-primary">{letter(v.variant_id)}</span>
                      <span className="font-serif text-base text-ink">{v.label}</span>
                    </div>
                    <div className="grid shrink-0 justify-items-end gap-1">
                      {v.overall_score !== null && (
                        <span className="text-3xl font-semibold text-ink tabular-nums">
                          {formatScore(v.overall_score)}
                          <span className="text-xs font-normal text-ink-secondary">/100</span>
                        </span>
                      )}
                      {v.overall_score !== null &&
                        (rank === 0 ? (
                          <Pill tone="green" icon="check">
                            Leading
                          </Pill>
                        ) : gap !== null && Math.abs(gap) < MEANINGFUL_DIFFERENCE ? (
                          <Pill tone="blue">Within 5 pts of leader</Pill>
                        ) : gap !== null ? (
                          <Pill tone="gray">{signedDelta(gap)} vs leader</Pill>
                        ) : null)}
                    </div>
                  </div>
                  {v.overall_score === null && <NotScored v={v} />}
                  {focus && (
                    <Pill tone="indigo" className="w-fit">
                      Current focus
                    </Pill>
                  )}
                  <ul className="grid gap-2">
                    {DIMS.map((d) => {
                      const r = v.dimension_results[d];
                      const Icon = DIM_ICON[d];
                      return (
                        <li key={d} className="grid grid-cols-[auto_minmax(0,7rem)_minmax(0,1fr)_2.5rem] items-center gap-2 text-xs">
                          <Icon aria-hidden className={cn("size-3.5", d === "cultural_risk" ? "text-danger" : "text-primary")} />
                          <span className="truncate text-ink-secondary">{DIMENSION_LABEL[d]}</span>
                          <span className="h-1.5 overflow-hidden rounded-full bg-surface-muted" aria-hidden>
                            {r?.score != null && <span className={cn("block h-full rounded-full", d === "cultural_risk" ? "bg-danger" : "bg-primary")} style={{ width: `${r.score}%` }} />}
                          </span>
                          <span className="text-right text-ink tabular-nums">{r?.score != null ? formatScore(r.score) : "n/a"}</span>
                        </li>
                      );
                    })}
                  </ul>
                  <div className="grid grid-cols-[minmax(0,1fr)_auto] gap-3 border-t border-border pt-3">
                    <div className="grid content-start gap-1">
                      <h3 className="text-xs font-semibold text-ink">Key takeaways</h3>
                      <ul className="grid gap-1 text-xs text-ink">
                        {v.strengths.slice(0, 2).map((s, i) => (
                          <li key={`s${i}`} className="flex gap-1.5">
                            <Check aria-hidden className="mt-0.5 size-3 shrink-0 text-success" />
                            {s}
                          </li>
                        ))}
                        {v.weaknesses.slice(0, 1).map((w, i) => (
                          <li key={`w${i}`} className="flex gap-1.5">
                            <TriangleAlert aria-hidden className="mt-0.5 size-3 shrink-0 text-warning" />
                            {w}
                          </li>
                        ))}
                      </ul>
                    </div>
                    {v.asset_id && <AssetImage assetId={v.asset_id} alt={`${v.label} creative`} className="size-16" />}
                  </div>
                  <Button size="sm" variant={focus ? "secondary" : "outline"} className="w-fit" disabled={prefer.isPending} onClick={() => prefer.mutate(focus ? null : v.variant_id)}>
                    {focus ? "Clear focus" : "Set as focus"}
                  </Button>
                </li>
              );
            })}
          </ul>
          <p className="text-xs text-ink-secondary">
            Differences under {MEANINGFUL_DIFFERENCE} points are not meaningful. Overall is the mvp-1 weighted utility of synthetic dimension
            scores. Setting a focus is not approval: it records which creative you want to take forward.
          </p>
          {prefer.error instanceof ApiError && prefer.error.code === "CONFLICT" ? (
            <p role="alert" className="rounded-lg border border-warning/30 bg-warning-soft/70 px-3 py-2 text-[13px] text-ink">
              <span className="font-semibold">Focus not changed.</span> {prefer.error.message}
            </p>
          ) : prefer.error ? (
            <ErrorState error={prefer.error} />
          ) : null}
        </section>
        <aside aria-labelledby="arena-insights-heading" className="grid content-start gap-3 rounded-card border border-border bg-surface p-5 shadow-card">
          <h2 id="arena-insights-heading" className="font-serif text-lg text-ink">
            Key insights
          </h2>
          {insights.length === 0 ? (
            <p className="text-sm text-ink-secondary">No insights were produced for this arena.</p>
          ) : (
            <ul className="grid gap-3">
              {insights.map(({ Icon, text, kind }, i) => (
                <li key={i} className="grid grid-cols-[auto_minmax(0,1fr)] gap-3 rounded-lg bg-surface-muted/60 p-3">
                  <span className="flex size-9 items-center justify-center rounded-full bg-surface text-primary">
                    <Icon aria-hidden className="size-4" />
                  </span>
                  <span className="grid gap-0.5">
                    <span className="text-[11px] font-medium text-ink-secondary">{kind}</span>
                    <span className="text-[13px] text-ink">{text}</span>
                  </span>
                </li>
              ))}
            </ul>
          )}
        </aside>
      </div>

      <h2 id="arena-details" className="scroll-mt-24 font-serif text-2xl text-ink">
        Detailed analysis
      </h2>
      <section aria-label="Side-by-side creative comparison" className={cn("grid gap-4", COLUMNS[ranked.length])}>
        {ranked.map((v, i) => (
          <VariantColumn key={v.variant_id} v={v} rank={i + 1} arena={arena} />
        ))}
      </section>

      <div className="grid gap-6 lg:grid-cols-2">
        <Panel id="segments-diff-heading" title="Segment differences">
          <Bullets items={arena.segment_differences} />
        </Panel>
        <Panel id="arena-tradeoffs-heading" title="Trade-offs">
          <Bullets items={arena.tradeoffs} />
        </Panel>
      </div>

      <Panel id="improvements-heading" title="Recommended improvements">
        {arena.recommended_improvements.length === 0 ? (
          <p className="text-sm text-ink-secondary">No improvements were suggested.</p>
        ) : (
          <ul className="divide-y divide-border">
            {arena.recommended_improvements.map((imp, i) => (
              <li key={i} className="grid gap-1.5 py-3 first:pt-0 last:pb-0">
                <div className="flex flex-wrap items-center gap-2">
                  <span className="text-sm font-medium text-ink">{byId.get(imp.variant_id)?.label ?? "Variant"}</span>
                  <ClaimBadge claim={imp.claim_type} />
                </div>
                <p className="text-sm text-ink">{imp.suggestion}</p>
                <p className="text-[13px] text-ink-secondary">{imp.rationale}</p>
                <EvidenceLinks ids={imp.evidence_ids} evidence={arena.evidence} title={imp.suggestion} />
              </li>
            ))}
          </ul>
        )}
      </Panel>

      <LimitationList items={arena.limitations} />

      <p className="text-sm text-ink-secondary">
        Also:{" "}
        <Link className="underline underline-offset-2" href={`/projects/${projectId}/risk-radar?${campaignQuery}`}>
          scan these concepts in Risk Radar
        </Link>{" "}
        or{" "}
        <Link
          className="underline underline-offset-2"
          href={`/projects/${projectId}/loop?${campaignQuery}${adaptationIds.length ? `&candidates=${adaptationIds.slice(0, 3).join(",")}` : ""}`}
        >
          evaluate the adaptations in Loop
        </Link>
        .
      </p>
    </div>
  );
}
