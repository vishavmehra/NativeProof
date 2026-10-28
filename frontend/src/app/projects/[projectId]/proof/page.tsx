import type { Metadata } from "next";

import { ProofWorkspace } from "@/features/proof/proof-workspace";

export const metadata: Metadata = { title: "Proof" };
export const instant = false;

type SearchParams = Promise<Record<string, string | string[] | undefined>>;
const one = (value: string | string[] | undefined) => (Array.isArray(value) ? value[0] : value);

export default async function ProofPage({ searchParams }: { searchParams: SearchParams }) {
  const query = await searchParams;
  return <ProofWorkspace evaluationParam={one(query.evaluation)} />;
}
