/** Display formatting. All timestamps from the API are ISO 8601 UTC; these render them in the viewer's locale. */

const dateTime = new Intl.DateTimeFormat("en", { dateStyle: "medium", timeStyle: "short" });
const dateOnly = new Intl.DateTimeFormat("en", { dateStyle: "medium" });
const relative = new Intl.RelativeTimeFormat("en", { numeric: "auto" });

export function formatDateTime(iso: string | null | undefined) {
  return iso ? dateTime.format(new Date(iso)) : "—";
}

export function formatDate(iso: string | null | undefined) {
  return iso ? dateOnly.format(new Date(iso)) : "—";
}

const UNITS: [Intl.RelativeTimeFormatUnit, number][] = [
  ["year", 31_536_000],
  ["month", 2_592_000],
  ["week", 604_800],
  ["day", 86_400],
  ["hour", 3_600],
  ["minute", 60],
];

/** "3 minutes ago", "yesterday". Falls back to "just now" under a minute. */
export function formatRelative(iso: string | null | undefined, now = Date.now()) {
  if (!iso) return "—";
  const seconds = Math.round((Date.parse(iso) - now) / 1000);
  for (const [unit, size] of UNITS) {
    if (Math.abs(seconds) >= size) return relative.format(Math.round(seconds / size), unit);
  }
  return "just now";
}

/** Elapsed duration as "42s", "3m 05s", or "1h 02m". */
export function formatElapsed(ms: number) {
  const total = Math.max(0, Math.floor(ms / 1000));
  const h = Math.floor(total / 3600);
  const m = Math.floor((total % 3600) / 60);
  const s = total % 60;
  if (h) return `${h}h ${String(m).padStart(2, "0")}m`;
  if (m) return `${m}m ${String(s).padStart(2, "0")}s`;
  return `${s}s`;
}

/** "retrieving_affinities" → "Retrieving affinities". */
export function humanize(value: string) {
  const text = value.replace(/_/g, " ").trim();
  return text.charAt(0).toUpperCase() + text.slice(1);
}

/** First 8 characters of a UUID, for compact monospace display. */
export function shortId(id: string) {
  return id.length > 12 ? id.slice(0, 8) : id;
}
