"use client";

import { ChevronDownIcon } from "lucide-react";

import { ModeBadge } from "@/components/evidence/badges";
import { Collapsible, CollapsibleContent, CollapsibleTrigger } from "@/components/ui/collapsible";
import { Table, TableBody, TableCell, TableHead, TableHeader, TableRow } from "@/components/ui/table";
import type { RunMetadata, StepTrace } from "@/lib/api/types";
import { formatDateTime, humanize } from "@/lib/format";

// shared by Atlas and Audience; Voice/Loop/Proof could reuse it once promoted to the components.

function sampling(step: StepTrace) {
  const s = step.sampling;
  if (!s) return null;
  const parts = [s.seed !== null && `seed ${s.seed}`, s.temperature !== null && `temperature ${s.temperature}`, s.top_p !== null && `top_p ${s.top_p}`];
  return parts.filter(Boolean).join(" · ") || null;
}

/** Collapsed "How this was produced": the executed stages, providers, models, and prompt versions of a run. */
export function RunProvenance({ metadata }: { metadata: RunMetadata }) {
  return (
    <Collapsible className="rounded-lg border bg-card">
      <CollapsibleTrigger className="group flex w-full items-center justify-between gap-3 rounded-lg px-4 py-3 text-left text-sm font-semibold outline-none focus-visible:ring-3 focus-visible:ring-ring/50">
        How this was produced
        <ChevronDownIcon aria-hidden className="size-4 text-muted-foreground transition-transform group-data-[panel-open]:rotate-180" />
      </CollapsibleTrigger>
      <CollapsibleContent className="grid gap-3 border-t px-4 py-3">
        <dl className="flex flex-wrap gap-x-6 gap-y-2 text-xs">
          <div className="flex items-center gap-2">
            <dt className="text-muted-foreground">Mode</dt>
            <dd>
              <ModeBadge mode={metadata.mode} />
            </dd>
          </div>
          <div className="flex gap-2">
            <dt className="text-muted-foreground">Run</dt>
            <dd className="font-mono break-all">{metadata.run_id}</dd>
          </div>
          <div className="flex gap-2">
            <dt className="text-muted-foreground">Started</dt>
            <dd className="tabular-nums">{formatDateTime(metadata.started_at)}</dd>
          </div>
          <div className="flex gap-2">
            <dt className="text-muted-foreground">Completed</dt>
            <dd className="tabular-nums">{formatDateTime(metadata.completed_at)}</dd>
          </div>
        </dl>
        {metadata.steps.length === 0 ? (
          <p className="text-sm text-muted-foreground">No stage traces were recorded for this run.</p>
        ) : (
          <Table className="text-xs">
            <TableHeader>
              <TableRow>
                <TableHead>Stage</TableHead>
                <TableHead>Status</TableHead>
                <TableHead>Provider</TableHead>
                <TableHead>Model</TableHead>
                <TableHead>Prompt version</TableHead>
                <TableHead className="text-right">Latency</TableHead>
              </TableRow>
            </TableHeader>
            <TableBody>
              {metadata.steps.map((step) => (
                <TableRow key={step.stage}>
                  <TableCell className="font-medium">{humanize(step.stage)}</TableCell>
                  <TableCell>
                    {step.status}
                    {step.retries > 0 && `, ${step.retries} ${step.retries === 1 ? "retry" : "retries"}`}
                    {step.fallback_used && ", fallback used"}
                    {step.error_code && <span className="font-mono"> {step.error_code}</span>}
                  </TableCell>
                  <TableCell className="font-mono">{step.provider ?? "n/a"}</TableCell>
                  <TableCell>
                    <span className="font-mono">{step.model_id ?? "n/a"}</span>
                    {sampling(step) && <span className="block text-muted-foreground">{sampling(step)}</span>}
                  </TableCell>
                  <TableCell className="font-mono">{step.prompt_version ?? "n/a"}</TableCell>
                  <TableCell className="text-right tabular-nums">
                    {step.latency_ms === null ? "n/a" : `${step.latency_ms} ms`}
                  </TableCell>
                </TableRow>
              ))}
            </TableBody>
          </Table>
        )}
      </CollapsibleContent>
    </Collapsible>
  );
}
