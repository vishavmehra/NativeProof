"use client";

import { useQueryClient } from "@tanstack/react-query";
import { useEffect, useState } from "react";

import { ErrorState, LoadingState } from "@/components/states";
import { RunStatusPanel } from "@/components/workflow/run-status";
import { Button } from "@/components/ui/button";
import { Label } from "@/components/ui/label";
import { hasResult, useRunFlow } from "@/features/atlas/api";
import { PageHeader } from "@/features/atlas/page-header";
import type { ConfirmCandidate } from "@/features/atlas/reference-table";
import { useProject } from "@/features/project/project-context";
import { formatDateTime } from "@/lib/format";

import type { MarketComparisonCreate } from "@/lib/api/types";

import { marketKeys, useComparison, useComparisons, useStartComparison } from "./api";
import { ComparisonForm } from "./comparison-form";
import { ComparisonView } from "./comparison-view";

export function MarketsWorkspace() {
  const { project, campaign } = useProject();
  const queryClient = useQueryClient();
  const listQuery = useComparisons(project.id);
  const flow = useRunFlow(project.id, "market_comparison");
  const start = useStartComparison(project.id);
  const [selectedId, setSelectedId] = useState<string | null>(null);
  const [formOpen, setFormOpen] = useState(false);
  const [lastBody, setLastBody] = useState<MarketComparisonCreate | null>(null);

  const finishedId = hasResult(flow.run) ? flow.run?.result?.ids[0] : undefined;
  useEffect(() => {
    if (finishedId) queryClient.invalidateQueries({ queryKey: marketKeys.list(project.id) });
  }, [finishedId, project.id, queryClient]);

  const summaries = listQuery.data?.items ?? [];
  const comparisonId = selectedId ?? finishedId ?? summaries.find((s) => hasResult(s))?.id ?? null;
  const comparisonQuery = useComparison(comparisonId);

  function submit(body: MarketComparisonCreate) {
    setLastBody(body);
    start.mutate(body, {
      onSuccess: (accepted) => {
        flow.setStartedRunId(accepted.run_id);
        setSelectedId(null);
        setFormOpen(false);
      },
    });
  }

  /** Rerun with the person's choice for an ambiguous term, as Atlas does. Qloo tag matching does not depend on the
   * market, so one confirmation applies to every market; a later choice for the same term replaces it. */
  const confirm: ConfirmCandidate = (term, candidate) => {
    const c = comparisonQuery.data;
    const base: MarketComparisonCreate | null =
      lastBody ??
      (c
        ? {
            markets: c.markets,
            campaign_id: c.campaign_id,
            product_category: c.product_category,
            research_question: c.research_question,
            reference_terms: c.reference_terms,
            confirmed_references: c.confirmed_references ?? [],
          }
        : null);
    if (!base || !candidate.entity_id) return;
    const kind = candidate.entity_type?.toLowerCase().includes("tag") ? "tag" : "entity";
    const terms = base.reference_terms ?? [];
    const listed = terms.find((t) => t.toLowerCase() === term.toLowerCase());
    const isCategory = base.product_category.toLowerCase() === term.toLowerCase();
    const confirmedTerm = listed ?? (isCategory ? base.product_category : term);
    submit({
      ...base,
      reference_terms: listed || isCategory ? terms : [...terms, term],
      confirmed_references: [
        ...(base.confirmed_references ?? []).filter((x) => x.term.toLowerCase() !== confirmedTerm.toLowerCase()),
        { term: confirmedTerm, ref_id: candidate.entity_id, ref_kind: kind },
      ],
    });
  };

  const header = (
    <PageHeader
      feature="markets"
      description="Run the same discovery in two to five markets and read the evidence side by side: signals, opportunities, risks, hypotheses, brand fit, and gaps."
    />
  );
  if (listQuery.isPending)
    return (
      <div className="grid gap-8">
        {header}
        <LoadingState label="Loading market comparisons…" />
      </div>
    );

  const showForm = formOpen || (summaries.length === 0 && !flow.runId);

  return (
    <div className="grid gap-8">
      {header}
      {listQuery.isError && <ErrorState error={listQuery.error} onRetry={() => listQuery.refetch()} />}

      <section aria-labelledby="mx-setup" className="rounded-2xl border bg-card shadow-card">
        <div className="flex flex-wrap items-center justify-between gap-3 border-b px-4 py-3">
          <h2 id="mx-setup" className="text-[15px] font-semibold">
            Comparison setup
          </h2>
          <div className="flex flex-wrap items-center gap-3">
            {summaries.length > 0 && (
              <div className="flex min-w-0 flex-wrap items-center gap-2">
                <Label htmlFor="mx-history" className="text-xs">
                  Past comparisons
                </Label>
                <select
                  id="mx-history"
                  value={comparisonId ?? ""}
                  onChange={(e) => setSelectedId(e.target.value)}
                  className="h-8 max-w-full min-w-0 rounded-lg border sm:max-w-64 border-input bg-transparent px-2 text-sm outline-none focus-visible:border-ring focus-visible:ring-3 focus-visible:ring-ring/50"
                >
                  {summaries.map((s) => (
                    <option key={s.id} value={s.id}>
                      {s.markets.map((m) => m.country_code).join(" · ")} · {formatDateTime(s.created_at)}
                      {s.status !== "completed" ? ` (${s.status})` : ""}
                    </option>
                  ))}
                </select>
              </div>
            )}
            {!showForm && (
              <Button variant="outline" size="sm" onClick={() => setFormOpen(true)}>
                New comparison
              </Button>
            )}
          </div>
        </div>
        {showForm && (
          <div className="p-4 md:p-5">
            <ComparisonForm
              project={project}
              campaign={campaign}
              busy={flow.busy}
              pending={start.isPending}
              error={start.error}
              onSubmit={submit}
              onCancel={summaries.length > 0 || flow.runId ? () => setFormOpen(false) : undefined}
            />
          </div>
        )}
      </section>

      {flow.runQuery.isError && <ErrorState error={flow.runQuery.error} onRetry={() => flow.runQuery.refetch()} />}
      {flow.run && !hasResult(flow.run) && !selectedId && (
        <RunStatusPanel
          run={flow.run}
          operation="Market comparison"
          onRetry={lastBody && flow.run.error?.retryable ? () => submit(lastBody) : undefined}
        />
      )}
      {comparisonQuery.isError && <ErrorState error={comparisonQuery.error} onRetry={() => comparisonQuery.refetch()} />}
      {comparisonId && comparisonQuery.isPending && <LoadingState label="Loading comparison…" />}
      {comparisonQuery.data && (
        <ComparisonView
          comparison={comparisonQuery.data}
          onConfirm={confirm}
          onRefine={() => setFormOpen(true)}
          busy={flow.busy || start.isPending}
        />
      )}
    </div>
  );
}
