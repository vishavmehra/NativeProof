import { CircleAlert, Info, Sigma, TriangleAlert } from "lucide-react";

import { Tag } from "@/components/evidence/badges";
import type { RiskFlag } from "@/lib/api/types";
import { humanize } from "@/lib/format";

export const SEVERITY = {
  high: { label: "High severity", Icon: CircleAlert, className: "border-danger/30 bg-danger-soft text-danger" },
  medium: { label: "Medium severity", Icon: TriangleAlert, className: "border-warning/30 bg-warning-soft text-warning" },
  low: { label: "Low severity", Icon: Info, className: "border-border bg-surface-muted text-ink-secondary" },
} as const;

/** Marks a result computed in code by a documented rule, as opposed to a model claim. */
export function DeterministicTag() {
  return (
    <Tag className="border-border bg-surface-muted text-ink" title="Computed in code by a documented rule, not a model claim.">
      <Sigma aria-hidden />
      Deterministic check
    </Tag>
  );
}

export function SeverityTag({ severity, className }: { severity: RiskFlag["severity"]; className?: string }) {
  const s = SEVERITY[severity];
  return (
    <Tag className={`${s.className} ${className ?? ""}`}>
      <s.Icon aria-hidden />
      {s.label}
    </Tag>
  );
}

/** Risk flags with severity in text and icon (never color alone) and the source that raised them. */
export function RiskFlagList({ flags, empty = "No risk flags raised." }: { flags: RiskFlag[]; empty?: string }) {
  if (flags.length === 0) return <p className="text-xs text-ink-secondary">{empty}</p>;
  return (
    <ul className="space-y-2.5">
      {flags.map((flag, i) => (
        <li key={i} className="grid gap-1">
          <SeverityTag severity={flag.severity} className="w-fit" />
          <p className="text-[13px] leading-snug text-ink">{flag.description}</p>
          <p className="text-xs text-ink-secondary">
            {humanize(flag.category)} · {flag.source === "deterministic_check" ? "Deterministic check" : "Model assessment"}
          </p>
        </li>
      ))}
    </ul>
  );
}
