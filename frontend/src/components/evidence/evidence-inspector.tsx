"use client";

import { createContext, useContext, useMemo, useState, type ReactNode } from "react";

import { EvidenceLabel, RetrievalBadge } from "@/components/evidence/badges";
import { LimitationList } from "@/components/evidence/limitation-list";
import { Sheet, SheetContent, SheetDescription, SheetHeader, SheetTitle } from "@/components/ui/sheet";
import { useMediaQuery } from "@/hooks/use-media-query";
import type { EvidenceRecord } from "@/lib/api/types";
import { LABEL_MEANING, evidenceLabel } from "@/lib/evidence";
import { formatDateTime, humanize } from "@/lib/format";

export type InspectInput = {
  title: string;
  summary?: string;
  rationale?: string;
  /** Epistemic status of the rationale, e.g. "Model interpretation". */
  claimLabel?: string;
  records: EvidenceRecord[];
  limitations?: string[];
};

type InspectorApi = { inspect(input: InspectInput): void; close(): void };

const InspectorContext = createContext<InspectorApi | null>(null);

export function useEvidenceInspector(): InspectorApi {
  const ctx = useContext(InspectorContext);
  if (!ctx) throw new Error("useEvidenceInspector must be used inside EvidenceInspectorProvider (mounted by the project layout).");
  return ctx;
}

/** Shared evidence inspector: a right-hand sheet on desktop, a bottom drawer on small screens. */
export function EvidenceInspectorProvider({ children }: { children: ReactNode }) {
  const [input, setInput] = useState<InspectInput | null>(null);
  const [open, setOpen] = useState(false);
  const isMobile = useMediaQuery("(max-width: 767px)");
  const api = useMemo<InspectorApi>(
    () => ({
      inspect(next) {
        setInput(next);
        setOpen(true);
      },
      close: () => setOpen(false),
    }),
    [],
  );

  return (
    <InspectorContext.Provider value={api}>
      {children}
      <Sheet open={open} onOpenChange={setOpen}>
        <SheetContent
          side={isMobile ? "bottom" : "right"}
          className="gap-0 bg-surface data-[side=bottom]:max-h-[88dvh] data-[side=right]:w-full data-[side=right]:sm:max-w-[380px]"
        >
          {input && <InspectorBody input={input} />}
        </SheetContent>
      </Sheet>
    </InspectorContext.Provider>
  );
}

function InspectorBody({ input }: { input: InspectInput }) {
  return (
    <>
      <SheetHeader className="border-b border-border pr-12">
        <p className="text-[11px] font-medium tracking-wide text-ink-secondary uppercase">Evidence inspector</p>
        <SheetTitle className="text-[15px] font-semibold text-ink">{input.title}</SheetTitle>
        {input.summary && <SheetDescription className="text-[13px] text-ink-secondary">{input.summary}</SheetDescription>}
      </SheetHeader>
      <div className="flex-1 space-y-5 overflow-y-auto px-4 py-4">
        {input.rationale && (
          <section className="space-y-1">
            <h3 className="text-xs font-semibold text-ink">
              Rationale
              {input.claimLabel && <span className="font-normal text-ink-secondary"> · {input.claimLabel}</span>}
            </h3>
            <p className="text-[13px] leading-relaxed text-ink">{input.rationale}</p>
          </section>
        )}
        <LimitationList items={input.limitations ?? []} />
        <section className="space-y-3">
          <h3 className="text-xs font-semibold text-ink">
            Supporting records <span className="font-normal text-ink-secondary tabular-nums">({input.records.length})</span>
          </h3>
          {input.records.length === 0 ? (
            <p className="text-[13px] text-ink-secondary">No evidence records are linked to this item. Treat it as unsupported until it is validated.</p>
          ) : (
            input.records.map((record) => <RecordView key={record.id} record={record} />)
          )}
        </section>
      </div>
    </>
  );
}

function Entity({ entity }: { entity: NonNullable<EvidenceRecord["subject"]> }) {
  return (
    <span>
      {entity.name}
      {entity.entity_type && <span className="text-ink-secondary"> · {entity.entity_type}</span>}
      <span className="block font-mono text-[11px] break-all text-ink-secondary">{entity.entity_id ?? "No provider identifier returned"}</span>
    </span>
  );
}

function Row({ term, children }: { term: string; children: ReactNode }) {
  return (
    <>
      <dt className="text-ink-secondary">{term}</dt>
      <dd className="min-w-0 text-ink">{children}</dd>
    </>
  );
}

const FIXTURE_ORIGIN = { hand_authored: "Hand-authored fixture (not retrieved from the provider)", captured_live: "Sanitized capture of a real provider response" };

function RecordView({ record: r }: { record: EvidenceRecord }) {
  return (
    <article className="space-y-2.5 border-t border-border pt-3 first-of-type:border-t-0 first-of-type:pt-0">
      <div className="flex flex-wrap gap-1.5">
        <EvidenceLabel record={r} />
        <RetrievalBadge mode={r.retrieval_mode} retrievedAt={r.retrieved_at} />
      </div>
      <div className="space-y-0.5">
        <h4 className="text-sm font-medium text-ink">{r.title}</h4>
        <p className="text-[13px] leading-snug text-ink">{r.summary}</p>
        <p className="text-xs text-ink-secondary">{LABEL_MEANING[evidenceLabel(r)]}</p>
      </div>
      <dl className="grid grid-cols-[96px_minmax(0,1fr)] gap-x-3 gap-y-1.5 text-[13px]">
        <Row term="Provider">
          {r.source_provider}
          {r.source_workflow && <span className="font-mono text-xs text-ink-secondary"> · {r.source_workflow}</span>}
        </Row>
        {r.source_reference && (
          <Row term="Source ref.">
            <span className="font-mono text-xs break-all">{r.source_reference}</span>
          </Row>
        )}
        {r.subject && (
          <Row term="Subject">
            <Entity entity={r.subject} />
          </Row>
        )}
        {r.related_entity && (
          <Row term="Related">
            <Entity entity={r.related_entity} />
          </Row>
        )}
        <Row term="Method">{humanize(r.method)}</Row>
        <Row term="Retrieved">{r.retrieved_at ? formatDateTime(r.retrieved_at) : "Not recorded"}</Row>
        {r.source_run_id && (
          <Row term="Run">
            <span className="font-mono text-xs break-all">{r.source_run_id}</span>
          </Row>
        )}
      </dl>
      {r.attributes.length > 0 && (
        <section className="space-y-1.5">
          <h5 className="text-xs font-semibold text-ink">Returned attributes</h5>
          <ul className="divide-y divide-border rounded-md border border-border">
            {r.attributes.map((a) => (
              <li key={a.key} className="space-y-0.5 px-2.5 py-1.5">
                <div className="flex items-baseline justify-between gap-3 text-[13px]">
                  <span className="text-ink">{a.label}</span>
                  <span className="font-mono text-xs text-ink tabular-nums">{a.value === null ? "null" : String(a.value)}</span>
                </div>
                <p className="text-xs text-ink-secondary">{a.description ?? "The source did not describe this value's meaning."}</p>
              </li>
            ))}
          </ul>
        </section>
      )}
      <LimitationList items={r.limitations} title="Record limitations" />
      {r.provenance && (
        <dl className="grid grid-cols-[96px_minmax(0,1fr)] gap-x-3 gap-y-1 text-xs">
          {r.provenance.fixture_origin && <Row term="Fixture origin">{FIXTURE_ORIGIN[r.provenance.fixture_origin]}</Row>}
          {r.provenance.normalizer_version && (
            <Row term="Normalizer">
              <span className="font-mono">v{r.provenance.normalizer_version}</span>
            </Row>
          )}
          {r.provenance.request_hash && (
            <Row term="Request hash">
              <span className="font-mono break-all">{r.provenance.request_hash}</span>
            </Row>
          )}
          {r.provenance.response_hash && (
            <Row term="Response hash">
              <span className="font-mono break-all">{r.provenance.response_hash}</span>
            </Row>
          )}
        </dl>
      )}
      <details className="group text-xs">
        <summary className="cursor-pointer text-ink-secondary select-none hover:text-ink">Technical details</summary>
        <pre className="mt-1.5 max-h-64 overflow-auto rounded-md bg-surface-muted p-2 font-mono text-[11px] leading-snug text-ink">
          {JSON.stringify(r, null, 2)}
        </pre>
      </details>
    </article>
  );
}
