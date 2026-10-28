"use client";

import { GraphCanvas, fromGraphView } from "@/components/graph/graph-canvas";
import { Button } from "@/components/ui/button";
import { Label } from "@/components/ui/label";
import type { Market, PopulationGroup } from "@/lib/api/types";

import { useLandscape, type LandscapeFilters } from "./api";

const SELECT =
  "h-8 rounded-lg border border-input bg-surface px-2 text-sm outline-none focus-visible:border-ring focus-visible:ring-3 focus-visible:ring-ring/50";

export function Landscape({
  populationId,
  groups,
  regions,
  filters,
  onFilters,
  selected,
  onSelect,
}: {
  populationId: string;
  groups: PopulationGroup[];
  regions: Market[];
  filters: LandscapeFilters;
  onFilters: (next: LandscapeFilters) => void;
  selected: string[];
  onSelect: (groupId: string, compare: boolean) => void;
}) {
  const query = useLandscape(populationId, filters);
  const graph = query.data && fromGraphView(query.data);
  const interests = [...new Map(groups.flatMap((g) => g.interests).map((i) => [i.ref_id, i])).values()];
  return (
    <div className="grid gap-3">
      <div className="flex flex-wrap items-end gap-x-4 gap-y-2">
        <div className="grid gap-1">
          <Label htmlFor="ls-region" className="text-xs">
            Region
          </Label>
          <select id="ls-region" className={SELECT} value={filters.region ?? ""} onChange={(e) => onFilters({ ...filters, region: e.target.value || undefined })}>
            <option value="">All regions</option>
            {regions.map((m) => (
              <option key={m.country_code} value={m.country_code}>
                {m.display_name}
              </option>
            ))}
          </select>
        </div>
        <div className="grid min-w-0 gap-1">
          <Label htmlFor="ls-interest" className="text-xs">
            Interest
          </Label>
          <select
            id="ls-interest"
            className={`${SELECT} max-w-full`}
            value={filters.interest ?? ""}
            onChange={(e) => onFilters({ ...filters, interest: e.target.value || undefined })}
          >
            <option value="">All interests</option>
            {interests.map((i) => (
              <option key={i.ref_id} value={i.ref_id}>
                {i.name}
              </option>
            ))}
          </select>
        </div>
        {selected.length > 0 && (
          <Button variant="ghost" size="sm" onClick={() => selected.forEach((id) => onSelect(id, true))}>
            Clear comparison
          </Button>
        )}
      </div>
      <GraphCanvas
        label="Audience landscape"
        nodes={graph?.nodes ?? []}
        edges={graph?.edges ?? []}
        legend={graph?.legend ?? []}
        isLoading={query.isPending}
        error={query.error}
        onRetry={() => query.refetch()}
        truncated={graph?.truncated}
        limitations={graph?.limitations}
        height={520}
        emptyTitle="No audience groups to draw"
        emptyDescription="Groups appear once the population is built; similarity links appear only above the stated threshold."
        renderDetails={(node) => {
          const groupId = query.data?.nodes.find((n) => n.id === node.id)?.group_id;
          return node.kind === "audience_group" && groupId ? (
            <div className="flex flex-wrap gap-2">
              <Button size="sm" variant="outline" onClick={() => onSelect(groupId, false)}>
                Open group profile
              </Button>
              <Button size="sm" variant="ghost" aria-pressed={selected.includes(groupId)} onClick={() => onSelect(groupId, true)}>
                {selected.includes(groupId) ? "Remove from comparison" : "Add to comparison"}
              </Button>
            </div>
          ) : null;
        }}
      />
    </div>
  );
}
