"use client";

import { useEffect, type ReactNode } from "react";

import { SyntheticBadge } from "@/components/evidence/badges";
import { EvidenceLinks } from "@/components/evidence/evidence-links";
import { Button } from "@/components/ui/button";
import { Label } from "@/components/ui/label";
import type { EvidenceRecord, SyntheticReaction } from "@/lib/api/types";
import { humanize } from "@/lib/format";
import { cn } from "@/lib/utils";

import { DIMENSION_LABEL } from "./dimensions";

export type Sentiment = SyntheticReaction["sentiment"];
export type Highlight = { ids: string[]; focus: string } | null;

const SENTIMENTS: Sentiment[] = ["positive", "neutral", "negative", "mixed"];
const SENTIMENT_TONE: Record<Sentiment, string> = {
  positive: "text-success",
  neutral: "text-muted-foreground",
  negative: "text-danger",
  mixed: "text-warning",
};
const SEVERITY_TONE = { low: "text-muted-foreground", medium: "text-warning", high: "text-danger" } as const;
const SELECT =
  "h-8 rounded-lg border border-input bg-transparent px-2 text-sm outline-none focus-visible:border-ring focus-visible:ring-3 focus-visible:ring-ring/50";

function Row({ term, children }: { term: string; children: ReactNode }) {
  return (
    <div className="grid gap-0.5 sm:grid-cols-[8.5rem_minmax(0,1fr)] sm:gap-3">
      <dt className="text-xs font-medium text-muted-foreground sm:pt-0.5">{term}</dt>
      <dd>{children}</dd>
    </div>
  );
}

function ReactionCard({
  reaction: r,
  no,
  evidence,
  highlighted,
}: {
  reaction: SyntheticReaction;
  no: number;
  evidence: EvidenceRecord[];
  highlighted: boolean;
}) {
  return (
    <li>
      <article
        id={`reaction-${r.id}`}
        tabIndex={-1}
        aria-labelledby={`reaction-${r.id}-title`}
        className={cn(
          "grid h-full scroll-mt-24 content-start gap-3 rounded-lg border bg-card p-4 outline-none focus-visible:ring-3 focus-visible:ring-ring/50",
          highlighted && "border-primary ring-2 ring-primary/30",
        )}
      >
        <header className="grid gap-1.5">
          <div className="flex flex-wrap items-baseline gap-x-2 gap-y-1">
            <h3 id={`reaction-${r.id}-title`} className="text-sm font-semibold tabular-nums">
              Reaction {no}
            </h3>
            <span className="text-xs text-muted-foreground">{r.segment_label}</span>
            <span className={cn("text-xs font-medium", SENTIMENT_TONE[r.sentiment])}>{humanize(r.sentiment)}</span>
            {highlighted && <span className="text-xs font-medium text-primary">Linked</span>}
          </div>
          <SyntheticBadge />
        </header>
        <p className="text-[15px] leading-snug">{r.reaction_summary}</p>
        <dl className="grid gap-2 text-sm">
          <Row term="Interpretation">{r.interpretation}</Row>
          <Row term="Ratings">
            <ul className="flex flex-wrap gap-x-3 gap-y-0.5 tabular-nums">
              {r.ratings.map((rating) => (
                <li key={rating.dimension}>
                  {DIMENSION_LABEL[rating.dimension]} <span className="font-semibold">{rating.value}</span>/5
                  {rating.dimension === "cultural_risk" && <span className="text-muted-foreground"> (5 = most risk)</span>}
                  {rating.rationale && <span className="text-muted-foreground"> — {rating.rationale}</span>}
                </li>
              ))}
            </ul>
          </Row>
          <Row term="Confusion">
            <span className="tabular-nums">{r.confusion_level}</span>{" "}
            <span className="text-muted-foreground">on a 0–1 scale (0 = understood, 1 = not understood)</span>
          </Row>
          {r.potential_confusions.length > 0 && (
            <Row term="Potential confusions">
              <ul className="list-disc space-y-0.5 pl-4">
                {r.potential_confusions.map((confusion) => (
                  <li key={confusion}>{confusion}</li>
                ))}
              </ul>
            </Row>
          )}
          {r.risk_flags.length > 0 && (
            <Row term="Risk flags">
              <ul className="grid gap-1">
                {r.risk_flags.map((flag, i) => (
                  <li key={i}>
                    <span className={cn("font-medium", SEVERITY_TONE[flag.severity])}>{humanize(flag.severity)} risk</span>
                    {" · "}
                    {humanize(flag.category)}: {flag.description}{" "}
                    <span className="text-xs whitespace-nowrap text-muted-foreground">
                      ({flag.source === "deterministic_check" ? "Deterministic check" : "Model assessment"})
                    </span>
                  </li>
                ))}
              </ul>
            </Row>
          )}
          {r.relevant_passage && (
            <Row term="Relevant passage">
              <blockquote className="border-l-2 pl-2 italic">“{r.relevant_passage}”</blockquote>
            </Row>
          )}
          <Row term="Evidence">
            <div className="[contain:inline-size]">
<EvidenceLinks ids={r.evidence_ids} evidence={evidence} title={`Reaction ${no}`} />
</div>
          </Row>
        </dl>
      </article>
    </li>
  );
}

export function ReactionList({
  reactions,
  evidence,
  segment,
  sentiment,
  onSegment,
  onSentiment,
  highlight,
  onClearHighlight,
}: {
  reactions: SyntheticReaction[];
  evidence: EvidenceRecord[];
  segment: string;
  sentiment: Sentiment | "";
  onSegment: (segment: string) => void;
  onSentiment: (sentiment: Sentiment | "") => void;
  highlight: Highlight;
  onClearHighlight: () => void;
}) {
  const segments = [...new Set(reactions.map((r) => r.segment_label))];
  const numbered = reactions.map((reaction, i) => ({ reaction, no: i + 1 }));
  const visible = numbered.filter(
    ({ reaction }) => (!segment || reaction.segment_label === segment) && (!sentiment || reaction.sentiment === sentiment),
  );

  useEffect(() => {
    if (!highlight) return;
    const target = document.getElementById(`reaction-${highlight.focus}`);
    const reduce = window.matchMedia("(prefers-reduced-motion: reduce)").matches;
    target?.scrollIntoView({ behavior: reduce ? "auto" : "smooth", block: "center" });
    target?.focus({ preventScroll: true });
  }, [highlight]);

  return (
    <div className="@container grid gap-4">
      <div className="flex flex-wrap items-end gap-x-4 gap-y-3">
        <div className="grid gap-1">
          <Label htmlFor="filter-segment" className="text-xs">
            Segment
          </Label>
          <select id="filter-segment" className={SELECT} value={segment} onChange={(e) => onSegment(e.target.value)}>
            <option value="">All segments</option>
            {segments.map((label) => (
              <option key={label} value={label}>
                {label}
              </option>
            ))}
          </select>
        </div>
        <div className="grid gap-1">
          <Label htmlFor="filter-sentiment" className="text-xs">
            Sentiment
          </Label>
          <select
            id="filter-sentiment"
            className={SELECT}
            value={sentiment}
            onChange={(e) => onSentiment(e.target.value as Sentiment | "")}
          >
            <option value="">All sentiments</option>
            {SENTIMENTS.map((s) => (
              <option key={s} value={s}>
                {humanize(s)}
              </option>
            ))}
          </select>
        </div>
        <p aria-live="polite" className="pb-1.5 text-xs text-muted-foreground tabular-nums">
          Showing {visible.length} of {reactions.length}
        </p>
      </div>

      {highlight && (
        <div className="flex flex-wrap items-center gap-2 rounded-md bg-accent px-3 py-1.5 text-xs">
          Highlighting {highlight.ids.length} linked {highlight.ids.length === 1 ? "reaction" : "reactions"}.
          <Button type="button" variant="ghost" size="xs" onClick={onClearHighlight}>
            Clear
          </Button>
        </div>
      )}

      {visible.length === 0 ? (
        <p className="text-sm text-muted-foreground">No reactions match these filters.</p>
      ) : (
        <ul className="grid gap-3 @3xl:grid-cols-2">
          {visible.map(({ reaction, no }) => (
            <ReactionCard
              key={reaction.id}
              reaction={reaction}
              no={no}
              evidence={evidence}
              highlighted={Boolean(highlight?.ids.includes(reaction.id))}
            />
          ))}
        </ul>
      )}
    </div>
  );
}
