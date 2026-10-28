"use client";

import { ClaimBadge, ConfidenceBadge } from "@/components/evidence/badges";
import { useEvidenceInspector } from "@/components/evidence/evidence-inspector";
import { EvidenceLinks } from "@/components/evidence/evidence-links";
import { LimitationList } from "@/components/evidence/limitation-list";
import { Badge } from "@/components/ui/badge";
import type { BriefFinding, EvidenceRecord, MarketBrief as MarketBriefData } from "@/lib/api/types";

export const sectionHeading = "text-xl font-semibold tracking-tight";
export const panelHeading = "text-[15px] font-semibold";

export function BriefFindingList({
  findings,
  evidence,
  empty,
}: {
  findings: BriefFinding[];
  evidence: EvidenceRecord[];
  empty: string;
}) {
  const { inspect } = useEvidenceInspector();
  if (findings.length === 0) return <p className="text-sm text-muted-foreground">{empty}</p>;
  return (
    <ul className="divide-y">
      {findings.map((finding) => (
        <li key={finding.id} className="grid gap-1.5 py-3 first:pt-0 last:pb-0">
          <div className="flex flex-wrap items-center gap-x-2 gap-y-1">
            <button
              type="button"
              className="rounded-sm text-left font-medium underline-offset-4 outline-none hover:underline focus-visible:ring-3 focus-visible:ring-ring/50"
              onClick={() =>
                inspect({
                  title: finding.title,
                  summary: finding.explanation,
                  records: evidence.filter((record) => finding.evidence_ids.includes(record.id)),
                })
              }
            >
              {finding.title}
            </button>
            <ClaimBadge claim={finding.claim_type} />
            <ConfidenceBadge label={finding.confidence_label} />
          </div>
          <p className="text-sm text-muted-foreground">{finding.explanation}</p>
          <div className="[contain:inline-size]">
<EvidenceLinks ids={finding.evidence_ids} evidence={evidence} title={finding.title} />
</div>
          {finding.validation_question && (
            <p className="text-sm">
              <span className="text-muted-foreground">Validation question: </span>
              {finding.validation_question}
            </p>
          )}
        </li>
      ))}
    </ul>
  );
}

export function MarketBrief({ brief, evidence }: { brief: MarketBriefData | null; evidence: EvidenceRecord[] }) {
  return (
    <section aria-labelledby="brief-heading" className="grid gap-5">
      <div className="flex flex-wrap items-baseline gap-x-3 gap-y-1">
        <h2 id="brief-heading" className={sectionHeading}>
          Market brief
        </h2>
        {brief && <Badge variant="outline">Model-written summary</Badge>}
      </div>
      {!brief ? (
        <p className="text-sm text-muted-foreground">
          No market brief was generated for this run. The references below are what was retrieved.
        </p>
      ) : (
        <>
          <p className="max-w-prose rounded-lg border border-atlas/30 bg-atlas-soft px-4 py-3 text-base leading-relaxed text-ink">{brief.summary}</p>
          <div className="grid gap-8 lg:grid-cols-[minmax(0,3fr)_minmax(0,2fr)]">
            <section aria-labelledby="observations-heading" className="grid content-start gap-3">
              <h3 id="observations-heading" className={panelHeading}>
                Observations
              </h3>
              <BriefFindingList findings={brief.observations} evidence={evidence} empty="No observations were reported." />
            </section>
            <div className="grid content-start gap-6">
              <section aria-labelledby="questions-heading" className="grid gap-2">
                <h3 id="questions-heading" className={panelHeading}>
                  Open validation questions
                </h3>
                {brief.validation_questions.length === 0 ? (
                  <p className="text-sm text-muted-foreground">None were suggested.</p>
                ) : (
                  <ol className="list-decimal space-y-1.5 pl-5 text-sm">
                    {brief.validation_questions.map((question) => (
                      <li key={question}>{question}</li>
                    ))}
                  </ol>
                )}
              </section>
              <LimitationList title="Brief limitations" items={brief.limitations} />
            </div>
          </div>
        </>
      )}
    </section>
  );
}
