"use client";

import { BotIcon, XIcon } from "lucide-react";
import { useState, type FormEvent } from "react";

import { Field, MarketListField, marketNames } from "@/components/forms/fields";
import { ErrorState } from "@/components/states";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { AssetUploader } from "@/features/assets/asset-uploader";
import type { Asset, Campaign, DiscoveryResult, Market, PopulationStudyCreate, Project, Study } from "@/lib/api/types";
import { formatDateTime } from "@/lib/format";
import { cn } from "@/lib/utils";

import { usePopulations } from "./api";

const SELECT = "h-9 w-full rounded-lg border border-input bg-surface px-2.5 text-sm outline-none focus-visible:border-ring";

const SIZES = [100, 250, 500, 1000, 2000];
const DEMO_CAP = 120; // README §14.8: larger demo sizes are refused with 409.
const DEPTHS = [
  ["brief", "Brief", "The core protocol: eight questions per participant."],
  ["standard", "Standard", "The core protocol plus one adaptive follow-up."],
  ["deep", "Deep", "The core protocol plus two adaptive follow-ups."],
] as const;

export function PopulationForm({
  project,
  campaign,
  study,
  discovery,
  busy,
  pending,
  error,
  onSubmit,
}: {
  project: Project;
  campaign: Campaign;
  study: Study;
  /** Discovery evidence that grounds the groups; without it the groups are hypotheses. */
  discovery: DiscoveryResult | undefined;
  busy: boolean;
  pending: boolean;
  error: unknown;
  onSubmit: (body: PopulationStudyCreate) => void;
}) {
  const isDemo = project.mode === "demo";
  const [size, setSize] = useState(isDemo ? 100 : 250);
  const [regions, setRegions] = useState<Market[]>([study.market]);
  const [depth, setDepth] = useState<NonNullable<PopulationStudyCreate["interview_depth"]>>("standard");
  const [asset, setAsset] = useState<Asset | null>(null);
  const [regionError, setRegionError] = useState<string>();
  const [populationId, setPopulationId] = useState("");
  const [versionId, setVersionId] = useState(campaign.current_version.id);
  const populations = usePopulations(project.id).data?.items ?? [];
  const reuse = Boolean(populationId);

  function submit(event: FormEvent) {
    event.preventDefault();
    if (!reuse && (regions.length < 1 || regions.length > 5)) return setRegionError("Choose one to five regions.");
    setRegionError(undefined);
    onSubmit({
      // A reused population keeps its own size and regions (the API ignores them), so versions meet the same participants.
      ...(reuse ? { population_id: populationId, regions: [] } : { population_size: size, regions }),
      content_version_id: versionId,
      interview_depth: depth,
      asset_id: asset?.id ?? null,
      discovery_run_id: discovery?.run_id ?? null,
      seed: 42, // The contract default; recorded with the run so the same population can be rebuilt.
    });
  }

  return (
    <form noValidate onSubmit={submit} className="grid gap-x-6 gap-y-5 md:grid-cols-2">
      <div className="grid min-w-0 gap-1.5">
        <Label htmlFor="pop-reuse" className="text-[13px]">
          Population
        </Label>
        <select id="pop-reuse" value={populationId} onChange={(e) => setPopulationId(e.target.value)} className={SELECT}>
          <option value="">Build a new population</option>
          {populations.map((p) => (
            <option key={p.id} value={p.id}>
              Reuse: {p.size} participants · {p.group_count} groups · {p.regions.map((m) => m.country_code).join(", ")} · {formatDateTime(p.created_at)}
            </option>
          ))}
        </select>
        <p className="text-xs text-ink-secondary">
          {reuse ? "Same participants as before, so differences come from the content, not the people." : "Reuse a population to compare content versions on identical participants."}
        </p>
      </div>
      <div className="grid min-w-0 gap-1.5">
        <Label htmlFor="pop-version" className="text-[13px]">
          Content version
        </Label>
        <select id="pop-version" value={versionId} onChange={(e) => setVersionId(e.target.value)} className={SELECT}>
          {campaign.versions.map((v) => (
            <option key={v.id} value={v.id}>
              Version {v.version_number} · {formatDateTime(v.created_at)}
              {v.id === campaign.current_version.id ? " (current)" : ""}
            </option>
          ))}
        </select>
        <p className="text-xs text-ink-secondary">The campaign version every participant is interviewed about.</p>
      </div>
      {!reuse && <fieldset className="grid min-w-0 grid-cols-[minmax(0,1fr)] gap-2 md:col-span-2">
        <legend className="mb-1.5 text-[13px] font-medium">
          Population size <span className="text-danger">*</span>
        </legend>
        <div className="flex flex-wrap gap-2">
          {SIZES.map((n) => {
            const refused = isDemo && n > DEMO_CAP;
            return (
              <Label
                key={n}
                className={cn(
                  "cursor-pointer rounded-md border px-3 py-1.5 font-normal tabular-nums has-checked:border-primary has-checked:bg-accent has-focus-visible:outline-2 has-focus-visible:outline-ring",
                  refused && "cursor-not-allowed opacity-50",
                )}
              >
                <input
                  type="radio"
                  name="pop-size"
                  className="sr-only"
                  checked={size === n}
                  disabled={refused}
                  onChange={() => setSize(n)}
                />
                {n.toLocaleString("en")}
              </Label>
            );
          })}
        </div>
        <p className="text-xs text-ink-secondary">
          {isDemo
            ? `Demo projects run on labeled fixtures and are capped at ${DEMO_CAP} participants, so larger sizes are refused before anything runs.`
            : "Synthetic participants to construct and interview. A generation target, not a sample size; the server refuses sizes beyond its configured limits rather than shrinking them."}
        </p>
      </fieldset>}

      {!reuse && (
        <Field
          label="Regions"
          htmlFor="pop-regions"
          required
          className="md:col-span-2"
          hint={isDemo ? "Demo projects are fixed to their seeded market." : "Up to five. Defaults to the study market."}
          error={regionError}
        >
          {isDemo ? (
            <Input id="pop-regions" readOnly value={marketNames(regions)} className="border-dashed bg-surface-muted/60" />
          ) : (
            <MarketListField id="pop-regions" value={regions} onChange={(next) => setRegions(next.slice(0, 5))} />
          )}
        </Field>
        )}

      <fieldset className="grid min-w-0 grid-cols-[minmax(0,1fr)] gap-2 md:col-span-2">
        <legend className="mb-1.5 text-[13px] font-medium">Interview depth</legend>
        <div className="grid min-w-0 grid-cols-[minmax(0,1fr)] gap-2 sm:grid-cols-3">
          {DEPTHS.map(([value, label, description]) => (
            <Label
              key={value}
              className="cursor-pointer items-start rounded-md border p-3 font-normal has-checked:border-primary has-checked:bg-accent"
            >
              <input
                type="radio"
                name="pop-depth"
                className="mt-0.5 size-4 accent-primary"
                checked={depth === value}
                onChange={() => setDepth(value)}
              />
              <span className="grid gap-0.5">
                <span className="font-medium">{label}</span>
                <span className="text-xs text-ink-secondary">{description}</span>
              </span>
            </Label>
          ))}
        </div>
      </fieldset>

      <div className="grid min-w-0 grid-cols-[minmax(0,1fr)] gap-2 md:col-span-2">
        <p className="text-[13px] font-medium">
          Creative <span className="font-normal text-ink-secondary">(optional)</span>
        </p>
        {asset ? (
          <p className="flex items-center gap-2 text-sm">
            {asset.filename}
            <Button type="button" variant="ghost" size="icon-xs" aria-label={`Remove ${asset.filename}`} onClick={() => setAsset(null)}>
              <XIcon aria-hidden />
            </Button>
          </p>
        ) : (
          <AssetUploader
            projectId={project.id}
            kind="image"
            onUploaded={setAsset}
            label="Upload the creative participants should see"
            disabledReason={isDemo ? "Demo projects do not analyze uploads." : undefined}
          />
        )}
        <p className="text-xs text-ink-secondary">
          A creative is shown to participants only as verified visual observations; without a vision model, interviews
          cover the text alone and say so.
        </p>
      </div>

      <p className="text-sm md:col-span-2">
        {discovery
          ? `Groups are built from the discovery evidence of ${formatDateTime(discovery.run_metadata.completed_at)} (${discovery.market.display_name}).`
          : "No completed discovery for this campaign: groups will be built without cultural evidence and labeled hypotheses."}
      </p>

      <div className="grid min-w-0 grid-cols-[minmax(0,1fr)] gap-3 border-t pt-4 md:col-span-2">
        <div className="grid min-w-0 grid-cols-[minmax(0,1fr)] gap-1 rounded-md border border-dashed border-ink-secondary/50 bg-surface-muted px-3 py-2.5 text-sm">
          <p className="flex items-center gap-2 font-medium">
            <BotIcon aria-hidden className="size-4" />
            Before you run
          </p>
          <p>
            Participants and their interviews are AI-generated, not real people. The size is a generation target, and
            every answer shares one model&apos;s biases, so agreement among participants is not confirmation.
          </p>
        </div>
        {Boolean(error) && <ErrorState error={error} />}
        <div className="flex flex-wrap items-center justify-end gap-3">
          {busy && <p className="text-xs text-ink-secondary">A population study is running. Start another when it finishes.</p>}
          <Button type="submit" size="lg" disabled={busy || pending} aria-busy={pending || undefined}>
            Run population study
          </Button>
        </div>
      </div>
    </form>
  );
}
