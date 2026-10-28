"use client";

import { useQuery } from "@tanstack/react-query";

import { api } from "@/lib/api/client";
import { unwrap } from "@/lib/api/errors";
import type { components } from "@/lib/api/schema";

type Readiness = components["schemas"]["Readiness"];
export type CapabilityName = keyof Readiness["capabilities"];
export type CapabilityStatus = Readiness["capabilities"][CapabilityName];

/** Backend readiness and optional AI capabilities (GET /ready). `configured` does not mean a provider was reachable. */
export function useCapabilities() {
  return useQuery({
    queryKey: ["ready"],
    queryFn: () => unwrap(api.GET("/ready")),
    staleTime: 60_000,
  });
}

/** True when the capability can be attempted. Callers must still handle 501/503 from the endpoint. */
export function isCapabilityUsable(status: CapabilityStatus | undefined) {
  return status === "configured" || status === "available";
}

// Speech-to-text is out of scope for the UI, so it has no label even though /ready still reports it.
export const CAPABILITY_LABEL: Partial<Record<CapabilityName, string>> = {
  embeddings: "Semantic search (embeddings)",
  reranking: "Reranking",
  vision: "Image analysis (vision)",
};
