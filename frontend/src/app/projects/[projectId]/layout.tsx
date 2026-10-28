import { Suspense } from "react";

import { ProjectShell, ProjectShellFallback } from "@/components/app-shell/project-shell";

// The shell reads route params and ?campaign= on the client; both are runtime data under Cache Components.
// Pages below it render inside this boundary, so they opt out of instant-navigation validation with
// `export const instant = false` (otherwise Next reports them as dropped segments in development).
export default function ProjectLayout({ children }: LayoutProps<"/projects/[projectId]">) {
  return (
    <Suspense fallback={<ProjectShellFallback />}>
      <ProjectShell>{children}</ProjectShell>
    </Suspense>
  );
}
