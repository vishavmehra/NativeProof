"use client";

import { useState } from "react";

import { ErrorState, LoadingState } from "@/components/states";
import { Button } from "@/components/ui/button";
import { SELECT_CLASS } from "@/features/voice/field";
import type { GroupResult } from "@/lib/api/types";
import { humanize, shortId } from "@/lib/format";

import { useSocialPosts } from "./api";

const PAGE = 20;

/**
 * Paginated synthetic posts, filtered by round and group. Each post shows its stance trail (previous → current, with
 * the stated reason as model interpretation) and the feed it reacted to.
 */
export function FeedBrowser({ simulationId, rounds, groups }: { simulationId: string; rounds: number; groups: GroupResult[] }) {
  const [round, setRound] = useState<number>();
  const [groupId, setGroupId] = useState("");
  const [offset, setOffset] = useState(0);
  const posts = useSocialPosts(simulationId, { roundIndex: round, groupId, offset });
  const label = new Map(groups.map((g) => [g.group_id, g.label]));
  const total = posts.data?.total ?? 0;

  return (
    <div className="grid gap-3">
      <div className="flex flex-wrap gap-3">
        <label className="grid gap-1 text-xs text-ink-secondary">
          Round
          <select
            className={SELECT_CLASS}
            value={round ?? ""}
            onChange={(e) => {
              setRound(e.target.value ? Number(e.target.value) : undefined);
              setOffset(0);
            }}
          >
            <option value="">All rounds</option>
            {Array.from({ length: rounds }, (_, i) => i + 1).map((r) => (
              <option key={r} value={r}>
                Round {r}
              </option>
            ))}
          </select>
        </label>
        <label className="grid gap-1 text-xs text-ink-secondary">
          Group
          <select
            className={SELECT_CLASS}
            value={groupId}
            onChange={(e) => {
              setGroupId(e.target.value);
              setOffset(0);
            }}
          >
            <option value="">All groups</option>
            {groups.map((g) => (
              <option key={g.group_id} value={g.group_id}>
                {g.label}
              </option>
            ))}
          </select>
        </label>
      </div>

      {posts.isPending ? (
        <LoadingState label="Loading posts…" />
      ) : posts.isError ? (
        <ErrorState error={posts.error} onRetry={() => posts.refetch()} />
      ) : posts.data.items.length === 0 ? (
        <p className="text-sm text-ink-secondary">No posts match these filters.</p>
      ) : (
        <ul className="divide-y divide-border">
          {posts.data.items.map((p) => (
            <li key={p.id} className="grid gap-1 py-2.5">
              <p className="text-xs text-ink-secondary">
                <code className="font-mono">{shortId(p.id)}</code> · round {p.round_index} · {label.get(p.group_id) ?? shortId(p.group_id)} ·{" "}
                {humanize(p.action)} ·{" "}
                {p.previous_stance === null ? (
                  `stance ${p.stance}`
                ) : p.previous_stance === p.stance ? (
                  `kept ${p.stance}`
                ) : (
                  <span className="font-medium text-ink">
                    {p.previous_stance} → {p.stance}
                  </span>
                )}
                {p.parent_post_id && (
                  <>
                    {" "}
                    · reply to <code className="font-mono">{shortId(p.parent_post_id)}</code>
                  </>
                )}
              </p>
              {p.text ? <p className="text-[13px] text-ink">{p.text}</p> : <p className="text-xs text-ink-secondary italic">No text ({p.action}).</p>}
              {p.reason && (
                <p className="text-xs text-ink-secondary">
                  <span className="font-medium text-ink">{p.previous_stance && p.previous_stance !== p.stance ? "Why it changed" : "Why"}</span> (model
                  interpretation): {p.reason}
                </p>
              )}
              <p className="text-[11px] text-ink-secondary">
                Reacted to a feed of {p.seen_post_ids.length} {p.seen_post_ids.length === 1 ? "post" : "posts"}
                {p.seen_post_ids.length > 0 && <>: {p.seen_post_ids.slice(0, 5).map(shortId).join(", ")}{p.seen_post_ids.length > 5 && "…"}</>}
              </p>
            </li>
          ))}
        </ul>
      )}

      {total > PAGE && (
        <div className="flex items-center gap-3 text-xs text-ink-secondary tabular-nums">
          <Button variant="outline" size="sm" disabled={offset === 0} onClick={() => setOffset(Math.max(0, offset - PAGE))}>
            Previous
          </Button>
          {offset + 1}–{Math.min(offset + PAGE, total)} of {total}
          <Button variant="outline" size="sm" disabled={offset + PAGE >= total} onClick={() => setOffset(offset + PAGE)}>
            Next
          </Button>
        </div>
      )}
    </div>
  );
}
