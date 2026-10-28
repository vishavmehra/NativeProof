import type { Metadata } from "next";

import { AudienceIntelligence } from "@/features/population/audience-intelligence";

export const metadata: Metadata = { title: "Audience Intelligence" };
// Rendered inside the project layout's params boundary, which validation cannot see past (see layout.tsx).
export const instant = false;

export default function AudiencePage() {
  return <AudienceIntelligence />;
}
