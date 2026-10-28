import type { Metadata } from "next";

import { RiskWorkspace } from "@/features/risk/risk-workspace";

export const metadata: Metadata = { title: "Risk Radar" };
export const instant = false;

type SearchParams = Promise<Record<string, string | string[] | undefined>>;
const one = (value: string | string[] | undefined) => (Array.isArray(value) ? value[0] : value);

export default async function RiskRadarPage({ searchParams }: { searchParams: SearchParams }) {
  const query = await searchParams;
  return <RiskWorkspace runParam={one(query.run)} />;
}
