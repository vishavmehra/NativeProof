"use client";

import { Play } from "lucide-react";
import type { ReactNode } from "react";

import { Popover, PopoverContent, PopoverTrigger } from "@/components/ui/popover";
import { FEATURES, type FeatureKey } from "@/features/project/features";
import { cn } from "@/lib/utils";

/**
 * Reference page header (docs/16 §1): tinted rounded-square feature icon, large serif title, navy subtitle, gray
 * description, and right-aligned "How it works" + primary CTA.
 *
 * Usage:
 *   <FeatureHeader feature="arena" description="…" howItWorks={<p>…</p>}
 *     primaryAction={<Button>Run comparison <ArrowRight /></Button>} />
 *
 * "How it works" renders only when `howItWorks` content is given (no dead controls). Spacing is the caller's via
 * `className` (default "mb-8").
 */
export function FeatureHeader({
  feature,
  title,
  subtitle,
  description,
  howItWorks,
  primaryAction,
  actions,
  className = "mb-8",
  children,
}: {
  feature: FeatureKey;
  title?: string;
  /** One-line navy subtitle; defaults to the feature's description. */
  subtitle?: ReactNode;
  /** Optional gray second line. */
  description?: ReactNode;
  /** Content of the "How it works" popover. */
  howItWorks?: ReactNode;
  primaryAction?: ReactNode;
  /** Extra secondary actions, rendered before "How it works". */
  actions?: ReactNode;
  className?: string;
  children?: ReactNode;
}) {
  const f = FEATURES[feature];
  return (
    <header className={cn("flex flex-col gap-4 lg:flex-row lg:items-start lg:justify-between lg:gap-6", className)}>
      <div className="flex min-w-0 flex-1 items-start gap-4 sm:gap-5">
        <span className={cn("mt-1 flex size-12 shrink-0 items-center justify-center rounded-2xl sm:size-14", f.tone.soft)}>
          <f.Icon aria-hidden className={cn("size-6 sm:size-7", f.tone.text)} />
        </span>
        <div className="min-w-0 space-y-1.5">
          <h1 className="font-serif text-[40px] leading-[1.02] font-semibold tracking-tight text-ink sm:text-[56px]">{title ?? f.label}</h1>
          <p className="text-[17px] text-ink sm:text-lg">{subtitle ?? f.description}</p>
          {description && <p className="max-w-3xl text-[15px] text-ink-secondary">{description}</p>}
          {children}
        </div>
      </div>
      {(actions || howItWorks || primaryAction) && (
        <div className="flex flex-wrap items-center gap-3 lg:shrink-0 lg:pt-3">
          {actions}
          {howItWorks && (
            <Popover>
              <PopoverTrigger className="inline-flex h-11 items-center gap-2.5 rounded-xl border border-border bg-surface px-4 text-[15px] font-medium text-ink shadow-card hover:bg-surface-muted">
                <span className="flex size-5 items-center justify-center rounded-full bg-primary">
                  <Play aria-hidden className="size-2.5 fill-white text-white" />
                </span>
                How it works
              </PopoverTrigger>
              <PopoverContent align="end" className="w-96 text-[13px] leading-relaxed text-ink-body">
                {howItWorks}
              </PopoverContent>
            </Popover>
          )}
          {primaryAction}
        </div>
      )}
    </header>
  );
}
