import type { Metadata } from "next";

import { BrandMemory } from "@/features/brand/brand-memory";

export const metadata: Metadata = { title: "Brand Memory" };

// Rendered inside the project layout's params boundary (see ../layout.tsx).
export const instant = false;

export default function BrandMemoryPage() {
  return <BrandMemory />;
}
