"use client";

import { useState, type FormEvent } from "react";

import { Field, MarketListField, marketNames } from "@/components/forms/fields";
import { ErrorState, LoadingState } from "@/components/states";
import { Button } from "@/components/ui/button";
import { Checkbox } from "@/components/ui/checkbox";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { Textarea } from "@/components/ui/textarea";
import { useDiscoveryRuns } from "@/features/atlas/api";
import { pickError, serverFieldErrors } from "@/features/atlas/form-errors";
import type { Campaign, CulturalProfile, CulturalProfileCreate, Market, Project } from "@/lib/api/types";
import { formatDateTime, shortId } from "@/lib/format";


const SUBJECTS = [
  ["brand", "Brand"],
  ["product", "Product"],
  ["campaign", "Campaign"],
] as const;
const MAX_RUNS = 5;

export function ProfileForm({
  project,
  campaign,
  campaigns,
  basedOn,
  pending,
  error,
  onSubmit,
  onCancel,
}: {
  project: Project;
  campaign: Campaign | null;
  campaigns: Campaign[];
  /** Regenerate as the next version of this profile. */
  basedOn: CulturalProfile | null;
  pending: boolean;
  error: unknown;
  onSubmit: (body: CulturalProfileCreate) => void;
  onCancel?: () => void;
}) {
  const isDemo = project.mode === "demo";
  const runsQuery = useDiscoveryRuns(project.id);
  const [subject, setSubject] = useState<CulturalProfileCreate["subject"]>(basedOn?.subject ?? "brand");
  const [title, setTitle] = useState(basedOn?.title ?? "");
  const [markets, setMarkets] = useState<Market[]>(
    isDemo ? project.target_markets.slice(0, 1) : (basedOn?.markets ?? project.target_markets.slice(0, 1)),
  );
  const [runIds, setRunIds] = useState<string[]>(basedOn?.source_discovery_run_ids ?? []);
  const [focus, setFocus] = useState("");
  const [linkCampaign, setLinkCampaign] = useState(Boolean(basedOn?.campaign_id ?? campaign));
  const [clientErrors, setClientErrors] = useState<Record<string, string>>({});

  const server = serverFieldErrors(error);
  const errorFor = (field: string) => clientErrors[field] ?? pickError(server, field);
  const linkedCampaign = basedOn?.campaign_id ? campaigns.find((c) => c.id === basedOn.campaign_id) ?? null : campaign;
  const campaignName = (id: string | null) => campaigns.find((c) => c.id === id)?.name;

  function submit(event: FormEvent) {
    event.preventDefault();
    const errors: Record<string, string> = {};
    if (!title.trim()) errors.title = "Give the profile a title.";
    if (markets.length < 1 || markets.length > 5) errors.markets = "Choose one to five markets.";
    setClientErrors(errors);
    if (Object.keys(errors).length > 0) return;
    onSubmit({
      subject,
      title: title.trim(),
      markets,
      discovery_run_ids: runIds,
      focus: focus.trim() || null,
      campaign_id: linkCampaign && linkedCampaign ? linkedCampaign.id : null,
      based_on_profile_id: basedOn?.id ?? null,
    });
  }

  return (
    <form noValidate onSubmit={submit} className="grid gap-x-6 gap-y-5 md:grid-cols-2">
      {basedOn && (
        <p className="rounded-md bg-surface-muted px-3 py-2 text-sm md:col-span-2">
          Regenerates as version {basedOn.version + 1} of “{basedOn.title}”. Version {basedOn.version} stays as it is.
        </p>
      )}
      <fieldset className="grid gap-1.5">
        <legend className="mb-1.5 text-[13px] font-medium">
          Subject <span className="text-danger">*</span>
        </legend>
        <div className="flex flex-wrap gap-x-5 gap-y-2">
          {SUBJECTS.map(([value, label]) => (
            <Label key={value} className="font-normal">
              <input
                type="radio"
                name="dna-subject"
                className="size-4 accent-primary"
                checked={subject === value}
                onChange={() => setSubject(value)}
              />
              {label}
            </Label>
          ))}
        </div>
      </fieldset>
      <Field label="Title" htmlFor="dna-title" required error={errorFor("title")}>
        <Input
          id={"dna-title"}
          value={title}
          onChange={(e) => setTitle(e.target.value)}
          maxLength={120}
          placeholder="e.g. Northstar in Japan"
          className="bg-surface"
        />
      </Field>

      <Field
        label="Markets"
        htmlFor="dna-markets"
        required
        className="md:col-span-2"
        hint={isDemo ? "Demo projects are fixed to their seeded market." : "One to five markets."}
        error={errorFor("markets")}
      >
        {isDemo ? (
          <Input id={"dna-markets"} readOnly value={marketNames(markets)} className="border-dashed bg-surface-muted/60" />
        ) : (
          <MarketListField id="dna-markets" value={markets} onChange={setMarkets} />
        )}
      </Field>

      <fieldset className="grid gap-2 md:col-span-2">
        <legend className="mb-1.5 text-[13px] font-medium">
          Discovery runs <span className="font-normal text-ink-secondary">(optional, up to {MAX_RUNS})</span>
        </legend>
        <p className="-mt-1 text-xs text-ink-secondary">
          Every profile item must rest on discovery evidence. Leave these empty to use the latest completed discovery for
          each market.
        </p>
        {runsQuery.isPending ? (
          <LoadingState label="Loading discovery runs…" />
        ) : runsQuery.isError ? (
          <ErrorState error={runsQuery.error} onRetry={() => runsQuery.refetch()} />
        ) : runsQuery.data.length === 0 ? (
          <p className="text-sm text-ink-secondary">No completed discoveries yet. Run one in Atlas first.</p>
        ) : (
          <ul className="grid gap-1.5 sm:grid-cols-2">
            {runsQuery.data.map((run) => {
              const checked = runIds.includes(run.id);
              return (
                <li key={run.id}>
                  <Label className="font-normal">
                    <Checkbox
                      checked={checked}
                      disabled={!checked && runIds.length >= MAX_RUNS}
                      onCheckedChange={(next) => setRunIds(next ? [...runIds, run.id] : runIds.filter((id) => id !== run.id))}
                    />
                    <span>
                      {formatDateTime(run.completed_at ?? run.created_at)}
                      {campaignName(run.campaign_id) && <span className="text-ink-secondary"> · {campaignName(run.campaign_id)}</span>}
                      {run.status === "partial" && <span className="text-warning"> · partial</span>}{" "}
                      <span className="font-mono text-[11px] text-ink-secondary">{shortId(run.id)}</span>
                    </span>
                  </Label>
                </li>
              );
            })}
          </ul>
        )}
      </fieldset>

      <Field label="Focus" htmlFor="dna-focus" className="md:col-span-2" hint="What the profile should concentrate on, if anything.">
        <Textarea
          id={"dna-focus"}
          value={focus}
          onChange={(e) => setFocus(e.target.value)}
          maxLength={500}
          rows={2}
          placeholder="e.g. Outdoor and design references relevant to an autumn launch"
          className="bg-surface"
        />
      </Field>

      {linkedCampaign && (
        <Label className="font-normal md:col-span-2">
          <Checkbox checked={linkCampaign} onCheckedChange={(next) => setLinkCampaign(next)} />
          Link to campaign “{linkedCampaign.name}”
        </Label>
      )}

      <div className="grid gap-3 border-t pt-4 md:col-span-2">
        {Boolean(error) && <ErrorState error={error} />}
        <div className="flex flex-col gap-3 md:flex-row md:items-center md:justify-between">
          <p className="max-w-prose text-xs text-ink-secondary">
            Items without supporting evidence are labeled hypotheses with insufficient support.
          </p>
          <div className="flex shrink-0 gap-2">
            {onCancel && (
              <Button type="button" variant="ghost" onClick={onCancel}>
                Cancel
              </Button>
            )}
            <Button type="submit" size="lg" disabled={pending} aria-busy={pending || undefined}>
              {basedOn ? "Regenerate profile" : "Generate profile"}
            </Button>
          </div>
        </div>
      </div>
    </form>
  );
}
