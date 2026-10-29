"use client";

import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { ArrowRight, Check, Heart, Lock, MapPin, Pencil, Plus, Trash2, Users, X, type LucideIcon } from "lucide-react";
import { useState, type ReactNode } from "react";
import { toast } from "sonner";

import { FeatureHeader } from "@/components/app-shell/feature-header";
import { flagEmoji, TagChip } from "@/components/data/pills";
import { Field, TermListInput } from "@/components/forms/fields";
import { Card } from "@/components/layout/page-parts";
import { ErrorState, LoadingState } from "@/components/states";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Textarea } from "@/components/ui/textarea";
import { FEATURES, type FeatureKey } from "@/features/project/features";
import { projectKeys, useProject } from "@/features/project/project-context";
import { api } from "@/lib/api/client";
import { unwrap } from "@/lib/api/errors";
import type { components } from "@/lib/api/schema";
import type { Market } from "@/lib/api/types";
import { formatDateTime } from "@/lib/format";
import { pickImagery } from "@/lib/imagery";
import { cn } from "@/lib/utils";

type Brand = components["schemas"]["Brand"];
type BrandUpdate = components["schemas"]["BrandUpdate"];
type Tab = "overview" | "details" | "audience" | "guidelines" | "examples";

const TABS: { key: Tab; label: string }[] = [
  { key: "overview", label: "Overview" },
  { key: "details", label: "Brand details" },
  { key: "audience", label: "Audience" },
  { key: "guidelines", label: "Guidelines" },
  { key: "examples", label: "Examples" },
];

const brandKey = (projectId: string) => ["brand", projectId] as const;

type Draft = {
  name: string;
  description: string;
  positioning: string;
  communication_style: string;
  target_audience: string;
  audience_preferences: string;
  voice: string[];
  preferred_terms: string[];
  prohibited_terms: string[];
  protected_terms: string[];
  constraints: string[];
  approved_examples: { text: string; note: string }[];
};

const toDraft = (b: Brand): Draft => ({
  name: b.name,
  description: b.description ?? "",
  positioning: b.positioning ?? "",
  communication_style: b.communication_style ?? "",
  target_audience: b.target_audience ?? "",
  audience_preferences: b.audience_preferences ?? "",
  voice: b.voice,
  preferred_terms: b.preferred_terms,
  prohibited_terms: b.prohibited_terms,
  protected_terms: b.protected_terms,
  constraints: b.constraints,
  approved_examples: b.approved_examples.map((e) => ({ text: e.text, note: e.note ?? "" })),
});

const opt = (s: string) => (s.trim() ? s.trim() : null);
const toUpdate = (d: Draft): BrandUpdate => ({
  name: d.name.trim(),
  description: opt(d.description),
  positioning: opt(d.positioning),
  communication_style: opt(d.communication_style),
  target_audience: opt(d.target_audience),
  audience_preferences: opt(d.audience_preferences),
  voice: d.voice,
  preferred_terms: d.preferred_terms,
  prohibited_terms: d.prohibited_terms,
  protected_terms: d.protected_terms,
  constraints: d.constraints,
  approved_examples: d.approved_examples.filter((x) => x.text.trim()).map((x) => ({ text: x.text.trim(), note: opt(x.note) })),
});

export function BrandMemory() {
  const { project } = useProject();
  const brand = useQuery({
    queryKey: brandKey(project.id),
    queryFn: () => unwrap(api.GET("/api/v1/projects/{project_id}/brand", { params: { path: { project_id: project.id } } })),
  });
  if (brand.isPending) return <LoadingState label="Loading brand memory…" />;
  if (brand.error) return <ErrorState error={brand.error} onRetry={() => void brand.refetch()} />;
  return <BrandMemoryEditor key={brand.data.updated_at} brand={brand.data} projectId={project.id} demo={project.mode === "demo"} markets={project.target_markets} />;
}

function BrandMemoryEditor({ brand, projectId, demo, markets }: { brand: Brand; projectId: string; demo: boolean; markets: Market[] }) {
  const queryClient = useQueryClient();
  const [draft, setDraft] = useState<Draft>(() => toDraft(brand));
  const [tab, setTab] = useState<Tab>("overview");
  const set = <K extends keyof Draft>(key: K, value: Draft[K]) => setDraft((d) => ({ ...d, [key]: value }));
  const dirty = JSON.stringify(draft) !== JSON.stringify(toDraft(brand));

  const save = useMutation({
    mutationFn: () => unwrap(api.PUT("/api/v1/projects/{project_id}/brand", { params: { path: { project_id: projectId } }, body: toUpdate(draft) })),
    onSuccess: (saved) => {
      queryClient.setQueryData(brandKey(projectId), saved);
      void queryClient.invalidateQueries({ queryKey: projectKeys.detail(projectId) });
      toast.success("Brand Memory saved");
    },
  });

  return (
    <div className="space-y-6">
      <FeatureHeader
        feature="brand"
        className="mb-2"
        description="Define your brand, audience, guidelines, and preferences. Nativeproof uses them to keep results relevant and consistent."
        actions={
          <a href="#brand-usage" className="inline-flex h-11 items-center gap-2 rounded-xl border border-border bg-surface px-4 text-[15px] font-medium text-ink shadow-card hover:bg-surface-muted">
            View usage
          </a>
        }
        primaryAction={
          <Button size="lg" className="h-11 rounded-xl px-5 text-[15px]" onClick={() => save.mutate()} disabled={demo || !dirty || save.isPending || !draft.name.trim()}>
            {save.isPending ? "Saving…" : "Save changes"}
            <ArrowRight aria-hidden />
          </Button>
        }
      >
        <p className="text-xs text-ink-secondary">
          Last updated {formatDateTime(brand.updated_at)}
          {dirty && !demo && " · unsaved changes"}
        </p>
      </FeatureHeader>

      {demo && (
        <p className="flex items-start gap-2 rounded-card border border-border bg-surface px-4 py-3 text-[14px] text-ink-body">
          <Lock aria-hidden className="mt-0.5 size-4 shrink-0" />
          This is a demo project, so Brand Memory is read-only: the fixtures describe the seeded brand, and the API rejects
          changes with 409. Create a live project to set your own brand rules.
        </p>
      )}
      {save.error && <ErrorState error={save.error} onRetry={() => save.mutate()} />}

      <div role="tablist" aria-label="Brand Memory sections" className="flex gap-1 overflow-x-auto border-b border-border [scrollbar-width:none]">
        {TABS.map((t) => (
          <button
            key={t.key}
            role="tab"
            type="button"
            aria-selected={tab === t.key}
            onClick={() => setTab(t.key)}
            className={cn(
              "-mb-px shrink-0 border-b-2 px-4 py-3 text-[15px] font-medium whitespace-nowrap",
              tab === t.key ? "border-primary text-primary" : "border-transparent text-ink-body hover:text-ink",
            )}
          >
            {t.label}
          </button>
        ))}
      </div>

      <div role="tabpanel" aria-label={TABS.find((t) => t.key === tab)?.label}>
        {tab === "overview" && <OverviewTab draft={draft} markets={markets} onEdit={demo ? undefined : setTab} />}
        {tab === "details" && (
          <Section readOnly={demo} title="Brand details" subtitle="Who the brand is, in your words.">
            <Field label="Brand name" htmlFor="b-name" required>
              <Input id="b-name" value={draft.name} onChange={(e) => set("name", e.target.value)} disabled={demo} className="bg-surface" />
            </Field>
            <Field label="Description" htmlFor="b-description">
              <Textarea id="b-description" value={draft.description} onChange={(e) => set("description", e.target.value)} rows={2} disabled={demo} className="bg-surface" />
            </Field>
            <Field label="Positioning" htmlFor="b-positioning" hint="How the brand wants to be understood relative to alternatives.">
              <Textarea id="b-positioning" value={draft.positioning} onChange={(e) => set("positioning", e.target.value)} rows={2} disabled={demo} className="bg-surface" aria-describedby="b-positioning-hint" />
            </Field>
            <Field label="Communication style" htmlFor="b-style">
              <Textarea id="b-style" value={draft.communication_style} onChange={(e) => set("communication_style", e.target.value)} rows={2} disabled={demo} className="bg-surface" />
            </Field>
            <Field label="Key values (voice attributes)" htmlFor="b-voice" hint="Short attributes such as confident, minimal. Press Enter to add.">
              <TermListInput id="b-voice" value={draft.voice} onChange={(v) => set("voice", v)} placeholder="Add an attribute" disabled={demo} />
            </Field>
          </Section>
        )}
        {tab === "audience" && (
          <Section readOnly={demo} title="Audience" subtitle="Stated assumptions about who you want to reach, not verified demographic facts.">
            <Field label="Primary audience" htmlFor="b-audience">
              <Input id="b-audience" value={draft.target_audience} onChange={(e) => set("target_audience", e.target.value)} disabled={demo} className="bg-surface" />
            </Field>
            <Field label="Audience preferences and interests" htmlFor="b-preferences">
              <Textarea id="b-preferences" value={draft.audience_preferences} onChange={(e) => set("audience_preferences", e.target.value)} rows={3} disabled={demo} className="bg-surface" />
            </Field>
            <p className="text-[13px] text-ink-secondary">Geographic focus comes from the project&apos;s target markets: {markets.length ? markets.map((m) => m.display_name).join(", ") : "none set"}.</p>
          </Section>
        )}
        {tab === "guidelines" && (
          <Section readOnly={demo} title="Brand guidelines" subtitle="Rules every workflow applies. Deterministic checks enforce protected and prohibited terms.">
            <Field label="Protected terms" htmlFor="b-protected" hint="Kept verbatim in adaptations whenever they appear in the source.">
              <TermListInput id="b-protected" value={draft.protected_terms} onChange={(v) => set("protected_terms", v)} placeholder="Add a term" disabled={demo} />
            </Field>
            <Field label="Preferred terms" htmlFor="b-preferred">
              <TermListInput id="b-preferred" value={draft.preferred_terms} onChange={(v) => set("preferred_terms", v)} placeholder="Add a term" disabled={demo} />
            </Field>
            <Field label="Prohibited terms" htmlFor="b-prohibited" hint="An adaptation that uses one is flagged as a constraint violation.">
              <TermListInput id="b-prohibited" value={draft.prohibited_terms} onChange={(v) => set("prohibited_terms", v)} placeholder="Add a term" disabled={demo} />
            </Field>
            <Field label="Constraints" htmlFor="b-constraints" hint="Explicit rules, e.g. “Never reference religious holidays.”">
              <TermListInput id="b-constraints" value={draft.constraints} onChange={(v) => set("constraints", v)} placeholder="Add a rule" disabled={demo} />
            </Field>
          </Section>
        )}
        {tab === "examples" && (
          <Section readOnly={demo} title="Example content" subtitle="Copy the brand has approved. Workflows use it as a voice reference, not as evidence.">
            {draft.approved_examples.length === 0 && <p className="text-[14px] text-ink-secondary">No approved examples yet.</p>}
            <ul className="space-y-3">
              {draft.approved_examples.map((ex, i) => (
                <li key={i} className="grid gap-2 rounded-xl border border-border bg-surface p-3 sm:grid-cols-[minmax(0,1fr)_220px_auto] sm:items-start">
                  <label className="sr-only" htmlFor={`ex-text-${i}`}>
                    Example {i + 1} text
                  </label>
                  <Textarea id={`ex-text-${i}`} value={ex.text} rows={2} disabled={demo} onChange={(e) => set("approved_examples", draft.approved_examples.map((x, j) => (j === i ? { ...x, text: e.target.value } : x)))} className="bg-surface" />
                  <label className="sr-only" htmlFor={`ex-note-${i}`}>
                    Example {i + 1} note
                  </label>
                  <Input id={`ex-note-${i}`} value={ex.note} placeholder="Note (optional)" disabled={demo} onChange={(e) => set("approved_examples", draft.approved_examples.map((x, j) => (j === i ? { ...x, note: e.target.value } : x)))} className="bg-surface" />
                  {!demo && (
                    <Button type="button" variant="ghost" size="icon-sm" aria-label={`Remove example ${i + 1}`} onClick={() => set("approved_examples", draft.approved_examples.filter((_, j) => j !== i))}>
                      <Trash2 aria-hidden />
                    </Button>
                  )}
                </li>
              ))}
            </ul>
            {!demo && (
              <Button type="button" variant="outline" size="sm" onClick={() => set("approved_examples", [...draft.approved_examples, { text: "", note: "" }])}>
                <Plus aria-hidden />
                Add example
              </Button>
            )}
          </Section>
        )}
      </div>

      <UsageBand />
    </div>
  );
}

/** A tab body: a form in live projects, plain readable values in demo projects (disabled inputs would fail contrast). */
function Section({ title, subtitle, readOnly, children }: { title: string; subtitle: string; readOnly: boolean; children: ReactNode }) {
  return (
    <Card title={title} subtitle={subtitle}>
      {/* Demo: the same fields read as plain text: full opacity (disabled:opacity-50 would fail contrast), no borders,
          no placeholders, no add/remove controls. */}
      <div
        className={cn(
          "max-w-3xl space-y-4",
          readOnly &&
            "[&_button]:hidden [&_input:disabled]:cursor-default [&_input:disabled]:border-transparent [&_input:disabled]:bg-transparent [&_input:disabled]:px-0 [&_input:disabled]:opacity-100 [&_input:disabled]:placeholder:text-transparent [&_textarea:disabled]:cursor-default [&_textarea:disabled]:resize-none [&_textarea:disabled]:border-transparent [&_textarea:disabled]:bg-transparent [&_textarea:disabled]:px-0 [&_textarea:disabled]:opacity-100",
        )}
      >
        {children}
      </div>
    </Card>
  );
}

function EditButton({ onClick }: { onClick?: () => void }) {
  if (!onClick) return null;
  return (
    <Button variant="outline" size="sm" onClick={onClick}>
      <Pencil aria-hidden />
      Edit
    </Button>
  );
}

function Row({ label, children }: { label: string; children: ReactNode }) {
  return (
    <div className="grid grid-cols-[120px_minmax(0,1fr)] gap-4 border-b border-border py-2.5 text-[14px] last:border-0">
      <dt className="text-ink-secondary">{label}</dt>
      <dd className="text-ink">{children}</dd>
    </div>
  );
}

const notSet = <span className="text-ink-secondary">Not set</span>;

function OverviewTab({ draft, markets, onEdit }: { draft: Draft; markets: Market[]; onEdit?: (t: Tab) => void }) {
  const image = pickImagery([draft.name, draft.description, draft.positioning, ...draft.voice], draft.name);
  const doUse = [...draft.preferred_terms.map((t) => `Use “${t}”`), ...draft.protected_terms.map((t) => `Keep “${t}” verbatim`)];
  const avoid = [...draft.prohibited_terms.map((t) => `Avoid “${t}”`), ...draft.constraints];
  return (
    <div className="grid grid-cols-[minmax(0,1fr)] gap-5 lg:grid-cols-[minmax(0,1.15fr)_minmax(0,1fr)]">
      <Card title="Brand overview" subtitle="A quick summary of your brand for this project." action={<EditButton onClick={onEdit && (() => onEdit("details"))} />}>
        <div className="grid gap-5 sm:grid-cols-[minmax(0,1fr)_minmax(0,1.2fr)]">
          <div className="relative overflow-hidden rounded-xl">
            {/* eslint-disable-next-line @next/next/no-img-element -- decorative library image */}
            <img src={image.src} alt="" className="h-full min-h-48 w-full object-cover" />
            <span className="absolute inset-x-0 bottom-0 bg-ink/55 px-4 py-3 text-lg font-semibold tracking-[0.2em] text-white uppercase">{draft.name}</span>
          </div>
          <dl>
            <Row label="Brand name">{draft.name || notSet}</Row>
            <Row label="Description">{draft.description || notSet}</Row>
            <Row label="Positioning">{draft.positioning || notSet}</Row>
            <Row label="Style">{draft.communication_style || notSet}</Row>
            <Row label="Key values">
              {draft.voice.length ? (
                <span className="flex flex-wrap gap-1.5">
                  {draft.voice.map((v) => (
                    <TagChip key={v}>{v}</TagChip>
                  ))}
                </span>
              ) : (
                notSet
              )}
            </Row>
          </dl>
        </div>
      </Card>

      <Card title="Target audience" subtitle="Who you are trying to reach with this project." action={<EditButton onClick={onEdit && (() => onEdit("audience"))} />}>
        <ul className="divide-y divide-border rounded-xl border border-border">
          <AudienceRow Icon={Users} tone="audience" label="Primary audience" value={draft.target_audience || null} />
          <AudienceRow
            Icon={MapPin}
            tone="risk"
            label="Geographic focus"
            value={markets.length ? markets.map((m) => `${flagEmoji(m.country_code)} ${m.display_name}`).join(", ") : null}
          />
          <AudienceRow Icon={Heart} tone="voice" label="Interests" value={draft.audience_preferences || null} />
        </ul>
        <p className="mt-3 text-xs text-ink-secondary">Stated assumptions, not verified demographic facts.</p>
      </Card>

      <Card title="Brand guidelines" subtitle="Key principles that guide all content and analysis." action={<EditButton onClick={onEdit && (() => onEdit("guidelines"))} />}>
        <div className="grid gap-4 sm:grid-cols-2">
          <GuideList title="Do use" items={doUse} tone="do" />
          <GuideList title="Avoid" items={avoid} tone="avoid" />
        </div>
      </Card>

      <Card title="Example content" subtitle="Reference examples that capture your brand's tone." action={<EditButton onClick={onEdit && (() => onEdit("examples"))} />}>
        {draft.approved_examples.length === 0 ? (
          <p className="text-[14px] text-ink-secondary">No approved examples yet.</p>
        ) : (
          <ul className="grid gap-3 sm:grid-cols-3">
            {draft.approved_examples.slice(0, 3).map((ex, i) => (
              <li key={i} className="rounded-xl border border-border bg-surface-muted p-3">
                <p className="font-serif text-[16px] leading-snug font-semibold text-ink">“{ex.text}”</p>
                {ex.note && <p className="mt-1 text-[13px] text-ink-secondary">{ex.note}</p>}
              </li>
            ))}
          </ul>
        )}
      </Card>
    </div>
  );
}

function AudienceRow({ Icon, tone, label, value }: { Icon: LucideIcon; tone: FeatureKey; label: string; value: string | null }) {
  const f = FEATURES[tone];
  return (
    <li className="grid grid-cols-[40px_140px_minmax(0,1fr)] items-start gap-3 p-3.5 text-[14px]">
      <span className={cn("flex size-10 items-center justify-center rounded-full", f.tone.soft)}>
        <Icon aria-hidden className={cn("size-5", f.tone.text)} />
      </span>
      <span className="pt-2 font-semibold text-ink">{label}</span>
      <span className="pt-2 text-ink-body">{value ?? notSet}</span>
    </li>
  );
}

function GuideList({ title, items, tone }: { title: string; items: string[]; tone: "do" | "avoid" }) {
  const Mark = tone === "do" ? Check : X;
  return (
    <div className={cn("rounded-xl p-4", tone === "do" ? "bg-success-soft" : "bg-danger-soft")}>
      <p className={cn("mb-3 flex items-center gap-2 text-[16px] font-semibold", tone === "do" ? "text-success" : "text-danger")}>
        <span className={cn("flex size-6 items-center justify-center rounded-full text-white", tone === "do" ? "bg-success" : "bg-danger")}>
          <Mark aria-hidden className="size-3.5" />
        </span>
        {title}
      </p>
      {items.length === 0 ? (
        <p className="text-[13px] text-ink-secondary">None set.</p>
      ) : (
        <ul className="space-y-1.5">
          {items.map((item, i) => (
            <li key={i} className="flex items-start gap-2 text-[14px] text-ink-body">
              <Mark aria-hidden className={cn("mt-0.5 size-4 shrink-0", tone === "do" ? "text-success" : "text-danger")} />
              {item}
            </li>
          ))}
        </ul>
      )}
    </div>
  );
}

const USAGE: { key: FeatureKey; text: string }[] = [
  { key: "dna", text: "Aligns cultural interests with your brand and audience." },
  { key: "arena", text: "Scores campaign variants against your tone and rules." },
  { key: "risk", text: "Checks your content against your guidelines and protected terms." },
  { key: "markets", text: "Considers your positioning when comparing markets." },
];

function UsageBand() {
  return (
    <section id="brand-usage" aria-labelledby="brand-usage-title" className="scroll-mt-24 overflow-hidden rounded-card border border-border bg-surface shadow-card">
      <div className="flex items-start gap-4 bg-lavender px-6 py-4">
        <span className={cn("flex size-10 shrink-0 items-center justify-center rounded-xl bg-surface")}>
          <FEATURES.brand.Icon aria-hidden className="size-5 text-brand" />
        </span>
        <div>
          <h2 id="brand-usage-title" className="font-serif text-[21px] font-semibold text-ink">
            How Nativeproof uses your Brand Memory
          </h2>
          <p className="text-[14px] text-ink-body">Every workflow reads it, and each result records which rules it applied. Only people write it.</p>
        </div>
      </div>
      <ul className="grid gap-px bg-border sm:grid-cols-2 lg:grid-cols-4">
        {USAGE.map((u) => {
          const f = FEATURES[u.key];
          return (
            <li key={u.key} className="flex items-start gap-3 bg-surface px-5 py-4">
              <span className={cn("flex size-10 shrink-0 items-center justify-center rounded-xl", f.tone.soft)}>
                <f.Icon aria-hidden className={cn("size-5", f.tone.text)} />
              </span>
              <span>
                <span className="block text-[15px] font-semibold text-ink">{f.label}</span>
                <span className="block text-[13.5px] text-ink-secondary">{u.text}</span>
              </span>
            </li>
          );
        })}
      </ul>
    </section>
  );
}
