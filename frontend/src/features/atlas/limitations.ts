/**
 * Each distinct limitation once per page. Lines stated for the whole result, or repeated on two or more items, go to
 * one page-level list (with how many items they also qualify); items keep only the lines unique to them.
 */
export function splitLimitations(pageLevel: string[], perItem: string[][], noun: string) {
  const counts = new Map<string, number>();
  for (const list of perItem) for (const line of new Set(list)) counts.set(line, (counts.get(line) ?? 0) + 1);
  const shared = new Set(pageLevel);
  for (const [line, n] of counts) if (n > 1) shared.add(line);
  return {
    page: [...shared].map((line) => {
      const n = counts.get(line) ?? 0;
      return n > 1 ? `${line} (applies to ${n} ${noun})` : line;
    }),
    own: (list: string[]) => list.filter((line) => !shared.has(line)),
  };
}
