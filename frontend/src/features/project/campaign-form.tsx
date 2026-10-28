"use client";

import { useMutation, useQueryClient } from "@tanstack/react-query";
import { ChevronDown, Lock } from "lucide-react";
import { useState, type FormEvent } from "react";
import { toast } from "sonner";

import { Field, MarketListField, TermListInput } from "@/components/forms/fields";
import { ErrorState } from "@/components/states";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Textarea } from "@/components/ui/textarea";
import { projectKeys } from "@/features/project/project-context";
import { api } from "@/lib/api/client";
import { unwrap } from "@/lib/api/errors";
import type { Campaign, CampaignCreate, CampaignUpdate, EvaluationCriteria, Market } from "@/lib/api/types";
import { cn } from "@/lib/utils";

type CampaignType = Campaign["campaign_type"];

export const CAMPAIGN_TYPES: { value: CampaignType; label: string }[] = [
  { value: "advertisement", label: "Advertisement" },
  { value: "landing_page", label: "Landing page" },
  { value: "product_description", label: "Product description" },
  { value: "slogan", label: "Slogan" },
  { value: "social_post", label: "Social post" },
];

export const DEFAULT_WEIGHTS: EvaluationCriteria = { clarity: 0.3, brand_fidelity: 0.25, cultural_relevance: 0.3, cultural_risk: 0.15 };

export const WEIGHT_FIELDS: { key: keyof EvaluationCriteria; label: string; help: string }[] = [
  { key: "clarity", label: "Clarity", help: "How clearly the message reads." },
  { key: "brand_fidelity", label: "Brand fidelity", help: "Consistency with the brand voice and terms." },
  { key: "cultural_relevance", label: "Cultural relevance", help: "Fit with the target market's context." },
  { key: "cultural_risk", label: "Cultural risk", help: "Inverted into utility: 100 − risk score." },
];

const LIMITS = { headline: 300, body: 5000, call_to_action: 200, reference_terms: 20 };

type WeightDraft = Record<keyof EvaluationCriteria, string>;

const toDraft = (w: EvaluationCriteria): WeightDraft => ({
  clarity: String(w.clarity),
  brand_fidelity: String(w.brand_fidelity),
  cultural_relevance: String(w.cultural_relevance),
  cultural_risk: String(w.cultural_risk),
});

/** Parsed weights plus validity. Weights must sum to 1.0 within 0.001 and are never normalized (contracts/README §8). */
export function checkWeights(draft: WeightDraft) {
  const values = Object.fromEntries(WEIGHT_FIELDS.map((f) => [f.key, Number(draft[f.key])])) as EvaluationCriteria;
  const numbers = Object.values(values);
  const wellFormed = WEIGHT_FIELDS.every((f) => draft[f.key].trim() !== "") && numbers.every((n) => Number.isFinite(n) && n >= 0 && n <= 1);
  const total = numbers.reduce((sum, n) => sum + (Number.isFinite(n) ? n : 0), 0);
  return { values, total, valid: wellFormed && Math.abs(total - 1) <= 0.001, wellFormed };
}

function WeightsEditor({ draft, onChange }: { draft: WeightDraft; onChange(next: WeightDraft): void }) {
  const { total, valid, wellFormed } = checkWeights(draft);
  return (
    <fieldset className="space-y-3" aria-describedby="weights-help weights-total">
      <legend className="text-[13px] font-medium text-ink">Evaluation weights</legend>
      <p id="weights-help" className="text-xs text-ink-secondary">
        Importance of each criterion when Loop computes the overall score. They must add up to exactly 1.00 (±0.001); Nativeproof never rescales them for you.
      </p>
      <div className="grid gap-3 sm:grid-cols-2">
        {WEIGHT_FIELDS.map((f) => (
          <div key={f.key} className="space-y-1">
            <label htmlFor={`w-${f.key}`} className="flex items-baseline justify-between gap-2 text-[13px] text-ink">
              {f.label}
              <span className="text-[11px] text-ink-secondary">{f.help}</span>
            </label>
            <Input
              id={`w-${f.key}`}
              type="number"
              inputMode="decimal"
              min={0}
              max={1}
              step={0.05}
              value={draft[f.key]}
              onChange={(e) => onChange({ ...draft, [f.key]: e.target.value })}
              className="bg-surface tabular-nums"
            />
          </div>
        ))}
      </div>
      <div className="flex flex-wrap items-center gap-3">
        <p
          id="weights-total"
          role="status"
          className={cn("rounded-sm px-2 py-1 text-[13px] tabular-nums", valid ? "bg-accent text-primary" : "bg-danger-soft text-danger")}
        >
          Total {total.toFixed(3)} — {valid ? "valid" : wellFormed ? "must equal 1.000 (±0.001) before saving" : "each weight must be a number from 0 to 1"}
        </p>
        <Button type="button" variant="ghost" size="sm" onClick={() => onChange(toDraft(DEFAULT_WEIGHTS))}>
          Reset to defaults
        </Button>
      </div>
    </fieldset>
  );
}

function Counter({ value, max }: { value: string; max: number }) {
  return (
    <span className={cn("tabular-nums", value.length > max && "text-danger")}>
      {value.length}/{max}
    </span>
  );
}

const optional = (s: string) => (s.trim() ? s.trim() : null);
const sameList = <T,>(a: T[], b: T[], key: (x: T) => string) => a.length === b.length && a.every((x, i) => key(x) === key(b[i]));

/**
 * Create a campaign (every CampaignCreate field) or edit one through PATCH. A content change creates a new
 * version. Demo campaigns keep their seeded content (the API returns 409), so content fields are locked.
 */
export function CampaignForm({
  projectId,
  campaign,
  demo,
  onDone,
  onCancel,
}: {
  projectId: string;
  campaign?: Campaign;
  demo: boolean;
  onDone(campaign: Campaign): void;
  onCancel(): void;
}) {
  const queryClient = useQueryClient();
  const current = campaign?.current_version.content;
  const [name, setName] = useState(campaign?.name ?? "");
  const [type, setType] = useState<CampaignType>(campaign?.campaign_type ?? "advertisement");
  const [objective, setObjective] = useState(campaign?.objective ?? "");
  const [headline, setHeadline] = useState(current?.headline ?? "");
  const [body, setBody] = useState(current?.body ?? "");
  const [cta, setCta] = useState(current?.call_to_action ?? "");
  const [terms, setTerms] = useState<string[]>(current?.reference_terms ?? []);
  const [markets, setMarkets] = useState<Market[]>(campaign?.target_markets ?? []);
  const [weights, setWeights] = useState<WeightDraft>(toDraft(campaign?.evaluation_criteria ?? DEFAULT_WEIGHTS));
  const contentLocked = Boolean(campaign) && demo;

  const weightCheck = checkWeights(weights);
  const content = { headline: optional(headline), body: optional(body), call_to_action: optional(cta), reference_terms: terms };
  const contentChanged =
    !!current &&
    (content.headline !== current.headline ||
      content.body !== current.body ||
      content.call_to_action !== current.call_to_action ||
      !sameList(terms, current.reference_terms, (t) => t));
  const overLimit = headline.length > LIMITS.headline || body.length > LIMITS.body || cta.length > LIMITS.call_to_action;
  const hasContent = Boolean(content.headline || content.body || content.call_to_action);

  const patch: CampaignUpdate = {};
  if (campaign) {
    if (name.trim() !== campaign.name) patch.name = name.trim();
    if (optional(objective) !== campaign.objective) patch.objective = optional(objective);
    if (!sameList(markets, campaign.target_markets, (m) => m.country_code)) patch.target_markets = markets;
    if (WEIGHT_FIELDS.some((f) => weightCheck.values[f.key] !== campaign.evaluation_criteria[f.key])) patch.evaluation_criteria = weightCheck.values;
    if (contentChanged && !contentLocked) patch.original_content = content;
  }
  const dirty = !campaign || Object.keys(patch).length > 0;

  const save = useMutation({
    mutationFn: async () => {
      if (!campaign) {
        const createBody: CampaignCreate = {
          name: name.trim(),
          campaign_type: type,
          objective: optional(objective),
          original_content: content,
          target_markets: markets,
          evaluation_criteria: weightCheck.values,
        };
        return unwrap(api.POST("/api/v1/projects/{project_id}/campaigns", { params: { path: { project_id: projectId } }, body: createBody }));
      }
      return unwrap(api.PATCH("/api/v1/campaigns/{campaign_id}", { params: { path: { campaign_id: campaign.id } }, body: patch }));
    },
    onSuccess: (saved) => {
      void queryClient.invalidateQueries({ queryKey: projectKeys.campaigns(projectId) });
      if (!campaign) toast.success(`Campaign “${saved.name}” created`);
      else if (patch.original_content) toast.success(`Content saved as version ${saved.current_version.version_number}`);
      else toast.success("Campaign updated");
      onDone(saved);
    },
  });

  function submit(e: FormEvent) {
    e.preventDefault();
    if (!save.isPending && dirty && weightCheck.valid && !overLimit && name.trim() && hasContent) save.mutate();
  }

  const blockers = [
    !name.trim() && "a campaign name",
    !hasContent && "a headline, body, or call to action",
    overLimit && "content within the character limits",
    !weightCheck.valid && "weights that total 1.000",
  ].filter(Boolean);

  return (
    <form onSubmit={submit} className="space-y-6">
      <div className="grid gap-4 sm:grid-cols-2">
        <Field label="Campaign name" htmlFor="c-name" required>
          <Input id="c-name" value={name} onChange={(e) => setName(e.target.value)} required maxLength={200} className="bg-surface" />
        </Field>
        <Field label="Campaign type" htmlFor="c-type" required hint={campaign ? "Fixed when the campaign was created." : undefined}>
          <span className="relative block">
            <select
              id="c-type"
              value={type}
              disabled={Boolean(campaign)}
              aria-describedby={campaign ? "c-type-hint" : undefined}
              onChange={(e) => setType(e.target.value as CampaignType)}
              className="h-8 w-full appearance-none rounded-lg border border-input bg-surface pr-8 pl-2.5 text-sm text-ink outline-none focus-visible:border-ring disabled:opacity-60"
            >
              {CAMPAIGN_TYPES.map((t) => (
                <option key={t.value} value={t.value}>
                  {t.label}
                </option>
              ))}
            </select>
            <ChevronDown aria-hidden className="pointer-events-none absolute top-1/2 right-2 size-4 -translate-y-1/2 text-ink-secondary" />
          </span>
        </Field>
        <Field label="Objective" htmlFor="c-objective" className="sm:col-span-2" hint="What the campaign should achieve. Loop scores consistency with it.">
          <Textarea id="c-objective" value={objective} onChange={(e) => setObjective(e.target.value)} rows={2} className="bg-surface" aria-describedby="c-objective-hint" />
        </Field>
        <Field label="Target markets" htmlFor="c-markets" className="sm:col-span-2" hint={demo ? "Demo runs only support the seeded market (Japan)." : "Search by country name or ISO code."}>
          <MarketListField id="c-markets" value={markets} onChange={setMarkets} />
        </Field>
      </div>

      <fieldset className="space-y-4 rounded-lg border border-border bg-surface-muted p-4" disabled={contentLocked} aria-describedby={contentLocked ? "content-locked" : undefined}>
        <legend className="px-1 text-[13px] font-medium text-ink">
          Original content{campaign && !contentLocked && <span className="font-normal text-ink-secondary"> — saving a change creates a new version</span>}
        </legend>
        {contentLocked && (
          <p id="content-locked" className="flex items-start gap-2 text-[13px] text-ink-secondary">
            <Lock aria-hidden className="mt-0.5 size-3.5 shrink-0" />
            Demo campaign content is fixed so the fixture results stay truthful; the API rejects content edits with 409. Create a live project to test your own copy.
          </p>
        )}
        <Field label="Headline" htmlFor="c-headline" hint={<Counter value={headline} max={LIMITS.headline} />}>
          <Input id="c-headline" value={headline} onChange={(e) => setHeadline(e.target.value)} className="bg-surface" aria-describedby="c-headline-hint" />
        </Field>
        <Field label="Body" htmlFor="c-body" hint={<Counter value={body} max={LIMITS.body} />}>
          <Textarea id="c-body" value={body} onChange={(e) => setBody(e.target.value)} rows={5} className="bg-surface" aria-describedby="c-body-hint" />
        </Field>
        <Field label="Call to action" htmlFor="c-cta" hint={<Counter value={cta} max={LIMITS.call_to_action} />}>
          <Input id="c-cta" value={cta} onChange={(e) => setCta(e.target.value)} className="bg-surface" aria-describedby="c-cta-hint" />
        </Field>
        <Field label="Reference terms" htmlFor="c-terms" hint={`Cultural references in the copy that Atlas and Voice should investigate (up to ${LIMITS.reference_terms}).`}>
          <TermListInput id="c-terms" value={terms} onChange={setTerms} max={LIMITS.reference_terms} placeholder="Add a reference" disabled={contentLocked} />
        </Field>
      </fieldset>

      <WeightsEditor draft={weights} onChange={setWeights} />

      {save.error && <ErrorState error={save.error} />}
      <div className="flex flex-wrap items-center gap-2 border-t border-border pt-4">
        <Button type="submit" disabled={save.isPending || !dirty || blockers.length > 0}>
          {save.isPending ? "Saving…" : campaign ? "Save changes" : "Create campaign"}
        </Button>
        <Button type="button" variant="ghost" onClick={onCancel} disabled={save.isPending}>
          Cancel
        </Button>
        <p className="text-xs text-ink-secondary" aria-live="polite">
          {blockers.length > 0 ? `Needs ${blockers.join(", ")}.` : !dirty ? "No changes to save." : null}
        </p>
      </div>
    </form>
  );
}
