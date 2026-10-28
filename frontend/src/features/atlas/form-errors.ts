import { ApiError } from "@/lib/api/errors";

// shared by the Atlas and Audience forms.

/** Server 422 details keyed by dotted field path. */
export function serverFieldErrors(error: unknown): Record<string, string> {
  if (!(error instanceof ApiError) || error.code !== "VALIDATION_ERROR") return {};
  const out: Record<string, string> = {};
  for (const { field, message } of error.details) out[field?.replace(/^body\./, "") ?? ""] ??= message;
  return out;
}

/** First message for a field or any nested path below it ("reference_terms" matches "reference_terms.2"). */
export function pickError(errors: Record<string, string>, field: string) {
  const key = Object.keys(errors).find((k) => k === field || k.startsWith(`${field}.`));
  return key === undefined ? undefined : errors[key];
}

