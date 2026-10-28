import type { Metadata } from "next";

import { MarketsWorkspace } from "@/features/markets/markets-workspace";

export const metadata: Metadata = { title: "Market Expansion" };
// Rendered inside the project layout's params boundary, which validation cannot see past (see layout.tsx).
export const instant = false;

export default function MarketExpansionPage() {
  return <MarketsWorkspace />;
}
