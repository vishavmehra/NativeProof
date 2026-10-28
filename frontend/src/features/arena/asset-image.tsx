"use client";

import { useAssetObjectUrl } from "@/features/assets/asset-uploader";
import { cn } from "@/lib/utils";

/** An uploaded image, fetched with the API token (content URLs cannot be a plain <img src>). */
export function AssetImage({ assetId, alt, className }: { assetId: string; alt: string; className?: string }) {
  const url = useAssetObjectUrl({ id: assetId, content_url: `/api/v1/assets/${assetId}/content` });
  if (!url) return <div className={cn("rounded-lg border border-dashed border-border bg-surface-muted", className)} role="img" aria-label={`${alt} (loading or unavailable)`} />;
  // eslint-disable-next-line @next/next/no-img-element -- authenticated object URL, not optimizable
  return <img src={url} alt={alt} className={cn("rounded-lg border border-border object-cover", className)} />;
}
