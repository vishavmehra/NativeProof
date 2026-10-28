"use client";

import { ArrowRight, Gauge, Heart, Pencil, Plus, ShieldAlert, Sparkles, Target, Users } from "lucide-react";
import Link from "next/link";
import { useEffect, useState, type FormEvent, type ReactNode } from "react";

import { Field } from "@/components/forms/fields";
import { EmptyState, ErrorState, LoadingState } from "@/components/states";
import { Button, buttonVariants } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Textarea } from "@/components/ui/textarea";
import { AssetUploader, type Asset } from "@/features/assets/asset-uploader";
import { CriteriaEditor, DIMENSION_LABEL, criteriaValid, formatWeights, parseDraft, toDraft } from "@/features/loop/criteria-editor";
import { NONE, RunSelect, useResultRuns } from "@/features/proof/run-select";
import { sectionHref } from "@/features/project/workflow";
import { useAdaptations } from "@/features/voice/api";
import { SELECT_CLASS } from "@/features/voice/field";
import type { Adaptation, Campaign, Project, Study } from "@/lib/api/types";
import { cn } from "@/lib/utils";

import { useStudies, type ArenaCreate, type ArenaVariantInput } from "./api";
import { AssetImage } from "./asset-image";

/** The header's "Run evaluation" button submits this form through the `form` attribute. */
export const ARENA_FORM_ID = "arena-setup-form";

type Source = "content_version" | "adaptation" | "custom";
type Draft = {
  key: number;
  label: string;
  source: Source;
  versionId: string;
  adaptationId: string;
  headline: string;
  body: string;
  cta: string;
  asset?: Asset;
};

const MIN = 2;
const MAX = 4;
const LETTERS = "ABCD";
const CRITERIA_ICON = { clarity: Gauge, brand_fidelity: Heart, cultural_relevance: Target, cultural_risk: ShieldAlert } as const;
const CRITERIA_HINT = {
  clarity: "Is the message easy to understand?",
  brand_fidelity: "Does it keep your brand's voice and terms?",
  cultural_relevance: "Does it resonate with the audience's interests?",
  cultural_risk: "Any sensitivities or likely misreadings? Lower is better.",
} as const;

function toInput(v: Draft): ArenaVariantInput {
  const base = { label: v.label.trim(), ...(v.asset ? { asset_id: v.asset.id } : {}) };
  if (v.source === "content_version") return { ...base, content_version_id: v.versionId };
  if (v.source === "adaptation") return { ...base, adaptation_id: v.adaptationId };
  return {
    ...base,
    content: { headline: v.headline.trim() || null, body: v.body.trim() || null, call_to_action: v.cta.trim() || null, reference_terms: [] },
  };
}

function problem(v: Draft) {
  if (!v.label.trim()) return "needs a label";
  if (v.source === "adaptation" && !v.adaptationId) return "needs an adaptation";
  if (v.source === "custom" && !v.headline.trim() && !v.body.trim() && !v.cta.trim()) return "needs some text";
  return null;
}

type SetupProps = {
  project: Project;
  campaign: Campaign;
  busy: boolean;
  pending: boolean;
  error: unknown;
  onSubmit(body: ArenaCreate): void;
  preferredId?: string | null;
  /** Tells the header whether the form its "Run evaluation" and "Edit audience" controls point at exists. */
  onFormMount?(mounted: boolean): void;
};

/** Loads what the form needs first, so variant B can default to the latest adaptation instead of an empty select. */
export function ArenaSetup(props: SetupProps) {
  const { project, campaign } = props;
  const studies = useStudies(project.id, campaign.id);
  const adaptations = useAdaptations(campaign.id);
  if (studies.isPending || adaptations.isPending) return <LoadingState label="Loading studies and adaptations…" />;
  if (studies.isError) return <ErrorState error={studies.error} onRetry={() => studies.refetch()} />;
  if (adaptations.isError) return <ErrorState error={adaptations.error} onRetry={() => adaptations.refetch()} />;
  if (studies.data.length === 0) {
    return (
      <EmptyState
        title="Compare needs a study"
        description="Arena gives every variant one study's market, segments, and dimensions. This campaign has no study yet."
        action={
          <Link className={buttonVariants({ variant: "outline" })} href={sectionHref(project.id, "audience", campaign.id)}>
            Create a study in Audience
          </Link>
        }
      />
    );
  }
  if (adaptations.data.length === 0 && project.mode === "demo") {
    return (
      <EmptyState
        title="Compare needs two variants"
        description="Generate adaptations in Voice, or write an alternative (live projects; demo fixtures cannot score custom text)."
        action={
          <Link className={buttonVariants()} href={sectionHref(project.id, "voice", campaign.id)}>
            Generate adaptations in Voice
          </Link>
        }
      />
    );
  }
  return <SetupForm {...props} studies={studies.data} adaptations={adaptations.data} />;
}

function SideCard({ id, title, editing, onEdit, children }: { id?: string; title: string; editing?: boolean; onEdit?: () => void; children: ReactNode }) {
  return (
    <section id={id} aria-label={title} className="grid scroll-mt-24 content-start gap-3 rounded-card border border-border bg-surface p-5 shadow-card">
      <div className="flex items-center justify-between gap-2">
        <h2 className="font-serif text-lg text-ink">{title}</h2>
        {onEdit && (
          <Button type="button" variant="outline" size="sm" aria-pressed={editing} onClick={onEdit}>
            {editing ? "Done" : "Edit"}
          </Button>
        )}
      </div>
      {children}
    </section>
  );
}

function SetupForm({ project, campaign, busy, pending, error, onSubmit, onFormMount, studies, adaptations }: SetupProps & { studies: Study[]; adaptations: Adaptation[] }) {
  useEffect(() => {
    onFormMount?.(true);
    return () => onFormMount?.(false);
  }, [onFormMount]);
  const discoveries = useResultRuns(project.id, "market_discovery");
  const current = campaign.current_version.id;
  const [studyId, setStudyId] = useState<string>();
  const [discovery, setDiscovery] = useState<string>();
  const [responses, setResponses] = useState(6);
  const [draft, setDraft] = useState(() => toDraft(campaign.evaluation_criteria));
  const [editing, setEditing] = useState<number | null>(null);
  const [audienceEdit, setAudienceEdit] = useState(false);
  const [criteriaEdit, setCriteriaEdit] = useState(false);
  const [variants, setVariants] = useState<Draft[]>(() => {
    // The latest generated adaptation (scorable in demo projects), else the latest of any kind, else custom text.
    const latest = adaptations.findLast((a) => a.origin === "generated") ?? adaptations.at(-1);
    const blank = { versionId: current, adaptationId: "", headline: "", body: "", cta: "" };
    return [
      { ...blank, key: 0, label: "Original", source: "content_version" },
      latest
        ? { ...blank, key: 1, label: latest.label.slice(0, 60), source: "adaptation", adaptationId: latest.id }
        : { ...blank, key: 1, label: "Alternative", source: "custom" },
    ];
  });

  const study = studies.find((s) => s.id === studyId) ?? studies[0];
  const discoveryId = discovery ?? discoveries.runs[0]?.id ?? NONE;
  const criteria = parseDraft(draft);
  const issues = variants.map(problem);
  const weightsOk = criteriaValid(criteria);
  const canSubmit = study && issues.every((i) => i === null) && weightsOk && !busy && !pending;

  function update(key: number, patch: Partial<Draft>) {
    setVariants((list) => list.map((v) => (v.key === key ? { ...v, ...patch } : v)));
  }

  function add() {
    const key = Math.max(...variants.map((v) => v.key)) + 1;
    setVariants([...variants, { key, label: `Variant ${LETTERS[variants.length]}`, source: "custom", versionId: current, adaptationId: "", headline: "", body: "", cta: "" }]);
    setEditing(key);
  }

  function submit(event: FormEvent) {
    event.preventDefault();
    if (!canSubmit || !study) return;
    onSubmit({ study_id: study.id, variants: variants.map(toInput), criteria, responses_per_variant: responses, discovery_run_id: discoveryId === NONE ? null : discoveryId });
  }

  /** What a concept card shows for its source. */
  function preview(v: Draft) {
    if (v.source === "content_version") {
      const version = campaign.versions.find((cv) => cv.id === v.versionId);
      return { headline: version?.content.headline, text: version?.content.body, chips: version?.content.reference_terms ?? [], source: `Campaign version ${version?.version_number ?? ""}` };
    }
    if (v.source === "adaptation") {
      const a = adaptations.find((x) => x.id === v.adaptationId);
      return { headline: a?.content.headline, text: a?.strategy, chips: a?.content.reference_terms ?? [], source: a ? `Adaptation · ${a.origin === "user_edit" ? "user edit" : "generated"}` : "Adaptation" };
    }
    return { headline: v.headline, text: v.body, chips: [], source: "Your own text" };
  }

  return (
    <form id={ARENA_FORM_ID} onSubmit={submit} noValidate className="grid grid-cols-[minmax(0,1fr)] gap-5 xl:grid-cols-[minmax(0,1fr)_minmax(0,21rem)]">
      <section aria-labelledby="concepts-heading" className="grid content-start gap-4 rounded-card border border-border bg-surface p-5 shadow-card">
        <div className="flex flex-wrap items-start justify-between gap-3">
          <div className="grid gap-0.5">
            <h2 id="concepts-heading" className="font-serif text-2xl text-ink">
              Campaign concepts
            </h2>
            <p className="text-sm text-ink-secondary">
              Compare {variants.length} campaign directions for {project.brand.name}.
            </p>
          </div>
          <div className="flex flex-wrap gap-2">
            <Link className={buttonVariants({ variant: "outline" })} href={sectionHref(project.id, "voice", campaign.id)}>
              <Sparkles aria-hidden />
              Generate variants with AI
            </Link>
            <Button type="button" onClick={add} disabled={variants.length >= MAX}>
              <Plus aria-hidden />
              Add variant
            </Button>
          </div>
        </div>
        {adaptations.length === 0 && (
          <p className="text-sm text-ink-secondary">
            No adaptations yet, so variant B starts as your own text.{" "}
            <Link className="underline underline-offset-2" href={sectionHref(project.id, "voice", campaign.id)}>
              Generate adaptations in Voice
            </Link>
            .
          </p>
        )}
        <ul className="grid grid-cols-[minmax(0,1fr)] gap-4 md:grid-cols-2 2xl:grid-cols-3">
          {variants.map((v, i) => {
            const id = `arena-v${v.key}`;
            const p = preview(v);
            const isEditing = editing === v.key;
            return (
              <li key={v.key} className="grid content-start overflow-hidden rounded-xl border border-border bg-surface">
                <div className="relative flex h-44 items-end bg-ink p-4">
                  {v.asset ? (
                    <AssetImage assetId={v.asset.id} alt={`Image creative for concept ${LETTERS[i]}`} className="absolute inset-0 size-full rounded-none border-0" />
                  ) : (
                    <p className="line-clamp-3 font-serif text-2xl leading-tight text-white">{p.headline || "No headline"}</p>
                  )}
                  <span className="absolute top-3 left-3 flex size-8 items-center justify-center rounded-full bg-surface font-semibold text-primary">{LETTERS[i]}</span>
                  <Button
                    type="button"
                    variant="secondary"
                    size="icon-sm"
                    className="absolute top-3 right-3"
                    aria-label={`${isEditing ? "Close editor for" : "Edit"} concept ${LETTERS[i]}`}
                    aria-pressed={isEditing}
                    onClick={() => setEditing(isEditing ? null : v.key)}
                  >
                    <Pencil aria-hidden />
                  </Button>
                </div>
                <div className="grid gap-2 p-4">
                  <h3 className="font-serif text-lg text-ink">{v.label || `Concept ${LETTERS[i]}`}</h3>
                  <p className="text-xs text-ink-secondary">{p.source}</p>
                  {p.text && <p className="line-clamp-3 text-sm text-ink-secondary">{p.text}</p>}
                  {p.chips.length > 0 && (
                    <ul className="flex flex-wrap gap-1.5">
                      {p.chips.map((c) => (
                        <li key={c} className="rounded-full border border-border bg-surface-muted px-2.5 py-0.5 text-xs text-ink">
                          {c}
                        </li>
                      ))}
                    </ul>
                  )}
                  {issues[i] && <p className="text-xs text-danger">This concept {issues[i]}.</p>}
                  {isEditing && (
                    <div className="mt-2 grid gap-3 border-t border-border pt-3">
                      <div className="grid gap-3 sm:grid-cols-2">
                        <Field label="Label" htmlFor={`${id}-label`} required>
                          <Input id={`${id}-label`} value={v.label} maxLength={60} onChange={(e) => update(v.key, { label: e.target.value })} className="bg-surface" />
                        </Field>
                        <Field label="Source" htmlFor={`${id}-source`} required>
                          <select id={`${id}-source`} className={SELECT_CLASS} value={v.source} onChange={(e) => update(v.key, { source: e.target.value as Source })}>
                            <option value="content_version">Content version</option>
                            <option value="adaptation">Adaptation</option>
                            <option value="custom">Custom text</option>
                          </select>
                        </Field>
                      </div>
                      {v.source === "content_version" && (
                        <Field label="Version" htmlFor={`${id}-version`} required>
                          <select id={`${id}-version`} className={SELECT_CLASS} value={v.versionId} onChange={(e) => update(v.key, { versionId: e.target.value })}>
                            {campaign.versions.map((cv) => (
                              <option key={cv.id} value={cv.id}>
                                Version {cv.version_number}
                                {cv.id === current ? " (current)" : ""}
                              </option>
                            ))}
                          </select>
                        </Field>
                      )}
                      {v.source === "adaptation" && (
                        <Field label="Adaptation" htmlFor={`${id}-adaptation`} required>
                          <select id={`${id}-adaptation`} className={SELECT_CLASS} value={v.adaptationId} onChange={(e) => update(v.key, { adaptationId: e.target.value })}>
                            <option value="">Select an adaptation</option>
                            {adaptations.map((a) => (
                              <option key={a.id} value={a.id}>
                                {a.label} ({a.origin === "user_edit" ? "user edit" : "generated"}, {a.market.display_name})
                              </option>
                            ))}
                          </select>
                        </Field>
                      )}
                      {v.source === "custom" && (
                        <div className="grid gap-2">
                          <Input aria-label={`Concept ${LETTERS[i]} headline`} placeholder="Headline" maxLength={300} value={v.headline} onChange={(e) => update(v.key, { headline: e.target.value })} className="bg-surface" />
                          <Textarea aria-label={`Concept ${LETTERS[i]} body`} placeholder="Body" maxLength={5000} value={v.body} onChange={(e) => update(v.key, { body: e.target.value })} className="min-h-16 bg-surface" />
                          <Input aria-label={`Concept ${LETTERS[i]} call to action`} placeholder="Call to action" maxLength={200} value={v.cta} onChange={(e) => update(v.key, { cta: e.target.value })} className="bg-surface" />
                          {project.mode === "demo" && <p className="text-xs text-warning">Demo fixtures cannot assess custom text; its scores will read “Not assessed”.</p>}
                        </div>
                      )}
                      {v.asset ? (
                        <Button type="button" variant="ghost" size="sm" className="w-fit" onClick={() => update(v.key, { asset: undefined })}>
                          Remove image ({v.asset.filename})
                        </Button>
                      ) : (
                        <AssetUploader projectId={project.id} kind="image" label="Image creative (optional)" onUploaded={(asset) => update(v.key, { asset })} />
                      )}
                      {v.asset && project.mode === "demo" && <p className="text-xs text-warning">Demo projects do not analyze uploaded images.</p>}
                      <Button type="button" variant="ghost" size="sm" className="w-fit text-danger" disabled={variants.length <= MIN} onClick={() => setVariants(variants.filter((x) => x.key !== v.key))}>
                        Remove concept
                      </Button>
                    </div>
                  )}
                </div>
              </li>
            );
          })}
        </ul>
        {error ? <ErrorState error={error} /> : null}
        <p className="text-xs text-ink-secondary">
          {busy
            ? "An arena is running for this campaign."
            : !weightsOk
              ? "Fix the criteria weights to run the evaluation."
              : "Every concept gets the same study segments, dimensions, and criteria. Reactions are AI-generated."}
        </p>
      </section>

      <div className="grid content-start gap-5">
        <SideCard id="arena-audience" title="Audience for this test" editing={audienceEdit} onEdit={() => setAudienceEdit(!audienceEdit)}>
          {study && (
            <div className="flex items-center gap-3">
              <span className="flex size-11 items-center justify-center rounded-full bg-success-soft text-success">
                <Users aria-hidden className="size-5" />
              </span>
              <div className="grid">
                <span className="font-serif text-base text-ink">{study.name}</span>
                <span className="text-xs text-ink-secondary">Synthetic audience · {study.segments.length || "model-generated"} segments</span>
              </div>
            </div>
          )}
          {study && (
            <dl className="grid grid-cols-[auto_minmax(0,1fr)] gap-x-4 gap-y-2 border-t border-border pt-3 text-sm">
              <dt className="text-ink-secondary">Primary market</dt>
              <dd className="text-ink">{study.market.display_name}</dd>
              <dt className="text-ink-secondary">Segments</dt>
              <dd className="text-ink">{study.segments.length ? study.segments.map((s) => s.label).join(", ") : "Generated by the model, labeled as assumptions"}</dd>
              <dt className="text-ink-secondary">Responses</dt>
              <dd className="text-ink tabular-nums">{responses} per concept (synthetic)</dd>
            </dl>
          )}
          {audienceEdit && (
            <div className="grid gap-3 border-t border-border pt-3">
              <Field label="Study" htmlFor="arena-study" required>
                <select id="arena-study" className={SELECT_CLASS} value={study?.id ?? ""} onChange={(e) => setStudyId(e.target.value)}>
                  {studies.map((s) => (
                    <option key={s.id} value={s.id}>
                      {s.name}
                    </option>
                  ))}
                </select>
              </Field>
              <Field label="Synthetic responses per concept" htmlFor="arena-responses" required hint="3 to 12. Generated, not people.">
                <select id="arena-responses" aria-describedby="arena-responses-hint" className={SELECT_CLASS} value={responses} onChange={(e) => setResponses(Number(e.target.value))}>
                  {[3, 4, 5, 6, 8, 10, 12].map((n) => (
                    <option key={n} value={n}>
                      {n}
                    </option>
                  ))}
                </select>
              </Field>
              <Field label="Discovery evidence" htmlFor="arena-discovery">
                <RunSelect id="arena-discovery" runs={discoveries.runs} failed={discoveries.error} value={discoveryId} onChange={setDiscovery} noneLabel="None (ungrounded)" />
              </Field>
            </div>
          )}
          <Link className={buttonVariants({ variant: "outline" })} href={sectionHref(project.id, "audience", campaign.id)}>
            View audience details
            <ArrowRight aria-hidden />
          </Link>
        </SideCard>

        <SideCard title="Evaluation criteria" editing={criteriaEdit} onEdit={() => setCriteriaEdit(!criteriaEdit)}>
          {criteriaEdit ? (
            <CriteriaEditor value={draft} defaults={campaign.evaluation_criteria} onChange={setDraft} />
          ) : (
            <ul className="grid gap-3">
              {(Object.keys(CRITERIA_ICON) as (keyof typeof CRITERIA_ICON)[]).map((d) => {
                const Icon = CRITERIA_ICON[d];
                return (
                  <li key={d} className="grid grid-cols-[auto_minmax(0,1fr)] gap-3">
                    <span className={cn("flex size-9 items-center justify-center rounded-lg", d === "cultural_risk" ? "bg-danger-soft text-danger" : "bg-accent text-primary")}>
                      <Icon aria-hidden className="size-4" />
                    </span>
                    <span className="grid">
                      <span className="text-sm font-medium text-ink">
                        {DIMENSION_LABEL[d]} <span className="font-normal text-ink-secondary tabular-nums">· weight {Number.isFinite(criteria[d]) ? criteria[d].toFixed(2) : "—"}</span>
                      </span>
                      <span className="text-xs text-ink-secondary">{CRITERIA_HINT[d]}</span>
                    </span>
                  </li>
                );
              })}
            </ul>
          )}
          {!criteriaEdit && <p className="text-xs text-ink-secondary tabular-nums">{weightsOk ? formatWeights(criteria) : "Weights must total 1.00."}</p>}
        </SideCard>
      </div>
    </form>
  );
}
