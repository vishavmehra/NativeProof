import { CircleAlert, Eye, TriangleAlert } from "lucide-react";

import type { VisionStatus } from "./api";

/** Image analysis status. Images never go to a text-only model; when vision is unavailable or failed, the text analysis still ran. */
export function VisionBanner({ vision }: { vision: VisionStatus }) {
  if (vision.status === "not_requested") return null;
  if (vision.status === "analyzed") {
    return (
      <p className="flex items-center gap-2 text-xs text-ink-secondary">
        <Eye aria-hidden className="size-3.5" />
        Images analyzed by a verified vision model
        {vision.model_id && <code className="font-mono">{vision.model_id}</code>}. Visible elements are observations; cultural readings of
        them are interpretations.
      </p>
    );
  }
  const failed = vision.status === "failed";
  const Icon = failed ? CircleAlert : TriangleAlert;
  return (
    <div role="status" className="flex gap-2.5 rounded-md border border-warning/30 bg-warning-soft/70 px-4 py-3 text-sm text-ink">
      <Icon aria-hidden className="mt-0.5 size-4 shrink-0 text-warning" />
      <div className="grid gap-0.5">
        <p className="font-semibold">{failed ? "Image analysis failed" : "Image analysis unavailable"}</p>
        <p>{vision.message ?? (failed ? "The vision model call failed." : "No verified vision model is configured.")}</p>
        <p className="text-xs text-ink-secondary">The text analysis still ran. Images were not sent to a text-only model, so nothing below describes them.</p>
      </div>
    </div>
  );
}
