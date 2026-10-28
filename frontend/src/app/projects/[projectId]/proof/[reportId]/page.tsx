import type { Metadata } from "next";

import { ReportViewer } from "@/features/proof/report-viewer";

export const metadata: Metadata = { title: "Report" };
export const instant = false;

export default async function ReportPage({ params }: { params: Promise<{ projectId: string; reportId: string }> }) {
  const { reportId } = await params;
  return <ReportViewer key={reportId} reportId={reportId} />;
}
