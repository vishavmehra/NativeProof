"use client";

import { ArrowRightIcon } from "lucide-react";
import Link from "next/link";
import { useSearchParams } from "next/navigation";
import { useRef, useState } from "react";

import { EmptyState, ErrorState, LoadingState } from "@/components/states";
import { RunStatusPanel } from "@/components/workflow/run-status";
import { Button, buttonVariants } from "@/components/ui/button";
import { useProject } from "@/features/project/project-context";
import { isTerminal, useLatestRun, useRun } from "@/lib/api/runs";
import type { Campaign, DiscoveryCreate, Project } from "@/lib/api/types";
import { humanize } from "@/lib/format";

import { hasResult, setRunParam, useDiscoveryResult, useStartDiscovery } from "./api";
import { DiscoveryForm } from "./discovery-form";
import { DiscoveryResults, audienceHrefFor } from "./discovery-results";
import type { ConfirmCandidate } from "./reference-table";
import { PageHeader } from "./page-header";

export function AtlasWorkspace() {
  const { project, campaign } = useProject();
  // Remount per campaign so a run started for one campaign never shows under another.
  return <Workspace key={campaign?.id ?? "none"} project={project} campaign={campaign} />;
}

function Workspace({ project, campaign }: { project: Project; campaign: Campaign | null }) {
  const latestQuery = useLatestRun(project.id, { runType: "market_discovery", campaignId: campaign?.id });
  // Guard: only resume a run of this type, whatever the list endpoint returns.
  const latest = latestQuery.data?.run_type === "market_discovery" ? latestQuery.data : null;
  const [startedRunId, setStartedRunId] = useState<string | null>(null);
  const [lastBody, setLastBody] = useState<DiscoveryCreate | null>(null);
  const [formOpen, setFormOpen] = useState(false);
  const configRef = useRef<HTMLElement>(null);

  // A run linked with ?run= (e.g. from Proof's run history) wins over the latest one.
  const runParam = useSearchParams().get("run");
  const runId = startedRunId ?? runParam ?? latest?.id ?? null;
  const runQuery = useRun(runId);
  const run = runQuery.data;
  const wrongType = run && run.run_type !== "market_discovery";
  const resultQuery = useDiscoveryResult(project.id, hasResult(run) && !wrongType ? runId : null);
  const start = useStartDiscovery(project.id);
  const busy = Boolean(run && !isTerminal(run.status));

  function submit(body: DiscoveryCreate) {
    setLastBody(body);
    start.mutate(body, {
      onSuccess: (accepted) => {
        setStartedRunId(accepted.run_id);
        setRunParam(accepted.run_id);
        setFormOpen(false);
      },
    });
  }

  /** Rerun with the person's choice for an ambiguous term (README §14.2); a later choice for the same term replaces it. */
  const confirm: ConfirmCandidate = (term, candidate) => {
    const r = resultQuery.data;
    const base: DiscoveryCreate | null =
      lastBody ??
      (r ? {
        product_category: r.product_category,
        market: r.market,
        research_question: r.research_question,
        reference_terms: r.reference_terms,
        discovery_options: { include_related_interests: true, max_references: 10 },
        campaign_id: r.campaign_id,
        confirmed_references: [],
      } : null);
    if (!base || !candidate.entity_id) return;
    const kind = candidate.entity_type?.toLowerCase().includes("tag") ? "tag" : "entity";
    // Every confirmed term must appear in reference_terms exactly (README §14.2), so use the listed spelling, or list it.
    const listed = base.reference_terms.find((t) => t.toLowerCase() === term.toLowerCase());
    const reference_terms = listed ? base.reference_terms : [...base.reference_terms, term];
    const confirmedTerm = listed ?? term;
    submit({
      ...base,
      reference_terms,
      confirmed_references: [
        ...(base.confirmed_references ?? []).filter((c) => c.term.toLowerCase() !== confirmedTerm.toLowerCase()),
        { term: confirmedTerm, ref_id: candidate.entity_id, ref_kind: kind },
      ],
    });
  };

  function openForm() {
    setFormOpen(true);
    configRef.current?.scrollIntoView({ behavior: "smooth", block: "start" });
  }

  if (latestQuery.isPending) return <LoadingState label="Loading the latest discovery…" />;

  const showForm = !runId || formOpen;
  const previous = lastBody ?? resultQuery.data ?? null;

  return (
    <div className="grid gap-8">
      <PageHeader
        feature="atlas"
        description="Explore the cultural universe: discover cultural signals, see how they connect, and inspect the evidence behind them."
        actions={
          resultQuery.data && (
            <Link href={audienceHrefFor(resultQuery.data, campaign?.id ?? null)} className={buttonVariants()}>
              Continue to Audience <ArrowRightIcon aria-hidden data-icon="inline-end" />
            </Link>
          )
        }
      />

      {latestQuery.isError && <ErrorState error={latestQuery.error} onRetry={() => latestQuery.refetch()} />}

      <section ref={configRef} aria-labelledby="config-heading" className="scroll-mt-4 rounded-2xl border bg-card shadow-card">
        <div className="flex flex-wrap items-center justify-between gap-2 border-b px-4 py-3">
          <h2 id="config-heading" className="text-[15px] font-semibold">
            Research configuration
          </h2>
          {!showForm && (
            <Button variant="outline" size="sm" onClick={openForm}>
              New discovery
            </Button>
          )}
        </div>
        <div className="p-4 md:p-5">
          {showForm ? (
            <DiscoveryForm
              project={project}
              campaign={campaign}
              previous={previous}
              busy={busy}
              pending={start.isPending}
              error={start.error}
              onSubmit={submit}
              onCancel={runId ? () => setFormOpen(false) : undefined}
            />
          ) : previous ? (
            <dl className="grid gap-x-8 gap-y-2 text-sm sm:grid-cols-[auto_1fr]">
              <dt className="text-muted-foreground">Market</dt>
              <dd>{previous.market.display_name}</dd>
              <dt className="text-muted-foreground">Product category</dt>
              <dd>{previous.product_category}</dd>
              <dt className="text-muted-foreground">Research question</dt>
              <dd>{previous.research_question}</dd>
              <dt className="text-muted-foreground">Reference terms</dt>
              <dd>{previous.reference_terms.length ? previous.reference_terms.join(", ") : "None"}</dd>
            </dl>
          ) : (
            <p className="text-sm text-muted-foreground">
              Showing the latest discovery for this campaign. Start a new one to change the inputs.
            </p>
          )}
        </div>
      </section>

      {runQuery.isError && <ErrorState error={runQuery.error} onRetry={() => runQuery.refetch()} />}
      {wrongType && (
        <EmptyState
          title="This link does not point to a discovery"
          description={`Run ${run.id} is a ${humanize(run.run_type).toLowerCase()} run. Open it from its own section, or start a discovery here.`}
        />
      )}
      {run && !wrongType && !hasResult(run) && (
        <RunStatusPanel
          run={run}
          operation="Market discovery"
          onRetry={lastBody && run.error?.retryable ? () => submit(lastBody) : undefined}
        />
      )}

      {resultQuery.isPending && hasResult(run) && <LoadingState label="Loading discovery results…" />}
      {resultQuery.isError && <ErrorState error={resultQuery.error} onRetry={() => resultQuery.refetch()} />}
      {resultQuery.data && <DiscoveryResults
          result={resultQuery.data}
          campaignId={campaign?.id ?? null}
          onRefine={openForm}
          onConfirm={confirm}
          busy={busy || start.isPending}
        />}
    </div>
  );
}
