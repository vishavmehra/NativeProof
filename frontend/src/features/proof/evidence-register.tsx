"use client";

import { EvidenceLabel, RetrievalBadge } from "@/components/evidence/badges";
import { useEvidenceInspector } from "@/components/evidence/evidence-inspector";
import type { EvidenceRecord } from "@/lib/api/types";
import { formatDateTime } from "@/lib/format";

/** Every evidence record a report used. Each row opens the shared inspector. */
export function EvidenceRegister({ records }: { records: EvidenceRecord[] }) {
  const { inspect } = useEvidenceInspector();
  if (records.length === 0) return <p className="text-sm text-ink-secondary">No evidence records were referenced.</p>;
  return (
    <ul className="divide-y divide-border border-y border-border">
      {records.map((r) => (
        <li key={r.id}>
          <button
            type="button"
            onClick={() => inspect({ title: r.title, records: [r] })}
            className="grid w-full gap-1.5 px-2 py-3 text-left outline-none hover:bg-surface-muted/60 focus-visible:ring-2 focus-visible:ring-ring/50 md:grid-cols-[minmax(0,1fr)_minmax(0,15rem)] md:gap-6"
          >
            <span className="grid gap-1">
              <span className="flex flex-wrap items-center gap-1.5">
                <EvidenceLabel record={r} />
                <RetrievalBadge mode={r.retrieval_mode} retrievedAt={r.retrieved_at} />
              </span>
              <span className="text-sm font-medium text-ink">{r.title}</span>
              <span className="text-[13px] text-ink-secondary">{r.summary}</span>
              {r.limitations.length > 0 && (
                <span className="text-xs text-ink-secondary">
                  <span className="font-medium text-ink">Limitations: </span>
                  {r.limitations.join(" · ")}
                </span>
              )}
            </span>
            <span className="grid content-start gap-0.5 text-xs text-ink-secondary">
              <span>
                {r.source_provider}
                {r.source_workflow && <code className="font-mono"> · {r.source_workflow}</code>}
              </span>
              <span>Retrieved {r.retrieved_at ? formatDateTime(r.retrieved_at) : "not recorded"}</span>
            </span>
          </button>
        </li>
      ))}
    </ul>
  );
}
