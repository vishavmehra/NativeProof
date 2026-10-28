"use client";

import { useState, type FormEvent } from "react";

import { Field } from "@/components/forms/fields";
import { ErrorState } from "@/components/states";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Textarea } from "@/components/ui/textarea";
import type { Adaptation } from "@/lib/api/types";

import { useReviseAdaptation } from "./api";

const LIMIT = { headline: 300, body: 5000, call_to_action: 200, terms: 20 } as const;

const count = (value: string, max: number) => (
  <span className="tabular-nums">
    {value.length} / {max}
  </span>
);

/** Edits are saved as a new adaptation (origin user_edit, parent link). The edited variant is never overwritten. */
export function RevisionEditor({
  adaptation,
  onCancel,
  onSaved,
}: {
  adaptation: Adaptation;
  onCancel(): void;
  onSaved(revision: Adaptation): void;
}) {
  const revise = useReviseAdaptation();
  const source = adaptation.content;
  const [headline, setHeadline] = useState(source.headline ?? "");
  const [body, setBody] = useState(source.body ?? "");
  const [cta, setCta] = useState(source.call_to_action ?? "");
  const [terms, setTerms] = useState(source.reference_terms.join(", "));
  const [note, setNote] = useState("");

  const termList = [...new Set(terms.split(",").map((t) => t.trim()).filter(Boolean))];
  const unchanged =
    headline === (source.headline ?? "") &&
    body === (source.body ?? "") &&
    cta === (source.call_to_action ?? "") &&
    termList.join("\n") === source.reference_terms.join("\n");
  const empty = !headline.trim() && !body.trim() && !cta.trim();
  const tooManyTerms = termList.length > LIMIT.terms;

  function submit(event: FormEvent) {
    event.preventDefault();
    if (unchanged || empty || tooManyTerms) return;
    revise.mutate(
      {
        id: adaptation.id,
        body: {
          content: {
            headline: headline.trim() || null,
            body: body.trim() || null,
            call_to_action: cta.trim() || null,
            reference_terms: termList,
          },
          note: note.trim() || null,
        },
      },
      { onSuccess: onSaved },
    );
  }

  return (
    <form onSubmit={submit} className="grid gap-4" aria-label={`Edit ${adaptation.label}`}>
      <Field label="Headline" htmlFor="rev-headline" hint={count(headline, LIMIT.headline)}>
        <Input id="rev-headline" aria-describedby="rev-headline-hint" value={headline} maxLength={LIMIT.headline} onChange={(e) => setHeadline(e.target.value)} className="bg-surface" />
      </Field>
      <Field label="Body" htmlFor="rev-body" hint={count(body, LIMIT.body)}>
        <Textarea id="rev-body" aria-describedby="rev-body-hint" value={body} maxLength={LIMIT.body} onChange={(e) => setBody(e.target.value)} className="min-h-24 bg-surface" />
      </Field>
      <Field label="Call to action" htmlFor="rev-cta" hint={count(cta, LIMIT.call_to_action)}>
        <Input id="rev-cta" aria-describedby="rev-cta-hint" value={cta} maxLength={LIMIT.call_to_action} onChange={(e) => setCta(e.target.value)} className="bg-surface" />
      </Field>
      <Field
        label="Reference terms"
        htmlFor="rev-terms"
        hint="Comma-separated."
        error={tooManyTerms ? `At most ${LIMIT.terms} terms (currently ${termList.length}).` : null}
      >
        <Input id="rev-terms" aria-describedby="rev-terms-hint" value={terms} onChange={(e) => setTerms(e.target.value)} className="bg-surface" />
      </Field>
      <Field label="Note" htmlFor="rev-note" hint="Why you made this edit. Stored with the revision.">
        <Input id="rev-note" aria-describedby="rev-note-hint" value={note} onChange={(e) => setNote(e.target.value)} className="bg-surface" />
      </Field>

      <p className="text-xs text-ink-secondary">
        Saving creates a new version marked “User edit”; “{adaptation.label}” stays unchanged. Deterministic checks rerun, and no model
        reviews the edit.
      </p>
      {revise.error ? <ErrorState error={revise.error} /> : null}
      <div className="flex flex-wrap items-center gap-2">
        <Button type="submit" disabled={unchanged || empty || tooManyTerms || revise.isPending}>
          {revise.isPending ? "Saving…" : "Save as new version"}
        </Button>
        <Button type="button" variant="ghost" onClick={onCancel} disabled={revise.isPending}>
          Cancel
        </Button>
        {unchanged && <span className="text-xs text-ink-secondary">No changes yet.</span>}
        {empty && <span className="text-xs text-ink-secondary">Provide at least a headline, body, or call to action.</span>}
      </div>
    </form>
  );
}
