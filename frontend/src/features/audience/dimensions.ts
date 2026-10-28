import type { Dimension } from "@/lib/api/types";

/** Canonical dimension order (contracts: StudyCreate default). */
export const DIMENSIONS: readonly Dimension[] = ["clarity", "brand_fidelity", "cultural_relevance", "cultural_risk"];

export const DIMENSION_LABEL: Record<Dimension, string> = {
  clarity: "Clarity",
  brand_fidelity: "Brand fidelity",
  cultural_relevance: "Cultural relevance",
  cultural_risk: "Cultural risk",
};
