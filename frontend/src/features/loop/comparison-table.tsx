"use client";

import { Info } from "lucide-react";
import { Fragment, useState } from "react";

import { ClaimBadge } from "@/components/evidence/badges";
import { Button } from "@/components/ui/button";
import { Tooltip, TooltipContent, TooltipTrigger } from "@/components/ui/tooltip";
import type { CandidateResult, EvaluationResult } from "@/lib/api/types";

import { DECISION_COPY } from "./recommendation-panel";

/** Score differences below this many points are not treated as meaningful (contracts/README §8, R3). */
export const MEANINGFUL_DIFFERENCE = 5;

export const formatScore = (value: number) => (Number.isInteger(value) ? String(value) : value.toFixed(1));

/** "Adaptation", or "Original" only when the label does not already say so (avoids "Original Original"). */
export const candidateType = (r: Pick<CandidateResult, "candidate_type" | "label">) =>
  r.candidate_type === "adaptation" ? "Adaptation" : r.label.trim().toLowerCase() === "original" ? null : "Original";

export function signedDelta(value: number) {
  return `${value > 0 ? "+" : value < 0 ? "−" : "±"}${formatScore(Math.abs(value))}`;
}

function Hint({ label, text }: { label: string; text: string }) {
  return (
    <Tooltip>
      <TooltipTrigger
        aria-label={`${label}: ${text}`}
        className="inline-flex rounded-sm text-ink-secondary outline-none hover:text-ink focus-visible:ring-2 focus-visible:ring-ring/50"
      >
        <Info aria-hidden className="size-3.5" />
      </TooltipTrigger>
      <TooltipContent className="max-w-72 text-left">{text}</TooltipContent>
    </Tooltip>
  );
}

function Score({ value }: { value: number | null }) {
  return value === null ? (
    <span className="text-ink-secondary italic">Not assessed</span>
  ) : (
    <span className="font-medium text-ink">{formatScore(value)}</span>
  );
}

function OverallDelta({ result, original }: { result: CandidateResult; original?: CandidateResult }) {
  if (result.candidate_type === "original" || result.overall_score === null || original?.overall_score == null) return null;
  const delta = Math.round((result.overall_score - original.overall_score) * 10) / 10;
  return (
    <span className="block text-xs font-normal text-ink-secondary">
      {signedDelta(delta)} vs original
      {Math.abs(delta) < MEANINGFUL_DIFFERENCE && " · not meaningful"}
    </span>
  );
}

/** Original plus candidates, scored per dimension. Values come only from the backend; null shows "Not assessed". */
export function ComparisonTable({ evaluation, headingAs: Heading = "h2" }: { evaluation: EvaluationResult; headingAs?: "h2" | "h3" }) {
  const [showRationales, setShowRationales] = useState(false);
  const { results, criteria, scoring_definition: scoring } = evaluation;
  const dimensions = scoring.dimensions;
  const original = results.find((r) => r.candidate_type === "original");
  const rec = evaluation.recommendation;

  const decisionTag = (r: CandidateResult) =>
    rec && rec.candidate_id === r.candidate_id ? (
      <span className="mt-1 inline-block rounded-sm border border-primary/30 bg-accent px-1.5 py-0.5 text-[11px] font-medium text-primary">
        {DECISION_COPY[rec.decision]}
      </span>
    ) : null;

  const rationale = (r: CandidateResult, d: (typeof dimensions)[number]["dimension"]) =>
    showRationales && (
      <span className="mt-1 block text-left text-xs font-normal whitespace-normal text-ink-secondary">
        {r.dimension_rationales[d] ?? "No rationale recorded."}
      </span>
    );

  return (
    <section aria-labelledby="comparison-heading" className="grid gap-3 rounded-card border border-border bg-surface shadow-card p-4 md:p-5">
      <div className="flex flex-wrap items-start justify-between gap-3">
        <div className="grid gap-1.5">
          <Heading id="comparison-heading" className="text-[15px] font-semibold text-ink">
            Candidate comparison
          </Heading>
          <p className="flex flex-wrap items-center gap-1.5 text-xs text-ink-secondary">
            Dimension scores ({scoring.scale}) <ClaimBadge claim="interpreted" /> Overall <ClaimBadge claim="derived" />
          </p>
        </div>
        <Button variant="outline" size="sm" aria-pressed={showRationales} onClick={() => setShowRationales((v) => !v)}>
          {showRationales ? "Hide rationales" : "Show rationales"}
        </Button>
      </div>

      {/* Desktop: aligned table. */}
      <table className="hidden w-full text-sm md:table">
        <caption className="sr-only">
          Scores for the original and each candidate. Cultural risk: higher means more risk. Differences under{" "}
          {MEANINGFUL_DIFFERENCE} points are not treated as meaningful.
        </caption>
        <thead>
          <tr className="border-b">
            <th scope="col" className="py-2 pr-3 text-left align-bottom text-xs font-medium text-ink-secondary">
              Criterion
            </th>
            {results.map((r) => (
              <th key={r.candidate_id} scope="col" className="px-3 py-2 text-right align-bottom">
                <span className="block text-sm font-semibold text-ink">{r.label}</span>
                <span className="block text-xs font-normal text-ink-secondary">
                  {candidateType(r)}
                </span>
                {decisionTag(r)}
              </th>
            ))}
          </tr>
        </thead>
        <tbody>
          {dimensions.map((d) => (
            <tr key={d.dimension} className="border-b align-top">
              <th scope="row" className="py-2.5 pr-3 text-left font-normal">
                <span className="flex items-center gap-1.5 font-medium text-ink">
                  {d.label}
                  <Hint label={d.label} text={d.definition} />
                </span>
                <span className="block text-xs text-ink-secondary">
                  Weight <span className="tabular-nums">{criteria[d.dimension].toFixed(2)}</span>
                  {!d.higher_is_better && " · higher means more risk"}
                </span>
              </th>
              {results.map((r) => (
                <td key={r.candidate_id} className="px-3 py-2.5 text-right tabular-nums">
                  <Score value={r.dimension_scores[d.dimension]} />
                  {rationale(r, d.dimension)}
                </td>
              ))}
            </tr>
          ))}
          <tr className="bg-surface-muted/50 align-top">
            <th scope="row" className="py-2.5 pr-3 text-left font-normal">
              <span className="flex items-center gap-1.5 font-semibold text-ink">
                Overall
                <Hint label="Overall" text={scoring.aggregation} />
              </span>
              <span className="block text-xs text-ink-secondary">Weighted utility, calculated</span>
            </th>
            {results.map((r) => (
              <td key={r.candidate_id} className="px-3 py-2.5 text-right text-base tabular-nums">
                <Score value={r.overall_score} />
                <OverallDelta result={r} original={original} />
              </td>
            ))}
          </tr>
        </tbody>
      </table>

      {/* Mobile: one block per candidate, no horizontal scrolling. */}
      <div className="grid gap-3 md:hidden">
        {results.map((r) => (
          <section key={r.candidate_id} aria-label={r.label} className="rounded-md border bg-surface p-3">
            <h3 className="text-sm font-semibold text-ink">
              {r.label}{" "}
              <span className="text-xs font-normal text-ink-secondary">
                {candidateType(r)}
              </span>
            </h3>
            {decisionTag(r)}
            <dl className="mt-2 grid grid-cols-[minmax(0,1fr)_auto] gap-x-3 gap-y-1.5 text-sm">
              {dimensions.map((d) => (
                <Fragment key={d.dimension}>
                  <dt className="text-ink">
                    {d.label}
                    {!d.higher_is_better && <span className="text-xs text-ink-secondary"> (higher = more risk)</span>}
                  </dt>
                  <dd className="text-right tabular-nums">
                    <Score value={r.dimension_scores[d.dimension]} />
                  </dd>
                  {showRationales && <dd className="col-span-2 -mt-1">{rationale(r, d.dimension)}</dd>}
                </Fragment>
              ))}
              <dt className="border-t pt-1.5 font-semibold text-ink">Overall</dt>
              <dd className="border-t pt-1.5 text-right tabular-nums">
                <Score value={r.overall_score} />
                <OverallDelta result={r} original={original} />
              </dd>
            </dl>
          </section>
        ))}
      </div>

      <p className="text-xs text-ink-secondary">
        Differences under {MEANINGFUL_DIFFERENCE} points are not treated as meaningful. Scores are model assessments of the text,
        not consumer measurements.
      </p>
      <details className="text-xs text-ink-secondary">
        <summary className="w-fit cursor-pointer select-none hover:text-ink">How the scores are defined</summary>
        <dl className="mt-2 grid gap-1.5 sm:grid-cols-[minmax(0,10rem)_minmax(0,1fr)]">
          {dimensions.map((d) => (
            <Fragment key={d.dimension}>
              <dt className="font-medium text-ink">{d.label}</dt>
              <dd>{d.definition}</dd>
            </Fragment>
          ))}
          <dt className="font-medium text-ink">Overall</dt>
          <dd>{scoring.aggregation}</dd>
        </dl>
      </details>
    </section>
  );
}
