import type { CampaignContent } from "@/lib/api/types";
import { cn } from "@/lib/utils";

type Field = "headline" | "body" | "call_to_action";

const FIELD_LABEL: Record<Field, string> = { headline: "Headline", body: "Body", call_to_action: "Call to action" };

function Changed() {
  return <span className="rounded-sm bg-primary/10 px-1 text-[11px] font-semibold tracking-wide text-primary uppercase">Changed</span>;
}

/** Read-only rendering of campaign content. Highlighted fields get a "Changed" marker, not just a tint. */
export function CampaignContentView({ content, highlightFields = [] }: { content: CampaignContent; highlightFields?: Field[] }) {
  const field = (name: Field) => {
    const value = content[name];
    const changed = highlightFields.includes(name);
    return (
      <div className={cn("space-y-1 rounded-sm", changed && "-mx-2 bg-accent px-2 py-1.5")}>
        <div className="flex items-center gap-2 text-[11px] font-medium tracking-wide text-ink-secondary uppercase">
          {FIELD_LABEL[name]}
          {changed && <Changed />}
        </div>
        {value ? (
          name === "headline" ? (
            <p className="font-serif text-[22px] leading-tight text-ink">{value}</p>
          ) : name === "body" ? (
            <p className="text-sm leading-relaxed whitespace-pre-wrap text-ink">{value}</p>
          ) : (
            <p className="text-sm font-medium text-ink">{value}</p>
          )
        ) : (
          <p className="text-sm text-ink-secondary italic">Not provided</p>
        )}
      </div>
    );
  };

  return (
    <div className="space-y-3">
      {field("headline")}
      {field("body")}
      {field("call_to_action")}
      {content.reference_terms.length > 0 && (
        <div className="space-y-1">
          <div className="text-[11px] font-medium tracking-wide text-ink-secondary uppercase">Reference terms</div>
          <ul className="flex flex-wrap gap-1.5">
            {content.reference_terms.map((term) => (
              <li key={term} className="rounded-sm border border-border bg-surface px-1.5 py-0.5 text-xs text-ink">
                {term}
              </li>
            ))}
          </ul>
        </div>
      )}
    </div>
  );
}
