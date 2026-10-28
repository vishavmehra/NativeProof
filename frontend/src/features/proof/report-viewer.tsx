"use client";

import { useMutation } from "@tanstack/react-query";
import { Download, Printer, TriangleAlert } from "lucide-react";
import Link from "next/link";
import type { ReactNode } from "react";

import { CampaignContentView } from "@/components/campaign/content-view";
import { ClaimBadge, ConfidenceBadge, ModeBadge, SyntheticBadge } from "@/components/evidence/badges";
import { EvidenceLinks } from "@/components/evidence/evidence-links";
import { LimitationList } from "@/components/evidence/limitation-list";
import { ScoreBar } from "@/components/data/score-bar";
import { ErrorState, LoadingState } from "@/components/states";
import { Button } from "@/components/ui/button";
import { ComparisonTable } from "@/features/loop/comparison-table";
import { IntegrityPanel, withFivePointNote } from "@/features/loop/evaluation-results";
import { RecommendationPanel } from "@/features/loop/recommendation-panel";
import { VerdictBlock } from "@/features/loop/verdict";
import { useProject } from "@/features/project/project-context";
import { ChangeList } from "@/features/voice/change-list";
import { RiskFlagList } from "@/features/voice/risk-flags";
import type { BriefFinding, EvidenceRecord, Finding, Report, StepTrace } from "@/lib/api/types";
import { formatDateTime, humanize, shortId } from "@/lib/format";

import { downloadReport, useReport, type ExportFormat } from "./api";
import { EvidenceRegister } from "./evidence-register";

function Section({ id, title, children }: { id: string; title: string; children: ReactNode }) {
  return (
    <section aria-labelledby={id} className="grid grid-cols-[minmax(0,1fr)] gap-4 border-t border-border pt-8">
      <h2 id={id} className="scroll-mt-24 font-serif text-2xl text-ink">
        {title}
      </h2>
      {children}
    </section>
  );
}

const uniq = (items: string[]) => [...new Set(items)];

const TOC = [
  ["summary-heading", "Executive summary"],
  ["signals-heading", "Market signals"],
  ["rehearsal-heading", "Rehearsal findings"],
  ["history-heading", "Adaptation history"],
  ["comparison-heading-report", "Comparison results"],
  ["register-heading", "Evidence register"],
  ["limits-heading", "Limitations and next steps"],
  ["repro-heading", "Reproducibility"],
] as const;

/** Print: drop the app shell, one column, keep headings with their content. Scoped to this page while it is mounted. */
const PRINT_CSS = `@media print {
  aside, header.sticky, nav[aria-label="Report contents"], [data-sonner-toaster], nextjs-portal { display: none !important; }
  html, body { background: #fff !important; }
  #report-root { max-width: none !important; padding-bottom: 0 !important; }
  #report-root .grid { grid-template-columns: minmax(0, 1fr) !important; }
  #report-root .shadow-card { box-shadow: none !important; }
  #report-root h2, #report-root h3, #report-root h4 { break-after: avoid; }
  #report-root li, #report-root tr, #report-root dl > div, #report-root [role="note"] { break-inside: avoid; }
}`;

function NotIncluded({ what }: { what: string }) {
  return <p className="text-sm text-ink-secondary italic">Not included: this report has no {what}.</p>;
}

function List({ items, empty = "None recorded." }: { items: string[]; empty?: string }) {
  if (items.length === 0) return <p className="text-sm text-ink-secondary">{empty}</p>;
  return (
    <ul className="list-disc space-y-1 pl-5 text-sm leading-relaxed text-ink">
      {items.map((item, i) => (
        <li key={i}>{item}</li>
      ))}
    </ul>
  );
}

/** A brief finding or rehearsal finding with its claim type, evidence-quality label, and evidence. */
function FindingItem({ finding, evidence }: { finding: BriefFinding | Finding; evidence: EvidenceRecord[] }) {
  const text = "explanation" in finding ? finding.explanation : finding.summary;
  return (
    <li className="grid grid-cols-[minmax(0,1fr)] gap-1.5 py-3 first:pt-0">
      <div className="flex flex-wrap items-center gap-1.5">
        <h4 className="mr-1 text-sm font-medium text-ink">{finding.title}</h4>
        <ClaimBadge claim={finding.claim_type} />
        <ConfidenceBadge label={finding.confidence_label} />
      </div>
      <p className="text-sm leading-relaxed text-ink">{text}</p>
      <EvidenceLinks ids={finding.evidence_ids} evidence={evidence} title={finding.title} />
    </li>
  );
}

function FindingGroup({ title, findings, evidence }: { title: string; findings: (BriefFinding | Finding)[]; evidence: EvidenceRecord[] }) {
  if (findings.length === 0) return null;
  return (
    <div className="grid grid-cols-[minmax(0,1fr)] gap-2">
      <h3 className="text-xs font-semibold tracking-wide text-ink-secondary uppercase">{title}</h3>
      <ul className="divide-y divide-border">
        {findings.map((f) => (
          <FindingItem key={f.id} finding={f} evidence={evidence} />
        ))}
      </ul>
    </div>
  );
}

function StepTable({ steps }: { steps: StepTrace[] }) {
  if (steps.length === 0) return <p className="text-xs text-ink-secondary">No step traces recorded.</p>;
  return (
    <div className="overflow-x-auto">
      <table className="w-full min-w-160 text-xs">
        <thead>
          <tr className="border-b text-left text-ink-secondary">
            {["Stage", "Agent", "Status", "Provider", "Model", "Prompt version", "Latency", "Retries"].map((h) => (
              <th key={h} scope="col" className="py-1.5 pr-3 font-medium">
                {h}
              </th>
            ))}
          </tr>
        </thead>
        <tbody>
          {steps.map((s, i) => (
            <tr key={i} className="border-b border-border/60 text-ink">
              <td className="py-1.5 pr-3">{humanize(s.stage)}</td>
              <td className="py-1.5 pr-3">{s.agent}</td>
              <td className="py-1.5 pr-3">{humanize(s.status)}</td>
              <td className="py-1.5 pr-3 font-mono">{s.provider ?? "—"}</td>
              <td className="py-1.5 pr-3 font-mono">{s.model_id ?? "—"}</td>
              <td className="py-1.5 pr-3 font-mono">{s.prompt_version ?? "—"}</td>
              <td className="py-1.5 pr-3 tabular-nums">{s.latency_ms === null ? "—" : `${s.latency_ms} ms`}</td>
              <td className="py-1.5 pr-3 tabular-nums">
                {s.retries}
                {s.fallback_used && " · fallback"}
              </td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}

function ExportButtons({ report }: { report: Report }) {
  const exporter = useMutation({ mutationFn: (format: ExportFormat) => downloadReport(report, format) });
  return (
    <div className="grid grid-cols-[minmax(0,1fr)] gap-2 print:hidden">
      <div className="flex flex-wrap gap-2">
        {(["markdown", "json"] as const).map((format) => (
          <Button key={format} variant="outline" size="sm" disabled={exporter.isPending} onClick={() => exporter.mutate(format)}>
            <Download aria-hidden />
            {format === "markdown" ? "Export Markdown" : "Export JSON"}
          </Button>
        ))}
        <Button variant="outline" size="sm" onClick={() => window.print()}>
          <Printer aria-hidden />
          Print / Save as PDF
        </Button>
      </div>
      {exporter.error ? <ErrorState error={exporter.error} onRetry={() => exporter.reset()} /> : null}
    </div>
  );
}

export function ReportViewer({ reportId }: { reportId: string }) {
  const { project } = useProject();
  const query = useReport(reportId);
  if (query.isPending) return <LoadingState label="Loading report…" />;
  if (query.isError) return <ErrorState error={query.error} onRetry={() => query.refetch()} />;
  const report = query.data;
  const { executive_summary: summary, discovery, rehearsal, evaluation, reproducibility: repro } = report;
  // version-consistency disclosures arrive as limitation strings until the contract gives them a field.
  const versionNotes = report.limitations.filter((l) => /\bversions?\b/i.test(l) && /differ|mismatch|inconsisten|another|other/i.test(l));
  // Each limitation appears once in the view: section lists first, then whatever is left at the end.
  const evaluationLimits = evaluation ? withFivePointNote(uniq(evaluation.limitations)) : [];
  const shownElsewhere = new Set([...versionNotes, ...evaluationLimits, ...(discovery?.market_brief?.limitations ?? [])]);
  const reportLimits = uniq(report.limitations).filter((l) => !shownElsewhere.has(l));
  const toc = TOC.filter(([id]) => id !== "comparison-heading-report" || evaluation);

  return (
    <article id="report-root" className="mx-auto grid w-full max-w-4xl grid-cols-[minmax(0,1fr)] gap-8 pb-12">
      <style>{PRINT_CSS}</style>
      <header className="grid grid-cols-[minmax(0,1fr)] gap-4">
        <Link href={`/projects/${project.id}/proof`} className="w-fit text-xs text-ink-secondary underline-offset-2 hover:underline print:hidden">
          ← All reports
        </Link>
        <div className="flex flex-wrap items-center gap-2">
          <ModeBadge mode={report.mode} />
          <span className={report.status === "partial" ? "text-xs font-medium text-warning" : "text-xs font-medium text-ink-secondary"}>
            {report.status === "partial" ? "Partial report" : "Complete report"} · version {report.version_number}
          </span>
        </div>
        <h1 className="font-serif text-4xl leading-tight text-ink md:text-[44px]">{report.title}</h1>
        <dl className="grid grid-cols-[minmax(0,1fr)] gap-x-8 gap-y-2 text-sm sm:grid-cols-2 lg:grid-cols-4">
          {[
            ["Project", project.name],
            ["Campaign", report.campaign.name],
            ["Market", report.market?.display_name ?? "Not recorded"],
            ["Created", formatDateTime(report.created_at)],
          ].map(([term, value]) => (
            <div key={term} className="grid grid-cols-[minmax(0,1fr)] gap-0.5">
              <dt className="text-xs text-ink-secondary">{term}</dt>
              <dd className="text-ink">{value}</dd>
            </div>
          ))}
        </dl>
        <ExportButtons report={report} />
      </header>

      {evaluation && <VerdictBlock evaluation={evaluation} />}

      <nav aria-label="Report contents" className="rounded-card border border-border bg-surface px-4 py-3 shadow-card print:hidden">
        <h2 className="text-xs font-semibold tracking-wide text-ink-secondary uppercase">Contents</h2>
        <ol className="mt-2 grid grid-cols-[minmax(0,1fr)] gap-x-6 gap-y-1 text-sm sm:grid-cols-2">
          {toc.map(([id, label], i) => (
            <li key={id}>
              <a href={`#${id}`} className="text-ink underline-offset-2 hover:underline">
                <span className="mr-1.5 text-xs text-ink-secondary tabular-nums">{i + 1}.</span>
                {label}
              </a>
            </li>
          ))}
        </ol>
      </nav>

      {report.missing_sections.length > 0 && (
        <div role="note" className="flex gap-2.5 rounded-md border border-warning/30 bg-warning-soft/70 px-4 py-3 text-sm text-ink">
          <TriangleAlert aria-hidden className="mt-0.5 size-4 shrink-0 text-warning" />
          <p>
            <span className="font-semibold">Partial report.</span> These sections are missing because their stage was not selected or
            did not complete: {report.missing_sections.join(", ")}.
          </p>
        </div>
      )}

      {versionNotes.length > 0 && (
        <div role="note" className="flex gap-2.5 rounded-lg border border-warning/30 bg-warning-soft/70 px-4 py-3 text-sm text-ink">
          <TriangleAlert aria-hidden className="mt-0.5 size-4 shrink-0 text-warning" />
          <div className="grid grid-cols-[minmax(0,1fr)] gap-1">
            <p className="font-semibold">Content versions differ across this report</p>
            <ul className="list-disc space-y-0.5 pl-5">
              {versionNotes.map((note, i) => (
                <li key={i}>{note}</li>
              ))}
            </ul>
          </div>
        </div>
      )}

      <Section id="summary-heading" title="Executive summary">
        <p className="text-base leading-relaxed text-ink">{summary.investigated}</p>
        <div className="grid grid-cols-[minmax(0,1fr)] gap-6 md:grid-cols-2">
          <div className="grid grid-cols-[minmax(0,1fr)] content-start gap-2">
            <h3 className="text-sm font-semibold text-ink">What the research suggests</h3>
            <List items={summary.findings} />
          </div>
          <div className="grid grid-cols-[minmax(0,1fr)] content-start gap-2">
            <h3 className="text-sm font-semibold text-ink">What changed</h3>
            <List items={summary.changes} />
          </div>
          <div className="grid grid-cols-[minmax(0,1fr)] content-start gap-2">
            <h3 className="text-sm font-semibold text-ink">What remains uncertain</h3>
            <List items={summary.uncertainties} />
          </div>
          <div className="grid grid-cols-[minmax(0,1fr)] content-start gap-2">
            <h3 className="text-sm font-semibold text-ink">What should happen next</h3>
            <List items={summary.next_steps} />
          </div>
        </div>
      </Section>

      <Section id="signals-heading" title="Market signals">
        {discovery ? (
          <>
            <p className="text-sm text-ink">
              <span className="text-ink-secondary">Research question: </span>
              {discovery.research_question}
            </p>
            <ul className="divide-y divide-border border-y border-border">
              {discovery.references.map((ref) => (
                <li key={ref.id} className="grid grid-cols-[minmax(0,1fr)] gap-1.5 py-3">
                  <div className="flex flex-wrap items-baseline gap-2">
                    <h3 className="text-sm font-medium text-ink">{ref.name ?? ref.query_term}</h3>
                    <span className="text-xs text-ink-secondary">
                      “{ref.query_term}” · {humanize(ref.match_status)}
                      {ref.entity_type && ` · ${ref.entity_type}`}
                    </span>
                  </div>
                  {ref.relevance_explanation && (
                    <p className="flex flex-wrap items-center gap-1.5 text-[13px] text-ink">
                      <ClaimBadge claim="interpreted" /> {ref.relevance_explanation}
                    </p>
                  )}
                  {ref.match_status === "ambiguous" && ref.candidates.length > 0 && (
                    <p className="text-xs text-ink-secondary">
                      Ambiguous; not used downstream. Candidates: {ref.candidates.map((c) => c.name).join(", ")}
                    </p>
                  )}
                  <EvidenceLinks ids={ref.evidence_ids} evidence={report.evidence_register} title={ref.name ?? ref.query_term} />
                  {ref.limitations.length > 0 && <p className="text-xs text-ink-secondary">{ref.limitations.join(" · ")}</p>}
                </li>
              ))}
            </ul>
            {discovery.market_brief ? (
              <div className="grid grid-cols-[minmax(0,1fr)] gap-4">
                <div className="grid grid-cols-[minmax(0,1fr)] gap-1.5">
                  <h3 className="flex flex-wrap items-center gap-2 text-sm font-semibold text-ink">
                    Market brief <ClaimBadge claim="interpreted" />
                  </h3>
                  <p className="text-sm leading-relaxed text-ink">{discovery.market_brief.summary}</p>
                </div>
                <FindingGroup title="Observations" findings={discovery.market_brief.observations} evidence={report.evidence_register} />
                <FindingGroup title="Opportunities" findings={discovery.market_brief.opportunities} evidence={report.evidence_register} />
                <FindingGroup title="Risks" findings={discovery.market_brief.risks} evidence={report.evidence_register} />
                <LimitationList items={discovery.market_brief.limitations} title="Brief limitations" />
              </div>
            ) : (
              <p className="text-sm text-ink-secondary">No market brief was generated for this discovery.</p>
            )}
          </>
        ) : (
          <NotIncluded what="discovery" />
        )}
      </Section>

      <Section id="rehearsal-heading" title="Rehearsal findings">
        {rehearsal ? (
          <>
            <div className="grid grid-cols-[minmax(0,1fr)] gap-1.5 rounded-md border border-dashed border-ink-secondary/40 bg-surface-muted/60 px-4 py-3">
              <SyntheticBadge />
              <p className="text-sm text-ink">{rehearsal.simulation_disclosure.description}</p>
              <p className="text-xs text-ink-secondary tabular-nums">
                {rehearsal.simulation_disclosure.generated_responses} generated of {rehearsal.simulation_disclosure.requested_responses}{" "}
                requested · not an independent human sample ·{" "}
                {rehearsal.simulation_disclosure.grounded
                  ? `grounded in ${rehearsal.simulation_disclosure.grounding_evidence_count} evidence records`
                  : "ungrounded"}
              </p>
            </div>
            <div className="grid grid-cols-[minmax(0,1fr)] gap-4 sm:grid-cols-2">
              {Object.values(rehearsal.dimension_results).flatMap((d) =>
                d ? (
                  <ScoreBar
                    key={d.dimension}
                    label={humanize(d.dimension)}
                    value={d.score}
                    higherIsBetter={d.higher_is_better}
                    definition={d.definition}
                    note={`${d.n} synthetic ratings · spread ${d.spread ?? "—"}${d.disagreement ? " · disagreement" : ""}`}
                  />
                ) : [],
              )}
            </div>
            {rehearsal.summary ? (
              <>
                <FindingGroup title="Key findings" findings={rehearsal.summary.key_findings} evidence={report.evidence_register} />
                <FindingGroup title="Potential confusions" findings={rehearsal.summary.potential_confusions} evidence={report.evidence_register} />
                <FindingGroup title="Potential cultural risks" findings={rehearsal.summary.potential_cultural_risks} evidence={report.evidence_register} />
                {rehearsal.summary.disagreements.length > 0 && (
                  <div className="grid grid-cols-[minmax(0,1fr)] gap-2">
                    <h3 className="text-xs font-semibold tracking-wide text-ink-secondary uppercase">Disagreements</h3>
                    <ul className="divide-y divide-border">
                      {rehearsal.summary.disagreements.map((d) => (
                        <li key={d.id} className="grid grid-cols-[minmax(0,1fr)] gap-1 py-3 first:pt-0 text-sm text-ink">
                          <h4 className="font-medium">{d.topic}</h4>
                          <p className="text-[13px]">
                            <span className="text-ink-secondary">Possible explanations (hypotheses): </span>
                            {d.possible_explanations.join(" · ")}
                          </p>
                          <p className="text-[13px]">
                            <span className="text-ink-secondary">Validate: </span>
                            {d.validation_question}
                          </p>
                        </li>
                      ))}
                    </ul>
                  </div>
                )}
              </>
            ) : (
              <p className="text-sm text-ink-secondary">No rehearsal summary was produced.</p>
            )}
          </>
        ) : (
          <NotIncluded what="rehearsal" />
        )}
      </Section>

      <Section id="history-heading" title="Adaptation history">
        <div className="grid grid-cols-[minmax(0,1fr)] gap-2 rounded-card border border-border bg-surface shadow-card p-4">
          <h3 className="text-sm font-semibold text-ink">Original</h3>
          <CampaignContentView content={report.campaign.content} />
        </div>
        {report.adaptations.length === 0 ? (
          <NotIncluded what="adaptations" />
        ) : (
          report.adaptations.map((a) => (
            <div key={a.id} className="grid grid-cols-[minmax(0,1fr)] gap-4 rounded-card border border-border bg-surface p-4 shadow-card lg:grid-cols-2">
              <div className="grid grid-cols-[minmax(0,1fr)] content-start gap-2">
                <h3 className="text-sm font-semibold text-ink">
                  {a.label}{" "}
                  <span className="text-xs font-normal text-ink-secondary">
                    {a.origin === "user_edit" ? "User edit" : "Generated"} · {a.market.display_name}
                  </span>
                </h3>
                <p className="text-[13px] text-ink-secondary">{a.strategy}</p>
                <CampaignContentView content={a.content} highlightFields={[...new Set(a.changes.map((c) => c.field))]} />
              </div>
              <div className="grid grid-cols-[minmax(0,1fr)] content-start gap-3">
                <ChangeList changes={a.changes} evidence={a.evidence} limitations={a.limitations} />
                <RiskFlagList flags={a.warnings} empty="No warnings were raised." />
              </div>
            </div>
          ))
        )}
      </Section>

      <Section id="comparison-heading-report" title="Comparison results">
        {evaluation ? (
          <>
            <ComparisonTable evaluation={evaluation} headingAs="h3" />
            <RecommendationPanel evaluation={evaluation} headingAs="h3" />
            <IntegrityPanel comparability={evaluation.comparability} headingAs="h3" />
            <LimitationList items={evaluationLimits} title="Evaluation limitations" />
          </>
        ) : (
          <NotIncluded what="evaluation" />
        )}
      </Section>

      <Section id="register-heading" title="Evidence register">
        <EvidenceRegister records={report.evidence_register} />
      </Section>

      <Section id="limits-heading" title="Limitations and next steps">
        <LimitationList items={reportLimits} title="Report limitations" />
        <div className="grid grid-cols-[minmax(0,1fr)] gap-2">
          <h3 className="text-sm font-semibold text-ink">Recommended real-world validation</h3>
          <List items={report.validation_steps} empty="No validation steps were recorded." />
        </div>
      </Section>

      <Section id="repro-heading" title="Reproducibility">
        <dl className="grid gap-x-8 gap-y-2 text-sm sm:grid-cols-2">
          <div className="grid grid-cols-[minmax(0,1fr)] gap-0.5">
            <dt className="text-xs text-ink-secondary">Generated</dt>
            <dd className="text-ink">{formatDateTime(repro.generated_at)}</dd>
          </div>
          <div className="grid grid-cols-[minmax(0,1fr)] gap-0.5">
            <dt className="text-xs text-ink-secondary">Scoring version</dt>
            <dd className="font-mono text-ink">{repro.scoring_version ?? "None"}</dd>
          </div>
          <div className="grid grid-cols-[minmax(0,1fr)] gap-0.5">
            <dt className="text-xs text-ink-secondary">Model identifiers</dt>
            <dd className="font-mono text-xs text-ink">{repro.model_ids.length ? repro.model_ids.join(", ") : "None recorded"}</dd>
          </div>
          <div className="grid grid-cols-[minmax(0,1fr)] gap-0.5">
            <dt className="text-xs text-ink-secondary">Prompt versions</dt>
            <dd className="font-mono text-xs text-ink">{repro.prompt_versions.length ? repro.prompt_versions.join(", ") : "None recorded"}</dd>
          </div>
        </dl>
        <List items={repro.notes} empty="No reproducibility notes." />
        <div className="grid grid-cols-[minmax(0,1fr)] gap-5">
          {repro.runs.map((run) => (
            <div key={run.run_id} className="grid grid-cols-[minmax(0,1fr)] gap-2">
              <h3 className="flex flex-wrap items-center gap-2 text-sm font-medium text-ink">
                Run <code className="font-mono text-xs">{shortId(run.run_id)}</code>
                <ModeBadge mode={run.mode} />
                <span className="text-xs font-normal text-ink-secondary">
                  {formatDateTime(run.started_at)} → {formatDateTime(run.completed_at)}
                </span>
              </h3>
              <StepTable steps={run.steps} />
            </div>
          ))}
        </div>
      </Section>
    </article>
  );
}
