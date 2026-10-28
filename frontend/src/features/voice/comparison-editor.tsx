"use client";

import { ArrowRight, CircleAlert, CircleCheck, Copy, PencilLine, Scale, ShieldAlert, Sparkles } from "lucide-react";
import Link from "next/link";
import { useRouter } from "next/navigation";
import { useState, type ReactNode } from "react";

import { CampaignContentView } from "@/components/campaign/content-view";
import { flagEmoji as flag } from "@/components/data/pills";
import { Tag } from "@/components/evidence/badges";
import { LimitationList } from "@/components/evidence/limitation-list";
import { Button, buttonVariants } from "@/components/ui/button";
import { Checkbox } from "@/components/ui/checkbox";
import type { Adaptation, Campaign, Project } from "@/lib/api/types";
import { formatDateTime, shortId } from "@/lib/format";
import { cn } from "@/lib/utils";

import { ChangeList, REASONING } from "./change-list";
import { Panel } from "./field";
import { RevisionEditor } from "./revision-editor";
import { DeterministicTag, RiskFlagList } from "./risk-flags";

const MAX_CANDIDATES = 3;

function OriginTag({ origin }: { origin: Adaptation["origin"] }) {
  return origin === "user_edit" ? (
    <Tag className="border-border bg-surface-muted text-ink">
      <PencilLine aria-hidden />
      User edit
    </Tag>
  ) : (
    <Tag className="border-dashed border-ink-secondary/50 bg-surface text-ink-secondary">Generated</Tag>
  );
}

function Check({ ok, children }: { ok: boolean; children: ReactNode }) {
  return (
    <li className="flex items-start gap-2 text-[13px] text-ink">
      {ok ? <CircleCheck aria-hidden className="mt-0.5 size-3.5 shrink-0 text-success" /> : <CircleAlert aria-hidden className="mt-0.5 size-3.5 shrink-0 text-danger" />}
      <span>{children}</span>
    </li>
  );
}

function BoardCard({ title, actions, children, className }: { title: ReactNode; actions?: ReactNode; children: ReactNode; className?: string }) {
  return (
    <section className={cn("grid content-start gap-3 rounded-card border border-border bg-surface p-5 shadow-card", className)}>
      <div className="flex flex-wrap items-center justify-between gap-2">
        <h2 className="font-serif text-lg text-ink">{title}</h2>
        {actions}
      </div>
      {children}
    </section>
  );
}

/**
 * Voice board (docs/16): 1. Your content | 2. Adapted variations | brand voice, considerations, compare, next steps.
 * The variation details below keep every change, its evidence, the deterministic checks, and the limitations.
 */
export function ComparisonEditor({
  projectId,
  project,
  campaign,
  variants,
  initialSelectedId,
  onRevised,
  contentColumn,
  emptyNote,
  onGenerateMore,
}: {
  projectId: string;
  project: Project;
  campaign: Campaign;
  variants: Adaptation[];
  initialSelectedId?: string;
  onRevised(revision: Adaptation): void;
  contentColumn: ReactNode;
  /** Replaces "No adaptations yet" when the lookup failed, so an error never reads as an empty result. */
  emptyNote?: string;
  /** Opens the adaptation settings; omitted while a run is in progress. */
  onGenerateMore?: () => void;
}) {
  const router = useRouter();
  const [selectedId, setSelectedId] = useState<string | null>(initialSelectedId ?? null);
  const [picked, setPicked] = useState<string[]>([]);
  const [editing, setEditing] = useState(false);
  const [market, setMarket] = useState<string | null>(null);
  const [copied, setCopied] = useState<string | null>(null);

  const markets = [...new Map(variants.map((v) => [v.market.country_code, v.market])).values()];
  const shown = variants.filter((v) => !market || v.market.country_code === market);
  const selected = variants.find((v) => v.id === selectedId) ?? variants[0];
  const byId = new Map(variants.map((v) => [v.id, v]));
  const pickedVersion = picked.length ? byId.get(picked[0])?.source_content_version_id : undefined;
  const source = selected ? campaign.versions.find((v) => v.id === selected.source_content_version_id) : undefined;
  const changedFields = selected ? [...new Set(selected.changes.map((c) => c.field))] : [];

  function select(id: string) {
    setSelectedId(id);
    setEditing(false);
  }

  function blockedReason(v: Adaptation) {
    if (picked.includes(v.id)) return null;
    if (pickedVersion && v.source_content_version_id !== pickedVersion) return "different source version";
    if (picked.length >= MAX_CANDIDATES) return `up to ${MAX_CANDIDATES}`;
    return null;
  }

  async function copy(v: Adaptation) {
    const text = [v.content.headline, v.content.body, v.content.call_to_action].filter(Boolean).join("\n\n");
    try {
      await navigator.clipboard.writeText(text);
      setCopied(v.id);
    } catch {
      setCopied(null);
    }
  }

  function evaluate() {
    const query = new URLSearchParams({ campaign: campaign.id, version: pickedVersion!, candidates: picked.join(",") });
    router.push(`/projects/${projectId}/loop?${query}`);
  }

  return (
    <div className="grid gap-6">
      <div className="grid grid-cols-[minmax(0,1fr)] gap-5 xl:grid-cols-[minmax(0,20rem)_minmax(0,1fr)_minmax(0,19rem)]">
        <BoardCard title="1. Your content">{contentColumn}</BoardCard>

        <BoardCard title="2. Adapted variations">
          {variants.length === 0 ? (
            <p className="text-sm text-ink-secondary">
              {emptyNote ?? "No adaptations yet. Set up your content and generate variations; nothing is scored until you evaluate them in Loop."}
            </p>
          ) : (
            <>
              <p className="-mt-2 text-sm text-ink-secondary">On-brand, culturally adapted variations of your content.</p>
              <div className="flex flex-wrap gap-2" role="group" aria-label="Filter by market">
                {[null, ...markets.map((m) => m.country_code)].map((code) => {
                  const m = markets.find((x) => x.country_code === code);
                  const count = code ? variants.filter((v) => v.market.country_code === code).length : variants.length;
                  return (
                    <button
                      key={code ?? "all"}
                      type="button"
                      aria-pressed={market === code}
                      onClick={() => setMarket(code)}
                      className={cn(
                        "rounded-lg border px-3 py-1 text-sm outline-none focus-visible:ring-2 focus-visible:ring-ring/50",
                        market === code ? "border-primary bg-accent text-primary" : "border-border bg-surface text-ink hover:bg-surface-muted",
                      )}
                    >
                      {m && <span aria-hidden>{flag(m.country_code)} </span>}
                      {m ? m.display_name : "All"} <span className="text-ink-secondary tabular-nums">({count})</span>
                    </button>
                  );
                })}
              </div>
              <ul className="grid grid-cols-[minmax(0,1fr)] gap-4 sm:grid-cols-2">
                {shown.map((v) => {
                  const isSelected = v.id === selected?.id;
                  const reason = blockedReason(v);
                  const parent = v.parent_adaptation_id ? byId.get(v.parent_adaptation_id) : undefined;
                  const issues = v.warnings.length + v.checks.missing_protected_terms.length + v.checks.prohibited_terms_found.length;
                  const evidenceBacked = v.changes.filter((c) => c.reasoning_type === "evidence_supported").length;
                  return (
                    <li key={v.id} className={cn("grid content-start overflow-hidden rounded-xl border bg-surface", isSelected ? "border-primary ring-1 ring-primary/30" : "border-border")}>
                      <button type="button" aria-pressed={isSelected} onClick={() => select(v.id)} className="grid text-left outline-none focus-visible:ring-2 focus-visible:ring-ring/50">
                        <span className="flex items-center justify-between gap-2 px-3 pt-3 text-xs text-ink">
                          <span>
                            <span aria-hidden>{flag(v.market.country_code)} </span>
                            {v.market.display_name}
                          </span>
                          <OriginTag origin={v.origin} />
                        </span>
                        <span className="m-3 flex h-28 items-end rounded-lg bg-ink p-3">
                          <span className="line-clamp-3 font-serif text-lg leading-tight text-white">{v.content.headline ?? "No headline"}</span>
                        </span>
                        <span className="grid gap-1 px-3">
                          <span className="text-sm font-semibold text-ink">{v.label}</span>
                          <span className="line-clamp-2 text-xs text-ink-secondary">{v.strategy}</span>
                          {v.origin === "user_edit" && (
                            <span className="text-xs text-ink-secondary">Edited from {parent ? `“${parent.label}”` : <code className="font-mono">{shortId(v.parent_adaptation_id ?? "")}</code>}</span>
                          )}
                        </span>
                        <span className="flex flex-wrap gap-1.5 px-3 pt-2 text-[11px]">
                          <span className="rounded-full bg-surface-muted px-2 py-0.5 text-ink tabular-nums">
                            {v.changes.length} {v.changes.length === 1 ? "change" : "changes"}
                          </span>
                          {evidenceBacked > 0 && <span className="rounded-full bg-info-soft px-2 py-0.5 text-info tabular-nums">{evidenceBacked} evidence-supported</span>}
                          <span className={cn("rounded-full px-2 py-0.5 tabular-nums", issues ? "bg-warning-soft text-warning" : "bg-success-soft text-success")}>
                            {issues ? `${issues} ${issues === 1 ? "flag" : "flags"}` : "No flags"}
                          </span>
                        </span>
                        {isSelected && <span className="sr-only"> (shown in the details below)</span>}
                      </button>
                      <div className="flex items-center justify-between gap-2 px-3 py-3">
                        <label className="flex items-center gap-2 text-xs text-ink">
                          <Checkbox
                            checked={picked.includes(v.id)}
                            disabled={reason !== null}
                            onCheckedChange={(checked) => setPicked((current) => (checked ? [...current, v.id] : current.filter((id) => id !== v.id)))}
                          />
                          Evaluate
                          {reason && <span className="text-ink-secondary">({reason})</span>}
                        </label>
                        <span className="flex gap-1">
                          <Button variant="ghost" size="icon-sm" aria-label={`Copy ${v.label}`} onClick={() => copy(v)}>
                            {copied === v.id ? <CircleCheck aria-hidden className="text-success" /> : <Copy aria-hidden />}
                          </Button>
                          <Button
                            variant="ghost"
                            size="icon-sm"
                            aria-label={`Edit ${v.label}`}
                            onClick={() => {
                              select(v.id);
                              setEditing(true);
                            }}
                          >
                            <PencilLine aria-hidden />
                          </Button>
                        </span>
                      </div>
                    </li>
                  );
                })}
              </ul>
              <div className="flex flex-wrap items-center gap-x-4 gap-y-2 border-t border-border pt-3">
                <Button onClick={evaluate} disabled={picked.length === 0}>
                  Evaluate selected versions
                </Button>
                <p className="max-w-prose text-xs text-ink-secondary">
                  <span className="tabular-nums">{picked.length}</span> of {MAX_CANDIDATES} selected. Selecting only queues a version for comparison in Loop; it is not
                  an approval.
                </p>
              </div>
            </>
          )}
        </BoardCard>

        <div className="grid content-start gap-5">
          <BoardCard
            title="Brand voice"
            actions={
              <Link className={buttonVariants({ variant: "outline", size: "sm" })} href={`/projects/${projectId}/brand`}>
                Edit
              </Link>
            }
          >
            <p className="-mt-2 text-xs text-ink-secondary">From your Brand Memory.</p>
            {project.brand.voice.length > 0 ? (
              <ul className="flex flex-wrap gap-1.5">
                {project.brand.voice.map((w) => (
                  <li key={w} className="rounded-full border border-border bg-surface-muted px-2.5 py-0.5 text-xs text-ink capitalize">
                    {w}
                  </li>
                ))}
              </ul>
            ) : (
              <p className="text-xs text-ink-secondary">No brand voice recorded yet.</p>
            )}
          </BoardCard>

          {selected && (
            <BoardCard title="Cultural considerations">
              <p className="-mt-2 text-xs text-ink-secondary">For {selected.label}, in {selected.market.display_name}.</p>
              <ul className="grid gap-1.5">
                <li className="flex items-center gap-2 text-[13px] text-ink">
                  <ShieldAlert aria-hidden className="size-4 text-ink-secondary" />
                  {selected.warnings.length ? `${selected.warnings.length} ${selected.warnings.length === 1 ? "warning" : "warnings"} raised` : "No warnings raised"}
                </li>
                <li className="flex items-center gap-2 text-[13px] text-ink">
                  <Scale aria-hidden className="size-4 text-ink-secondary" />
                  {selected.context.grounded ? "Grounded in Qloo evidence" : "Ungrounded: model reasoning only"}
                </li>
              </ul>
              <a className={buttonVariants({ variant: "outline", size: "sm" })} href="#variation-details">
                View considerations
                <ArrowRight aria-hidden />
              </a>
            </BoardCard>
          )}

          {selected && (
            <BoardCard title="Compare versions">
              <div className="grid grid-cols-[minmax(0,1fr)_auto_minmax(0,1fr)] items-start gap-2 text-xs">
                <div className="grid gap-1">
                  <span className="text-ink-secondary">Original</span>
                  <p className="rounded-lg border border-border p-2 text-ink">{source?.content.headline ?? "—"}</p>
                </div>
                <ArrowRight aria-hidden className="mt-6 size-4 text-primary" />
                <div className="grid gap-1">
                  <span className="text-ink-secondary">Selected</span>
                  <p className="rounded-lg border border-primary/30 bg-accent/50 p-2 text-ink">{selected.content.headline ?? "—"}</p>
                </div>
              </div>
              <ul className="flex flex-wrap gap-1.5">
                {selected.changes.map((c, i) => (
                  <li key={i} className={cn("rounded-full px-2 py-0.5 text-[11px]", c.reasoning_type === "evidence_supported" ? "bg-info-soft text-info" : "bg-surface-muted text-ink")}>
                    {c.field.replace(/_/g, " ")} · {REASONING[c.reasoning_type].label}
                  </li>
                ))}
              </ul>
            </BoardCard>
          )}

          <BoardCard title="Next steps">
            <p className="-mt-2 text-xs text-ink-secondary">Test the variations or generate more.</p>
            <div className="grid gap-2">
              <Link className={buttonVariants({ variant: "outline" })} href={`/projects/${projectId}/arena?campaign=${campaign.id}`}>
                Add to Campaign Arena
                <ArrowRight aria-hidden />
              </Link>
              <Button onClick={onGenerateMore} disabled={!onGenerateMore}>
                <Sparkles aria-hidden />
                Generate more
              </Button>
            </div>
          </BoardCard>
        </div>
      </div>

      {selected && (
        <section id="variation-details" aria-labelledby="variation-details-heading" className="grid scroll-mt-24 gap-5">
          <h2 id="variation-details-heading" className="font-serif text-2xl text-ink">
            Variation details · {selected.label}
          </h2>
          <section aria-label="Original and adapted content" className="grid grid-cols-[minmax(0,1fr)] gap-4 md:grid-cols-2">
            <div className="grid content-start gap-3 rounded-card border border-border bg-surface p-4 shadow-card md:p-5">
              <div className="flex flex-wrap items-baseline justify-between gap-2">
                <h3 className="text-[15px] font-semibold text-ink">Original</h3>
                {source && <span className="text-xs text-ink-secondary">Version {source.version_number}</span>}
              </div>
              {source ? (
                <CampaignContentView content={source.content} />
              ) : (
                <p className="text-sm text-ink-secondary">
                  Source version <code className="font-mono text-xs">{shortId(selected.source_content_version_id)}</code> is not part of this campaign&apos;s versions, so
                  the original cannot be shown.
                </p>
              )}
            </div>
            <div className="grid content-start gap-3 rounded-card border border-voice/30 bg-surface p-4 shadow-card md:p-5">
              <div className="flex flex-wrap items-center justify-between gap-2">
                <h3 className="flex flex-wrap items-center gap-2 text-[15px] font-semibold text-ink">
                  {selected.label}
                  <OriginTag origin={selected.origin} />
                </h3>
                {!editing && (
                  <Button variant="outline" size="sm" onClick={() => setEditing(true)}>
                    <PencilLine aria-hidden />
                    Edit variant
                  </Button>
                )}
              </div>
              {editing ? (
                <RevisionEditor
                  key={selected.id}
                  adaptation={selected}
                  onCancel={() => setEditing(false)}
                  onSaved={(revision) => {
                    onRevised(revision);
                    select(revision.id);
                  }}
                />
              ) : (
                <CampaignContentView content={selected.content} highlightFields={changedFields} />
              )}
            </div>
          </section>

          <div className="grid grid-cols-[minmax(0,1fr)] gap-6 lg:grid-cols-[minmax(0,1fr)_minmax(260px,320px)]">
            <Panel id="changes-heading" title="Changes from the original">
              <p className="mb-4 text-sm text-ink">
                <span className="font-medium">Strategy: </span>
                {selected.strategy}
              </p>
              <ChangeList changes={selected.changes} evidence={selected.evidence} limitations={selected.limitations} />
            </Panel>

            <aside className="grid content-start gap-4" aria-label={`Checks and context for ${selected.label}`}>
              <section aria-labelledby="checks-heading" className="grid gap-2.5 rounded-card border border-border bg-surface p-4 shadow-card">
                <div className="flex flex-wrap items-center justify-between gap-2">
                  <h3 id="checks-heading" className="text-sm font-semibold text-ink">
                    Constraint checks
                  </h3>
                  <DeterministicTag />
                </div>
                <ul className="grid gap-1.5">
                  <Check ok={selected.checks.protected_terms_preserved && selected.checks.missing_protected_terms.length === 0}>
                    {selected.checks.missing_protected_terms.length === 0 ? "Protected terms preserved" : `Protected terms missing: ${selected.checks.missing_protected_terms.join(", ")}`}
                  </Check>
                  <Check ok={selected.checks.prohibited_terms_found.length === 0}>
                    {selected.checks.prohibited_terms_found.length === 0 ? "No prohibited terms found" : `Prohibited terms found: ${selected.checks.prohibited_terms_found.join(", ")}`}
                  </Check>
                </ul>
                <p className="text-xs text-ink-secondary">
                  Case-insensitive matching in code. Model reviews run: brand voice {selected.checks.brand_voice_reviewed ? "yes" : "no"}, cultural risk{" "}
                  {selected.checks.cultural_risk_reviewed ? "yes" : "no"}.
                </p>
              </section>

              <section aria-labelledby="warnings-heading" className="grid gap-2.5 rounded-card border border-border bg-surface p-4 shadow-card">
                <h3 id="warnings-heading" className="text-sm font-semibold text-ink">
                  Warnings
                </h3>
                <RiskFlagList flags={selected.warnings} empty="No warnings were raised for this version." />
              </section>

              <section aria-labelledby="context-heading" className="grid gap-2.5 rounded-card border border-border bg-surface p-4 shadow-card">
                <h3 id="context-heading" className="text-sm font-semibold text-ink">
                  Generation context
                </h3>
                <dl className="grid grid-cols-[minmax(0,auto)_minmax(0,1fr)] gap-x-3 gap-y-1.5 text-[13px]">
                  <dt className="text-ink-secondary">Grounded</dt>
                  <dd className={cn(!selected.context.grounded && "text-warning")}>{selected.context.grounded ? "Yes, Qloo evidence supplied" : "No, ungrounded"}</dd>
                  <dt className="text-ink-secondary">Rehearsal</dt>
                  <dd>{selected.context.rehearsal_informed ? "Informed by findings" : "Not used"}</dd>
                  <dt className="text-ink-secondary">Market</dt>
                  <dd>{selected.market.display_name}</dd>
                  <dt className="text-ink-secondary">Created</dt>
                  <dd>{formatDateTime(selected.created_at)}</dd>
                  <dt className="text-ink-secondary">Id</dt>
                  <dd className="font-mono text-xs break-all">{selected.id}</dd>
                </dl>
              </section>

              <LimitationList items={selected.limitations} />
            </aside>
          </div>
        </section>
      )}
    </div>
  );
}
