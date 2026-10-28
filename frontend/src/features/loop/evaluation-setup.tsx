"use client";

import Link from "next/link";
import { useState, type FormEvent } from "react";

import { MarketSelect } from "@/components/forms/market-select";
import { ErrorState, LoadingState } from "@/components/states";
import { Button } from "@/components/ui/button";
import { Checkbox } from "@/components/ui/checkbox";
import { NONE, RunSelect, useResultRuns } from "@/features/proof/run-select";
import { sectionHref } from "@/features/project/workflow";
import { useAdaptations } from "@/features/voice/api";
import { Field } from "@/components/forms/fields";
import { SELECT_CLASS } from "@/features/voice/field";
import type { Campaign, EvaluationCreate, Market, Project } from "@/lib/api/types";
import { formatDate, formatDateTime } from "@/lib/format";

import { CriteriaEditor, criteriaValid, parseDraft, toDraft } from "./criteria-editor";

const MAX_CANDIDATES = 3;

export function EvaluationSetup({
  project,
  campaign,
  versionParam,
  candidateIds,
  busy,
  pending,
  error,
  onSubmit,
  onCancel,
}: {
  project: Project;
  campaign: Campaign;
  versionParam?: string;
  candidateIds: string[];
  busy: boolean;
  pending: boolean;
  error: unknown;
  onSubmit(body: EvaluationCreate): void;
  onCancel?: () => void;
}) {
  const adaptationsQuery = useAdaptations(campaign.id);
  const discoveries = useResultRuns(project.id, "market_discovery");
  const rehearsals = useResultRuns(project.id, "campaign_rehearsal", campaign.id);
  const [versionId, setVersionId] = useState(
    campaign.versions.some((v) => v.id === versionParam) ? versionParam! : campaign.current_version.id,
  );
  const [picked, setPicked] = useState<string[]>(candidateIds.slice(0, MAX_CANDIDATES));
  // undefined = not touched: follow the candidates' own context, else the latest completed run.
  const [market, setMarket] = useState<Market | null>();
  const [discovery, setDiscovery] = useState<string>();
  const [rehearsal, setRehearsal] = useState<string>();
  const [draft, setDraft] = useState(() => toDraft(campaign.evaluation_criteria));

  const all = adaptationsQuery.data ?? [];
  const compatible = all.filter((a) => a.source_content_version_id === versionId);
  // Request order is kept: it breaks ties between candidates (contracts/README §8).
  const chosen = picked.flatMap((id) => compatible.find((a) => a.id === id) ?? []);
  const loaded = adaptationsQuery.isSuccess;
  const linkedMissing = loaded ? candidateIds.filter((id) => !all.some((a) => a.id === id)).length : 0;
  const linkedOtherVersion = loaded ? candidateIds.filter((id) => all.some((a) => a.id === id && a.source_content_version_id !== versionId)).length : 0;
  const excluded = all.length - compatible.length;
  const version = campaign.versions.find((v) => v.id === versionId);

  const effectiveMarket = market === undefined ? (chosen[0]?.market ?? campaign.target_markets[0] ?? project.target_markets[0] ?? null) : market;
  const discoveryId = discovery ?? chosen[0]?.context.discovery_run_id ?? discoveries.runs[0]?.id ?? NONE;
  const rehearsalId = rehearsal ?? chosen[0]?.context.rehearsal_run_id ?? rehearsals.runs[0]?.id ?? NONE;
  const criteria = parseDraft(draft);
  const weightsOk = criteriaValid(criteria);
  const canSubmit = chosen.length > 0 && effectiveMarket && weightsOk && !busy && !pending && loaded;

  function toggle(id: string, checked: boolean) {
    setPicked((current) => (checked ? [...current.filter((c) => compatible.some((a) => a.id === c)), id] : current.filter((c) => c !== id)));
  }

  function submit(event: FormEvent) {
    event.preventDefault();
    if (!canSubmit || !effectiveMarket) return;
    onSubmit({
      candidate_adaptation_ids: chosen.map((a) => a.id),
      source_content_version_id: versionId,
      market: effectiveMarket,
      criteria,
      context: {
        discovery_run_id: discoveryId === NONE ? null : discoveryId,
        baseline_rehearsal_run_id: rehearsalId === NONE ? null : rehearsalId,
      },
    });
  }

  return (
    <form onSubmit={submit} className="grid gap-6" noValidate>
      <div className="grid gap-x-6 gap-y-4 md:grid-cols-2">
        <Field htmlFor="loop-version" label="Source content version" required hint="The original and every candidate must share it.">
          <select
            id="loop-version"
            aria-describedby="loop-version-hint"
            className={SELECT_CLASS}
            value={versionId}
            onChange={(e) => setVersionId(e.target.value)}
          >
            {campaign.versions.map((v) => (
              <option key={v.id} value={v.id}>
                Version {v.version_number}
                {v.id === campaign.current_version.id ? " (current)" : ""} · {formatDate(v.created_at)}
              </option>
            ))}
          </select>
        </Field>
        <Field htmlFor="loop-market" label="Target market" required>
          <MarketSelect id="loop-market" value={effectiveMarket} onChange={setMarket} />
        </Field>
      </div>

      <fieldset className="grid gap-2">
        <legend className="mb-1 text-sm font-medium text-ink">
          Candidates <span className="font-normal text-ink-secondary">(1 to {MAX_CANDIDATES}, compared with the original)</span>
        </legend>
        {adaptationsQuery.isPending && <LoadingState label="Loading adaptations…" />}
        {adaptationsQuery.isError && <ErrorState error={adaptationsQuery.error} onRetry={() => adaptationsQuery.refetch()} />}
        {loaded && compatible.length === 0 && (
          <p className="text-sm text-ink-secondary">
            No adaptations exist for version {version?.version_number ?? "?"} yet.{" "}
            <Link className="underline underline-offset-2" href={sectionHref(project.id, "voice", campaign.id)}>
              Generate them in Voice
            </Link>
            .
          </p>
        )}
        {compatible.length > 0 && (
          <ul className="grid gap-2 sm:grid-cols-2">
            {compatible.map((a) => {
              const checked = chosen.some((c) => c.id === a.id);
              const full = !checked && chosen.length >= MAX_CANDIDATES;
              return (
                <li key={a.id} className="rounded-md border bg-surface p-3">
                  <label className="flex items-start gap-2.5">
                    <Checkbox className="mt-0.5" checked={checked} disabled={full} onCheckedChange={(next) => toggle(a.id, next)} />
                    <span className="grid gap-0.5">
                      <span className="text-sm font-medium text-ink">
                        {a.label} <span className="text-xs font-normal text-ink-secondary">{a.origin === "user_edit" ? "User edit" : "Generated"}</span>
                      </span>
                      <span className="line-clamp-2 text-xs text-ink-secondary">{a.strategy}</span>
                      <span className="text-xs text-ink-secondary">
                        {a.market.display_name} · {formatDateTime(a.created_at)}
                        {full && " · limit reached"}
                      </span>
                      {project.mode === "demo" && a.origin === "user_edit" && (
                        <span className="text-xs text-warning">Demo projects do not assess edited revisions; its scores will read “Not assessed”.</span>
                      )}
                    </span>
                  </label>
                </li>
              );
            })}
          </ul>
        )}
        {(excluded > 0 || linkedOtherVersion > 0 || linkedMissing > 0) && (
          <p className="text-xs text-ink-secondary">
            {excluded > 0 && (
              <>
                {excluded} {excluded === 1 ? "adaptation was" : "adaptations were"} made from another content version and{" "}
                {excluded === 1 ? "is" : "are"} not listed: each candidate is compared with the original of one source version, so
                mixing versions would not be a like-for-like comparison.{" "}
              </>
            )}
            {linkedOtherVersion > 0 && <>{linkedOtherVersion} linked {linkedOtherVersion === 1 ? "candidate belongs" : "candidates belong"} to another version. </>}
            {linkedMissing > 0 && <>{linkedMissing} linked {linkedMissing === 1 ? "candidate was" : "candidates were"} not found.</>}
          </p>
        )}
      </fieldset>

      <CriteriaEditor value={draft} defaults={campaign.evaluation_criteria} onChange={setDraft} />

      <div className="grid gap-x-6 gap-y-4 md:grid-cols-2">
        <Field htmlFor="loop-discovery" label="Discovery evidence context" hint="Defaults to the evidence the candidates were generated with.">
          <RunSelect id="loop-discovery" describedBy="loop-discovery-hint" runs={discoveries.runs} failed={discoveries.error} value={discoveryId} onChange={setDiscovery} noneLabel="None" />
        </Field>
        <Field htmlFor="loop-rehearsal" label="Baseline rehearsal" hint="Synthetic rehearsal of the original, used as context.">
          <RunSelect id="loop-rehearsal" describedBy="loop-rehearsal-hint" runs={rehearsals.runs} failed={rehearsals.error} value={rehearsalId} onChange={setRehearsal} noneLabel="None" />
        </Field>
      </div>

      {error ? <ErrorState error={error} /> : null}

      <div className="flex flex-wrap items-center gap-3">
        <Button type="submit" size="lg" disabled={!canSubmit}>
          {pending ? "Starting…" : "Run evaluation"}
        </Button>
        {onCancel && (
          <Button type="button" variant="ghost" size="lg" onClick={onCancel}>
            Cancel
          </Button>
        )}
        <p className="text-xs text-ink-secondary">
          {busy
            ? "An evaluation is running for this campaign."
            : chosen.length === 0
              ? "Select at least one candidate."
              : !weightsOk
                ? "Fix the weights to continue."
                : `One model assesses the original and ${chosen.length} ${chosen.length === 1 ? "candidate" : "candidates"} in a single run with the same criteria.`}
        </p>
      </div>
    </form>
  );
}
