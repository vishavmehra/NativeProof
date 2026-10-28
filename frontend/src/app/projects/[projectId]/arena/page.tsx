import type { Metadata } from "next";

import { ArenaWorkspace } from "@/features/arena/arena-workspace";

export const metadata: Metadata = { title: "Campaign Arena" };
export const instant = false;

type SearchParams = Promise<Record<string, string | string[] | undefined>>;
const one = (value: string | string[] | undefined) => (Array.isArray(value) ? value[0] : value);

export default async function ArenaPage({ searchParams }: { searchParams: SearchParams }) {
  const query = await searchParams;
  return <ArenaWorkspace runParam={one(query.run)} />;
}
