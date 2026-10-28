import { cn } from "@/lib/utils";

/**
 * A 0–100 score as an aligned bar plus its numeric value. The direction is stated in text,
 * never by color alone. `null` renders "Not assessed" rather than a zero.
 */
export function ScoreBar({
  label,
  value,
  higherIsBetter,
  definition,
  note,
}: {
  label: string;
  value: number | null;
  higherIsBetter: boolean;
  definition?: string;
  note?: string;
}) {
  const clamped = value === null ? null : Math.min(100, Math.max(0, value));
  return (
    <div className="space-y-1">
      <div className="flex items-baseline justify-between gap-3">
        <span className="text-[13px] font-medium text-ink">{label}</span>
        <span className="text-[13px] text-ink tabular-nums">
          {value === null ? (
            <span className="text-ink-secondary">Not assessed</span>
          ) : (
            <>
              <span className="font-semibold">{Number.isInteger(value) ? value : value.toFixed(1)}</span>
              <span className="text-ink-secondary"> / 100</span>
            </>
          )}
        </span>
      </div>
      <div
        className="h-1.5 overflow-hidden rounded-full bg-surface-muted"
        {...(clamped === null
          ? { "aria-hidden": true }
          : { role: "meter", "aria-label": label, "aria-valuemin": 0, "aria-valuemax": 100, "aria-valuenow": clamped })}
      >
        {clamped !== null && (
          <div className={cn("h-full rounded-full", higherIsBetter ? "bg-primary" : "bg-warning")} style={{ width: `${clamped}%` }} />
        )}
      </div>
      <p className="text-xs text-ink-secondary">
        {higherIsBetter ? "Higher is better." : "Lower is better: a higher score means more perceived risk."}
        {definition && <> {definition}</>}
      </p>
      {note && <p className="text-xs text-ink-secondary italic">{note}</p>}
    </div>
  );
}
