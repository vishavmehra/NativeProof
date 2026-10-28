"use client";

import { useRouter } from "next/navigation";
import { useState, type FormEvent } from "react";

import { ErrorState } from "@/components/states";
import { Button } from "@/components/ui/button";
import { Checkbox } from "@/components/ui/checkbox";
import { Input } from "@/components/ui/input";
import { useEvaluation } from "@/features/loop/api";
import { useAdaptations } from "@/features/voice/api";
import { Field } from "@/components/forms/fields";
import { Panel, SELECT_CLASS } from "@/features/voice/field";
import type { Campaign, Project } from "@/lib/api/types";
import { formatDateTime } from "@/lib/format";

import { useCreateReport } from "./api";
import { NONE, RunSelect, runLabel, useResultRuns } from "./run-select";

const MAX_ADAPTATIONS = 3;

/** Every source defaults to the latest completed run; "none" is allowed and the report then says it is partial. */
export function ReportForm({ project, campaign, evaluationParam }: { project: Project; campaign: Campaign; evaluationParam?: string }) {
  const router = useRouter();
  const create = useCreateReport(project.id);
  const discoveries = useResultRuns(project.id, "market_discovery");
  const rehearsals = useResultRuns(project.id, "campaign_rehearsal", campaign.id);
  const evaluations = useResultRuns(project.id, "campaign_evaluation", campaign.id);
  const adaptationRuns = useResultRuns(project.id, "campaign_adaptation", campaign.id);
  const adaptations = useAdaptations(campaign.id);

  const [title, setTitle] = useState(`${campaign.name}: evidence report`);
  // undefined = not touched: use the latest completed run.
  const [discovery, setDiscovery] = useState<string>();
  const [rehearsal, setRehearsal] = useState<string>();
  const [evaluation, setEvaluation] = useState<string>();
  const [picked, setPicked] = useState<string[]>();

  const discoveryId = discovery ?? discoveries.runs[0]?.id ?? NONE;
  const rehearsalId = rehearsal ?? rehearsals.runs[0]?.id ?? NONE;
  const evaluationId = evaluation ?? evaluationParam ?? evaluations.runs[0]?.result?.ids[0] ?? NONE;
  const listed = adaptations.data ?? [];
  // Default to the evaluated candidates, so the report's adaptations match its comparison; else the latest run's variants.
  const evaluated = useEvaluation(campaign.id, evaluationId === NONE ? null : evaluationId);
  const evaluatedIds = evaluated.data?.results.flatMap((r) => (r.adaptation_id ? [r.adaptation_id] : [])) ?? [];
  const defaultIds = evaluatedIds.length ? evaluatedIds : (adaptationRuns.runs[0]?.result?.ids ?? []);
  const adaptationIds = picked ?? listed.filter((a) => defaultIds.includes(a.id)).slice(0, MAX_ADAPTATIONS).map((a) => a.id);
  const loading = discoveries.isPending || rehearsals.isPending || evaluations.isPending || adaptationRuns.isPending || adaptations.isPending;
  // A list that failed to load must not turn into a "partial report" that claims the data does not exist.
  const listError = discoveries.error ?? rehearsals.error ?? evaluations.error ?? adaptationRuns.error ?? adaptations.error;

  const missing = [
    discoveryId === NONE && "market signals",
    rehearsalId === NONE && "rehearsal findings",
    adaptationIds.length === 0 && "adaptation history",
    evaluationId === NONE && "comparison results",
  ].filter(Boolean);

  function submit(event: FormEvent) {
    event.preventDefault();
    if (!title.trim()) return;
    create.mutate(
      {
        title: title.trim(),
        campaign_id: campaign.id,
        discovery_run_id: discoveryId === NONE ? null : discoveryId,
        rehearsal_run_id: rehearsalId === NONE ? null : rehearsalId,
        evaluation_id: evaluationId === NONE ? null : evaluationId,
        adaptation_ids: adaptationIds,
      },
      { onSuccess: (report) => router.push(`/projects/${project.id}/proof/${report.id}`) },
    );
  }

  return (
    <Panel id="report-form-heading" title="Create a report">
      <form onSubmit={submit} className="grid gap-5" noValidate>
        <Field htmlFor="report-title" label="Title" required>
          <Input id="report-title" value={title} maxLength={200} onChange={(e) => setTitle(e.target.value)} className="bg-surface" required />
        </Field>
        <div className="grid gap-x-6 gap-y-4 md:grid-cols-3">
          <Field htmlFor="report-discovery" label="Discovery">
            <RunSelect id="report-discovery" runs={discoveries.runs} failed={discoveries.error} value={discoveryId} onChange={setDiscovery} noneLabel="None" />
          </Field>
          <Field htmlFor="report-rehearsal" label="Rehearsal">
            <RunSelect id="report-rehearsal" runs={rehearsals.runs} failed={rehearsals.error} value={rehearsalId} onChange={setRehearsal} noneLabel="None" />
          </Field>
          <Field htmlFor="report-evaluation" label="Evaluation">
            <select id="report-evaluation" className={SELECT_CLASS} value={evaluationId} onChange={(e) => setEvaluation(e.target.value)}>
              <option value={NONE}>None</option>
              {evaluations.runs.map((run) =>
                run.result?.ids[0] ? (
                  <option key={run.id} value={run.result.ids[0]}>
                    {runLabel(run)}
                  </option>
                ) : null,
              )}
            </select>
          </Field>
        </div>

        <fieldset className="grid gap-2">
          <legend className="mb-1 text-sm font-medium text-ink">
            Adaptations <span className="font-normal text-ink-secondary">(up to {MAX_ADAPTATIONS})</span>
          </legend>
          {listed.length === 0 ? (
            <p className="text-sm text-ink-secondary">{adaptations.isPending ? "Loading adaptations…" : "No adaptations for this campaign yet."}</p>
          ) : (
            <ul className="grid gap-2 sm:grid-cols-2 lg:grid-cols-3">
              {listed.map((a) => {
                const checked = adaptationIds.includes(a.id);
                return (
                  <li key={a.id} className="rounded-md border bg-surface px-3 py-2">
                    <label className="flex items-start gap-2.5 text-sm">
                      <Checkbox
                        className="mt-0.5"
                        checked={checked}
                        disabled={!checked && adaptationIds.length >= MAX_ADAPTATIONS}
                        onCheckedChange={(next) => setPicked(next ? [...adaptationIds, a.id] : adaptationIds.filter((id) => id !== a.id))}
                      />
                      <span className="grid gap-0.5">
                        <span className="font-medium text-ink">
                          {a.label} <span className="text-xs font-normal text-ink-secondary">{a.origin === "user_edit" ? "User edit" : "Generated"}</span>
                        </span>
                        <span className="text-xs text-ink-secondary">{formatDateTime(a.created_at)}</span>
                      </span>
                    </label>
                  </li>
                );
              })}
            </ul>
          )}
        </fieldset>

        {listError ? (
          <ErrorState error={listError} />
        ) : (
          missing.length > 0 &&
          !loading && (
            <p className="rounded-md border border-warning/25 bg-warning-soft/60 px-3 py-2.5 text-[13px] text-ink">
              <span className="font-medium">This report will be partial.</span> It will state that it has no {missing.join(", ")}.
            </p>
          )
        )}
        {create.error ? <ErrorState error={create.error} /> : null}
        <div className="flex flex-wrap items-center gap-3">
          <Button type="submit" size="lg" disabled={!title.trim() || loading || Boolean(listError) || create.isPending}>
            {create.isPending ? "Creating…" : "Create report"}
          </Button>
          <p className="text-xs text-ink-secondary">The report is assembled from stored results. No model is called.</p>
        </div>
      </form>
    </Panel>
  );
}
