import type { RunType } from "@/lib/api/types";

/** Run type → display label and the section (route segment) that owns it. */
export const RUN_TYPE_META: Record<RunType, { label: string; segment: string }> = {
  market_discovery: { label: "Market discovery", segment: "atlas" },
  campaign_rehearsal: { label: "Campaign rehearsal", segment: "audience" },
  campaign_adaptation: { label: "Campaign adaptation", segment: "voice" },
  campaign_evaluation: { label: "Campaign evaluation", segment: "loop" },
  cultural_profile: { label: "Cultural profile", segment: "cultural-dna" },
  market_comparison: { label: "Market comparison", segment: "market-expansion" },
  campaign_arena: { label: "Campaign arena", segment: "arena" },
  risk_scan: { label: "Risk scan", segment: "risk-radar" },
  // Contract v3: both run under a study; they link to Audience until v3 adds dedicated pages.
  population_study: { label: "Population study", segment: "audience" },
  social_simulation: { label: "Social simulation", segment: "audience" },
};

/** Section href that keeps the active campaign in the URL. `segment` null is the Overview. */
export function sectionHref(projectId: string, segment: string | null, campaignId?: string | null) {
  const path = segment ? `/projects/${projectId}/${segment}` : `/projects/${projectId}`;
  return campaignId ? `${path}?campaign=${encodeURIComponent(campaignId)}` : path;
}
