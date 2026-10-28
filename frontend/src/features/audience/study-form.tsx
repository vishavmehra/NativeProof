"use client";

import { ChevronDownIcon, PlusIcon, XIcon } from "lucide-react";
import { useState, type FormEvent } from "react";

import { MarketSelect } from "@/components/forms/market-select";
import { ErrorState } from "@/components/states";
import { Button } from "@/components/ui/button";
import { Checkbox } from "@/components/ui/checkbox";
import { Collapsible, CollapsibleContent, CollapsibleTrigger } from "@/components/ui/collapsible";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { Textarea } from "@/components/ui/textarea";
import { Field } from "@/components/forms/fields";
import { pickError, serverFieldErrors } from "@/features/atlas/form-errors";
import type { Campaign, Dimension, Market, Project, StudyCreate } from "@/lib/api/types";

import { DIMENSIONS, DIMENSION_LABEL } from "./dimensions";

type Segment = { label: string; description: string };

const isInt = (value: string, min: number, max = Number.MAX_SAFE_INTEGER) => {
  const n = Number(value);
  return value.trim() !== "" && Number.isInteger(n) && n >= min && n <= max;
};

export function StudyForm({
  project,
  campaign,
  pending,
  error,
  onSubmit,
  onCancel,
}: {
  project: Project;
  campaign: Campaign;
  pending: boolean;
  error: unknown;
  onSubmit: (body: StudyCreate) => void;
  onCancel?: () => void;
}) {
  const [name, setName] = useState("");
  const [market, setMarket] = useState<Market | null>(campaign.target_markets[0] ?? project.target_markets[0] ?? null);
  const [questions, setQuestions] = useState<string[]>([""]);
  const [dimensions, setDimensions] = useState<Dimension[]>([...DIMENSIONS]);
  const [segments, setSegments] = useState<Segment[]>([]);
  const [responseCount, setResponseCount] = useState("12");
  const [segmentCount, setSegmentCount] = useState("3");
  const [seed, setSeed] = useState("42");
  const [clientErrors, setClientErrors] = useState<Record<string, string>>({});
  const [advancedOpen, setAdvancedOpen] = useState(false);

  const server = serverFieldErrors(error);
  const errorFor = (field: string) => clientErrors[field] ?? pickError(server, field);
  // With explicit segments the count is theirs (the API requires them to match).
  const advancedError = ["response_count", "segment_count", "random_seed"].some((f) => errorFor(`simulation_config.${f}`));
  const effectiveSegmentCount = segments.length > 0 ? String(segments.length) : segmentCount;

  const setQuestion = (i: number, value: string) => setQuestions(questions.map((q, j) => (j === i ? value : q)));
  const setSegment = (i: number, patch: Partial<Segment>) =>
    setSegments(segments.map((s, j) => (j === i ? { ...s, ...patch } : s)));

  function submit(event: FormEvent) {
    event.preventDefault();
    const errors: Record<string, string> = {};
    if (!name.trim()) errors.name = "Name the study.";
    if (!market) errors.market = "Choose a target market.";
    questions.forEach((q, i) => {
      if (!q.trim()) errors[`research_questions.${i}`] = "Enter a question or remove this row.";
    });
    if (dimensions.length === 0) errors.dimensions = "Select at least one dimension.";
    segments.forEach((s, i) => {
      if (!s.label.trim()) errors[`segments.${i}.label`] = "Enter a label.";
      if (!s.description.trim()) errors[`segments.${i}.description`] = "Describe the assumption.";
    });
    if (!isInt(responseCount, 3, 24)) errors["simulation_config.response_count"] = "Enter a whole number from 3 to 24.";
    if (!isInt(effectiveSegmentCount, 1, 4)) errors["simulation_config.segment_count"] = "Enter a whole number from 1 to 4.";
    else if (isInt(responseCount, 3, 24) && Number(effectiveSegmentCount) > Number(responseCount))
      errors["simulation_config.segment_count"] = "Cannot exceed the response count.";
    if (seed.trim() !== "" && !isInt(seed, 0)) errors["simulation_config.random_seed"] = "Enter a whole number of 0 or more, or leave empty.";
    setClientErrors(errors);
    if (Object.keys(errors).length > 0 || !market) return;
    onSubmit({
      campaign_id: campaign.id,
      name: name.trim(),
      market,
      research_questions: questions.map((q) => q.trim()),
      // Keep the canonical order regardless of click order.
      dimensions: DIMENSIONS.filter((d) => dimensions.includes(d)),
      segments: segments.map((s) => ({ label: s.label.trim(), description: s.description.trim() })),
      simulation_config: {
        response_count: Number(responseCount),
        segment_count: Number(effectiveSegmentCount),
        random_seed: seed.trim() === "" ? null : Number(seed),
      },
    });
  }

  return (
    <form noValidate onSubmit={submit} className="grid gap-x-6 gap-y-5 md:grid-cols-2">
      <Field label="Study name" htmlFor="s-name" required error={errorFor("name")}>
        <Input
          id={"s-name"}
          value={name}
          onChange={(e) => setName(e.target.value)}
          maxLength={120}
          placeholder="e.g. Japan launch rehearsal"
        />
      </Field>
      <Field label="Target market" htmlFor="s-market" required error={errorFor("market")}>
        <MarketSelect id="s-market" value={market} onChange={setMarket} />
      </Field>

      <fieldset className="grid gap-2 md:col-span-2">
        <legend className="mb-1.5 text-sm font-medium">Research questions</legend>
        {questions.map((question, i) => {
          const id = `s-question-${i}`;
          const err = errorFor(`research_questions.${i}`);
          return (
            <div key={i} className="grid gap-1">
              <div className="flex gap-2">
                <Label htmlFor={id} className="sr-only">
                  Question {i + 1}
                </Label>
                <Input
                  id={id}
                  aria-invalid={err ? true : undefined}
                  aria-describedby={err ? `${id}-error` : undefined}
                  value={question}
                  onChange={(e) => setQuestion(i, e.target.value)}
                  maxLength={300}
                  placeholder={i === 0 ? "e.g. Is the main message clear?" : "Another question"}
                />
                {questions.length > 1 && (
                  <Button
                    type="button"
                    variant="ghost"
                    size="icon"
                    aria-label={`Remove question ${i + 1}`}
                    onClick={() => setQuestions(questions.filter((_, j) => j !== i))}
                  >
                    <XIcon aria-hidden />
                  </Button>
                )}
              </div>
              {err && (
                <p id={`${id}-error`} className="text-xs font-medium text-destructive">
                  {err}
                </p>
              )}
            </div>
          );
        })}
        {questions.length < 5 && (
          <Button type="button" variant="outline" size="sm" className="w-fit" onClick={() => setQuestions([...questions, ""])}>
            <PlusIcon aria-hidden /> Add question
          </Button>
        )}
        <p className="text-xs text-muted-foreground">One to five questions guide what the synthetic reactions address.</p>
      </fieldset>

      <fieldset className="grid gap-2 md:col-span-2" aria-describedby={errorFor("dimensions") ? "s-dimensions-error" : undefined}>
        <legend className="mb-1.5 text-sm font-medium">Evaluation dimensions</legend>
        <div className="flex flex-wrap gap-x-6 gap-y-2">
          {DIMENSIONS.map((dimension) => (
            <Label key={dimension} className="font-normal">
              <Checkbox
                checked={dimensions.includes(dimension)}
                onCheckedChange={(checked) =>
                  setDimensions(checked ? [...dimensions, dimension] : dimensions.filter((d) => d !== dimension))
                }
              />
              {DIMENSION_LABEL[dimension]}
            </Label>
          ))}
        </div>
        {errorFor("dimensions") && (
          <p id="s-dimensions-error" className="text-xs font-medium text-destructive">
            {errorFor("dimensions")}
          </p>
        )}
      </fieldset>

      <fieldset className="grid gap-3 md:col-span-2">
        <legend className="mb-1.5 text-sm font-medium">
          Segments <span className="font-normal text-muted-foreground">(optional, up to 4)</span>
        </legend>
        <p className="-mt-1 text-xs text-muted-foreground">
          Segments are audience hypotheses you state, not demographic facts. Leave this empty and the model proposes
          segment assumptions, labeled as model-generated.
        </p>
        {segments.map((segment, i) => (
          <div key={i} className="grid gap-3 rounded-md border p-3 md:grid-cols-[minmax(0,1fr)_minmax(0,2fr)_auto] md:items-start">
            <Field label={`Segment ${i + 1} label`} htmlFor={`s-seg-label-${i}`} required error={errorFor(`segments.${i}.label`)}>
              <Input
                id={`s-seg-label-${i}`}
                value={segment.label}
                onChange={(e) => setSegment(i, { label: e.target.value })}
                maxLength={60}
                placeholder="e.g. Weekend hikers"
              />
            </Field>
            <Field label="Assumption" htmlFor={`s-seg-desc-${i}`} required error={errorFor(`segments.${i}.description`)}>
              <Textarea
                id={`s-seg-desc-${i}`}
                value={segment.description}
                onChange={(e) => setSegment(i, { description: e.target.value })}
                maxLength={300}
                rows={1}
                placeholder="Who this perspective represents, stated as a hypothesis"
              />
            </Field>
            <Button
              type="button"
              variant="ghost"
              size="sm"
              className="md:mt-6"
              aria-label={`Remove segment ${i + 1}`}
              onClick={() => setSegments(segments.filter((_, j) => j !== i))}
            >
              <XIcon aria-hidden /> Remove
            </Button>
          </div>
        ))}
        {segments.length < 4 && (
          <Button
            type="button"
            variant="outline"
            size="sm"
            className="w-fit"
            onClick={() => setSegments([...segments, { label: "", description: "" }])}
          >
            <PlusIcon aria-hidden /> Add segment
          </Button>
        )}
      </fieldset>

      <Collapsible className="md:col-span-2" open={advancedOpen || advancedError} onOpenChange={setAdvancedOpen}>
        <CollapsibleTrigger className="group flex items-center gap-1.5 rounded-sm text-sm font-medium outline-none focus-visible:ring-3 focus-visible:ring-ring/50">
          <ChevronDownIcon aria-hidden className="size-4 transition-transform group-data-[panel-open]:rotate-180" />
          Advanced simulation settings
        </CollapsibleTrigger>
        <CollapsibleContent className="grid gap-4 pt-3 sm:grid-cols-3">
          <Field
            label="Reactions to generate"
            htmlFor="s-responses"
            required
            hint={"3–24. A generation target, not a sample size."} error={errorFor("simulation_config.response_count")}
          >
            <Input
              id={"s-responses"}
              type="number"
              inputMode="numeric"
              min={3}
              max={24}
              value={responseCount}
              onChange={(e) => setResponseCount(e.target.value)}
              className="tabular-nums"
            />
          </Field>
          <Field
            label="Segment count"
            htmlFor="s-segments"
            required
            hint={segments.length > 0 ? "Matches the segments you defined." : "1–4 model-proposed segments."}
            error={errorFor("simulation_config.segment_count")}
          >
            <Input
              id={"s-segments"}
              type="number"
              inputMode="numeric"
              min={1}
              max={4}
              value={effectiveSegmentCount}
              onChange={(e) => setSegmentCount(e.target.value)}
              disabled={segments.length > 0}
              className="tabular-nums"
            />
          </Field>
          <Field
            label="Random seed"
            htmlFor="s-seed"
            hint={"Recorded for reproducibility. Empty means no fixed seed."} error={errorFor("simulation_config.random_seed")}
          >
            <Input
              id={"s-seed"}
              type="number"
              inputMode="numeric"
              min={0}
              value={seed}
              onChange={(e) => setSeed(e.target.value)}
              className="tabular-nums"
            />
          </Field>
        </CollapsibleContent>
      </Collapsible>

      <div className="grid gap-3 border-t pt-4 md:col-span-2">
        {Boolean(error) && <ErrorState error={error} />}
        <div className="flex justify-end gap-2">
          {onCancel && (
            <Button type="button" variant="ghost" onClick={onCancel}>
              Cancel
            </Button>
          )}
          <Button type="submit" disabled={pending} aria-busy={pending || undefined}>
            Create study
          </Button>
        </div>
      </div>
    </form>
  );
}
