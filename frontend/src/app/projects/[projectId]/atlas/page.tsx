import type { Metadata } from "next";

import { AtlasWorkspace } from "@/features/atlas/atlas-workspace";

export const metadata: Metadata = { title: "Atlas" };
// Rendered inside the project layout's params boundary, which validation cannot see past (see layout.tsx).
export const instant = false;

export default function AtlasPage() {
  return <AtlasWorkspace />;
}
