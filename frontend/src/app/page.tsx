import { ArrowRight } from "lucide-react";
import type { Metadata } from "next";
import Link from "next/link";

import { buttonVariants } from "@/components/ui/button";
import { FEATURES, type FeatureKey } from "@/features/project/features";
import { LABEL_MEANING, type EvidenceUiLabel } from "@/lib/evidence";
import { cn } from "@/lib/utils";

export const metadata: Metadata = { title: { absolute: "Nativeproof: evidence-aware campaign research" } };

const STEPS: { key: FeatureKey; verb: string; text: string }[] = [
  { key: "atlas", verb: "Discover", text: "Resolve your campaign's cultural references against Qloo affinity data and read a market brief that separates source data from interpretation." },
  { key: "audience", verb: "Simulate", text: "Rehearse the campaign with synthetic reactions across stated audience assumptions. Each one is labeled AI-generated; none stands in for a participant." },
  { key: "voice", verb: "Adapt", text: "Generate market-specific variants that keep protected brand terms intact, with every change explained and its evidence linked." },
  { key: "loop", verb: "Compare", text: "Score the original and its adaptations under one documented scoring version, and see the trade-offs instead of a single opaque winner." },
  { key: "proof", verb: "Prove", text: "Assemble a report with the evidence register, provenance, and limitations, ready to export." },
];

const LABELS: EvidenceUiLabel[] = ["Source data", "Calculated", "Model interpretation", "Synthetic", "Unverified", "Observed outcome"];

const PRINCIPLES = [
  ["Affinity is not demand", "Cultural affinity data shows what a market engages with. It does not establish purchase intent or campaign success."],
  ["Synthetic is labeled", "Simulated reactions are hypotheses for real-world validation, never counted as human responses."],
  ["Scores have definitions", "Every score states how it was calculated and what it does not establish. Confidence labels are rules, not probabilities."],
  ["Demo data says so", "Demo projects run on labeled fixtures and carry a persistent DEMO DATA indicator."],
];

export default function LandingPage() {
  return (
    <div className="min-h-dvh">
      <header className="mx-auto flex h-16 max-w-[1200px] items-center justify-between px-4 sm:px-6">
        <span className="font-serif text-[24px] font-semibold tracking-tight text-ink">Nativeproof</span>
        <Link href="/projects" className={buttonVariants({ variant: "outline" })}>
          Open the workspace
        </Link>
      </header>

      <main id="main">
        <section className="mx-auto grid max-w-[1200px] gap-12 px-4 pt-12 pb-16 sm:px-6 lg:grid-cols-[minmax(0,1.15fr)_minmax(0,1fr)] lg:pt-20">
          <div className="space-y-6">
            <p className="text-sm font-medium text-primary">Cultural intelligence for campaign decisions</p>
            <h1 className="font-serif text-[44px] leading-[1.02] font-medium tracking-tight text-ink sm:text-[60px]">
              Understand the market. Test the message. Adapt with evidence.
            </h1>
            <p className="max-w-xl text-[17px] leading-relaxed text-ink-body">
              Nativeproof is a research workspace for taking a campaign into a new market. It combines cultural affinity data, synthetic
              rehearsals, and controlled adaptation, and shows exactly what each conclusion rests on.
            </p>
            <div className="flex flex-wrap gap-3">
              <Link href="/projects" className={buttonVariants({ size: "lg" })}>
                Start researching <ArrowRight aria-hidden />
              </Link>
              <a href="#how-it-works" className={buttonVariants({ size: "lg", variant: "ghost" })}>
                How it works
              </a>
            </div>
          </div>
          <div className="self-end rounded-2xl border border-border bg-surface p-6 shadow-card">
            <p className="text-xs font-semibold tracking-[0.08em] text-ink-secondary uppercase">Every result carries its label</p>
            <ul className="mt-4 divide-y divide-border">
              {LABELS.map((label) => (
                <li key={label} className="grid grid-cols-[150px_minmax(0,1fr)] gap-3 py-2.5 text-[13px]">
                  <span className="font-serif text-[17px] text-ink">{label}</span>
                  <span className="text-ink-secondary">{LABEL_MEANING[label]}</span>
                </li>
              ))}
            </ul>
          </div>
        </section>

        <section id="how-it-works" aria-labelledby="how-title" className="border-y border-border bg-surface-muted">
          <div className="mx-auto max-w-[1200px] px-4 py-16 sm:px-6">
            <h2 id="how-title" className="font-serif text-[34px] font-medium tracking-tight text-ink">
              One workflow, from signal to report
            </h2>
            <ol className="mt-10 grid gap-6 md:grid-cols-5">
              {STEPS.map((step, i) => {
                const f = FEATURES[step.key];
                return (
                  <li key={step.key} className="space-y-3">
                    <div className="flex items-center gap-2.5">
                      <span className={cn("flex size-9 items-center justify-center rounded-lg", f.tone.soft)}>
                        <f.Icon aria-hidden className={cn("size-[18px]", f.tone.ink)} />
                      </span>
                      <span className="font-serif text-lg text-ink-secondary tabular-nums">{String(i + 1).padStart(2, "0")}</span>
                    </div>
                    <h3 className="text-[15px] font-semibold text-ink">
                      {step.verb} <span className="font-normal text-ink-secondary">· {f.label}</span>
                    </h3>
                    <p className="text-[13.5px] leading-relaxed text-ink-body">{step.text}</p>
                  </li>
                );
              })}
            </ol>
          </div>
        </section>

        <section aria-labelledby="principles-title" className="mx-auto max-w-[1200px] px-4 py-16 sm:px-6">
          <h2 id="principles-title" className="font-serif text-[34px] font-medium tracking-tight text-ink">
            What it will not claim
          </h2>
          <dl className="mt-8 grid gap-8 sm:grid-cols-2 lg:grid-cols-4">
            {PRINCIPLES.map(([title, text]) => (
              <div key={title} className="space-y-2 border-t-2 border-ink pt-4">
                <dt className="text-[15px] font-semibold text-ink">{title}</dt>
                <dd className="text-[13.5px] leading-relaxed text-ink-body">{text}</dd>
              </div>
            ))}
          </dl>
          <div className="mt-14 flex flex-wrap items-center justify-between gap-4 rounded-2xl bg-ink px-6 py-8 text-white sm:px-10">
            <p className="max-w-xl font-serif text-2xl leading-snug">Try the full workflow on a labeled demo project. No account details or provider keys needed.</p>
            {/* ghost has no base color, so the white-on-navy treatment is not overridden by the variant's foreground. */}
            <Link href="/projects" className={cn(buttonVariants({ size: "lg", variant: "ghost" }), "bg-white text-ink hover:bg-white/90 hover:text-ink")}>
              Open the workspace <ArrowRight aria-hidden />
            </Link>
          </div>
        </section>
      </main>

      <footer className="border-t border-border">
        <p className="mx-auto max-w-[1200px] px-4 py-6 text-xs text-ink-secondary sm:px-6">
          Nativeproof · decision support, not a prediction of market outcomes.
        </p>
      </footer>
    </div>
  );
}
