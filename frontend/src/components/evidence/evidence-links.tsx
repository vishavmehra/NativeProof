"use client";

import { EvidenceLabel } from "@/components/evidence/badges";
import { useEvidenceInspector } from "@/components/evidence/evidence-inspector";
import type { EvidenceRecord } from "@/lib/api/types";
import { shortId } from "@/lib/format";

/** Evidence chips that open the inspector. Ids missing from `evidence` are shown as missing, never invented. */
export function EvidenceLinks({ ids, evidence, title }: { ids: string[]; evidence: EvidenceRecord[]; title: string }) {
  const { inspect } = useEvidenceInspector();
  if (ids.length === 0) return <p className="text-xs text-ink-secondary">No linked evidence</p>;
  const byId = new Map(evidence.map((e) => [e.id, e]));
  return (
    <ul className="flex flex-wrap gap-1.5" aria-label={`Evidence for ${title}`}>
      {ids.map((id) => {
        const record = byId.get(id);
        return (
          <li key={id} className="max-w-full min-w-0">
            {record ? (
              <button
                type="button"
                onClick={() => inspect({ title, records: [record] })}
                title={record.title}
                className="inline-flex max-w-full min-w-0 items-center gap-1.5 rounded-sm border border-border bg-surface py-0.5 pr-2 pl-0.5 text-xs text-ink outline-none hover:bg-surface-muted"
              >
                <EvidenceLabel record={record} />
                <span className="min-w-0 truncate">{record.title}</span>
              </button>
            ) : (
              <span
                className="inline-flex items-center gap-1.5 rounded-sm border border-dashed border-danger/40 px-1.5 py-0.5 text-xs text-danger"
                title="This evidence id is referenced but the record was not included in the response."
              >
                Missing record <code className="font-mono text-[11px]">{shortId(id)}</code>
              </span>
            )}
          </li>
        );
      })}
    </ul>
  );
}
