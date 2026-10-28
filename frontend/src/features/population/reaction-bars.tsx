import type { ReactionCategory, ReactionDistribution } from "@/lib/api/types";
import { cn } from "@/lib/utils";

export const REACTIONS: NonNullable<ReactionCategory>[] = ["positive", "mixed", "neutral", "negative", "confused"];
export const REACTION_LABEL: Record<NonNullable<ReactionCategory>, string> = {
  positive: "Positive",
  mixed: "Mixed",
  neutral: "Neutral",
  negative: "Negative",
  confused: "Confused",
};
// Text labels always accompany the colors; amber is reserved for unverified/partial/demo states.
const FILL: Record<NonNullable<ReactionCategory>, string> = {
  positive: "bg-success",
  mixed: "bg-info",
  neutral: "bg-ink-secondary/45",
  negative: "bg-danger",
  confused: "bg-audience",
};

const pct = (rate: number | undefined) => `${Math.round((rate ?? 0) * 100)}%`;

/** One stacked bar of reaction shares over completed interviews, with every count printed. */
export function ReactionBar({ d, compact = false }: { d: ReactionDistribution; compact?: boolean }) {
  if (d.denominator === 0)
    return <p className="text-xs text-ink-secondary">No completed interviews{d.failed > 0 && ` (${d.failed} failed)`}.</p>;
  const text = REACTIONS.map((r) => `${REACTION_LABEL[r]} ${d.counts[r] ?? 0} (${pct(d.rates[r])})`).join(", ");
  return (
    <div className="grid gap-1.5">
      <div role="img" aria-label={`${text}; of ${d.denominator} completed interviews, ${d.failed} failed`} className={cn("flex overflow-hidden rounded-sm bg-surface-muted", compact ? "h-2" : "h-3")}>
        {REACTIONS.map((r) => (
          <div key={r} className={FILL[r]} style={{ width: pct(d.rates[r]) }} />
        ))}
      </div>
      <ul aria-hidden className={cn("flex flex-wrap gap-x-3 gap-y-0.5 tabular-nums", compact ? "text-[11px]" : "text-xs")}>
        {REACTIONS.filter((r) => (d.counts[r] ?? 0) > 0 || !compact).map((r) => (
          <li key={r} className="flex items-center gap-1">
            <span className={cn("size-2 rounded-[2px]", FILL[r])} />
            {REACTION_LABEL[r]} {d.counts[r] ?? 0} <span className="text-ink-secondary">({pct(d.rates[r])})</span>
          </li>
        ))}
      </ul>
      <p className={cn("text-ink-secondary tabular-nums", compact ? "text-[11px]" : "text-xs")}>
        Of {d.denominator} completed interviews
        {d.failed > 0 ? `; ${d.failed} failed and are not counted` : ""}.
      </p>
    </div>
  );
}
