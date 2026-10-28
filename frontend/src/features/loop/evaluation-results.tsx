"use client";

import { CircleCheck, FileText, TriangleAlert } from "lucide-react";
import Link from "next/link";
import type { ReactNode } from "react";

import { buttonVariants } from "@/components/ui/button";

import { ClaimBadge } from "@/components/evidence/badges";
import { EvidenceLinks } from "@/components/evidence/evidence-links";
import { LimitationList } from "@/components/evidence/limitation-list";
import { Panel } from "@/features/voice/field";
import { DeterministicTag, RiskFlagList } from "@/features/voice/risk-flags";
import type { CandidateResult, EvaluationResult } from "@/lib/api/types";
import { formatDateTime, shortId } from "@/lib/format";
import { cn } from "@/lib/utils";

import { ComparisonTable, MEANINGFUL_DIFFERENCE, candidateType, signedDelta } from "./comparison-table";
import { formatWeights } from "./criteria-editor";
import { RecommendationPanel } from "./recommendation-panel";
import { VerdictBlock } from "./verdict";

const FIVE_POINT_NOTE = `Differences under ${MEANINGFUL_DIFFERENCE} points are not treated as meaningful.`;

/** Backend limitations, plus the 5-point rule when the backend did not already state it. */
export const withFivePointNote = (items: string[]) =>
  items.some((item) => /under 5 points/i.test(item)) ? items : [...items, FIVE_POINT_NOTE];

export function EvaluationHeader({
  evaluation,
  campaignName,
  versionNumber,
}: {
  evaluation: EvaluationResult;
  campaignName: string;
  versionNumber?: number;
}) {
  return (
    <dl className="grid gap-x-8 gap-y-3 text-sm sm:grid-cols-2 lg:grid-cols-3">
      <Item term="Campaign">{campaignName}</Item>
      <Item term="Market">
        {evaluation.market.display_name} <span className="font-mono text-xs text-ink-secondary">{evaluation.market.country_code}</span>
      </Item>
      <Item term="Source version">
        {versionNumber ? `Version ${versionNumber} ` : null}
        <span className="font-mono text-xs text-ink-secondary">{shortId(evaluation.source_content_version_id)}</span>
      </Item>
      <Item term="Evaluated">{formatDateTime(evaluation.created_at)}</Item>
      <Item term="Scoring version">
        <span className="font-mono">{evaluation.scoring_version}</span>
      </Item>
      <Item term="Run">
        <span className="font-mono text-xs">{shortId(evaluation.run_id)}</span>
      </Item>
      <Item term="Criteria and weights" className="sm:col-span-2 lg:col-span-3">
        <span className="tabular-nums">{formatWeights(evaluation.criteria)}</span>
      </Item>
    </dl>
  );
}

function Item({ term, className, children }: { term: string; className?: string; children: ReactNode }) {
  return (
    <div className={cn("grid gap-0.5", className)}>
      <dt className="text-xs text-ink-secondary">{term}</dt>
      <dd className="text-ink">{children}</dd>
    </div>
  );
}

function Bullets({ title, items }: { title: string; items: string[] }) {
  return (
    <div className="grid gap-1">
      <h4 className="text-xs font-semibold text-ink">{title}</h4>
      {items.length ? (
        <ul className="list-disc space-y-0.5 pl-4 text-[13px] leading-snug text-ink">
          {items.map((item, i) => (
            <li key={i}>{item}</li>
          ))}
        </ul>
      ) : (
        <p className="text-xs text-ink-secondary">None stated.</p>
      )}
    </div>
  );
}

/** Per-dimension movement against the original, calculated from the backend scores. */
function VersusOriginal({ result, original, evaluation }: { result: CandidateResult; original: CandidateResult; evaluation: EvaluationResult }) {
  const rows = evaluation.scoring_definition.dimensions.map((d) => {
    const a = result.dimension_scores[d.dimension];
    const b = original.dimension_scores[d.dimension];
    if (a === null || b === null) return { label: d.label, text: "not comparable: score missing" };
    const delta = Math.round((a - b) * 10) / 10;
    const better = d.higher_is_better ? delta > 0 : delta < 0;
    const verdict =
      Math.abs(delta) < MEANINGFUL_DIFFERENCE
        ? "no meaningful change"
        : d.higher_is_better
          ? better ? "improved" : "regressed"
          : better ? "less risk" : "more risk";
    return { label: d.label, text: `${signedDelta(delta)} · ${verdict}` };
  });
  return (
    <div className="grid gap-1">
      <h4 className="text-xs font-semibold text-ink">Versus the original</h4>
      <ul className="grid gap-0.5 text-[13px] text-ink">
        {rows.map((row) => (
          <li key={row.label} className="flex justify-between gap-3">
            <span className="text-ink-secondary">{row.label}</span>
            <span className="tabular-nums">{row.text}</span>
          </li>
        ))}
      </ul>
    </div>
  );
}

const COLUMNS: Record<number, string> = { 2: "md:grid-cols-2", 3: "md:grid-cols-2 xl:grid-cols-3", 4: "md:grid-cols-2 xl:grid-cols-4" };

export function TradeoffAnalysis({ evaluation }: { evaluation: EvaluationResult }) {
  const original = evaluation.results.find((r) => r.candidate_type === "original");
  return (
    <Panel id="tradeoffs-heading" title="Trade-off analysis">
      <p className="mb-4 flex flex-wrap items-center gap-1.5 text-xs text-ink-secondary">
        Strengths, weaknesses, and trade-offs <ClaimBadge claim="interpreted" /> Movement against the original{" "}
        <ClaimBadge claim="derived" /> Constraint violations <DeterministicTag />
      </p>
      <div className={cn("grid gap-4", COLUMNS[evaluation.results.length])}>
        {evaluation.results.map((r) => (
          <section key={r.candidate_id} aria-label={r.label} className="grid content-start gap-3 rounded-md border bg-surface p-3">
            <h3 className="text-sm font-semibold text-ink">
              {r.label}{" "}
              <span className="text-xs font-normal text-ink-secondary">{candidateType(r)}</span>
            </h3>
            {original && r.candidate_type === "adaptation" && <VersusOriginal result={r} original={original} evaluation={evaluation} />}
            <Bullets title="Strengths" items={r.strengths} />
            <Bullets title="Weaknesses" items={r.weaknesses} />
            <Bullets title="Trade-offs" items={r.tradeoffs} />
            <div className="grid gap-1">
              <h4 className="text-xs font-semibold text-ink">Risk flags</h4>
              <RiskFlagList flags={r.risk_flags} empty="None raised." />
            </div>
            <div className="grid gap-1">
              <h4 className="text-xs font-semibold text-ink">Constraint violations</h4>
              {r.constraint_violations.length ? (
                <ul className="list-disc space-y-0.5 pl-4 text-[13px] text-danger">
                  {r.constraint_violations.map((v, i) => (
                    <li key={i}>{v}</li>
                  ))}
                </ul>
              ) : (
                <p className="text-xs text-ink-secondary">None.</p>
              )}
            </div>
            <div className="grid gap-1">
              <h4 className="text-xs font-semibold text-ink">Evidence</h4>
              <EvidenceLinks ids={r.evidence_ids} evidence={evaluation.evidence} title={r.label} />
            </div>
          </section>
        ))}
      </div>
    </Panel>
  );
}

const FLAGS = [
  ["same_market", "Same market configuration"],
  ["same_criteria", "Same criteria and weights"],
  ["same_source_version", "Same source version"],
  ["same_scoring_version", "Same scoring version"],
  ["same_evidence_context", "Comparable evidence context"],
  ["same_model", "Same assessing model"],
] as const;

export function IntegrityPanel({ comparability, headingAs }: { comparability: EvaluationResult["comparability"]; headingAs?: "h2" | "h3" }) {
  const differing = FLAGS.filter(([key]) => !comparability[key]).length;
  return (
    <Panel id="integrity-heading" title="Evaluation integrity" headingAs={headingAs}>
      {differing > 0 && (
        <p className="mb-3 flex items-center gap-1.5 text-sm font-medium text-warning">
          <TriangleAlert aria-hidden className="size-4" />
          {differing} {differing === 1 ? "condition differs" : "conditions differ"} between candidates. Treat score differences with
          extra caution.
        </p>
      )}
      <ul className="grid gap-2 sm:grid-cols-2">
        {FLAGS.map(([key, label]) => {
          const ok = comparability[key];
          return (
            <li
              key={key}
              className={cn(
                "flex items-center gap-2 rounded-md border px-3 py-2 text-sm text-ink",
                ok ? "border-border bg-surface" : "border-warning/40 bg-warning-soft",
              )}
            >
              {ok ? (
                <CircleCheck aria-hidden className="size-4 shrink-0 text-success" />
              ) : (
                <TriangleAlert aria-hidden className="size-4 shrink-0 text-warning" />
              )}
              <span className="flex-1">{label}</span>
              <span className={cn("text-xs font-medium", ok ? "text-ink-secondary" : "text-warning")}>{ok ? "Yes" : "Differs"}</span>
            </li>
          );
        })}
      </ul>
      {comparability.notes.length > 0 && (
        <ul className="mt-3 list-disc space-y-0.5 pl-5 text-[13px] text-ink">
          {comparability.notes.map((note, i) => (
            <li key={i}>{note}</li>
          ))}
        </ul>
      )}
    </Panel>
  );
}

export function EvaluationResults({
  evaluation,
  campaignName,
  versionNumber,
  reportHref,
}: {
  evaluation: EvaluationResult;
  campaignName: string;
  versionNumber?: number;
  reportHref?: string;
}) {
  return (
    <div className="grid gap-6">
      <VerdictBlock
        evaluation={evaluation}
        actions={
          reportHref && (
            <Link className={buttonVariants({ size: "lg" })} href={reportHref}>
              <FileText aria-hidden />
              Create report
            </Link>
          )
        }
      />
      <Panel
        id="evaluation-heading"
        title={evaluation.status === "partial" ? "Evaluation results (partial)" : "Evaluation results"}
      >
        <EvaluationHeader evaluation={evaluation} campaignName={campaignName} versionNumber={versionNumber} />
      </Panel>
      <ComparisonTable evaluation={evaluation} />
      <RecommendationPanel evaluation={evaluation} />
      <TradeoffAnalysis evaluation={evaluation} />
      <IntegrityPanel comparability={evaluation.comparability} />
      <LimitationList items={withFivePointNote(evaluation.limitations)} />
    </div>
  );
}
