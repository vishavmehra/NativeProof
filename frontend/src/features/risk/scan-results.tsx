"use client";

import { ArrowRight, ChevronLeft, ChevronRight, FileCheck2, Globe, Lightbulb, ShieldAlert, Sparkles } from "lucide-react";
import Link from "next/link";
import { useState, type ReactNode } from "react";

import { Pill, flagEmoji as flag, type PillTone } from "@/components/data/pills";
import { ClaimBadge, ConfidenceBadge, Tag } from "@/components/evidence/badges";
import { EvidenceLinks } from "@/components/evidence/evidence-links";
import { LimitationList } from "@/components/evidence/limitation-list";
import { ErrorState } from "@/components/states";
import { Button, buttonVariants } from "@/components/ui/button";
import { Tabs, TabsContent, TabsList, TabsTrigger } from "@/components/ui/tabs";
import { Textarea } from "@/components/ui/textarea";
import { AssetImage } from "@/features/arena/asset-image";
import { VisionBanner } from "@/features/arena/vision-banner";
import { FIELD_LABEL } from "@/features/voice/change-list";
import { SELECT_CLASS } from "@/features/voice/field";
import { DeterministicTag } from "@/features/voice/risk-flags";
import { formatDateTime, humanize } from "@/lib/format";
import { cn } from "@/lib/utils";

import { useApplyAlternative, useUpdateFinding, type RiskFinding, type RiskScan } from "./api";

type Severity = RiskFinding["severity"];
type Status = "dismissed" | "resolved" | "open";
const FIELDS = ["headline", "body", "call_to_action"] as const;

const RISK: Record<Severity, { label: string; dot: string; tile: string }> = {
  high: { label: "High risk", dot: "bg-danger text-white", tile: "bg-danger-soft/70" },
  medium: { label: "Moderate risk", dot: "bg-warning text-white", tile: "bg-warning-soft/70" },
  low: { label: "Low risk", dot: "bg-info text-white", tile: "bg-info-soft/70" },
};
const ORDER: Severity[] = ["high", "medium", "low"];
const SOURCE_KIND = { content_version: "Campaign version", adaptation: "Adaptation", custom: "Custom text" } as const;
const ACTION_LABEL: Record<Status, string> = { dismissed: "Dismiss", resolved: "Mark resolved", open: "Reopen" };

const PILL_TONE = { high: "red", medium: "orange", low: "blue" } as const satisfies Record<Severity, PillTone>;

function Card({ className, children }: { className?: string; children: ReactNode }) {
  return <section className={cn("rounded-card border border-border bg-surface p-5 shadow-card", className)}>{children}</section>;
}

function Num({ n, severity, className }: { n: number; severity: Severity; className?: string }) {
  return (
    <span className={cn("inline-flex size-6 shrink-0 items-center justify-center rounded-full text-xs font-semibold tabular-nums", RISK[severity].dot, className)}>
      {n}
    </span>
  );
}

function RiskPill({ severity }: { severity: Severity }) {
  return <Pill tone={PILL_TONE[severity]}>{RISK[severity].label}</Pill>;
}

/** Text range of a finding in its field: stored offsets when they match, else the first exact occurrence. */
function rangeOf(f: RiskFinding, text: string) {
  const loc = f.text_location;
  if (!loc) return null;
  if (loc.start != null && loc.end != null && text.slice(loc.start, loc.end) === loc.excerpt) return [loc.start, loc.end] as const;
  const start = text.indexOf(loc.excerpt);
  return start < 0 ? null : ([start, start + loc.excerpt.length] as const);
}

/** The scanned copy with each text finding highlighted and numbered; highlights are buttons that select the finding. */
function HighlightedField({ text, field, ordered, selectedId, onSelect }: { text: string; field: (typeof FIELDS)[number]; ordered: RiskFinding[]; selectedId?: string; onSelect(id: string): void }) {
  const ranges = ordered
    .flatMap((f, i) => {
      if (f.text_location?.field !== field) return [];
      const r = rangeOf(f, text);
      return r ? [{ f, n: i + 1, start: r[0], end: r[1] }] : [];
    })
    .sort((a, b) => a.start - b.start)
    .filter((r, i, all) => i === 0 || r.start >= all[i - 1].end);
  const parts: ReactNode[] = [];
  let at = 0;
  for (const r of ranges) {
    parts.push(text.slice(at, r.start));
    parts.push(
      <button
        key={r.f.id}
        type="button"
        onClick={() => onSelect(r.f.id)}
        aria-pressed={selectedId === r.f.id}
        className={cn(
          "relative rounded-sm px-0.5 text-left underline decoration-2 underline-offset-4 outline-none focus-visible:ring-2 focus-visible:ring-ring/50",
          RISK[r.f.severity].tile,
          r.f.severity === "high" ? "decoration-danger" : r.f.severity === "medium" ? "decoration-warning" : "decoration-info",
          selectedId === r.f.id && "ring-2 ring-primary/40",
        )}
      >
        {text.slice(r.start, r.end)}
        <Num n={r.n} severity={r.f.severity} className="absolute -top-3 -right-3 size-5 text-[10px]" />
      </button>,
    );
    at = r.end;
  }
  parts.push(text.slice(at));
  return <>{parts}</>;
}

function Preview({ scan, ordered, selectedId, onSelect }: { scan: RiskScan; ordered: RiskFinding[]; selectedId?: string; onSelect(id: string): void }) {
  const hasImages = scan.asset_ids.length > 0;
  return (
    <Card>
      <Tabs defaultValue="text">
        <div className="flex flex-wrap items-start justify-between gap-3">
          <div className="grid gap-0.5">
            <h2 className="font-serif text-xl text-ink">Campaign preview</h2>
            <p className="text-sm text-ink-secondary">Select a highlighted passage to see details and the suggested change.</p>
          </div>
          <TabsList>
            <TabsTrigger value="text">Text</TabsTrigger>
            {hasImages && <TabsTrigger value="image">Image</TabsTrigger>}
          </TabsList>
        </div>
        <TabsContent value="text" className="mt-4">
          <div className="grid gap-4 rounded-xl bg-surface-muted/60 p-5">
            {FIELDS.map((field) => {
              const text = scan.content[field];
              if (!text) return null;
              return (
                <div key={field} className="grid gap-1">
                  <span className="text-[11px] font-medium tracking-wide text-ink-secondary uppercase">{FIELD_LABEL[field]}</span>
                  <p className={cn("leading-relaxed text-ink", field === "headline" ? "font-serif text-3xl leading-tight" : "text-base")}>
                    <HighlightedField text={text} field={field} ordered={ordered} selectedId={selectedId} onSelect={onSelect} />
                  </p>
                </div>
              );
            })}
          </div>
        </TabsContent>
        {hasImages && (
          <TabsContent value="image" className="mt-4 grid gap-3">
            <div className="grid grid-cols-[minmax(0,1fr)] gap-3 sm:grid-cols-2">
              {scan.asset_ids.map((id, i) => (
                <AssetImage key={id} assetId={id} alt={`Scanned image ${i + 1}`} className="aspect-video w-full" />
              ))}
            </div>
            {scan.visual_observations.length > 0 ? (
              <ul className="grid gap-1 text-[13px] text-ink">
                {scan.visual_observations.map((o) => {
                  const linked = ordered.findIndex((f) => f.visual_observation_id === o.id);
                  return (
                    <li key={o.id} className="flex items-start gap-2">
                      {linked >= 0 ? <Num n={linked + 1} severity={ordered[linked].severity} /> : <span className="size-6 shrink-0" />}
                      <span>
                        {o.description}
                        <span className="text-xs text-ink-secondary">
                          {" "}
                          · {humanize(o.kind)}
                          {o.location && ` · ${o.location}`}
                        </span>
                      </span>
                    </li>
                  );
                })}
              </ul>
            ) : (
              <p className="text-xs text-ink-secondary">No visual observations were reported for these images.</p>
            )}
            <p className="text-xs text-ink-secondary">Visible elements are listed, not drawn on the image: the vision output has no coordinates.</p>
          </TabsContent>
        )}
      </Tabs>
    </Card>
  );
}

function IssueList({ ordered, selectedId, onSelect }: { ordered: RiskFinding[]; selectedId?: string; onSelect(id: string): void }) {
  return (
    <Card>
      <div className="grid gap-0.5">
        <h2 className="font-serif text-xl text-ink">All detected issues</h2>
        <p className="text-sm text-ink-secondary">Select an issue to view its details and its highlight in the preview.</p>
      </div>
      <ul className="mt-4 grid gap-2">
        {ordered.map((f, i) => (
          <li key={f.id}>
            <button
              type="button"
              onClick={() => onSelect(f.id)}
              aria-pressed={selectedId === f.id}
              className={cn(
                "grid w-full grid-cols-[auto_minmax(0,1fr)_auto] items-center gap-3 rounded-lg px-3 py-2.5 text-left outline-none focus-visible:ring-2 focus-visible:ring-ring/50 sm:grid-cols-[auto_minmax(0,12rem)_auto_minmax(0,1fr)_auto]",
                selectedId === f.id ? "bg-accent" : "bg-surface-muted/50 hover:bg-surface-muted",
              )}
            >
              <Num n={i + 1} severity={f.severity} />
              <span className="font-serif text-[15px] text-ink">{humanize(f.category)}</span>
              <span className="hidden sm:inline">
                <RiskPill severity={f.severity} />
              </span>
              <span className="hidden truncate text-sm text-ink-secondary sm:inline">“{f.observation}”</span>
              <ChevronRight aria-hidden className="size-4 text-ink-secondary" />
            </button>
          </li>
        ))}
      </ul>
    </Card>
  );
}

function Row({ icon, title, children }: { icon: ReactNode; title: string; children: ReactNode }) {
  return (
    <div className="grid grid-cols-[auto_minmax(0,1fr)] gap-3">
      <span className="flex size-9 items-center justify-center rounded-lg bg-surface-muted text-ink-secondary">{icon}</span>
      <div className="grid gap-0.5">
        <h4 className="text-sm font-semibold text-ink">{title}</h4>
        <div className="text-[13px] text-ink-secondary">{children}</div>
      </div>
    </div>
  );
}

function IssueDetail({ scan, ordered, finding, onSelect, projectId }: { scan: RiskScan; ordered: RiskFinding[]; finding: RiskFinding; onSelect(id: string): void; projectId: string }) {
  const update = useUpdateFinding(scan.id);
  const apply = useApplyAlternative(scan.id);
  const [action, setAction] = useState<Status | null>(null);
  const [note, setNote] = useState("");
  const index = ordered.findIndex((f) => f.id === finding.id);
  const original = finding.text_location ? (scan.content[finding.text_location.field] ?? finding.observation) : finding.observation;
  const suggested =
    finding.suggested_alternative && finding.text_location && original.includes(finding.text_location.excerpt)
      ? original.replace(finding.text_location.excerpt, finding.suggested_alternative)
      : finding.suggested_alternative;
  const applyBlocked = scan.source_kind === "custom" ? "Not available for custom text: there is no version to derive from." : !finding.suggested_alternative ? "No alternative was suggested." : null;
  const voiceHref = apply.data ? `/projects/${projectId}/voice?campaign=${apply.data.campaign_id}&adaptation=${apply.data.id}` : null;

  function confirm() {
    if (!action) return;
    update.mutate(
      { findingId: finding.id, body: { status: action, note: note.trim() || null } },
      {
        onSuccess: () => {
          setAction(null);
          setNote("");
        },
      },
    );
  }

  return (
    <Card className="grid content-start gap-4">
      <div className="flex items-center justify-between gap-2 text-sm text-ink-secondary">
        <div className="flex items-center gap-1">
          <Button variant="ghost" size="icon-sm" aria-label="Previous issue" disabled={index <= 0} onClick={() => onSelect(ordered[index - 1].id)}>
            <ChevronLeft aria-hidden />
          </Button>
          <span className="tabular-nums">
            {index + 1} of {ordered.length}
          </span>
          <Button variant="ghost" size="icon-sm" aria-label="Next issue" disabled={index >= ordered.length - 1} onClick={() => onSelect(ordered[index + 1].id)}>
            <ChevronRight aria-hidden />
          </Button>
        </div>
        <Tag className="border-border bg-surface text-ink">{humanize(finding.status)}</Tag>
      </div>

      <div className="grid grid-cols-[auto_minmax(0,1fr)] gap-3">
        <Num n={index + 1} severity={finding.severity} className="size-9 text-base" />
        <div className="grid gap-2">
          <div className="flex flex-wrap items-center justify-between gap-2">
            <h3 className="font-serif text-xl text-ink">{humanize(finding.category)}</h3>
            <RiskPill severity={finding.severity} />
          </div>
          <p className={cn("rounded-lg px-3 py-2 text-sm text-ink", RISK[finding.severity].tile)}>“{finding.observation}”</p>
          <p className="text-[13px] leading-relaxed text-ink-secondary">{finding.interpretation}</p>
        </div>
      </div>

      <Tabs defaultValue="details">
        <TabsList variant="line" className="w-full justify-start">
          <TabsTrigger value="details">Details</TabsTrigger>
          <TabsTrigger value="change">Suggested change</TabsTrigger>
          <TabsTrigger value="evidence">Evidence</TabsTrigger>
        </TabsList>
        <TabsContent value="details" className="mt-4 grid gap-4">
          <Row icon={<ShieldAlert aria-hidden className="size-4" />} title="Why this might be a risk">
            <span className="mr-1.5 inline-flex align-middle">{finding.source === "deterministic_check" ? <DeterministicTag /> : <ClaimBadge claim="interpreted" />}</span>
            {finding.interpretation}
          </Row>
          <Row icon={<Globe aria-hidden className="size-4" />} title="Affected markets">
            <span aria-hidden>{flag(scan.market.country_code)} </span>
            {scan.market.display_name}
          </Row>
          <Row icon={<FileCheck2 aria-hidden className="size-4" />} title="Source of insight">
            {finding.source === "vision_model" ? "Vision model reading of the image" : finding.source === "deterministic_check" ? "Deterministic brand-rule check" : "Model assessment of the copy"}
            {finding.brand_rule && <> · Brand rule: {finding.brand_rule}</>}
            <span className="ml-1.5 inline-flex align-middle">
              <ConfidenceBadge label={finding.confidence_label} />
            </span>
          </Row>
          {finding.suggested_alternative && (
            <Row icon={<Lightbulb aria-hidden className="size-4" />} title="Suggested alternative">
              <div className="mt-1 grid grid-cols-[minmax(0,1fr)_auto_minmax(0,1fr)] items-center gap-2">
                <div className="grid gap-1">
                  <span className="text-xs">Original</span>
                  <p className="rounded-lg bg-ink px-3 py-2 font-serif text-base leading-snug text-white">{original}</p>
                </div>
                <ArrowRight aria-hidden className="size-4 text-primary" />
                <div className="grid gap-1">
                  <span className="text-xs">Suggested</span>
                  <p className="rounded-lg bg-ink px-3 py-2 font-serif text-base leading-snug text-white">{suggested}</p>
                </div>
              </div>
            </Row>
          )}
        </TabsContent>
        <TabsContent value="change" className="mt-4 grid gap-3">
          {finding.suggested_alternative ? (
            <p className="text-sm text-ink">
              Replace <span className="font-medium">“{finding.text_location?.excerpt ?? finding.observation}”</span> with{" "}
              <span className="font-medium">“{finding.suggested_alternative}”</span>. Applying creates a new user-edit adaptation; the campaign is
              never edited in place.
            </p>
          ) : (
            <p className="text-sm text-ink-secondary">No alternative was suggested for this issue.</p>
          )}
          {finding.status_note && (
            <p className="text-[13px] text-ink-secondary">
              <span className="font-medium text-ink">Note: </span>
              {finding.status_note}
            </p>
          )}
          {action ? (
            <div className="grid gap-2">
              <label htmlFor={`note-${finding.id}`} className="text-xs font-medium text-ink">
                Note (optional)
              </label>
              <Textarea id={`note-${finding.id}`} value={note} maxLength={1000} onChange={(e) => setNote(e.target.value)} className="min-h-14 bg-surface" />
              <div className="flex gap-2">
                <Button size="sm" onClick={confirm} disabled={update.isPending}>
                  {update.isPending ? "Saving…" : `Confirm: ${ACTION_LABEL[action].toLowerCase()}`}
                </Button>
                <Button size="sm" variant="ghost" onClick={() => setAction(null)} disabled={update.isPending}>
                  Cancel
                </Button>
              </div>
            </div>
          ) : (
            <div className="flex flex-wrap gap-2">
              {finding.status === "open" ? (
                <>
                  <Button size="sm" variant="outline" onClick={() => setAction("dismissed")}>
                    Dismiss
                  </Button>
                  <Button size="sm" variant="outline" onClick={() => setAction("resolved")}>
                    Mark resolved
                  </Button>
                </>
              ) : finding.status !== "applied" ? (
                <Button size="sm" variant="outline" onClick={() => setAction("open")}>
                  Reopen
                </Button>
              ) : null}
            </div>
          )}
          {update.error ? <ErrorState error={update.error} /> : null}
        </TabsContent>
        <TabsContent value="evidence" className="mt-4 grid gap-3">
          <EvidenceLinks ids={finding.evidence_ids} evidence={scan.evidence} title={humanize(finding.category)} />
          <LimitationList items={finding.limitations} />
        </TabsContent>
      </Tabs>

      {apply.error ? <ErrorState error={apply.error} /> : null}
      <div className="grid grid-cols-[minmax(0,1fr)] gap-2 sm:grid-cols-2">
        <Button
          variant="outline"
          size="lg"
          disabled={Boolean(applyBlocked) || finding.status !== "open" || apply.isPending || Boolean(apply.data)}
          title={applyBlocked ?? undefined}
          onClick={() => apply.mutate(finding.id)}
        >
          <Sparkles aria-hidden />
          {apply.isPending ? "Applying…" : apply.data || finding.status === "applied" ? "Change applied" : "Apply this change"}
        </Button>
        {voiceHref ? (
          <Link className={buttonVariants({ size: "lg" })} href={voiceHref}>
            Use updated version
            <ArrowRight aria-hidden />
          </Link>
        ) : (
          <Button size="lg" disabled title="Apply the change first">
            Use updated version
            <ArrowRight aria-hidden />
          </Button>
        )}
      </div>
      {applyBlocked && finding.status === "open" && <p className="text-xs text-ink-secondary">{applyBlocked}</p>}
    </Card>
  );
}

export function ScanResults({ scan, projectId }: { scan: RiskScan; projectId: string }) {
  const [sort, setSort] = useState<"severity" | "status">("severity");
  const ordered = [...scan.findings].sort((a, b) =>
    sort === "severity" ? ORDER.indexOf(a.severity) - ORDER.indexOf(b.severity) : a.status.localeCompare(b.status) || ORDER.indexOf(a.severity) - ORDER.indexOf(b.severity),
  );
  const [selectedId, setSelectedId] = useState<string | undefined>(ordered[0]?.id);
  const selected = ordered.find((f) => f.id === selectedId) ?? ordered[0];
  const { counts } = scan;

  return (
    <div className="grid gap-5">
      <Card className="grid gap-4 lg:grid-cols-[minmax(0,14rem)_repeat(3,minmax(0,1fr))_minmax(0,14rem)] lg:items-center">
        <div className="grid gap-0.5">
          <h2 className="font-serif text-xl text-ink">Risk overview</h2>
          <p className="text-ink-secondary">
            {scan.findings.length} potential {scan.findings.length === 1 ? "issue" : "issues"} found
          </p>
        </div>
        {ORDER.map((s) => (
          <div key={s} className={cn("flex items-center gap-3 rounded-xl px-4 py-3", RISK[s].tile)}>
            <Num n={counts[s]} severity={s} className="size-9 text-base" />
            <div className="grid">
              <span className="text-sm font-medium text-ink">{RISK[s].label}</span>
              <span className="text-xs text-ink-secondary">
                {s === "high" ? "Needs attention" : s === "medium" ? "Review recommended" : "Minor suggestion"}
              </span>
            </div>
          </div>
        ))}
        <div className="flex items-center gap-3 rounded-xl border border-border px-4 py-3">
          <Globe aria-hidden className="size-5 text-ink" />
          <div className="grid text-sm">
            <span className="text-ink-secondary">Checked for</span>
            <span className="font-medium text-ink">
              <span aria-hidden>{flag(scan.market.country_code)} </span>
              {scan.market.display_name}
            </span>
          </div>
        </div>
      </Card>

      <p className="text-xs text-ink-secondary tabular-nums">
        Scanned: {SOURCE_KIND[scan.source_kind]} · {formatDateTime(scan.created_at)} · {counts.open} open · {counts.dismissed} dismissed ·{" "}
        {counts.resolved} resolved · {counts.applied} applied
        {scan.status === "partial" && " · partial scan"}
      </p>
      <VisionBanner vision={scan.vision} />

      {ordered.length === 0 ? (
        <Card>
          <p className="text-sm text-ink">
            No risks were flagged. That is not proof the content is safe for this market: it reflects only the checks and model reading
            applied here.
          </p>
        </Card>
      ) : (
        <div className="grid grid-cols-[minmax(0,1fr)] gap-5 xl:grid-cols-[minmax(0,1fr)_minmax(0,30rem)]">
          <div className="grid content-start gap-5">
            <Preview scan={scan} ordered={ordered} selectedId={selected?.id} onSelect={setSelectedId} />
            <div className="flex items-center justify-end gap-2 text-sm text-ink-secondary">
              <label htmlFor="risk-sort">Sort by</label>
              <select id="risk-sort" className={cn(SELECT_CLASS, "w-auto")} value={sort} onChange={(e) => setSort(e.target.value as "severity" | "status")}>
                <option value="severity">Severity</option>
                <option value="status">Status</option>
              </select>
            </div>
            <IssueList ordered={ordered} selectedId={selected?.id} onSelect={setSelectedId} />
          </div>
          {selected && <IssueDetail key={selected.id} scan={scan} ordered={ordered} finding={selected} onSelect={setSelectedId} projectId={projectId} />}
        </div>
      )}

      <LimitationList items={scan.limitations} />
    </div>
  );
}
