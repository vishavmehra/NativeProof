"use client";

import { ArrowRightIcon, BotIcon } from "lucide-react";
import Link from "next/link";
import { useState, type ReactNode } from "react";

import { LimitationList } from "@/components/evidence/limitation-list";
import { Alert, AlertDescription, AlertTitle } from "@/components/ui/alert";
import { buttonVariants } from "@/components/ui/button";
import { Table, TableBody, TableCaption, TableCell, TableHead, TableHeader, TableRow } from "@/components/ui/table";
import { sectionHeading } from "@/features/atlas/market-brief";
import { splitLimitations } from "@/features/atlas/limitations";
import { RunProvenance } from "@/features/atlas/run-provenance";
import type { RehearsalResult, Study } from "@/lib/api/types";
import { formatDateTime } from "@/lib/format";

import { DimensionSummary } from "./dimension-summary";
import { DIMENSIONS, DIMENSION_LABEL } from "./dimensions";
import { DisagreementPanel } from "./disagreement-panel";
import { FindingList, type ReactionIndex, type ShowReactions } from "./finding-list";
import { ReactionList, type Highlight, type Sentiment } from "./reaction-list";

function SimulationDisclosure({ disclosure }: { disclosure: RehearsalResult["simulation_disclosure"] }) {
  const { generated_responses: generated, requested_responses: requested } = disclosure;
  return (
    <aside
      aria-label="Simulation disclosure"
      className="grid gap-1.5 rounded-lg border border-audience/30 bg-audience-soft px-4 py-3 text-sm"
    >
      <p className="flex items-center gap-2 font-semibold">
        <BotIcon aria-hidden className="size-4" />
        Simulated reactions: AI-generated, not real people
      </p>
      <p>{disclosure.description}</p>
      <p className="tabular-nums">
        Generated {generated} of {requested} requested reactions. The count is a generation target, not a sample size
        {generated < requested && "; fewer were available than requested (see limitations)"}.
      </p>
      <p>
        {disclosure.grounded
          ? `Grounded: ${disclosure.grounding_evidence_count} discovery evidence records were supplied to the generator.`
          : "Ungrounded: generated without discovery evidence."}
      </p>
    </aside>
  );
}

const SECTIONS = [
  ["findings", "Findings"],
  ["dimensions", "Dimensions"],
  ["reactions", "Reactions"],
  ["disagreement", "Disagreement"],
  ["validation", "Validation questions"],
] as const;

function Section({ id, title, children }: { id: string; title: string; children: ReactNode }) {
  return (
    <section id={id} aria-labelledby={`${id}-heading`} className="grid scroll-mt-6 gap-4">
      <h2 id={`${id}-heading`} className={sectionHeading}>
        {title}
      </h2>
      {children}
    </section>
  );
}

export function RehearsalResults({
  result,
  study,
  projectId,
}: {
  result: RehearsalResult;
  study: Study | null;
  projectId: string;
}) {
  const [segment, setSegment] = useState("");
  const [sentiment, setSentiment] = useState<Sentiment | "">("");
  const [highlight, setHighlight] = useState<Highlight>(null);

  const index: ReactionIndex = new Map(result.reactions.map((r, i) => [r.id, { no: i + 1, segment: r.segment_label }]));
  const show: ShowReactions = (ids, focus) => {
    const target = result.reactions.find((r) => r.id === focus);
    // Reveal the target if a filter hides it.
    if (target && ((segment && target.segment_label !== segment) || (sentiment && target.sentiment !== sentiment))) {
      setSegment("");
      setSentiment("");
    }
    setHighlight({ ids, focus });
  };
  const raw = result.summary;
  const limits = splitLimitations(
    result.limitations,
    [
      ...(raw ? [...raw.key_findings, ...raw.potential_confusions, ...raw.potential_cultural_risks] : []).map((f) => f.limitations),
      ...DIMENSIONS.map((d) => result.dimension_results[d]?.limitations ?? []),
    ],
    "findings and scores",
  );
  const strip = <T extends { limitations: string[] }>(item: T): T => ({ ...item, limitations: limits.own(item.limitations) });
  const summary = raw && {
    ...raw,
    key_findings: raw.key_findings.map(strip),
    potential_confusions: raw.potential_confusions.map(strip),
    potential_cultural_risks: raw.potential_cultural_risks.map(strip),
  };
  const dimensionResults = Object.fromEntries(
    DIMENSIONS.map((d) => {
      const row = result.dimension_results[d];
      return [d, row && strip(row)];
    }),
  ) as RehearsalResult["dimension_results"];
  const voiceHref = `/projects/${projectId}/voice?${new URLSearchParams({ campaign: result.campaign_id, rehearsal: result.run_id })}`;

  return (
    <div className="grid gap-10">
      <div className="flex flex-col gap-3 border-b pb-4 sm:flex-row sm:items-end sm:justify-between">
        <div className="grid gap-1">
          <h2 className="text-2xl font-semibold tracking-tight">Rehearsal results</h2>
          <p className="text-sm text-muted-foreground">
            {study?.name ?? "Study"} · {result.market.display_name} ·{" "}
            <span className="tabular-nums">{formatDateTime(result.run_metadata.completed_at)}</span>
          </p>
        </div>
        <Link href={voiceHref} className={buttonVariants({ size: "lg" })}>
          Continue to Voice <ArrowRightIcon aria-hidden data-icon="inline-end" />
        </Link>
      </div>

      <SimulationDisclosure disclosure={result.simulation_disclosure} />

      <nav aria-label="Result sections" className="-mt-4 flex flex-wrap gap-x-4 gap-y-1 text-sm">
        {SECTIONS.map(([id, label]) => (
          <a key={id} href={`#${id}`} className="text-muted-foreground underline-offset-4 hover:text-foreground hover:underline">
            {label}
          </a>
        ))}
      </nav>

      {result.status === "partial" && (
        <Alert>
          <AlertTitle>Partial result</AlertTitle>
          <AlertDescription>
            Some stages did not complete. What is shown below was saved; the limitations name what is missing.
          </AlertDescription>
        </Alert>
      )}
      <LimitationList title="Result limitations" items={limits.page} />

      <Section id="findings" title="Executive findings">
        {summary ? (
          <>
            <FindingList
              findings={summary.key_findings}
              evidence={result.evidence}
              index={index}
              onShow={show}
              empty="No key findings were produced."
            />
            <div className="grid gap-8 border-t pt-6 lg:grid-cols-2">
              <section aria-labelledby="confusions-heading" className="grid content-start gap-3">
                <h3 id="confusions-heading" className="text-[15px] font-semibold">
                  Potential confusions
                </h3>
                <FindingList
                  findings={summary.potential_confusions}
                  evidence={result.evidence}
                  index={index}
                  onShow={show}
                  empty="No potential confusions were identified."
                />
              </section>
              <section aria-labelledby="risks-heading" className="grid content-start gap-3">
                <h3 id="risks-heading" className="text-[15px] font-semibold">
                  Potential cultural risks
                </h3>
                <FindingList
                  findings={summary.potential_cultural_risks}
                  evidence={result.evidence}
                  index={index}
                  onShow={show}
                  empty="No potential cultural risks were identified."
                />
              </section>
            </div>
          </>
        ) : (
          <p className="text-sm text-muted-foreground">The analysis stage did not produce a summary for this run.</p>
        )}
      </Section>

      <Section id="dimensions" title="Dimension summary">
        <DimensionSummary results={dimensionResults} />
        {result.segments.length > 0 && (
          <Table className="text-sm">
            <TableCaption className="text-left text-xs">
              Segment scores use the same 0–100 formula over each segment&apos;s reactions; cultural risk is higher when more
              risk is perceived. Few reactions per segment make these thin, and differences are model-generated, not
              verified differences between real groups.
            </TableCaption>
            <TableHeader>
              <TableRow>
                <TableHead>Segment</TableHead>
                <TableHead className="text-right">Reactions</TableHead>
                {DIMENSIONS.map((d) => (
                  <TableHead key={d} className="text-right whitespace-normal">
                    {DIMENSION_LABEL[d]}
                  </TableHead>
                ))}
              </TableRow>
            </TableHeader>
            <TableBody>
              {result.segments.map((s) => (
                <TableRow key={s.label}>
                  <TableCell className="min-w-48 whitespace-normal">
                    <p className="font-medium">{s.label}</p>
                    <p className="text-xs text-muted-foreground">{s.assumptions}</p>
                    <p className="text-[11px] text-muted-foreground">
                      {s.source === "user" ? "Assumption defined in the study" : "Model-generated assumption"}
                    </p>
                  </TableCell>
                  <TableCell className="text-right tabular-nums">{s.response_count}</TableCell>
                  {DIMENSIONS.map((d) => (
                    <TableCell key={d} className="text-right tabular-nums">
                      {s.dimension_scores[d]?.toFixed(1) ?? "—"}
                    </TableCell>
                  ))}
                </TableRow>
              ))}
            </TableBody>
          </Table>
        )}
      </Section>

      <Section id="reactions" title="Synthetic reactions">
        <ReactionList
          reactions={result.reactions}
          evidence={result.evidence}
          segment={segment}
          sentiment={sentiment}
          onSegment={(value) => {
            setSegment(value);
            setHighlight(null);
          }}
          onSentiment={(value) => {
            setSentiment(value);
            setHighlight(null);
          }}
          highlight={highlight}
          onClearHighlight={() => setHighlight(null)}
        />
      </Section>

      <Section id="disagreement" title="Disagreement analysis">
        <DisagreementPanel disagreements={summary?.disagreements ?? []} index={index} onShow={show} />
      </Section>

      <Section id="validation" title="Validation questions">
        {summary && summary.validation_questions.length > 0 ? (
          <>
            <p className="max-w-prose text-xs text-muted-foreground">
              Questions to put to real people or local experts before relying on these synthetic findings.
            </p>
            <ol className="list-decimal space-y-1.5 pl-5 text-sm">
              {summary.validation_questions.map((question) => (
                <li key={question}>{question}</li>
              ))}
            </ol>
          </>
        ) : (
          <p className="text-sm text-muted-foreground">No validation questions were suggested.</p>
        )}
      </Section>

      <RunProvenance metadata={result.run_metadata} />
    </div>
  );
}
