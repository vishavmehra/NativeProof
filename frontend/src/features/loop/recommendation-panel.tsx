import { CircleCheck, CircleHelp, PencilLine, Users } from "lucide-react";

import type { EvaluationResult, Recommendation } from "@/lib/api/types";
import { cn } from "@/lib/utils";

type Decision = Recommendation["decision"];

export const DECISION_COPY: Record<Decision, string> = {
  accept: "Accept for next review",
  revise: "Revise",
  validate: "Validate with real users",
  inconclusive: "Inconclusive",
};

const DECISION_MEANING: Record<Decision, string> = {
  accept: "Meets the documented criteria for the next internal review.",
  revise: "The identified issues should be addressed before going further.",
  validate: "The evidence is insufficient for a responsible decision. Test with real people.",
  inconclusive: "Inconclusive: required scores are missing, so rerun the evaluation.",
};

const DECISION_ICON = { accept: CircleCheck, revise: PencilLine, validate: Users, inconclusive: CircleHelp } as const;

/** The deterministic recommendation, the rule that produced it, and the full rule list (contracts/README §8). */
export function RecommendationPanel({ evaluation, headingAs: Heading = "h2" }: { evaluation: EvaluationResult; headingAs?: "h2" | "h3" }) {
  const rec = evaluation.recommendation;
  const rules = evaluation.scoring_definition.recommendation_rules;
  const subject = rec ? evaluation.results.find((r) => r.candidate_id === rec.candidate_id) : undefined;
  const Icon = rec ? DECISION_ICON[rec.decision] : CircleHelp;

  return (
    <section aria-labelledby="recommendation-heading" className="grid gap-4 rounded-card border border-border bg-surface shadow-card p-4 md:p-5">
      <div className="flex items-start gap-3">
        <Icon aria-hidden className="mt-1 size-5 shrink-0 text-ink" />
        <div className="grid gap-1">
          <p className="text-xs font-medium tracking-wide text-ink-secondary uppercase">Recommendation</p>
          <Heading id="recommendation-heading" className="text-xl font-semibold text-ink">
            {rec ? DECISION_COPY[rec.decision] : "No recommendation"}
            {subject && <span className="font-normal text-ink-secondary"> · {subject.label}</span>}
          </Heading>
          <p className="text-sm text-ink">
            {rec
              ? DECISION_MEANING[rec.decision]
              : "The evaluation did not produce a recommendation. Its limitations state what is missing."}
          </p>
        </div>
      </div>

      {rec && (
        <div className="grid gap-1">
          <p className="text-sm leading-relaxed text-ink">{rec.rationale}</p>
          <p className="text-xs text-ink-secondary">
            Rule <code className="font-mono text-ink">{rec.rule_id}</code> · scoring version{" "}
            <code className="font-mono text-ink">{evaluation.scoring_version}</code>
          </p>
        </div>
      )}
      <p className="text-sm font-medium text-ink">This is not proof of real-world campaign success.</p>

      <div className="grid gap-2">
        <h3 className="text-xs font-semibold text-ink">
          Decision rules <span className="font-normal text-ink-secondary">· deterministic, the first matching rule wins</span>
        </h3>
        <ol className="grid gap-1 text-xs">
          {rules.map((rule) => {
            const split = rule.indexOf(":");
            const id = split > 0 ? rule.slice(0, split) : rule;
            const text = split > 0 ? rule.slice(split + 1).trim() : "";
            const applied = rec?.rule_id === id;
            return (
              <li
                key={rule}
                className={cn(
                  "grid gap-x-2 rounded-sm px-2 py-1 sm:grid-cols-[minmax(0,13rem)_minmax(0,1fr)_auto]",
                  applied ? "bg-loop-soft text-ink" : "text-ink-secondary",
                )}
              >
                <code className="font-mono break-all">{id}</code>
                <span>{text}</span>
                {applied && <span className="font-semibold text-ink">Applied</span>}
              </li>
            );
          })}
        </ol>
      </div>
    </section>
  );
}
