"use client";

import { CircleAlert, LoaderCircle, RotateCw } from "lucide-react";
import Link from "next/link";
import type { ReactNode } from "react";

import { Button } from "@/components/ui/button";
import { ApiError, type ErrorCode } from "@/lib/api/errors";
import { env } from "@/lib/env";

export function EmptyState({ title, description, action }: { title: string; description: string; action?: ReactNode }) {
  return (
    <div className="flex flex-col items-start gap-3 rounded-md border border-dashed border-border bg-surface/60 px-5 py-6">
      <div className="max-w-prose space-y-1">
        {/* Not a heading: empty states appear under h1, h2, or h3 and must not break the outline. */}
        <p className="text-[15px] font-semibold text-ink">{title}</p>
        <p className="text-sm text-ink-secondary">{description}</p>
      </div>
      {action}
    </div>
  );
}

export function LoadingState({ label }: { label: string }) {
  return (
    <div role="status" aria-live="polite" className="flex items-center gap-2 px-1 py-6 text-sm text-ink-secondary">
      <LoaderCircle aria-hidden className="size-4 animate-spin" />
      {label}
    </div>
  );
}

type Explanation = { title: string; saved: string; retry: string; next: ReactNode };

const NOTHING_SAVED = "Nothing was saved or started; the API rejected the request before acting on it.";

function explain(code: ErrorCode | "NETWORK_ERROR"): Explanation {
  switch (code) {
    case "NETWORK_ERROR":
      return {
        title: "Could not reach the Nativeproof API",
        saved: "The request may not have reached the server. If you were saving a change, reload to check before trying again.",
        retry: "Retrying is safe for viewing data.",
        next: `Check that the backend is running at ${env.apiBaseUrl}.`,
      };
    case "VALIDATION_ERROR":
      return {
        title: "The request was rejected as invalid",
        saved: "Nothing was saved.",
        retry: "Retrying unchanged will fail again.",
        next: "Correct the fields listed below and submit again.",
      };
    case "UNAUTHENTICATED":
      return {
        title: "Your session is missing or has expired",
        saved: NOTHING_SAVED,
        retry: "Retrying will fail until you sign in again.",
        next: env.authMode === "supabase" ? <Link className="underline underline-offset-2" href="/login">Sign in again</Link> : "Restart the frontend in development auth mode, or check the backend's AUTH_MODE.",
      };
    case "FORBIDDEN":
      return { title: "This action is not permitted", saved: NOTHING_SAVED, retry: "Retrying will not help.", next: "Check that you are working in the right project." };
    case "NOT_FOUND":
      return {
        title: "Not found",
        saved: NOTHING_SAVED,
        retry: "Retrying will not help.",
        next: <>It may have been archived, or it belongs to another account. <Link className="underline underline-offset-2" href="/projects">Return to projects</Link>.</>,
      };
    case "CONFLICT":
      return {
        title: "This conflicts with the current state",
        saved: "Nothing was changed.",
        retry: "Retrying unchanged will fail again.",
        next: "Demo campaigns and archived projects are read-only. Create a live project to change content.",
      };
    case "RATE_LIMITED":
      return { title: "Too many active runs", saved: "No new run was started.", retry: "Retry once a running operation finishes.", next: "Each account can run 2 operations at a time." };
    case "PROVIDER_NOT_CONFIGURED":
      return {
        title: "A live provider is not configured",
        saved: "No run was started and nothing was saved.",
        retry: "Retrying will fail until the provider credentials are configured on the backend.",
        next: <>Live projects call Qloo and the model provider. <Link className="underline underline-offset-2" href="/projects">Try a demo project</Link> to explore the workflow on labeled fixtures.</>,
      };
    case "UNSUPPORTED_CAPABILITY":
      return { title: "The verified Qloo workflows cannot answer this request", saved: NOTHING_SAVED, retry: "Retrying unchanged will fail again.", next: "Rephrase the request or use different reference terms." };
    case "PROVIDER_ERROR":
    case "PROVIDER_TIMEOUT":
      return { title: "An external provider failed", saved: "The message above states what was saved.", retry: "Retrying is usually safe.", next: "Try again in a moment." };
    case "RUN_FAILED":
    case "RUN_INTERRUPTED":
      return { title: "The workflow did not finish", saved: "The message above states what was saved.", retry: "Retrying is usually safe.", next: "Start the operation again." };
    default:
      return {
        title: "Something went wrong",
        saved: "Unknown. Reload to check before repeating a change.",
        retry: "Retrying may be safe for viewing data.",
        next: "If it keeps happening, share the request id with the team.",
      };
  }
}

/** Explains a failed request: what failed, whether anything was saved, whether retry is safe, and what to do next. */
export function ErrorState({ error, onRetry }: { error: unknown; onRetry?: () => void }) {
  const apiError = error instanceof ApiError ? error : null;
  const info = explain(apiError?.code ?? "INTERNAL_ERROR");
  const message = apiError?.message ?? (error instanceof Error ? error.message : null);
  return (
    <div role="alert" className="rounded-md border border-danger/25 bg-danger-soft/60 px-4 py-3.5">
      <div className="flex items-start gap-2.5">
        <CircleAlert aria-hidden className="mt-0.5 size-4 shrink-0 text-danger" />
        <div className="min-w-0 space-y-2 text-sm">
          <div>
            <p className="font-semibold text-ink">{info.title}</p>
            {message && <p className="text-ink">{message}</p>}
          </div>
          {apiError && apiError.details.length > 0 && (
            <ul className="list-disc space-y-0.5 pl-5 text-[13px] text-ink">
              {apiError.details.map((d, i) => (
                <li key={i}>
                  {d.field && <span className="font-mono text-xs">{d.field}: </span>}
                  {d.message}
                </li>
              ))}
            </ul>
          )}
          <dl className="grid gap-x-3 gap-y-0.5 text-[13px] text-ink-secondary sm:grid-cols-[auto_1fr]">
            <dt className="font-medium text-ink">Saved</dt>
            <dd>{info.saved}</dd>
            <dt className="font-medium text-ink">Retry</dt>
            <dd>{info.retry}</dd>
            <dt className="font-medium text-ink">Next</dt>
            <dd>{info.next}</dd>
          </dl>
          <div className="flex flex-wrap items-center gap-3">
            {onRetry && (
              <Button size="sm" variant="outline" onClick={onRetry}>
                <RotateCw aria-hidden />
                Try again
              </Button>
            )}
            {apiError?.requestId && (
              <span className="font-mono text-[11px] text-ink-secondary">request {apiError.requestId}</span>
            )}
          </div>
        </div>
      </div>
    </div>
  );
}
