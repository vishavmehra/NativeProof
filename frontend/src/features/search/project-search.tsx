"use client";

import { useQuery } from "@tanstack/react-query";
import { Search, X } from "lucide-react";
import { useRouter } from "next/navigation";
import { useEffect, useRef, useState, type FormEvent } from "react";

import { EvidenceLabel, RetrievalBadge } from "@/components/evidence/badges";
import { useEvidenceInspector } from "@/components/evidence/evidence-inspector";
import { ErrorState, LoadingState } from "@/components/states";
import { sectionHref } from "@/features/project/workflow";
import { api } from "@/lib/api/client";
import { unwrap } from "@/lib/api/errors";
import type { components } from "@/lib/api/schema";

type SearchHit = components["schemas"]["SearchHit"];

const KIND: Record<SearchHit["kind"], { label: string; segment: string | null }> = {
  evidence: { label: "Evidence", segment: null },
  brand_example: { label: "Brand example", segment: "brand" },
  risk_finding: { label: "Risk finding", segment: "risk-radar" },
  profile_item: { label: "Cultural DNA item", segment: "cultural-dna" },
  adaptation: { label: "Adaptation", segment: "voice" },
};

/**
 * Semantic search over the project's stored embeddings (GET /projects/{id}/search). Runs on submit, not per
 * keystroke. When embeddings are not configured the API says so and the panel shows that, never lexical guesses.
 */
export function ProjectSearch({ projectId, campaignId }: { projectId: string; campaignId?: string | null }) {
  const router = useRouter();
  const { inspect } = useEvidenceInspector();
  const [draft, setDraft] = useState("");
  const [query, setQuery] = useState("");
  const [open, setOpen] = useState(false);
  const rootRef = useRef<HTMLDivElement>(null);
  const inputRef = useRef<HTMLInputElement>(null);

  // Ctrl+K / ⌘K focuses search from anywhere in the workspace.
  useEffect(() => {
    const onKey = (e: KeyboardEvent) => {
      if ((e.ctrlKey || e.metaKey) && e.key.toLowerCase() === "k") {
        e.preventDefault();
        inputRef.current?.focus();
      }
    };
    document.addEventListener("keydown", onKey);
    return () => document.removeEventListener("keydown", onKey);
  }, []);

  const results = useQuery({
    queryKey: ["search", projectId, query],
    enabled: query.length > 0,
    staleTime: 60_000,
    queryFn: () => unwrap(api.GET("/api/v1/projects/{project_id}/search", { params: { path: { project_id: projectId }, query: { q: query, limit: 8 } } })),
  });

  useEffect(() => {
    if (!open) return;
    const onDown = (e: MouseEvent) => !rootRef.current?.contains(e.target as Node) && setOpen(false);
    const onKey = (e: KeyboardEvent) => e.key === "Escape" && setOpen(false);
    document.addEventListener("mousedown", onDown);
    document.addEventListener("keydown", onKey);
    return () => {
      document.removeEventListener("mousedown", onDown);
      document.removeEventListener("keydown", onKey);
    };
  }, [open]);

  function submit(e: FormEvent) {
    e.preventDefault();
    const q = draft.trim();
    if (!q) return;
    setQuery(q);
    setOpen(true);
  }

  async function openHit(hit: SearchHit) {
    setOpen(false);
    if (hit.kind === "evidence") {
      const record = await unwrap(api.GET("/api/v1/evidence/{evidence_id}", { params: { path: { evidence_id: hit.ref.id } } })).catch(() => null);
      inspect({ title: hit.title, summary: record ? undefined : "The evidence record could not be loaded.", records: record ? [record] : [] });
      return;
    }
    const segment = KIND[hit.kind].segment;
    if (segment) router.push(sectionHref(projectId, segment, campaignId));
  }

  const data = results.data;
  return (
    <div ref={rootRef} className="relative w-full sm:w-[360px]">
      <form role="search" onSubmit={submit} className="relative">
        <label htmlFor="project-search" className="sr-only">
          Search this project
        </label>
        <Search aria-hidden className="pointer-events-none absolute top-1/2 left-3.5 size-4 -translate-y-1/2 text-ink-secondary" />
        <input
          ref={inputRef}
          id="project-search"
          type="search"
          value={draft}
          onChange={(e) => setDraft(e.target.value)}
          onFocus={() => query && setOpen(true)}
          placeholder="Search projects, signals, or insights…"
          aria-keyshortcuts="Control+K Meta+K"
          className="h-11 w-full rounded-xl border border-border bg-surface pr-16 pl-10 text-[14px] text-ink shadow-card placeholder:text-ink-secondary"
        />
        <kbd aria-hidden className="pointer-events-none absolute top-1/2 right-2.5 -translate-y-1/2 rounded-md border border-border bg-surface-muted px-1.5 py-0.5 font-sans text-[11px] text-ink-secondary">
          Ctrl K
        </kbd>
      </form>
      {open && query && (
        <div className="absolute top-full right-0 z-40 mt-2 w-[min(28rem,calc(100vw-2rem))] overflow-hidden rounded-xl border border-border bg-surface shadow-raised">
          <div className="flex items-center justify-between border-b border-border px-3 py-2 text-xs text-ink-secondary">
            <span>
              Results for <span className="font-medium text-ink">“{query}”</span>
            </span>
            <button type="button" onClick={() => setOpen(false)} aria-label="Close search results" className="rounded p-0.5 hover:bg-surface-muted">
              <X aria-hidden className="size-3.5" />
            </button>
          </div>
          <div className="max-h-[60vh] overflow-y-auto">
            {results.isPending ? (
              <div className="px-3">
                <LoadingState label="Searching…" />
              </div>
            ) : results.error ? (
              <div className="p-3">
                <ErrorState error={results.error} onRetry={() => void results.refetch()} />
              </div>
            ) : data?.status === "unavailable" ? (
              <p className="px-3 py-4 text-[13px] text-ink-secondary">
                <span className="font-medium text-ink">Search is unavailable.</span> {data.message ?? "Semantic search needs an embedding model configured on the backend."}
              </p>
            ) : data && data.hits.length === 0 ? (
              <p className="px-3 py-4 text-[13px] text-ink-secondary">No stored evidence or findings are similar to this query.</p>
            ) : (
              <ul className="divide-y divide-border">
                {data?.hits.map((hit) => (
                  <li key={`${hit.kind}-${hit.id}`}>
                    <button type="button" onClick={() => void openHit(hit)} className="w-full space-y-1 px-3 py-2.5 text-left outline-none hover:bg-surface-muted focus-visible:bg-surface-muted">
                      <span className="flex flex-wrap items-center gap-1.5">
                        <span className="text-[11px] font-medium text-ink-secondary uppercase">{KIND[hit.kind].label}</span>
                        {hit.evidence_type && hit.claim_type && <EvidenceLabel record={{ evidence_type: hit.evidence_type, claim_type: hit.claim_type }} />}
                        {hit.retrieval_mode && <RetrievalBadge mode={hit.retrieval_mode} />}
                      </span>
                      <span className="block text-[13px] font-medium text-ink">{hit.title}</span>
                      <span className="line-clamp-2 block text-xs text-ink-secondary">{hit.snippet}</span>
                      <span className="block text-[11px] text-ink-secondary tabular-nums">Similarity {hit.similarity.toFixed(2)} · a ranking signal, not a probability</span>
                    </button>
                  </li>
                ))}
              </ul>
            )}
          </div>
          {data?.embedding_model && <p className="border-t border-border px-3 py-1.5 font-mono text-[11px] text-ink-secondary">{data.embedding_model}</p>}
        </div>
      )}
    </div>
  );
}
