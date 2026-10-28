"use client";

import { CircleCheckIcon, CircleHelpIcon, CircleSlashIcon } from "lucide-react";

import { useEvidenceInspector } from "@/components/evidence/evidence-inspector";
import { EvidenceLinks } from "@/components/evidence/evidence-links";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import type { CulturalReference, EvidenceRecord } from "@/lib/api/types";
import { cn } from "@/lib/utils";

const MATCH = {
  resolved: { label: "Resolved", Icon: CircleCheckIcon, tone: "text-success" },
  ambiguous: { label: "Ambiguous", Icon: CircleHelpIcon, tone: "text-warning" },
  unresolved: { label: "Unresolved", Icon: CircleSlashIcon, tone: "text-muted-foreground" },
} as const;

const formatValue = (value: string | number | boolean | null) => (value === null ? "Not returned" : String(value));

function matchSummary(ref: CulturalReference) {
  if (ref.match_status === "resolved")
    return `“${ref.query_term}” resolved to ${ref.entity_type ?? "entity"} ${ref.name}${ref.entity_id ? ` (${ref.entity_id})` : ""}.`;
  if (ref.match_status === "ambiguous")
    return `“${ref.query_term}” matched ${ref.candidates.length} candidates. Nativeproof did not choose one, so none is used downstream.`;
  return `No usable match was found for “${ref.query_term}”.`;
}

const term = "text-xs font-medium text-muted-foreground";

type Candidate = CulturalReference["candidates"][number];
export type ConfirmCandidate = (term: string, candidate: Candidate) => void;

function ReferenceRow({
  reference: ref,
  evidence,
  onRefine,
  onConfirm,
  busy,
}: {
  reference: CulturalReference;
  evidence: EvidenceRecord[];
  onRefine: () => void;
  onConfirm?: ConfirmCandidate;
  busy?: boolean;
}) {
  const { inspect } = useEvidenceInspector();
  const { label, Icon, tone } = MATCH[ref.match_status];
  const records = evidence.filter((record) => ref.evidence_ids.includes(record.id));
  const title = ref.name ?? `“${ref.query_term}”`;

  return (
    <li className="grid gap-3 py-4 md:grid-cols-[minmax(0,2fr)_minmax(0,3fr)] md:gap-8">
      <div className="grid content-start gap-1.5">
        <button
          type="button"
          className="w-fit rounded-sm text-left font-medium underline-offset-4 outline-none hover:underline focus-visible:ring-3 focus-visible:ring-ring/50"
          onClick={() =>
            inspect({
              title,
              summary: matchSummary(ref),
              rationale: ref.relevance_explanation ?? undefined,
              claimLabel: ref.relevance_explanation ? "Model interpretation" : undefined,
              records,
              limitations: ref.limitations,
            })
          }
        >
          {title}
        </button>
        {ref.name && <p className="text-xs text-muted-foreground">Query: “{ref.query_term}”</p>}
        <p className="flex flex-wrap items-center gap-x-3 gap-y-1 text-xs">
          <span className={cn("inline-flex items-center gap-1 font-medium", tone)}>
            <Icon aria-hidden className="size-3.5" />
            {label}
          </span>
          {ref.entity_type && <span className="text-muted-foreground">{ref.entity_type}</span>}
          {ref.entity_id && <code className="font-mono text-[11px] break-all text-muted-foreground">{ref.entity_id}</code>}
        </p>
      </div>

      <dl className="grid content-start gap-3 text-sm">
        {ref.match_status === "ambiguous" && (
          <div className="grid gap-2 rounded-md border border-warning/40 bg-warning-soft px-3 py-2.5">
            <dt className="font-medium">
              {ref.candidates.length} candidates returned; none was chosen.
            </dt>
            <dd className="grid gap-2">
              <ul className="grid gap-1">
                {ref.candidates.map((candidate) => (
                  <li key={candidate.entity_id ?? candidate.name} className="flex flex-wrap items-baseline gap-x-2">
                    {onConfirm && candidate.entity_id && (
                      <Button
                        type="button"
                        variant="outline"
                        size="xs"
                        disabled={busy}
                        aria-label={`Use ${candidate.name} for “${ref.query_term}” and run discovery again`}
                        onClick={() => onConfirm(ref.query_term, candidate)}
                      >
                        Use this
                      </Button>
                    )}
                    <span>{candidate.name}</span>
                    {candidate.entity_type && <span className="text-xs text-muted-foreground">{candidate.entity_type}</span>}
                    {candidate.entity_id && (
                      <code className="font-mono text-[11px] break-all text-muted-foreground">{candidate.entity_id}</code>
                    )}
                  </li>
                ))}
              </ul>
              <div className="flex flex-wrap items-center gap-x-3 gap-y-1">
                <span>
                  {onConfirm ? "Choose the intended match to rerun discovery with it, or refine the term." : "Refine the term and run discovery again."}
                </span>
                <Button type="button" variant="outline" size="sm" onClick={onRefine}>
                  Refine terms
                </Button>
              </div>
            </dd>
          </div>
        )}
        {ref.match_status === "unresolved" && (
          <div>
            <dt className="sr-only">Match</dt>
            <dd>No usable match was found for this term. Treat any reading of it as a hypothesis.</dd>
          </div>
        )}
        {ref.attributes.length > 0 && (
          <div className="grid gap-1">
            <dt className={term}>Source attributes</dt>
            <dd>
              <ul className="grid gap-1.5">
                {ref.attributes.map((attribute) => (
                  <li key={attribute.key}>
                    <span className="font-medium">{attribute.label}:</span>{" "}
                    <span className="tabular-nums">{formatValue(attribute.value)}</span>
                    {attribute.description && (
                      <span className="block text-xs text-muted-foreground">{attribute.description}</span>
                    )}
                  </li>
                ))}
              </ul>
            </dd>
          </div>
        )}
        {ref.relevance_explanation && (
          <div className="grid gap-1">
            <dt className={cn(term, "flex items-center gap-2")}>
              Why it may matter <Badge variant="outline">Model interpretation</Badge>
            </dt>
            <dd>{ref.relevance_explanation}</dd>
          </div>
        )}
        <div className="grid gap-1">
          <dt className={term}>Evidence</dt>
          <dd>
            <div className="[contain:inline-size]">
<EvidenceLinks ids={ref.evidence_ids} evidence={evidence} title={title} />
</div>
          </dd>
        </div>
        {ref.limitations.length > 0 && (
          <div className="grid gap-1">
            <dt className={term}>Limitations</dt>
            <dd>
              <ul className="list-disc space-y-0.5 pl-4 text-muted-foreground">
                {ref.limitations.map((limitation) => (
                  <li key={limitation}>{limitation}</li>
                ))}
              </ul>
            </dd>
          </div>
        )}
      </dl>
    </li>
  );
}

export function ReferenceTable({
  references,
  evidence,
  onRefine,
  onConfirm,
  busy,
}: {
  references: CulturalReference[];
  evidence: EvidenceRecord[];
  onRefine: () => void;
  onConfirm?: ConfirmCandidate;
  busy?: boolean;
}) {
  if (references.length === 0)
    return <p className="text-sm text-muted-foreground">No cultural references were returned for these inputs.</p>;
  return (
    <ul className="divide-y border-y">
      {references.map((reference) => (
        <ReferenceRow key={reference.id} reference={reference} evidence={evidence} onRefine={onRefine} onConfirm={onConfirm} busy={busy} />
      ))}
    </ul>
  );
}

/** "2 resolved · 1 ambiguous · 1 unresolved" */
export function matchCounts(references: CulturalReference[]) {
  return (["resolved", "ambiguous", "unresolved"] as const)
    .map((status) => [status, references.filter((r) => r.match_status === status).length] as const)
    .filter(([, count]) => count > 0)
    .map(([status, count]) => `${count} ${status}`)
    .join(" · ");
}

/** Dense one-line-per-reference list (Market Expansion columns). Each opens the inspector. */
export function SignalList({ references, evidence }: { references: CulturalReference[]; evidence: EvidenceRecord[] }) {
  const { inspect } = useEvidenceInspector();
  if (references.length === 0) return <p className="text-sm text-muted-foreground">No signals returned.</p>;
  return (
    <ul className="grid gap-1.5">
      {references.map((ref) => {
        const { label, Icon, tone } = MATCH[ref.match_status];
        const title = ref.name ?? `“${ref.query_term}”`;
        return (
          <li key={ref.id} className="grid gap-0.5">
            <button
              type="button"
              className="w-fit rounded-sm text-left text-sm font-medium underline-offset-4 outline-none hover:underline focus-visible:ring-3 focus-visible:ring-ring/50"
              onClick={() =>
                inspect({
                  title,
                  summary: matchSummary(ref),
                  rationale: ref.relevance_explanation ?? undefined,
                  claimLabel: ref.relevance_explanation ? "Model interpretation" : undefined,
                  records: evidence.filter((record) => ref.evidence_ids.includes(record.id)),
                  limitations: ref.limitations,
                })
              }
            >
              {title}
            </button>
            <span className={cn("inline-flex items-center gap-1 text-xs", tone)}>
              <Icon aria-hidden className="size-3" />
              {label}
              {ref.name && <span className="text-muted-foreground">· from “{ref.query_term}”</span>}
            </span>
          </li>
        );
      })}
    </ul>
  );
}
