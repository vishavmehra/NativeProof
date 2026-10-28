import type { Metadata } from "next";
import { Suspense } from "react";

import { LoadingState } from "@/components/states";
import { HomeDashboard } from "@/features/home/home-dashboard";

export const metadata: Metadata = { title: "Home" };

// The shell reads ?campaign= (useSearchParams), which is runtime data under Cache Components.
export default function ProjectsPage() {
  return (
    <Suspense fallback={<div className="min-h-dvh bg-canvas p-10"><LoadingState label="Loading…" /></div>}>
      <HomeDashboard />
    </Suspense>
  );
}
