import type { Metadata } from "next";

import { ProjectOverview } from "@/features/project/overview";

export const metadata: Metadata = { title: "Overview" };

// Rendered inside the project layout's params boundary, which validation cannot see past (see layout.tsx).
export const instant = false;

export default function ProjectOverviewPage() {
  return <ProjectOverview />;
}
