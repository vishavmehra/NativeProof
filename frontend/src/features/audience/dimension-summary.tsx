import { SplitIcon } from "lucide-react";

import { ScoreBar } from "@/components/data/score-bar";
import type { DimensionResult, RehearsalResult } from "@/lib/api/types";

import { DIMENSIONS, DIMENSION_LABEL } from "./dimensions";

/** Counts of ratings 1–5 as five labeled bars. The counts are printed, so the chart has a text equivalent. */
function Distribution({ result }: { result: DimensionResult }) {
  const max = Math.max(1, ...result.distribution);
  const text = result.distribution.map((count, i) => `rating ${i + 1}: ${count}`).join(", ");
  return (
    <figure className="grid gap-1">
      <div role="img" aria-label={`Rating distribution, ${text} (n = ${result.n})`} className="grid grid-cols-5 items-end gap-1.5">
        {result.distribution.map((count, i) => (
          <div key={i} className="flex flex-col items-center gap-0.5">
            <span className="text-[11px] font-medium tabular-nums">{count}</span>
            <div className="h-8 w-full rounded-sm bg-surface-muted">
              <div
                className="mt-auto h-full origin-bottom rounded-sm bg-ink-secondary/55"
                style={{ transform: `scaleY(${count / max})` }}
              />
            </div>
            <span className="text-[11px] text-muted-foreground tabular-nums">{i + 1}</span>
          </div>
        ))}
      </div>
      <figcaption className="text-[11px] text-muted-foreground">
        Ratings 1–5 ({result.higher_is_better ? "5 = highest" : "5 = most perceived risk"}), n = {result.n}
      </figcaption>
    </figure>
  );
}

export function DimensionSummary({ results }: { results: RehearsalResult["dimension_results"] }) {
  const rows = DIMENSIONS.map((d) => results[d]).filter((r): r is DimensionResult => r !== null);
  if (rows.length === 0) return <p className="text-sm text-muted-foreground">No dimension scores were produced.</p>;
  return (
    <ul className="divide-y border-y">
      {rows.map((r) => (
        <li key={r.dimension} className="grid gap-4 py-4 md:grid-cols-[minmax(0,3fr)_minmax(0,2fr)] md:gap-8">
          <div className="grid content-start gap-2">
            <ScoreBar label={DIMENSION_LABEL[r.dimension]} value={r.score} higherIsBetter={r.higher_is_better} definition={r.definition} />
            <p className="text-sm">{r.interpretation}</p>
            <p className="text-xs text-muted-foreground">
              <span className="font-medium text-foreground">Method:</span> Deterministic aggregation of synthetic ratings
              (score = (mean − 1) / 4 × 100).{" "}
              <span className="tabular-nums">
                Spread {r.spread ?? "n/a"} (standard deviation on the 1–5 scale).
              </span>
            </p>
            {r.disagreement && (
              <p className="flex items-center gap-1.5 text-xs font-medium text-warning">
                <SplitIcon aria-hidden className="size-3.5" />
                Ratings diverge. See the disagreement analysis.
              </p>
            )}
            {r.limitations.length > 0 && (
              <p className="text-xs text-muted-foreground">
                <span className="font-medium">Limitations:</span> {r.limitations.join(" ")}
              </p>
            )}
          </div>
          <Distribution result={r} />
        </li>
      ))}
    </ul>
  );
}
