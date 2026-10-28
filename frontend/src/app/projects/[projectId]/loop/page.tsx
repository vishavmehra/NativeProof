import type { Metadata } from "next";

import { LoopWorkspace } from "@/features/loop/loop-workspace";

export const metadata: Metadata = { title: "Loop" };
export const instant = false;

type SearchParams = Promise<Record<string, string | string[] | undefined>>;
const one = (value: string | string[] | undefined) => (Array.isArray(value) ? value[0] : value);

export default async function LoopPage({ searchParams }: { searchParams: SearchParams }) {
  const query = await searchParams;
  const candidateIds = (one(query.candidates) ?? "").split(",").map((id) => id.trim()).filter(Boolean);
  return <LoopWorkspace versionParam={one(query.version)} candidateIds={candidateIds} runParam={one(query.run)} />;
}
