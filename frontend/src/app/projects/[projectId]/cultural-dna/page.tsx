import type { Metadata } from "next";

import { DnaWorkspace } from "@/features/dna/dna-workspace";

export const metadata: Metadata = { title: "Cultural DNA" };
// Rendered inside the project layout's params boundary, which validation cannot see past (see layout.tsx).
export const instant = false;

export default function CulturalDnaPage() {
  return <DnaWorkspace />;
}
