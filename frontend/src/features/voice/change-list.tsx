"use client";

import { Database, MessageSquareText, PencilLine } from "lucide-react";

import { Tag } from "@/components/evidence/badges";
import { EvidenceLinks } from "@/components/evidence/evidence-links";
import { useEvidenceInspector } from "@/components/evidence/evidence-inspector";
import { Button } from "@/components/ui/button";
import type { ContentChange, EvidenceRecord } from "@/lib/api/types";

export const FIELD_LABEL: Record<ContentChange["field"], string> = {
  headline: "Headline",
  body: "Body",
  call_to_action: "Call to action",
};

type Reasoning = ContentChange["reasoning_type"];

/** The label follows `reasoning_type` only: a change is never shown as evidence-supported unless the backend says so. */
export const REASONING = {
  evidence_supported: {
    label: "Evidence-supported",
    Icon: Database,
    className: "border-info/25 bg-info-soft text-info",
    uncertainty:
      "Linked evidence supports the rationale. An affinity signal still does not show that the new wording carries the same meaning.",
  },
  model_interpretation: {
    label: "Model interpretation",
    Icon: MessageSquareText,
    className: "border-dashed border-ink-secondary/50 bg-surface text-ink-secondary",
    uncertainty: "No source evidence directly supports this change. It is the model's reasoning and needs human review.",
  },
  user_edit: {
    label: "User edit",
    Icon: PencilLine,
    className: "border-border bg-surface-muted text-ink",
    uncertainty: "Made by a person in a revision. Deterministic checks reran; no model reviewed the edit.",
  },
} satisfies Record<Reasoning, unknown>;

export function ReasoningTag({ type }: { type: Reasoning }) {
  const { label, Icon, className } = REASONING[type];
  return (
    <Tag className={className}>
      <Icon aria-hidden />
      {label}
    </Tag>
  );
}

/** Field-level changes: original and proposed wording, why, the reasoning type, evidence, and what stays uncertain. */
export function ChangeList({
  changes,
  evidence,
  limitations = [],
}: {
  changes: ContentChange[];
  evidence: EvidenceRecord[];
  limitations?: string[];
}) {
  const { inspect } = useEvidenceInspector();
  if (changes.length === 0) return <p className="text-sm text-ink-secondary">No field changes were recorded for this version.</p>;
  const byId = new Map(evidence.map((e) => [e.id, e]));

  return (
    <ol className="divide-y divide-border">
      {changes.map((change, i) => {
        const field = FIELD_LABEL[change.field];
        const reasoning = REASONING[change.reasoning_type];
        return (
          <li key={i} className="grid gap-2.5 py-3.5 first:pt-0 last:pb-0">
            <div className="flex flex-wrap items-center gap-2">
              <h4 className="text-[13px] font-semibold text-ink">{field}</h4>
              <ReasoningTag type={change.reasoning_type} />
            </div>
            <dl className="grid grid-cols-[72px_minmax(0,1fr)] gap-x-3 gap-y-1 text-sm">
              <dt className="text-xs leading-5 text-ink-secondary">Original</dt>
              <dd className="text-ink-secondary">{change.original ?? <em>Not provided</em>}</dd>
              <dt className="text-xs leading-5 text-ink-secondary">Proposed</dt>
              <dd className="text-ink">{change.adapted ?? <em className="text-ink-secondary">Removed</em>}</dd>
            </dl>
            <p className="text-[13px] leading-snug text-ink">
              <span className="font-medium">Why: </span>
              {change.reason}
            </p>
            <p className="text-xs text-ink-secondary">
              <span className="font-medium text-ink">Uncertainty: </span>
              {reasoning.uncertainty}
            </p>
            <div className="flex flex-wrap items-center justify-between gap-2">
              <EvidenceLinks ids={change.evidence_ids} evidence={evidence} title={`${field} change`} />
              <Button
                variant="ghost"
                size="xs"
                onClick={() =>
                  inspect({
                    title: `${field} change`,
                    summary: `“${change.original ?? "Not provided"}” → “${change.adapted ?? "Removed"}”`,
                    rationale: change.reason,
                    claimLabel: reasoning.label,
                    records: change.evidence_ids.flatMap((id) => byId.get(id) ?? []),
                    limitations: [reasoning.uncertainty, ...limitations],
                  })
                }
              >
                Inspect change
              </Button>
            </div>
          </li>
        );
      })}
    </ol>
  );
}
