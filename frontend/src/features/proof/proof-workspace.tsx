"use client";

import Link from "next/link";

import { EmptyState } from "@/components/states";
import { buttonVariants } from "@/components/ui/button";
import { useProject } from "@/features/project/project-context";
import { FeatureHeader } from "@/components/app-shell/feature-header";

import { ReportForm } from "./report-form";
import { ReportList } from "./report-list";
import { RunHistory } from "./run-history";

/** `evaluationParam` preselects an evaluation in the report form (Loop's "Create report"). */
export function ProofWorkspace({ evaluationParam }: { evaluationParam?: string }) {
  const { project, campaign } = useProject();
  return (
    <div className="grid gap-8 [&>header]:mb-0">
      <FeatureHeader
        feature="proof"
        description="A report snapshots the research with its provenance, evidence labels, synthetic disclosures, and limitations. Every run behind it stays inspectable."
        howItWorks={
          <ol className="grid list-decimal gap-1.5 pl-4">
            <li>Pick the discovery, rehearsal, adaptations, and evaluation to include. Anything missing is stated in the report.</li>
            <li>The report is assembled from stored results. No model is called.</li>
            <li>Export Markdown or JSON, or print to PDF. Synthetic disclosures and limitations always travel with it.</li>
          </ol>
        }
      />
      {campaign ? (
        <>
          <ReportList projectId={project.id} campaignId={campaign.id} />
          <ReportForm key={campaign.id} project={project} campaign={campaign} evaluationParam={evaluationParam} />
        </>
      ) : (
        <EmptyState
          title="No campaign yet"
          description="Reports cover one campaign. Create a campaign from the project overview first."
          action={
            <Link className={buttonVariants({ variant: "outline" })} href={`/projects/${project.id}`}>
              Go to overview
            </Link>
          }
        />
      )}
      <RunHistory projectId={project.id} />
    </div>
  );
}
