import { CircleCheck, CircleHelp, PencilLine, Users } from "lucide-react";
import type { ReactNode } from "react";

import { ConfidenceBadge } from "@/components/evidence/badges";
import type { EvaluationResult, Recommendation } from "@/lib/api/types";

import { MEANINGFUL_DIFFERENCE, formatScore, signedDelta } from "./comparison-table";

type Decision = Recommendation["decision"];

const VERDICT: Record<Decision, string> = {
  accept: "Accept for next review",
  revise: "Revise",
  validate: "Validate with people",
  inconclusive: "Inconclusive",
};

const ICON = { accept: CircleCheck, revise: PencilLine, validate: Users, inconclusive: CircleHelp } as const;

/** The mvp-1 rules in plain words (contracts/README §8). Unknown ids fall back to the backend's own rule text. */
const RULE_PLAIN: Record<string, string> = {
  R0_missing_scores: "A required score is missing for the original or the leading candidate.",
  R1_constraint_or_risk: "The leading candidate breaks a constraint, has a high-severity risk, or scores 60 or more on cultural risk.",
  R2_no_improvement: "No candidate beats the original's overall score.",
  R3_small_margin: `The leading candidate beats the original by fewer than ${MEANINGFUL_DIFFERENCE} points, which is not a meaningful difference.`,
  R4_meets_review_threshold: "The leading candidate scores at least 70 overall with cultural risk under 40.",
  R5_default: "No stronger rule applied, so the scores alone cannot settle it.",
};

export const NEXT_STEP: Record<Decision, string> = {
  accept: "Validate with real people before launch: test the original and this version with the target audience.",
  revise: "Address the flagged issues in Voice, then evaluate again.",
  validate: "Validate with real people. These scores cannot separate the versions responsibly.",
  inconclusive: "Rerun the evaluation with candidates that can be scored, then validate with real people.",
};

/** One-glance verdict: decision, leading version, score change, evidence quality, rule, and next step. */
export function VerdictBlock({ evaluation, actions }: { evaluation: EvaluationResult; actions?: ReactNode }) {
  const rec = evaluation.recommendation;
  if (!rec) return null;
  const original = evaluation.results.find((r) => r.candidate_type === "original");
  const subject = rec.candidate_id ? evaluation.results.find((r) => r.candidate_id === rec.candidate_id) : undefined;
  const delta =
    subject?.overall_score != null && original?.overall_score != null && subject !== original
      ? Math.round((subject.overall_score - original.overall_score) * 10) / 10
      : null;
  const ruleText =
    RULE_PLAIN[rec.rule_id] ??
    evaluation.scoring_definition.recommendation_rules.find((r) => r.startsWith(`${rec.rule_id}:`))?.split(":").slice(1).join(":").trim() ??
    "A documented scoring rule produced this decision.";
  const Icon = ICON[rec.decision];

  return (
    <section aria-labelledby="verdict-heading" className="grid gap-4 rounded-card border border-loop/30 bg-surface p-5 shadow-card md:p-6">
      <div className="flex flex-wrap items-start justify-between gap-4">
        <div className="flex min-w-0 items-start gap-3">
          <span className="flex size-10 shrink-0 items-center justify-center rounded-lg border border-loop/30 bg-loop-soft">
            <Icon aria-hidden className="size-5 text-loop-ink" />
          </span>
          <div className="grid min-w-0 gap-1">
            <p className="text-[11px] font-semibold tracking-[0.08em] text-loop-ink uppercase">Verdict</p>
            <h2 id="verdict-heading" className="font-serif text-2xl leading-tight text-ink">
              {VERDICT[rec.decision]}
            </h2>
            {subject && (
              <p className="text-sm text-ink">
                <span className="font-medium">{subject.label}</span>
                {subject.content.headline && <span className="text-ink-secondary">: “{subject.content.headline}”</span>}
              </p>
            )}
          </div>
        </div>
        {actions && <div className="flex flex-wrap gap-2">{actions}</div>}
      </div>

      <dl className="grid grid-cols-[minmax(0,1fr)] gap-x-8 gap-y-3 text-sm sm:grid-cols-2 lg:grid-cols-4">
        <div className="grid gap-0.5">
          <dt className="text-xs text-ink-secondary">Score change against the original</dt>
          <dd className="text-ink tabular-nums">
            {delta === null ? (
              "Not available: a score is missing"
            ) : (
              <>
                <span className="font-semibold">{signedDelta(delta)}</span> ({formatScore(subject!.overall_score!)} vs{" "}
                {formatScore(original!.overall_score!)})
                {Math.abs(delta) < MEANINGFUL_DIFFERENCE && <span className="text-ink-secondary">, not meaningful</span>}
              </>
            )}
          </dd>
        </div>
        <div className="grid gap-0.5">
          <dt className="text-xs text-ink-secondary">Evidence quality</dt>
          <dd className="flex flex-wrap items-center gap-1.5 text-ink">
            <ConfidenceBadge label={rec.decision === "inconclusive" ? "insufficient" : "limited"} />
            <span className="text-xs text-ink-secondary">model assessments of the text</span>
          </dd>
        </div>
        <div className="grid gap-0.5 sm:col-span-2">
          <dt className="text-xs text-ink-secondary">Why</dt>
          <dd className="text-ink">{ruleText}</dd>
        </div>
      </dl>

      <p className="rounded-lg bg-surface-muted/70 px-3 py-2 text-sm text-ink">
        <span className="font-semibold">Next step: </span>
        {NEXT_STEP[rec.decision]} This is not proof of real-world campaign success.
      </p>
    </section>
  );
}
