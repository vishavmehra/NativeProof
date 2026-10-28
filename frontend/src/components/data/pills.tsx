import { Check, type LucideIcon } from "lucide-react";
import type { ReactNode } from "react";

import { cn } from "@/lib/utils";

export type PillTone = "green" | "orange" | "red" | "blue" | "indigo" | "gray";

const TONE: Record<PillTone, string> = {
  green: "bg-success-soft text-success",
  orange: "bg-warning-soft text-warning",
  red: "bg-danger-soft text-danger",
  blue: "bg-info-soft text-info",
  indigo: "bg-lavender text-lavender-ink",
  gray: "bg-surface-muted text-ink-secondary",
};

/**
 * Status pill (reference: green "High relevance" with check, orange "Medium", red/orange/blue risk levels).
 * The level must come from real data (e.g. a confidence label or risk severity) — never decorative.
 */
export function Pill({ tone, icon: Icon, children, className }: { tone: PillTone; icon?: LucideIcon | "check"; children: ReactNode; className?: string }) {
  return (
    <span className={cn("inline-flex h-6 items-center gap-1 rounded-full px-2.5 text-[12px] font-medium whitespace-nowrap", TONE[tone], className)}>
      {Icon === "check" ? <Check aria-hidden className="size-3.5" /> : Icon ? <Icon aria-hidden className="size-3.5" /> : null}
      {children}
    </span>
  );
}

/** Outline tag chip (reference key values / interests). */
export function TagChip({ children, className }: { children: ReactNode; className?: string }) {
  return <span className={cn("inline-flex h-7 items-center rounded-full border border-border bg-surface px-3 text-[12.5px] text-ink-body", className)}>{children}</span>;
}

/** Thin colored progress bar for a real 0–100 value. */
export function ProgressBar({ value, tone = "indigo", label }: { value: number; tone?: PillTone; label: string }) {
  const fill = { green: "bg-success", orange: "bg-warning", red: "bg-danger", blue: "bg-info", indigo: "bg-primary", gray: "bg-ink-secondary" }[tone];
  const v = Math.max(0, Math.min(100, value));
  return (
    <div role="meter" aria-label={label} aria-valuemin={0} aria-valuemax={100} aria-valuenow={v} className="h-1.5 w-full overflow-hidden rounded-full bg-surface-muted">
      <div className={cn("h-full rounded-full", fill)} style={{ width: `${v}%` }} />
    </div>
  );
}

/** Country flag emoji from an ISO 3166-1 alpha-2 code ("JP" → 🇯🇵); empty for invalid codes. Decorative: add aria-hidden. */
export function flagEmoji(countryCode: string) {
  const code = countryCode.toUpperCase();
  if (!/^[A-Z]{2}$/.test(code)) return "";
  return String.fromCodePoint(...[...code].map((c) => 0x1f1e6 + c.charCodeAt(0) - 65));
}
