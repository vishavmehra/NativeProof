"use client";

import { useState } from "react";

import { ClaimBadge, ConfidenceBadge, ModeBadge } from "@/components/evidence/badges";
import { useEvidenceInspector } from "@/components/evidence/evidence-inspector";
import { EvidenceLinks } from "@/components/evidence/evidence-links";
import { LimitationList } from "@/components/evidence/limitation-list";
import { marketNames } from "@/components/forms/fields";
import { ErrorState } from "@/components/states";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { Textarea } from "@/components/ui/textarea";
import { splitLimitations } from "@/features/atlas/limitations";
import { RunProvenance } from "@/features/atlas/run-provenance";
import { CLAIM_LABEL } from "@/lib/evidence";
import { formatDateTime, humanize, shortId } from "@/lib/format";

import type { CulturalProfile, ProfileItem } from "@/lib/api/types";

import { useUpdateProfile } from "./api";

const KINDS: [ProfileItem["kind"], string][] = [
  ["affinity", "Affinities"],
  ["association", "Associations"],
  ["opportunity", "Opportunities"],
  ["conflict", "Conflicts"],
];

function ItemList({ items, profile }: { items: ProfileItem[]; profile: CulturalProfile }) {
  const { inspect } = useEvidenceInspector();
  return (
    <ul className="divide-y">
      {items.map((item) => (
        <li key={item.id} className="grid gap-1.5 py-3 first:pt-0 last:pb-0">
          <div className="flex flex-wrap items-center gap-x-2 gap-y-1">
            <button
              type="button"
              className="rounded-sm text-left font-medium underline-offset-4 outline-none hover:underline focus-visible:ring-3 focus-visible:ring-ring/50"
              onClick={() =>
                inspect({
                  title: item.title,
                  summary: item.explanation,
                  claimLabel: CLAIM_LABEL[item.claim_type],
                  records: profile.evidence.filter((record) => item.evidence_ids.includes(record.id)),
                  limitations: item.limitations,
                })
              }
            >
              {item.title}
            </button>
            <ClaimBadge claim={item.claim_type} />
            <ConfidenceBadge label={item.confidence_label} />
            {item.market && <span className="text-xs text-ink-secondary">{item.market.display_name}</span>}
          </div>
          <p className="text-sm text-ink-secondary">{item.explanation}</p>
          <div className="[contain:inline-size]">
<EvidenceLinks ids={item.evidence_ids} evidence={profile.evidence} title={item.title} />
</div>
          {item.limitations.length > 0 && (
            <p className="text-xs text-ink-secondary">
              <span className="font-medium">Limitations:</span> {item.limitations.join(" ")}
            </p>
          )}
        </li>
      ))}
    </ul>
  );
}

function EditDetails({ profile, onDone }: { profile: CulturalProfile; onDone: () => void }) {
  const update = useUpdateProfile(profile.project_id);
  const [title, setTitle] = useState(profile.title);
  const [notes, setNotes] = useState(profile.notes ?? "");
  const blank = !title.trim();
  return (
    <form
      className="grid gap-3 rounded-md border bg-surface p-3"
      onSubmit={(e) => {
        e.preventDefault();
        if (blank) return;
        update.mutate(
          { profileId: profile.id, body: { title: title.trim(), notes: notes.trim() || null } },
          { onSuccess: onDone },
        );
      }}
    >
      <div className="grid gap-1.5">
        <Label htmlFor="dna-edit-title">Title</Label>
        <Input id="dna-edit-title" value={title} maxLength={120} onChange={(e) => setTitle(e.target.value)} aria-invalid={blank || undefined} />
      </div>
      <div className="grid gap-1.5">
        <Label htmlFor="dna-edit-notes">Notes</Label>
        <Textarea id="dna-edit-notes" value={notes} maxLength={1000} rows={3} onChange={(e) => setNotes(e.target.value)} />
      </div>
      <p className="text-xs text-ink-secondary">Title and notes are yours; the generated items are never edited.</p>
      {Boolean(update.error) && <ErrorState error={update.error} />}
      <div className="flex justify-end gap-2">
        <Button type="button" variant="ghost" onClick={onDone}>
          Cancel
        </Button>
        <Button type="submit" disabled={blank || update.isPending}>
          Save
        </Button>
      </div>
    </form>
  );
}

export function ProfileView({ profile: raw, onRegenerate }: { profile: CulturalProfile; onRegenerate: () => void }) {
  const [editing, setEditing] = useState(false);
  const limits = splitLimitations(raw.limitations, raw.items.map((item) => item.limitations), "profile items");
  const profile = { ...raw, items: raw.items.map((item) => ({ ...item, limitations: limits.own(item.limitations) })) };
  return (
    <article className="grid gap-8">
      <header className="grid gap-3 border-b pb-4">
        <div className="flex flex-wrap items-start justify-between gap-3">
          <div className="grid gap-1">
            <h2 className="text-2xl font-semibold tracking-tight">{profile.title}</h2>
            <p className="flex flex-wrap items-center gap-x-2 gap-y-1 text-sm text-ink-secondary">
              <span>{humanize(profile.subject)} profile</span>·<span>{marketNames(profile.markets)}</span>·
              <span className="tabular-nums">Version {profile.version}</span>·
              <span className="tabular-nums">{formatDateTime(profile.created_at)}</span>
              {profile.status !== "completed" && <span className="font-medium text-warning">· {humanize(profile.status)}</span>}
              <ModeBadge mode={profile.mode} />
            </p>
          </div>
          <div className="flex gap-2">
            {!editing && (
              <Button variant="outline" size="sm" onClick={() => setEditing(true)}>
                Edit title and notes
              </Button>
            )}
            <Button size="sm" onClick={onRegenerate}>
              Regenerate
            </Button>
          </div>
        </div>
        {editing ? (
          <EditDetails profile={raw} onDone={() => setEditing(false)} />
        ) : (
          profile.notes && (
            <p className="max-w-prose text-sm">
              <span className="font-medium">Notes: </span>
              {profile.notes}
            </p>
          )
        )}
      </header>

      {profile.summary ? (
        <section aria-label="Summary" className="grid gap-2">
          <Badge variant="outline">Model-written summary</Badge>
          <p className="max-w-prose rounded-lg border border-dna/30 bg-dna-soft px-4 py-3 text-base leading-relaxed text-ink">{profile.summary}</p>
        </section>
      ) : (
        <p className="text-sm text-ink-secondary">No summary: the evidence was not sufficient for one.</p>
      )}
      <LimitationList title="Profile limitations" items={limits.page} />

      <div className="grid gap-8 xl:grid-cols-2">
        {KINDS.map(([kind, label]) => {
          const items = profile.items.filter((item) => item.kind === kind);
          return (
            <section key={kind} aria-labelledby={`kind-${kind}`} className="grid min-w-0 content-start gap-3 rounded-2xl border bg-card p-4 shadow-card">
              <h3 id={`kind-${kind}`} className="flex items-baseline gap-2 font-serif text-xl">
                {label} <span className="text-sm font-normal text-ink-secondary tabular-nums">{items.length}</span>
              </h3>
              {items.length === 0 ? (
                <p className="text-sm text-ink-secondary">None in this profile.</p>
              ) : (
                <ItemList items={items} profile={profile} />
              )}
            </section>
          );
        })}
      </div>

      <div className="grid gap-6 lg:grid-cols-2">
        <section aria-labelledby="dna-missing" className="grid min-w-0 content-start gap-2 rounded-2xl border bg-card p-4 shadow-card">
          <h3 id="dna-missing" className="font-serif text-lg">
            Missing evidence
          </h3>
          {profile.missing_evidence.length === 0 ? (
            <p className="text-sm text-ink-secondary">No gaps were reported.</p>
          ) : (
            <ul className="list-disc space-y-1 pl-5 text-sm">
              {profile.missing_evidence.map((gap) => (
                <li key={gap}>{gap}</li>
              ))}
            </ul>
          )}
        </section>
        <section aria-labelledby="dna-context" className="grid min-w-0 content-start gap-2 rounded-2xl border bg-card p-4 shadow-card">
          <h3 id="dna-context" className="font-serif text-lg">
            Market context
          </h3>
          {profile.market_context.length === 0 ? (
            <p className="text-sm text-ink-secondary">No market context was recorded.</p>
          ) : (
            <ul className="list-disc space-y-1 pl-5 text-sm">
              {profile.market_context.map((line) => (
                <li key={line}>{line}</li>
              ))}
            </ul>
          )}
        </section>
      </div>

      <p className="text-xs text-ink-secondary">
        Grounded in {profile.source_discovery_run_ids.length} discovery{" "}
        {profile.source_discovery_run_ids.length === 1 ? "run" : "runs"}
        {profile.source_discovery_run_ids.length > 0 && ": "}
        {profile.source_discovery_run_ids.map((id, i) => (
          <span key={id} className="font-mono">
            {i > 0 && ", "}
            {shortId(id)}
          </span>
        ))}
        .
      </p>
      {profile.run_metadata && <RunProvenance metadata={profile.run_metadata} />}
    </article>
  );
}
