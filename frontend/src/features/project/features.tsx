import {
  AudioLines,
  ClipboardList,
  Diamond,
  Dna,
  FileCheck,
  Globe,
  LayoutGrid,
  Network,
  RotateCcw,
  Sparkle,
  Swords,
  Target,
  Users,
  type LucideIcon,
} from "lucide-react";

export type FeatureKey =
  | "overview"
  | "atlas"
  | "dna"
  | "markets"
  | "trends"
  | "audience"
  | "arena"
  | "risk"
  | "voice"
  | "loop"
  | "brand"
  | "proof"
  | "graph";

/** Sidebar groups exactly as the reference (docs/16_REFERENCE_UI.md §1). The project overview is not in the nav. */
export type FeatureGroup = "workspace" | "discover" | "campaign" | "evidence";

/** Literal class names per feature (Tailwind needs them verbatim). Tokens live in globals.css. */
export type FeatureTone = { text: string; soft: string; ink: string; border: string; dot: string };

export type Feature = {
  key: FeatureKey;
  /** Nav label and page title (they must match). */
  label: string;
  /** Route segment under /projects/[projectId]; null for the project overview. */
  segment: string | null;
  group: FeatureGroup;
  Icon: LucideIcon;
  /** One-line subtitle under the page title. */
  description: string;
  tone: FeatureTone;
};

const tone = (f: string): FeatureTone => ({
  text: `text-${f}`,
  soft: `bg-${f}-soft`,
  ink: `text-${f}-ink`,
  border: `border-${f}/30`,
  dot: `bg-${f}`,
});

// Tailwind scans source for complete class names, so the generated ones are listed here once:
// text-atlas bg-atlas-soft text-atlas-ink border-atlas/30 bg-atlas text-dna bg-dna-soft text-dna-ink border-dna/30 bg-dna
// text-markets bg-markets-soft text-markets-ink border-markets/30 bg-markets text-trends bg-trends-soft text-trends-ink
// border-trends/30 bg-trends text-audience bg-audience-soft text-audience-ink border-audience/30 bg-audience text-arena
// bg-arena-soft text-arena-ink border-arena/30 bg-arena text-risk bg-risk-soft text-risk-ink border-risk/30 bg-risk
// text-voice bg-voice-soft text-voice-ink border-voice/30 bg-voice text-loop bg-loop-soft text-loop-ink border-loop/30
// bg-loop text-brand bg-brand-soft text-brand-ink border-brand/30 bg-brand text-proof bg-proof-soft text-proof-ink
// border-proof/30 bg-proof text-graph bg-graph-soft text-graph-ink border-graph/30 bg-graph

export const FEATURES: Record<FeatureKey, Feature> = {
  overview: {
    key: "overview",
    label: "Overview",
    segment: null,
    group: "workspace",
    Icon: LayoutGrid,
    description: "Project, campaign, and where the research stands.",
    tone: { text: "text-primary", soft: "bg-accent", ink: "text-primary", border: "border-primary/30", dot: "bg-primary" },
  },
  atlas: { key: "atlas", label: "Atlas", segment: "atlas", group: "discover", Icon: Target, description: "Explore the cultural signals around your concept, grounded in Qloo affinity data.", tone: tone("atlas") },
  dna: { key: "dna", label: "Cultural DNA", segment: "cultural-dna", group: "discover", Icon: Dna, description: "A versioned cultural profile of a market, grounded in discovery evidence.", tone: tone("dna") },
  markets: { key: "markets", label: "Market Expansion", segment: "market-expansion", group: "discover", Icon: Globe, description: "Compare candidate markets on the same evidence, and name the gaps.", tone: tone("markets") },
  trends: { key: "trends", label: "Trend Watch", segment: "trend-watch", group: "discover", Icon: Sparkle, description: "Compare saved snapshots to see what changed.", tone: tone("trends") },
  audience: { key: "audience", label: "Audience", segment: "audience", group: "campaign", Icon: Users, description: "Explore synthetic audience groups grounded in Qloo signals.", tone: tone("audience") },
  arena: { key: "arena", label: "Campaign Arena", segment: "arena", group: "campaign", Icon: Swords, description: "Test creative variants against the same synthetic audience and criteria.", tone: tone("arena") },
  risk: { key: "risk", label: "Risk Radar", segment: "risk-radar", group: "campaign", Icon: Diamond, description: "Identify potential cultural risks before you launch.", tone: tone("risk") },
  voice: { key: "voice", label: "Voice", segment: "voice", group: "campaign", Icon: AudioLines, description: "Adapt your content to resonate across cultures, channels, and audiences.", tone: tone("voice") },
  loop: { key: "loop", label: "Loop", segment: "loop", group: "campaign", Icon: RotateCcw, description: "Turn insights into better campaigns, one iteration at a time.", tone: tone("loop") },
  brand: { key: "brand", label: "Brand Memory", segment: "brand", group: "campaign", Icon: ClipboardList, description: "Save your brand's essence, so every insight, analysis, and campaign is aligned.", tone: tone("brand") },
  proof: { key: "proof", label: "Proof", segment: "proof", group: "evidence", Icon: FileCheck, description: "Assemble an evidence-backed report with provenance and limitations.", tone: tone("proof") },
  graph: { key: "graph", label: "Evidence Graph", segment: "graph", group: "evidence", Icon: Network, description: "See how everything connects.", tone: tone("graph") },
};

export const FEATURE_GROUPS: { group: FeatureGroup; label: string | null; keys: FeatureKey[] }[] = [
  { group: "discover", label: "Discover", keys: ["atlas", "dna", "markets", "trends"] },
  { group: "campaign", label: "Campaign intelligence", keys: ["audience", "arena", "risk", "voice", "loop", "brand"] },
  { group: "evidence", label: "Evidence", keys: ["proof", "graph"] },
];

export function featureBySegment(segment: string | null): Feature {
  return Object.values(FEATURES).find((f) => f.segment === segment) ?? FEATURES.overview;
}
