"use client";

import { CircleAlert, CircleCheck } from "lucide-react";

import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import type { EvaluationCriteria } from "@/lib/api/types";
import { cn } from "@/lib/utils";

export const DIMENSIONS = ["clarity", "brand_fidelity", "cultural_relevance", "cultural_risk"] as const;
type Dimension = (typeof DIMENSIONS)[number];

export const DIMENSION_LABEL: Record<Dimension, string> = {
  clarity: "Clarity",
  brand_fidelity: "Brand fidelity",
  cultural_relevance: "Cultural relevance",
  cultural_risk: "Cultural risk",
};

/** Raw input text per weight, so partial entries like "0." stay editable. */
export type CriteriaDraft = Record<Dimension, string>;

export const toDraft = (c: EvaluationCriteria) =>
  Object.fromEntries(DIMENSIONS.map((d) => [d, String(c[d])])) as CriteriaDraft;

/** Unparseable entries become NaN, which fails validation. */
export const parseDraft = (draft: CriteriaDraft) =>
  Object.fromEntries(DIMENSIONS.map((d) => [d, draft[d].trim() === "" ? NaN : Number(draft[d])])) as EvaluationCriteria;

const total = (c: EvaluationCriteria) => DIMENSIONS.reduce((sum, d) => sum + c[d], 0);

/** contracts/README §8: weights must sum to 1.0 within 0.001. Invalid weights are rejected, never normalized. */
export const criteriaValid = (c: EvaluationCriteria) =>
  DIMENSIONS.every((d) => c[d] >= 0 && c[d] <= 1) && Math.abs(total(c) - 1) <= 0.001;

export function formatWeights(c: EvaluationCriteria) {
  return DIMENSIONS.map((d) => `${DIMENSION_LABEL[d]} ${c[d].toFixed(2)}`).join(" · ");
}

export function CriteriaEditor({
  value,
  defaults,
  onChange,
}: {
  value: CriteriaDraft;
  defaults: EvaluationCriteria;
  onChange(next: CriteriaDraft): void;
}) {
  const parsed = parseDraft(value);
  const sum = total(parsed);
  const valid = criteriaValid(parsed);
  const outOfRange = DIMENSIONS.some((d) => !(parsed[d] >= 0 && parsed[d] <= 1));

  return (
    <fieldset className="grid gap-3" aria-describedby="criteria-total">
      <legend className="mb-1 text-sm font-medium text-ink">Criteria weights</legend>
      <div className="grid gap-3 sm:grid-cols-2 lg:grid-cols-4">
        {DIMENSIONS.map((d) => (
          <div key={d} className="grid content-start gap-1.5">
            <Label htmlFor={`weight-${d}`}>{DIMENSION_LABEL[d]}</Label>
            <Input
              id={`weight-${d}`}
              type="number"
              inputMode="decimal"
              step="0.05"
              min="0"
              max="1"
              value={value[d]}
              aria-invalid={!(parsed[d] >= 0 && parsed[d] <= 1) || undefined}
              aria-describedby={d === "cultural_risk" ? "weight-risk-desc" : undefined}
              onChange={(e) => onChange({ ...value, [d]: e.target.value })}
              className="bg-surface tabular-nums"
            />
            {d === "cultural_risk" && (
              <p id="weight-risk-desc" className="text-xs text-ink-secondary">
                Applied to 100 − risk, so lower risk adds more.
              </p>
            )}
          </div>
        ))}
      </div>
      <div className="flex flex-wrap items-center justify-between gap-2">
        <p
          id="criteria-total"
          role="status"
          aria-live="polite"
          className={cn("flex items-center gap-1.5 text-sm", valid ? "text-ink" : "font-medium text-danger")}
        >
          {valid ? (
            <CircleCheck aria-hidden className="size-4 text-success" />
          ) : (
            <CircleAlert aria-hidden className="size-4" />
          )}
          <span>
            Total <span className="tabular-nums">{Number.isFinite(sum) ? sum.toFixed(2) : "n/a"}</span>.{" "}
            {valid
              ? "Weights are valid."
              : outOfRange
                ? "Each weight must be a number from 0 to 1."
                : "Weights must total 1.00 (±0.001). They are never normalized automatically."}
          </span>
        </p>
        <Button type="button" variant="ghost" size="sm" onClick={() => onChange(toDraft(defaults))}>
          Reset to campaign weights
        </Button>
      </div>
    </fieldset>
  );
}
