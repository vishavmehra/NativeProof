"use client";

import { ClaimBadge, ConfidenceBadge } from "@/components/evidence/badges";
import { useEvidenceInspector } from "@/components/evidence/evidence-inspector";
import { EvidenceLinks } from "@/components/evidence/evidence-links";
import { Button } from "@/components/ui/button";
import type { EvidenceRecord, Finding } from "@/lib/api/types";
import { CLAIM_LABEL } from "@/lib/evidence";
import { humanize } from "@/lib/format";

/** Reaction id → display number and segment, in result order. */
export type ReactionIndex = Map<string, { no: number; segment: string }>;
/** Highlight `ids` in the reaction list and scroll to `focus`. */
export type ShowReactions = (ids: string[], focus: string) => void;

export function ResponseLinks({
  ids,
  index,
  onShow,
  label = "Supporting reactions",
}: {
  ids: string[];
  index: ReactionIndex;
  onShow: ShowReactions;
  label?: string;
}) {
  // Only link reactions that exist in this result.
  const known = ids.filter((id) => index.has(id));
  if (known.length === 0) return <p className="text-xs text-muted-foreground">No linked reactions.</p>;
  return (
    <div className="flex flex-wrap items-center gap-1 text-xs">
      <span className="mr-1 text-muted-foreground">{label}:</span>
      {known.map((id) => {
        const { no, segment } = index.get(id)!;
        return (
          <Button
            key={id}
            type="button"
            variant="outline"
            size="xs"
            className="tabular-nums"
            aria-label={`Show reaction ${no} (${segment})`}
            onClick={() => onShow(known, id)}
          >
            #{no}
          </Button>
        );
      })}
    </div>
  );
}

export function FindingList({
  findings,
  evidence,
  index,
  onShow,
  empty,
}: {
  findings: Finding[];
  evidence: EvidenceRecord[];
  index: ReactionIndex;
  onShow: ShowReactions;
  empty: string;
}) {
  const { inspect } = useEvidenceInspector();
  if (findings.length === 0) return <p className="text-sm text-muted-foreground">{empty}</p>;
  return (
    <ul className="divide-y">
      {findings.map((finding) => (
        <li key={finding.id} className="grid gap-2 py-3 first:pt-0 last:pb-0">
          <div className="flex flex-wrap items-center gap-x-2 gap-y-1">
            <button
              type="button"
              className="rounded-sm text-left font-medium underline-offset-4 outline-none hover:underline focus-visible:ring-3 focus-visible:ring-ring/50"
              onClick={() =>
                inspect({
                  title: finding.title,
                  summary: finding.summary,
                  claimLabel: CLAIM_LABEL[finding.claim_type],
                  records: evidence.filter((record) => finding.evidence_ids.includes(record.id)),
                  limitations: finding.limitations,
                })
              }
            >
              {finding.title}
            </button>
            <ClaimBadge claim={finding.claim_type} />
            <ConfidenceBadge label={finding.confidence_label} />
            <span className="text-xs text-muted-foreground">{humanize(finding.category)}</span>
          </div>
          <p className="text-sm text-muted-foreground">{finding.summary}</p>
          <ResponseLinks ids={finding.supporting_response_ids} index={index} onShow={onShow} />
          <div className="[contain:inline-size]">
<EvidenceLinks ids={finding.evidence_ids} evidence={evidence} title={finding.title} />
</div>
          {finding.limitations.length > 0 && (
            <p className="text-xs text-muted-foreground">
              <span className="font-medium">Limitations:</span> {finding.limitations.join(" ")}
            </p>
          )}
        </li>
      ))}
    </ul>
  );
}
