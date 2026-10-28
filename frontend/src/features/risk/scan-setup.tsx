"use client";

import { useState, type FormEvent } from "react";

import { Field } from "@/components/forms/fields";
import { MarketSelect } from "@/components/forms/market-select";
import { ErrorState } from "@/components/states";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Textarea } from "@/components/ui/textarea";
import { NONE, RunSelect, useResultRuns } from "@/features/proof/run-select";
import { useAdaptations } from "@/features/voice/api";
import { SELECT_CLASS } from "@/features/voice/field";
import type { Campaign, Market, Project } from "@/lib/api/types";
import { cn } from "@/lib/utils";

import { AssetImage } from "@/features/arena/asset-image";
import { AssetUploader, type Asset } from "@/features/assets/asset-uploader";

import type { RiskScanCreate } from "./api";

type Source = "content_version" | "adaptation" | "custom";
const MAX_IMAGES = 3;

const SOURCES: { value: Source; label: string }[] = [
  { value: "content_version", label: "Campaign version" },
  { value: "adaptation", label: "An adaptation" },
  { value: "custom", label: "Custom text" },
];

export function ScanSetup({
  project,
  campaign,
  busy,
  pending,
  error,
  onSubmit,
  onCancel,
}: {
  project: Project;
  campaign: Campaign;
  busy: boolean;
  pending: boolean;
  error: unknown;
  onSubmit(body: RiskScanCreate): void;
  onCancel?: () => void;
}) {
  const adaptations = useAdaptations(campaign.id);
  const discoveries = useResultRuns(project.id, "market_discovery");
  const [source, setSource] = useState<Source>("content_version");
  const [versionId, setVersionId] = useState(campaign.current_version.id);
  const [adaptationId, setAdaptationId] = useState("");
  const [custom, setCustom] = useState({ headline: "", body: "", cta: "" });
  const [market, setMarket] = useState<Market | null>(campaign.target_markets[0] ?? project.target_markets[0] ?? null);
  const [discovery, setDiscovery] = useState<string>();
  const [assets, setAssets] = useState<Asset[]>([]);
  const discoveryId = discovery ?? discoveries.runs[0]?.id ?? NONE;

  const sourceOk =
    source === "content_version" || (source === "adaptation" ? Boolean(adaptationId) : Boolean(custom.headline.trim() || custom.body.trim() || custom.cta.trim()));
  const canSubmit = market && sourceOk && !busy && !pending;

  function submit(event: FormEvent) {
    event.preventDefault();
    if (!canSubmit || !market) return;
    onSubmit({
      market,
      asset_ids: assets.map((a) => a.id),
      discovery_run_id: discoveryId === NONE ? null : discoveryId,
      ...(source === "content_version"
        ? { content_version_id: versionId }
        : source === "adaptation"
          ? { adaptation_id: adaptationId }
          : {
              content: {
                headline: custom.headline.trim() || null,
                body: custom.body.trim() || null,
                call_to_action: custom.cta.trim() || null,
                reference_terms: [],
              },
            }),
    });
  }

  return (
    <form onSubmit={submit} className="grid gap-5" noValidate>
      <fieldset className="grid gap-2">
        <legend className="mb-1 text-sm font-medium text-ink">What to scan</legend>
        <div className="flex flex-wrap gap-2">
          {SOURCES.map((s) => (
            <label
              key={s.value}
              className={cn(
                "flex cursor-pointer items-center gap-2 rounded-md border px-3 py-1.5 text-sm",
                source === s.value ? "border-primary bg-accent text-ink" : "border-border bg-surface text-ink",
              )}
            >
              <input type="radio" name="scan-source" className="size-4 accent-primary" checked={source === s.value} onChange={() => setSource(s.value)} />
              {s.label}
            </label>
          ))}
        </div>
      </fieldset>

      {source === "content_version" && (
        <Field label="Version" htmlFor="scan-version" required>
          <select id="scan-version" className={SELECT_CLASS} value={versionId} onChange={(e) => setVersionId(e.target.value)}>
            {campaign.versions.map((v) => (
              <option key={v.id} value={v.id}>
                Version {v.version_number}
                {v.id === campaign.current_version.id ? " (current)" : ""}
              </option>
            ))}
          </select>
        </Field>
      )}
      {source === "adaptation" && (
        <Field label="Adaptation" htmlFor="scan-adaptation" required hint={adaptations.data?.length === 0 ? "No adaptations yet. Generate them in Voice." : undefined}>
          <select id="scan-adaptation" className={SELECT_CLASS} value={adaptationId} onChange={(e) => setAdaptationId(e.target.value)}>
            <option value="">Select an adaptation</option>
            {(adaptations.data ?? []).map((a) => (
              <option key={a.id} value={a.id}>
                {a.label} ({a.origin === "user_edit" ? "user edit" : "generated"}, {a.market.display_name})
              </option>
            ))}
          </select>
        </Field>
      )}
      {source === "custom" && (
        <div className="grid gap-2">
          <Input aria-label="Headline" placeholder="Headline" maxLength={300} value={custom.headline} onChange={(e) => setCustom({ ...custom, headline: e.target.value })} className="bg-surface" />
          <Textarea aria-label="Body" placeholder="Body" maxLength={5000} value={custom.body} onChange={(e) => setCustom({ ...custom, body: e.target.value })} className="min-h-20 bg-surface" />
          <Input aria-label="Call to action" placeholder="Call to action" maxLength={200} value={custom.cta} onChange={(e) => setCustom({ ...custom, cta: e.target.value })} className="bg-surface" />
          <p className="text-xs text-ink-secondary">Suggested alternatives cannot be applied to custom text, because there is no campaign version or adaptation to derive from.</p>
        </div>
      )}

      <fieldset className="grid gap-2">
        <legend className="mb-1 text-sm font-medium text-ink">
          Images <span className="font-normal text-ink-secondary">(optional, up to {MAX_IMAGES})</span>
        </legend>
        {assets.length > 0 && (
          <ul className="flex flex-wrap gap-3">
            {assets.map((a, i) => (
              <li key={a.id} className="grid w-28 gap-1">
                <AssetImage assetId={a.id} alt={`Scan image ${i + 1}: ${a.filename}`} className="h-20 w-28" />
                <Button type="button" variant="ghost" size="xs" onClick={() => setAssets(assets.filter((x) => x.id !== a.id))}>
                  Remove
                </Button>
              </li>
            ))}
          </ul>
        )}
        {assets.length < MAX_IMAGES && (
          <AssetUploader key={assets.length} projectId={project.id} kind="image" onUploaded={(a) => setAssets((list) => [...list, a])} />
        )}
        <p className="text-xs text-ink-secondary">
          {project.mode === "demo"
            ? "Demo projects do not analyze uploaded images; the scan reports vision as unavailable."
            : "Images go only to a verified vision model. If none is available, the text is still scanned and the result says so."}
        </p>
      </fieldset>

      <div className="grid gap-x-6 gap-y-4 md:grid-cols-2">
        <Field label="Market" htmlFor="scan-market" required>
          <MarketSelect id="scan-market" value={market} onChange={setMarket} />
        </Field>
        <Field label="Discovery evidence" htmlFor="scan-discovery">
          <RunSelect id="scan-discovery" runs={discoveries.runs} failed={discoveries.error} value={discoveryId} onChange={setDiscovery} noneLabel="None" />
        </Field>
      </div>

      {error ? <ErrorState error={error} /> : null}
      <div className="flex flex-wrap items-center gap-3">
        <Button type="submit" size="lg" disabled={!canSubmit}>
          {pending ? "Starting…" : "Scan for risks"}
        </Button>
        {onCancel && (
          <Button type="button" variant="ghost" size="lg" onClick={onCancel}>
            Cancel
          </Button>
        )}
        <p className="text-xs text-ink-secondary">{busy ? "A scan is running for this campaign." : "Findings separate what the text says from how a model reads it."}</p>
      </div>
    </form>
  );
}
