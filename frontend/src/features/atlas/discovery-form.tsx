"use client";

import { useState, type FormEvent } from "react";

import { Field, TermListInput } from "@/components/forms/fields";
import { MarketSelect } from "@/components/forms/market-select";
import { ErrorState } from "@/components/states";
import { Button } from "@/components/ui/button";
import { Checkbox } from "@/components/ui/checkbox";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { Textarea } from "@/components/ui/textarea";
import type { Campaign, ConfirmedReference, DiscoveryCreate, Market, Project } from "@/lib/api/types";

import { pickError, serverFieldErrors } from "./form-errors";

const MAX_TERMS = 10;
// Product copy for the seeded demo scenario; demo fixtures cover exactly these terms.
export const DEMO = {
  productCategory: "outdoor lifestyle apparel",
  researchQuestion: "Which cultural interests could inform this launch?",
  terms: ["hiking", "minimal design", "great escape"],
};

/** The market demo runs must use: the project's seeded market (contracts/README §5). */
const demoMarket = (project: Project): Market =>
  project.target_markets[0] ?? { country_code: "JP", display_name: "Japan" };

export function DiscoveryForm({
  project,
  campaign,
  previous,
  busy,
  pending,
  error,
  onSubmit,
  onCancel,
}: {
  project: Project;
  campaign: Campaign | null;
  /** Prefill from the last discovery so a term can be refined and rerun. */
  previous:
    | (Pick<DiscoveryCreate, "product_category" | "market" | "research_question" | "reference_terms"> & {
        confirmed_references?: ConfirmedReference[];
      })
    | null;
  /** A discovery is already running. */
  busy: boolean;
  pending: boolean;
  error: unknown;
  onSubmit: (body: DiscoveryCreate) => void;
  onCancel?: () => void;
}) {
  const isDemo = project.mode === "demo";
  const [productCategory, setProductCategory] = useState(previous?.product_category ?? (isDemo ? DEMO.productCategory : ""));
  const [market, setMarket] = useState<Market | null>(
    isDemo ? demoMarket(project) : (previous?.market ?? campaign?.target_markets[0] ?? project.target_markets[0] ?? null),
  );
  const [researchQuestion, setResearchQuestion] = useState(previous?.research_question ?? (isDemo ? DEMO.researchQuestion : ""));
  const [terms, setTerms] = useState<string[]>(previous?.reference_terms ?? (isDemo ? DEMO.terms : []));
  const [includeRelated, setIncludeRelated] = useState(true);
  const [maxReferences, setMaxReferences] = useState("10");
  const [linkCampaign, setLinkCampaign] = useState(true);
  const [clientErrors, setClientErrors] = useState<Record<string, string>>({});

  const confirmations = previous?.confirmed_references ?? [];
  const server = serverFieldErrors(error);
  const errorFor = (field: string) => clientErrors[field] ?? pickError(server, field);

  function submit(event: FormEvent) {
    event.preventDefault();
    const errors: Record<string, string> = {};
    const category = productCategory.trim();
    const question = researchQuestion.trim();
    const max = Number(maxReferences);
    if (!category) errors.product_category = "Enter a product category.";
    if (!market) errors.market = "Choose a target market.";
    if (!question) errors.research_question = "Enter a research question.";
    if (terms.some((t) => t.length > 100)) errors.reference_terms = "Each term must be 100 characters or fewer.";
    if (!Number.isInteger(max) || max < 1 || max > 20)
      errors["discovery_options.max_references"] = "Enter a whole number from 1 to 20.";
    setClientErrors(errors);
    if (Object.keys(errors).length > 0 || !market) return;
    // Keep earlier choices for ambiguous terms only while their term is still listed (the API rejects others with 422),
    // spelled exactly as listed.
    const confirmed = confirmations.flatMap((c) => {
      const listed = terms.find((t) => t.toLowerCase() === c.term.toLowerCase());
      return listed ? [{ ...c, term: listed }] : [];
    });
    onSubmit({
      product_category: category,
      market,
      research_question: question,
      reference_terms: terms,
      discovery_options: { include_related_interests: includeRelated, max_references: max },
      campaign_id: campaign && linkCampaign ? campaign.id : null,
      // Sent only when there is a choice: the field defaults to [] and older servers reject unknown fields.
      ...(confirmed.length > 0 ? { confirmed_references: confirmed } : {}),
    } as DiscoveryCreate);
  }

  return (
    <form noValidate onSubmit={submit} className="grid gap-x-6 gap-y-5 md:grid-cols-2">
      <Field label="Product category" htmlFor="d-category" required error={errorFor("product_category")}>
        <Input
          id={"d-category"}
          value={productCategory}
          onChange={(e) => setProductCategory(e.target.value)}
          maxLength={200}
          placeholder="e.g. outdoor lifestyle apparel"
          className="bg-surface"
        />
      </Field>

      <Field
        label="Target market"
        htmlFor="d-market"
        required
        hint={isDemo ? "Demo projects are fixed to their seeded market." : undefined}
        error={errorFor("market")}
      >
        {isDemo ? (
          <Input
            id={"d-market"}
            readOnly
            value={`${market?.display_name} (${market?.country_code})`}
            className="border-dashed bg-surface-muted/60"
          />
        ) : (
          <MarketSelect id="d-market" value={market} onChange={setMarket} />
        )}
      </Field>

      <Field
        label="Research question"
        htmlFor="d-question"
        required
        className="md:col-span-2"
        error={errorFor("research_question")}
      >
        <Textarea
          id={"d-question"}
          value={researchQuestion}
          onChange={(e) => setResearchQuestion(e.target.value)}
          maxLength={500}
          rows={2}
          placeholder="What do you want to learn about this market?"
          className="bg-surface"
        />
      </Field>

      <Field
        label="Reference terms"
        htmlFor="d-terms"
        className="md:col-span-2"
        hint={
          <>
            {isDemo
              ? `Demo fixtures cover only “${DEMO.terms.join("”, “")}”. Other terms come back unresolved (“No demo fixture for this term”).`
              : "Concepts from the campaign to look up, such as themes or references. Each is resolved separately."}{" "}
            <span className="tabular-nums">
              {terms.length} of {MAX_TERMS}.
            </span>
          </>
        }
        error={errorFor("reference_terms")}
      >
        <TermListInput id="d-terms" value={terms} onChange={setTerms} max={MAX_TERMS} placeholder="Type a term and press Enter" />
      </Field>

      <fieldset className="grid gap-4 md:col-span-2 md:grid-cols-[auto_auto_1fr] md:items-start md:gap-8">
        <legend className="sr-only">Discovery options</legend>
        <Label className="font-normal md:mt-7">
          <Checkbox checked={includeRelated} onCheckedChange={(checked) => setIncludeRelated(checked)} />
          Include related interests
        </Label>
        <Field
          label="Max references"
          htmlFor="d-max"
          required
          className="max-w-40"
          hint={"1–20"} error={errorFor("discovery_options.max_references")}
        >
          <Input
            id={"d-max"}
            type="number"
            inputMode="numeric"
            min={1}
            max={20}
            step={1}
            value={maxReferences}
            onChange={(e) => setMaxReferences(e.target.value)}
            className="bg-surface tabular-nums"
          />
        </Field>
        {campaign ? (
          <div className="grid gap-1 md:mt-7">
            <Label className="font-normal">
              <Checkbox checked={linkCampaign} onCheckedChange={(checked) => setLinkCampaign(checked)} />
              Link to campaign “{campaign.name}”
            </Label>
            <p className="pl-6 text-xs text-muted-foreground">Linked discoveries can ground Audience rehearsals for this campaign.</p>
          </div>
        ) : (
          <p className="text-xs text-muted-foreground md:mt-7">No campaign selected; this discovery will not be linked to one.</p>
        )}
      </fieldset>

      <div className="grid gap-3 border-t pt-4 md:col-span-2">
        {Boolean(error) && <ErrorState error={error} />}
        <div className="flex flex-col gap-3 md:flex-row md:items-center md:justify-between">
          <p className="max-w-prose text-xs text-muted-foreground">
            Discovery relies on available cultural affinity data and does not establish market demand.
          </p>
          <div className="flex shrink-0 gap-2">
            {onCancel && (
              <Button type="button" variant="ghost" onClick={onCancel}>
                Cancel
              </Button>
            )}
            <Button type="submit" size="lg" disabled={busy || pending} aria-busy={pending || undefined}>
              Discover cultural signals
            </Button>
          </div>
        </div>
        {busy && <p className="text-xs text-muted-foreground">A discovery is running. You can start another when it finishes.</p>}
      </div>
    </form>
  );
}
