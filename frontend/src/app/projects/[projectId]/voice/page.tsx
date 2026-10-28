import type { Metadata } from "next";

import { VoiceWorkspace } from "@/features/voice/voice-workspace";

export const metadata: Metadata = { title: "Voice" };
export const instant = false;

type SearchParams = Promise<Record<string, string | string[] | undefined>>;
const one = (value: string | string[] | undefined) => (Array.isArray(value) ? value[0] : value);

export default async function VoicePage({ searchParams }: { searchParams: SearchParams }) {
  const query = await searchParams;
  return (
    <VoiceWorkspace
      discoveryParam={one(query.discovery)}
      rehearsalParam={one(query.rehearsal)}
      runParam={one(query.run)}
      adaptationParam={one(query.adaptation)}
    />
  );
}
