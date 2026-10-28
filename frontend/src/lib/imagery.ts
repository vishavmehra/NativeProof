/**
 * Decorative photography library (public/imagery, credits in public/imagery/CREDITS.md; Unsplash License).
 * Decorative only: render with alt="" and never inside evidence or result views (docs/16_REFERENCE_UI.md §4).
 */
export type Imagery = { src: string; credit: string; keywords: readonly string[] };

export const IMAGERY: readonly Imagery[] = [
  { src: "/imagery/outdoor-mountain-lake.webp", credit: "Philipp / Unsplash", keywords: ["outdoor", "mountain", "lake", "nature", "hiking", "adventure", "landscape", "travel"] },
  { src: "/imagery/outdoor-camping.webp", credit: "Ali Kazal / Unsplash", keywords: ["camping", "tent", "outdoor", "adventure", "travel", "canada", "rockies", "explorer"] },
  { src: "/imagery/sustainability-forest.webp", credit: "Joyce G / Unsplash", keywords: ["sustainability", "sustainable", "forest", "green", "eco", "environment", "nature"] },
  { src: "/imagery/urban-tokyo-night.webp", credit: "Johan Mouchet / Unsplash", keywords: ["urban", "city", "tokyo", "japan", "jp", "street", "nightlife"] },
  { src: "/imagery/wellness-yoga.webp", credit: "kike vega / Unsplash", keywords: ["wellness", "yoga", "fitness", "mindfulness", "health", "wellbeing"] },
  { src: "/imagery/food-table.webp", credit: "Joanie Simon / Unsplash", keywords: ["food", "dining", "restaurant", "cuisine", "culinary", "drink"] },
  { src: "/imagery/music-concert.webp", credit: "Marcel Strauß / Unsplash", keywords: ["music", "concert", "festival", "entertainment", "live"] },
];

const tokens = (values: readonly (string | null | undefined)[]) =>
  values.flatMap((v) => (v ?? "").toLowerCase().split(/[^a-z0-9]+/)).filter((t) => t.length > 1);

/**
 * Best keyword match from the library. With no match, a stable pick by `seed` (so neighbouring cards differ but a card
 * keeps its image across renders). Example: pickImagery(["Outdoor Explorers", "hiking"]).src → mountain lake.
 */
export function pickImagery(keywords: readonly (string | null | undefined)[], seed = ""): Imagery {
  const words = tokens(keywords);
  let best: Imagery | null = null;
  let bestScore = 0;
  for (const image of IMAGERY) {
    const score = words.filter((w) => image.keywords.some((k) => k === w || (w.length > 3 && (k.startsWith(w) || w.startsWith(k))))).length;
    if (score > bestScore) [best, bestScore] = [image, score];
  }
  if (best) return best;
  let h = 0;
  for (const ch of seed || words.join(" ")) h = (h * 31 + ch.charCodeAt(0)) >>> 0;
  return IMAGERY[h % IMAGERY.length];
}
