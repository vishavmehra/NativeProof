import { Info } from "lucide-react";

/**
 * Limitations stated by the backend, as a neutral list (amber is reserved for Unverified, partial, and DEMO/fixture
 * states). Renders nothing when there are none. The title is not a heading, so it never breaks the page outline.
 */
export function LimitationList({ items, title = "Limitations" }: { items: string[]; title?: string }) {
  if (items.length === 0) return null;
  return (
    <section aria-label={title} className="rounded-lg border border-border bg-surface-muted px-3.5 py-2.5">
      <p className="flex items-center gap-1.5 text-xs font-semibold text-ink">
        <Info aria-hidden className="size-3.5 text-ink-secondary" />
        {title}
      </p>
      <ul className="mt-1.5 max-w-prose list-disc space-y-1 pl-5 text-[13px] leading-snug text-ink-body marker:text-ink-secondary">
        {items.map((item, i) => (
          <li key={i}>{item}</li>
        ))}
      </ul>
    </section>
  );
}
