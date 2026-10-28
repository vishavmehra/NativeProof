import type { Metadata } from "next";

import { EvidenceGraphView } from "@/features/graph/evidence-graph";

export const metadata: Metadata = { title: "Evidence Graph" };

// Rendered inside the project layout's params boundary (see ../layout.tsx).
export const instant = false;

export default function EvidenceGraphPage() {
  return <EvidenceGraphView />;
}
