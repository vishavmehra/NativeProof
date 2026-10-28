import type { Metadata } from "next";

import { TrendsWorkspace } from "@/features/trends/trends-workspace";

export const metadata: Metadata = { title: "Trend Watch" };
// Rendered inside the project layout's params boundary, which validation cannot see past (see layout.tsx).
export const instant = false;

export default function TrendWatchPage() {
  return <TrendsWorkspace />;
}
