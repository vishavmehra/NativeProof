import type { ReactionDistribution } from "@/lib/api/types";
import { cn } from "@/lib/utils";

export const REACTIONS = ["positive", "mixed", "neutral", "negative", "confused"] as const;

const TONE: Record<(typeof REACTIONS)[number], string> = {
  positive: "bg-success",
  mixed: "bg-info",
  neutral: "bg-ink-secondary/40",
  negative: "bg-danger",
  confused: "bg-warning",
};

const pct = (rate: number) => `${Math.round(rate * 100)}%`;

/**
 * A stored reaction tally as a stacked bar plus the exact counts in text (never color alone).
 * Rates are counts / completed interviews; failed interviews are reported, not hidden.
 */
export function DistributionBar({ distribution, compact = false }: { distribution: ReactionDistribution; compact?: boolean }) {
  const { counts, rates, denominator, failed } = distribution;
  const present = REACTIONS.filter((r) => (counts[r] ?? 0) > 0);
  return (
    <div className="grid gap-1">
      <div className="flex h-2 overflow-hidden rounded-full bg-surface-muted" aria-hidden>
        {present.map((r) => (
          <span key={r} className={TONE[r]} style={{ width: pct(rates[r] ?? 0) }} />
        ))}
      </div>
      <p className={cn("text-ink-secondary tabular-nums", compact ? "text-[11px]" : "text-xs")}>
        {denominator === 0
          ? "No completed responses"
          : present.map((r) => `${r} ${pct(rates[r] ?? 0)} (${counts[r]})`).join(" · ")}
        {denominator > 0 && <> · n={denominator}</>}
        {failed > 0 && <> · {failed} failed</>}
      </p>
    </div>
  );
}
