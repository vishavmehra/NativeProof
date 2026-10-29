import type { Disagreement } from "@/lib/api/types";

import { DIMENSION_LABEL } from "./dimensions";
import { ResponseLinks, type ReactionIndex, type ShowReactions } from "./finding-list";

export function DisagreementPanel({
  disagreements,
  index,
  onShow,
}: {
  disagreements: Disagreement[];
  index: ReactionIndex;
  onShow: ShowReactions;
}) {
  return (
    <div className="grid gap-4">
      <p className="max-w-prose text-xs text-muted-foreground">
        Disagreement reflects alternative model-generated interpretations, not verified differences between real groups.
      </p>
      {disagreements.length === 0 ? (
        <p className="text-sm text-muted-foreground">No material disagreement was detected among the synthetic reactions.</p>
      ) : (
        <ul className="divide-y border-y">
          {disagreements.map((d) => (
            <li key={d.id} className="grid gap-3 py-4">
              <div className="flex flex-wrap items-baseline gap-x-3 gap-y-1">
                <h3 className="text-[15px] font-semibold">{d.topic}</h3>
                {d.dimension && <span className="text-xs text-muted-foreground">{DIMENSION_LABEL[d.dimension]}</span>}
                {d.spread !== null && (
                  <span className="text-xs text-muted-foreground tabular-nums">Spread {d.spread} (1–5 scale)</span>
                )}
              </div>
              <ul className="grid gap-2 md:grid-cols-[repeat(auto-fit,minmax(12rem,1fr))]">
                {d.interpretations.map((cluster) => (
                  <li key={cluster.label} className="grid content-start gap-1.5 rounded-md border bg-card px-3 py-2.5">
                    <p className="text-sm font-medium">{cluster.label}</p>
                    <p className="text-sm text-muted-foreground">{cluster.summary}</p>
                    <ResponseLinks ids={cluster.response_ids} index={index} onShow={onShow} label="Reactions" />
                  </li>
                ))}
              </ul>
              {d.possible_explanations.length > 0 && (
                <div className="grid gap-1">
                  <p className="text-xs font-medium text-muted-foreground">
                    Possible explanations (hypotheses, not established causes)
                  </p>
                  <ul className="list-disc space-y-0.5 pl-5 text-sm">
                    {d.possible_explanations.map((explanation) => (
                      <li key={explanation}>{explanation}</li>
                    ))}
                  </ul>
                </div>
              )}
              <p className="text-sm">
                <span className="text-muted-foreground">Validation question: </span>
                {d.validation_question}
              </p>
            </li>
          ))}
        </ul>
      )}
    </div>
  );
}
