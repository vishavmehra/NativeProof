"use client";

import { Lock } from "lucide-react";
import Link from "next/link";
import { useState, type FormEvent } from "react";

import { Tag } from "@/components/evidence/badges";
import { Field, TermListInput } from "@/components/forms/fields";
import { MarketSelect } from "@/components/forms/market-select";
import { ErrorState } from "@/components/states";
import { Button } from "@/components/ui/button";
import { Textarea } from "@/components/ui/textarea";
import { NONE, RunSelect, useResultRuns } from "@/features/proof/run-select";
import { sectionHref } from "@/features/project/workflow";
import type { AdaptationCreate, Campaign, Market, Project } from "@/lib/api/types";
import { formatDate } from "@/lib/format";

import { SELECT_CLASS } from "./field";

const MAX_INSTRUCTIONS = 1000;

/** Lets the page header's "Generate adaptations" submit this form. */
export const VOICE_FORM_ID = "voice-adaptation-form";

export function AdaptationForm({
  project,
  campaign,
  discoveryParam,
  rehearsalParam,
  busy,
  pending,
  error,
  onSubmit,
  onCancel,
}: {
  project: Project;
  campaign: Campaign;
  discoveryParam?: string;
  rehearsalParam?: string;
  busy: boolean;
  pending: boolean;
  error: unknown;
  onSubmit(body: AdaptationCreate): void;
  onCancel?: () => void;
}) {
  const discoveries = useResultRuns(project.id, "market_discovery");
  const rehearsals = useResultRuns(project.id, "campaign_rehearsal", campaign.id);
  const [market, setMarket] = useState<Market | null>(campaign.target_markets[0] ?? project.target_markets[0] ?? null);
  const [versionId, setVersionId] = useState(campaign.current_version.id);
  // undefined = not touched: follow the link parameter, else the latest completed run.
  const [discovery, setDiscovery] = useState<string>();
  const [rehearsal, setRehearsal] = useState<string>();
  const [variantCount, setVariantCount] = useState(3);
  const [instructions, setInstructions] = useState("");
  const [extraTerms, setExtraTerms] = useState<string[]>([]);

  const discoveryId = discovery ?? discoveryParam ?? discoveries.runs[0]?.id ?? NONE;
  const rehearsalId = rehearsal ?? rehearsalParam ?? rehearsals.runs[0]?.id ?? NONE;
  const brandTerms = project.brand.protected_terms;
  const loadingContext = discoveries.isPending || rehearsals.isPending;

  function submit(event: FormEvent) {
    event.preventDefault();
    if (!market) return;
    onSubmit({
      market,
      source_content_version_id: versionId,
      discovery_run_id: discoveryId === NONE ? null : discoveryId,
      rehearsal_run_id: rehearsalId === NONE ? null : rehearsalId,
      variant_count: variantCount,
      instructions: instructions.trim() || null,
      // The backend merges these with the brand kit's protected terms.
      protected_terms: extraTerms.filter((t) => !brandTerms.some((b) => b.toLowerCase() === t.toLowerCase())),
    });
  }

  return (
    <form id={VOICE_FORM_ID} onSubmit={submit} className="grid gap-5" noValidate>
      <div className="grid gap-x-6 gap-y-4 md:grid-cols-2">
        <Field label="Target market" htmlFor="voice-market" required>
          <MarketSelect id="voice-market" value={market} onChange={setMarket} />
        </Field>
        <Field label="Source content version" htmlFor="voice-version" required>
          <select id="voice-version" className={SELECT_CLASS} value={versionId} onChange={(e) => setVersionId(e.target.value)}>
            {campaign.versions.map((v) => (
              <option key={v.id} value={v.id}>
                Version {v.version_number}
                {v.id === campaign.current_version.id ? " (current)" : ""} · {formatDate(v.created_at)}
              </option>
            ))}
          </select>
        </Field>
        <Field
          label="Discovery evidence"
          htmlFor="voice-discovery"
          hint={
            discoveries.runs.length === 0 && !discoveries.isPending ? (
              <>
                No completed discovery yet.{" "}
                <Link className="underline underline-offset-2" href={sectionHref(project.id, "atlas", campaign.id)}>
                  Run Atlas
                </Link>{" "}
                to ground adaptations in Qloo evidence.
              </>
            ) : (
              "Qloo-derived evidence supplied to the generator."
            )
          }
        >
          <RunSelect id="voice-discovery" describedBy="voice-discovery-hint" runs={discoveries.runs} failed={discoveries.error} value={discoveryId} onChange={setDiscovery} noneLabel="None (ungrounded)" />
        </Field>
        <Field
          label="Rehearsal findings"
          htmlFor="voice-rehearsal"
          hint={
            rehearsals.runs.length === 0 && !rehearsals.isPending ? (
              <>
                No completed rehearsal for this campaign.{" "}
                <Link className="underline underline-offset-2" href={sectionHref(project.id, "audience", campaign.id)}>
                  Configure Audience
                </Link>{" "}
                to address synthetic-audience findings.
              </>
            ) : (
              "Synthetic-audience findings the variants should address."
            )
          }
        >
          <RunSelect id="voice-rehearsal" describedBy="voice-rehearsal-hint" runs={rehearsals.runs} failed={rehearsals.error} value={rehearsalId} onChange={setRehearsal} noneLabel="None" />
        </Field>
        <Field label="Candidate variants" htmlFor="voice-count" required hint="Between 1 and 3.">
          <select id="voice-count" aria-describedby="voice-count-hint" className={SELECT_CLASS} value={variantCount} onChange={(e) => setVariantCount(Number(e.target.value))}>
            {[1, 2, 3].map((n) => (
              <option key={n} value={n}>
                {n} {n === 1 ? "variant" : "variants"}
              </option>
            ))}
          </select>
        </Field>
      </div>

      <Field
        label="Brand-voice instructions"
        htmlFor="voice-instructions"
        hint={
          <>
            {project.brand.voice.length > 0 && <>Brand voice on file: {project.brand.voice.join(", ")}. </>}
            <span className="tabular-nums">
              {instructions.length} / {MAX_INSTRUCTIONS}
            </span>
          </>
        }
      >
        <Textarea
          id="voice-instructions"
          aria-describedby="voice-instructions-hint"
          value={instructions}
          maxLength={MAX_INSTRUCTIONS}
          onChange={(e) => setInstructions(e.target.value)}
          placeholder="e.g. Keep the confident, minimal tone. Avoid idioms that do not translate."
          className="min-h-20 bg-surface"
        />
      </Field>

      <div className="grid gap-2">
        <Field
          label="Extra protected terms"
          htmlFor="voice-terms"
          hint="Kept verbatim when they appear in the source, and checked deterministically after generation. Brand-kit terms (locked) always apply; edit them in Brand Memory."
        >
          <TermListInput id="voice-terms" value={extraTerms} onChange={setExtraTerms} placeholder="Add a term for this run" max={20} />
        </Field>
        {brandTerms.length > 0 && (
          <ul className="flex flex-wrap gap-1.5" aria-label="Brand-kit protected terms (always applied)">
            {brandTerms.map((term) => (
              <li key={term}>
                <Tag className="h-6 border-border bg-surface-muted text-ink" title="Brand-kit term, always applied">
                  <Lock aria-hidden />
                  {term}
                </Tag>
              </li>
            ))}
          </ul>
        )}
      </div>

      {(discoveryId === NONE || rehearsalId === NONE) && !loadingContext && (
        <ul className="grid gap-1.5 rounded-lg border border-warning/25 bg-warning-soft/60 px-3 py-2.5 text-[13px] text-ink">
          {discoveryId === NONE && (
            <li>
              <span className="font-medium">Ungrounded.</span> No Qloo evidence will be supplied, so every change will be a model
              interpretation and none can be marked evidence-supported.
            </li>
          )}
          {rehearsalId === NONE && (
            <li>
              <span className="font-medium">No rehearsal findings.</span> The variants will not address weaknesses found in a synthetic
              rehearsal.
            </li>
          )}
        </ul>
      )}

      {error ? <ErrorState error={error} /> : null}

      <div className="flex flex-wrap items-center gap-3">
        <Button type="submit" size="lg" disabled={!market || busy || pending || loadingContext}>
          {pending ? "Starting…" : "Generate adaptations"}
        </Button>
        {onCancel && (
          <Button type="button" variant="ghost" size="lg" onClick={onCancel}>
            Cancel
          </Button>
        )}
        {busy && <p className="text-xs text-ink-secondary">An adaptation run is in progress for this campaign.</p>}
        {!market && <p className="text-xs text-ink-secondary">Select a target market to continue.</p>}
      </div>
    </form>
  );
}
