"use client";

import { Plus, X } from "lucide-react";
import { cloneElement, isValidElement, useId, useState, type ReactElement, type ReactNode } from "react";

import { MarketSelect } from "@/components/forms/market-select";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import type { Market } from "@/lib/api/types";
import { cn } from "@/lib/utils";

/**
 * Label, control, helper text, and error with the associations screen readers need. With `error`, a single
 * element child gets `aria-invalid` and `aria-describedby` pointing at the message (`${htmlFor}-error`).
 */
export function Field({
  label,
  htmlFor,
  hint,
  error,
  required,
  className,
  children,
}: {
  label: string;
  htmlFor: string;
  hint?: ReactNode;
  error?: string | null;
  required?: boolean;
  className?: string;
  children: ReactNode;
}) {
  const errorId = `${htmlFor}-error`;
  const control =
    error && isValidElement<{ "aria-describedby"?: string }>(children)
      ? cloneElement(children as ReactElement<Record<string, unknown>>, {
          "aria-invalid": true,
          "aria-describedby": [children.props["aria-describedby"], errorId].filter(Boolean).join(" "),
        })
      : children;
  return (
    <div className={cn("space-y-1.5", className)}>
      <label htmlFor={htmlFor} className="block text-[13px] font-medium text-ink">
        {label}
        {required ? <span className="text-danger"> *</span> : <span className="font-normal text-ink-secondary"> (optional)</span>}
      </label>
      {control}
      {hint && (
        <p id={`${htmlFor}-hint`} className="max-w-prose text-xs text-ink-secondary">
          {hint}
        </p>
      )}
      {error && (
        <p id={errorId} role="alert" className="max-w-prose text-xs font-medium text-danger">
          {error}
        </p>
      )}
    </div>
  );
}

function Chip({ children, onRemove, removeLabel, readOnly }: { children: ReactNode; onRemove(): void; removeLabel: string; readOnly?: boolean }) {
  if (readOnly) return <li className="inline-flex items-center rounded-sm border border-border bg-surface-muted px-2 py-0.5 text-xs text-ink">{children}</li>;
  return (
    <li className="inline-flex items-center gap-1 rounded-sm border border-border bg-surface py-0.5 pr-0.5 pl-2 text-xs text-ink">
      {children}
      <button
        type="button"
        onClick={onRemove}
        aria-label={removeLabel}
        className="rounded-sm p-0.5 text-ink-secondary outline-none hover:bg-surface-muted hover:text-ink"
      >
        <X aria-hidden className="size-3" />
      </button>
    </li>
  );
}

/** A list of short terms. Enter or comma adds the typed term; duplicates (case-insensitive) are ignored. */
export function TermListInput({
  id,
  value,
  onChange,
  placeholder,
  max,
  disabled,
}: {
  id: string;
  value: string[];
  onChange(next: string[]): void;
  placeholder?: string;
  max?: number;
  disabled?: boolean;
}) {
  const [draft, setDraft] = useState("");
  const full = max !== undefined && value.length >= max;

  function add() {
    const term = draft.trim().replace(/,$/, "").trim();
    if (!term || full) return;
    if (!value.some((v) => v.toLowerCase() === term.toLowerCase())) onChange([...value, term]);
    setDraft("");
  }

  return (
    <div className="space-y-2">
      <div className="flex gap-2">
        <Input
          id={id}
          value={draft}
          disabled={disabled || full}
          placeholder={full ? `Limit of ${max} reached` : placeholder}
          aria-describedby={`${id}-hint`}
          onChange={(e) => setDraft(e.target.value)}
          onKeyDown={(e) => {
            if (e.key === "Enter" || e.key === ",") {
              e.preventDefault();
              add();
            }
          }}
          className="bg-surface"
        />
        <Button type="button" variant="outline" onClick={add} disabled={disabled || full || !draft.trim()} aria-label="Add term">
          <Plus aria-hidden />
          Add
        </Button>
      </div>
      {value.length > 0 && (
        <ul className="flex flex-wrap gap-1.5" aria-label="Added terms">
          {value.map((term) => (
            <Chip key={term} readOnly={disabled} onRemove={() => onChange(value.filter((v) => v !== term))} removeLabel={`Remove ${term}`}>
              {term}
            </Chip>
          ))}
        </ul>
      )}
    </div>
  );
}

/** Several markets: pick one at a time from the searchable list; each can be removed. */
export function MarketListField({ id, value, onChange }: { id?: string; value: Market[]; onChange(next: Market[]): void }) {
  const fallbackId = useId();
  return (
    <div className="space-y-2">
      <MarketSelect
        id={id ?? fallbackId}
        value={null}
        onChange={(m) => {
          if (!value.some((v) => v.country_code === m.country_code)) onChange([...value, m]);
        }}
      />
      {value.length > 0 && (
        <ul className="flex flex-wrap gap-1.5" aria-label="Selected markets">
          {value.map((m) => (
            <Chip key={m.country_code} onRemove={() => onChange(value.filter((v) => v.country_code !== m.country_code))} removeLabel={`Remove ${m.display_name}`}>
              {m.display_name} <span className="font-mono text-[11px] text-ink-secondary">{m.country_code}</span>
            </Chip>
          ))}
        </ul>
      )}
    </div>
  );
}

/** "Japan, Germany" or a fallback. */
export function marketNames(markets: Market[], empty = "No target market set") {
  return markets.length ? markets.map((m) => m.display_name).join(", ") : empty;
}
