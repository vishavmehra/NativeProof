import type { ReactNode } from "react";

import { cn } from "@/lib/utils";

/** Native select styled like the Input primitive. */
export const SELECT_CLASS =
  "h-9 w-full min-w-0 rounded-lg border border-input bg-surface px-2.5 text-sm text-ink shadow-card outline-none focus-visible:border-ring focus-visible:ring-3 focus-visible:ring-ring/25 disabled:cursor-not-allowed disabled:opacity-50";

/** Section frame shared by the Voice, Loop, Proof, Arena, and Risk Radar workspaces. */
export function Panel({
  id,
  title,
  actions,
  children,
  className,
  headingAs: Heading = "h2",
}: {
  id: string;
  title: ReactNode;
  actions?: ReactNode;
  children: ReactNode;
  className?: string;
  /** Use h3 when the panel sits inside another titled section. */
  headingAs?: "h2" | "h3";
}) {
  return (
    <section aria-labelledby={id} className={cn("rounded-card border border-border bg-surface shadow-card", className)}>
      <div className="flex flex-wrap items-center justify-between gap-2 border-b border-border px-4 py-3">
        <Heading id={id} className="text-[15px] font-semibold text-ink">
          {title}
        </Heading>
        {actions}
      </div>
      <div className="p-4 md:p-5">{children}</div>
    </section>
  );
}
