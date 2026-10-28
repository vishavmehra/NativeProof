"use client";

import { ArrowRight, SlidersHorizontal, type LucideIcon } from "lucide-react";
import Link from "next/link";
import type { ReactNode } from "react";

import { cn } from "@/lib/utils";

/** White reference card: 1px warm border, soft shadow, 14px radius. Serif title when given. */
export function Card({
  title,
  subtitle,
  action,
  className,
  children,
}: {
  title?: ReactNode;
  subtitle?: ReactNode;
  action?: ReactNode;
  className?: string;
  children?: ReactNode;
}) {
  return (
    <section className={cn("rounded-card border border-border bg-surface p-5 shadow-card sm:p-6", className)}>
      {(title || action) && (
        <div className="mb-4 flex items-start justify-between gap-3">
          <div className="min-w-0">
            {title && <h2 className="font-serif text-[21px] leading-tight font-semibold text-ink">{title}</h2>}
            {subtitle && <p className="mt-1 text-[14px] text-ink-secondary">{subtitle}</p>}
          </div>
          {action}
        </div>
      )}
      {children}
    </section>
  );
}

/**
 * Filter card (docs/16 §1): labeled dropdowns in one row plus an optional "More filters". Children are FilterField items;
 * every filter must change the query (no decorative filters).
 */
export function FilterCard({ children, onMoreFilters, className }: { children: ReactNode; onMoreFilters?: () => void; className?: string }) {
  return (
    <div className={cn("flex flex-wrap items-end gap-4 rounded-card border border-border bg-surface p-4 shadow-card", className)}>
      {children}
      {onMoreFilters && (
        <button type="button" onClick={onMoreFilters} className="ml-auto inline-flex h-10 items-center gap-2 rounded-lg border border-border px-3 text-[14px] text-ink hover:bg-surface-muted">
          <SlidersHorizontal aria-hidden className="size-4" />
          More filters
        </button>
      )}
    </div>
  );
}

/** A labeled control inside a FilterCard. Pass a native <select> or any control with the given id. */
export function FilterField({ label, htmlFor, children, className }: { label: string; htmlFor: string; children: ReactNode; className?: string }) {
  return (
    <div className={cn("min-w-40 flex-1 space-y-1.5", className)}>
      <label htmlFor={htmlFor} className="block text-[12px] font-medium text-ink-secondary">
        {label}
      </label>
      {children}
    </div>
  );
}

/** Class string for a FilterField <select>, matching the reference dropdowns. */
export const filterSelectClass =
  "h-10 w-full appearance-none rounded-lg border border-border bg-surface px-3 pr-8 text-[14px] text-ink bg-[url('data:image/svg+xml;utf8,<svg xmlns=%22http://www.w3.org/2000/svg%22 viewBox=%220 0 24 24%22 fill=%22none%22 stroke=%22%235f5b54%22 stroke-width=%222%22><path d=%22m6 9 6 6 6-6%22/></svg>')] bg-[length:16px] bg-[right_10px_center] bg-no-repeat";

export type NextStepAction = { label: string; href: string; Icon?: LucideIcon; primary?: boolean };

/** Lavender "What would you like to do next?" bar with 2–3 real actions (docs/16 §1). */
export function NextStepBar({ title = "What would you like to do next?", actions, className }: { title?: string; actions: NextStepAction[]; className?: string }) {
  if (actions.length === 0) return null;
  return (
    <section aria-label={title} className={cn("flex flex-wrap items-center justify-between gap-3 rounded-card bg-lavender px-5 py-4", className)}>
      <p className="font-serif text-lg font-semibold text-ink">{title}</p>
      <div className="flex flex-wrap gap-2">
        {actions.map((a) => (
          <Link
            key={a.href + a.label}
            href={a.href}
            className={cn(
              "inline-flex h-10 items-center gap-2 rounded-lg px-4 text-[14px] font-medium",
              a.primary ? "bg-primary text-primary-foreground hover:bg-accent-hover" : "border border-border bg-surface text-ink hover:bg-surface-muted",
            )}
          >
            {a.Icon && <a.Icon aria-hidden className="size-4" />}
            {a.label}
            <ArrowRight aria-hidden className="size-4" />
          </Link>
        ))}
      </div>
    </section>
  );
}
