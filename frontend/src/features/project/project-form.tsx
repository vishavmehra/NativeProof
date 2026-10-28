"use client";

import { useMutation, useQueryClient } from "@tanstack/react-query";
import { useState, type FormEvent } from "react";

import { Field, MarketListField, TermListInput } from "@/components/forms/fields";
import { ErrorState } from "@/components/states";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Textarea } from "@/components/ui/textarea";
import { projectKeys } from "@/features/project/project-context";
import { api } from "@/lib/api/client";
import { unwrap } from "@/lib/api/errors";
import type { Market, Project, ProjectCreate } from "@/lib/api/types";

const optional = (s: string) => (s.trim() ? s.trim() : null);

/** Create a live project and its brand kit (every ProjectCreate field). */
export function ProjectForm({ onCreated, onCancel }: { onCreated(project: Project): void; onCancel(): void }) {
  const queryClient = useQueryClient();
  const [name, setName] = useState("");
  const [description, setDescription] = useState("");
  const [objective, setObjective] = useState("");
  const [markets, setMarkets] = useState<Market[]>([]);
  const [brandName, setBrandName] = useState("");
  const [brandDescription, setBrandDescription] = useState("");
  const [audience, setAudience] = useState("");
  const [voice, setVoice] = useState<string[]>([]);
  const [preferred, setPreferred] = useState<string[]>([]);
  const [prohibited, setProhibited] = useState<string[]>([]);
  const [protectedTerms, setProtectedTerms] = useState<string[]>([]);

  const create = useMutation({
    mutationFn: (body: ProjectCreate) => unwrap(api.POST("/api/v1/projects", { body })),
    onSuccess: (project) => {
      void queryClient.invalidateQueries({ queryKey: projectKeys.list });
      onCreated(project);
    },
  });

  function submit(e: FormEvent) {
    e.preventDefault();
    if (create.isPending) return;
    create.mutate({
      name: name.trim(),
      description: optional(description),
      objective: optional(objective),
      target_markets: markets,
      brand_name: brandName.trim(),
      brand_description: optional(brandDescription),
      target_audience: optional(audience),
      brand_voice: voice,
      preferred_terms: preferred,
      prohibited_terms: prohibited,
      protected_terms: protectedTerms,
    });
  }

  return (
    <form onSubmit={submit} className="space-y-6" aria-describedby="new-project-note">
      <p id="new-project-note" className="text-[13px] text-ink-secondary">
        Creates a <strong className="font-medium text-ink">live</strong> project. Its runs call Qloo and the model provider; if they are not configured
        on the backend, starting a run fails with an explanation and nothing is saved.
      </p>
      <div className="grid gap-x-8 gap-y-6 md:grid-cols-2">
        <fieldset className="space-y-4">
          <legend className="mb-3 text-[15px] font-semibold text-ink">Project</legend>
          <Field label="Project name" htmlFor="p-name" required>
            <Input id="p-name" value={name} onChange={(e) => setName(e.target.value)} required maxLength={200} className="bg-surface" />
          </Field>
          <Field label="Description" htmlFor="p-description">
            <Textarea id="p-description" value={description} onChange={(e) => setDescription(e.target.value)} rows={2} className="bg-surface" />
          </Field>
          <Field label="Research objective" htmlFor="p-objective" hint="The decision this research should inform.">
            <Textarea id="p-objective" value={objective} onChange={(e) => setObjective(e.target.value)} rows={2} className="bg-surface" aria-describedby="p-objective-hint" />
          </Field>
          <Field label="Target markets" htmlFor="p-markets" hint="Search by country name or ISO code.">
            <MarketListField id="p-markets" value={markets} onChange={setMarkets} />
          </Field>
        </fieldset>
        <fieldset className="space-y-4">
          <legend className="mb-3 text-[15px] font-semibold text-ink">Brand kit</legend>
          <Field label="Brand name" htmlFor="p-brand" required>
            <Input id="p-brand" value={brandName} onChange={(e) => setBrandName(e.target.value)} required maxLength={200} className="bg-surface" />
          </Field>
          <Field label="Brand description" htmlFor="p-brand-description">
            <Textarea id="p-brand-description" value={brandDescription} onChange={(e) => setBrandDescription(e.target.value)} rows={2} className="bg-surface" />
          </Field>
          <Field label="Target audience" htmlFor="p-audience" hint="A stated assumption, not a verified demographic fact.">
            <Input id="p-audience" value={audience} onChange={(e) => setAudience(e.target.value)} className="bg-surface" aria-describedby="p-audience-hint" />
          </Field>
          <Field label="Brand voice attributes" htmlFor="p-voice" hint="For example: warm, precise, understated. Press Enter to add.">
            <TermListInput id="p-voice" value={voice} onChange={setVoice} placeholder="Add an attribute" />
          </Field>
          <Field label="Preferred terms" htmlFor="p-preferred" hint="Vocabulary the brand favors.">
            <TermListInput id="p-preferred" value={preferred} onChange={setPreferred} placeholder="Add a term" />
          </Field>
          <Field label="Prohibited terms" htmlFor="p-prohibited" hint="An adaptation that uses one is flagged as a constraint violation.">
            <TermListInput id="p-prohibited" value={prohibited} onChange={setProhibited} placeholder="Add a term" />
          </Field>
          <Field label="Protected terms" htmlFor="p-protected" hint="Must stay verbatim in adaptations whenever they appear in the source.">
            <TermListInput id="p-protected" value={protectedTerms} onChange={setProtectedTerms} placeholder="Add a term" />
          </Field>
        </fieldset>
      </div>
      {create.error && <ErrorState error={create.error} />}
      <div className="flex flex-wrap gap-2 border-t border-border pt-4">
        <Button type="submit" disabled={create.isPending || !name.trim() || !brandName.trim()}>
          {create.isPending ? "Creating project…" : "Create project"}
        </Button>
        <Button type="button" variant="ghost" onClick={onCancel} disabled={create.isPending}>
          Cancel
        </Button>
      </div>
    </form>
  );
}
