"use client";

import { useState, type FormEvent } from "react";

import { Field, MarketListField, TermListInput } from "@/components/forms/fields";
import { ErrorState } from "@/components/states";
import { Button } from "@/components/ui/button";
import { Checkbox } from "@/components/ui/checkbox";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { Textarea } from "@/components/ui/textarea";
import { DEMO } from "@/features/atlas/discovery-form";
import { pickError, serverFieldErrors } from "@/features/atlas/form-errors";
import type { Campaign, Market, MarketComparisonCreate, Project } from "@/lib/api/types";


export function ComparisonForm({
  project,
  campaign,
  busy,
  pending,
  error,
  onSubmit,
  onCancel,
}: {
  project: Project;
  campaign: Campaign | null;
  busy: boolean;
  pending: boolean;
  error: unknown;
  onSubmit: (body: MarketComparisonCreate) => void;
  onCancel?: () => void;
}) {
  const isDemo = project.mode === "demo";
  const [productCategory, setProductCategory] = useState(isDemo ? DEMO.productCategory : "");
  const [researchQuestion, setResearchQuestion] = useState(isDemo ? DEMO.researchQuestion : "");
  const [terms, setTerms] = useState<string[]>(isDemo ? DEMO.terms : []);
  const [markets, setMarkets] = useState<Market[]>(project.target_markets.slice(0, 5));
  const [linkCampaign, setLinkCampaign] = useState(true);
  const [clientErrors, setClientErrors] = useState<Record<string, string>>({});

  const server = serverFieldErrors(error);
  const errorFor = (field: string) => clientErrors[field] ?? pickError(server, field);

  function submit(event: FormEvent) {
    event.preventDefault();
    const errors: Record<string, string> = {};
    if (!productCategory.trim()) errors.product_category = "Enter a product category.";
    if (!researchQuestion.trim()) errors.research_question = "Enter a research question.";
    if (markets.length < 2 || markets.length > 5) errors.markets = "Choose two to five markets.";
    if (terms.some((t) => t.length > 100)) errors.reference_terms = "Each term must be 100 characters or fewer.";
    setClientErrors(errors);
    if (Object.keys(errors).length > 0) return;
    onSubmit({
      product_category: productCategory.trim(),
      research_question: researchQuestion.trim(),
      reference_terms: terms,
      markets,
      campaign_id: campaign && linkCampaign ? campaign.id : null,
    });
  }

  return (
    <form noValidate onSubmit={submit} className="grid gap-x-6 gap-y-5 md:grid-cols-2">
      <Field
        label="Markets to compare"
        htmlFor="mx-markets"
        required
        className="md:col-span-2"
        hint={`${markets.length} selected; choose two to five.${isDemo ? " Demo fixtures cover only the seeded market; other markets come back unavailable." : ""}`}
        error={errorFor("markets")}
      >
        <MarketListField id="mx-markets" value={markets} onChange={(next) => setMarkets(next.slice(0, 5))} />
      </Field>
      <Field label="Product category" htmlFor="mx-category" required error={errorFor("product_category")}>
        <Input
          id={"mx-category"}
          value={productCategory}
          onChange={(e) => setProductCategory(e.target.value)}
          maxLength={200}
          className="bg-surface"
        />
      </Field>
      <Field label="Reference terms" htmlFor="mx-terms" hint={`${terms.length} of 10.`} error={errorFor("reference_terms")}>
        <TermListInput id="mx-terms" value={terms} onChange={setTerms} max={10} placeholder="Type a term and press Enter" />
      </Field>
      <Field
        label="Research question"
        htmlFor="mx-question"
        required
        className="md:col-span-2"
        error={errorFor("research_question")}
      >
        <Textarea
          id={"mx-question"}
          value={researchQuestion}
          onChange={(e) => setResearchQuestion(e.target.value)}
          maxLength={500}
          rows={2}
          className="bg-surface"
        />
      </Field>
      {campaign && (
        <Label className="font-normal md:col-span-2">
          <Checkbox checked={linkCampaign} onCheckedChange={(next) => setLinkCampaign(next)} />
          Link to campaign “{campaign.name}”
        </Label>
      )}
      <div className="grid gap-3 border-t pt-4 md:col-span-2">
        {Boolean(error) && <ErrorState error={error} />}
        <div className="flex flex-col gap-3 md:flex-row md:items-center md:justify-between">
          <p className="max-w-prose text-xs text-ink-secondary">
            Each market runs the Atlas pipeline separately. Cultural affinity does not establish demand, and a market
            without data is reported as unavailable rather than filled in.
          </p>
          <div className="flex shrink-0 gap-2">
            {onCancel && (
              <Button type="button" variant="ghost" onClick={onCancel}>
                Cancel
              </Button>
            )}
            <Button type="submit" size="lg" disabled={busy || pending} aria-busy={pending || undefined}>
              Compare markets
            </Button>
          </div>
        </div>
        {busy && <p className="text-xs text-ink-secondary">A comparison is running. You can start another when it finishes.</p>}
      </div>
    </form>
  );
}
