"use client";

import { XIcon } from "lucide-react";
import { useState } from "react";

import { ClaimBadge } from "@/components/evidence/badges";
import { EvidenceLinks } from "@/components/evidence/evidence-links";
import { ErrorState, LoadingState } from "@/components/states";
import { Button } from "@/components/ui/button";
import type { EvidenceRecord, GroupResult, PopulationGroup } from "@/lib/api/types";
import { humanize, shortId } from "@/lib/format";

import { PAGE, useParticipants } from "./api";
import { ParticipantDetailPanel } from "./ask";
import { ReactionBar } from "./reaction-bars";

/** One group's profile: a model-built archetype, its cited evidence, its tallies, and (optionally) its participants. */
export function GroupProfile({
  group,
  result,
  evidence,
  populationId,
  onOpenInterviews,
  showParticipants = true,
}: {
  group: PopulationGroup;
  result?: GroupResult;
  evidence: EvidenceRecord[];
  populationId: string;
  onOpenInterviews: (groupId: string) => void;
  showParticipants?: boolean;
}) {
  const [open, setOpen] = useState(false);
  return (
    <div className="grid min-w-0 grid-cols-[minmax(0,1fr)] content-start gap-3">
      <div className="flex flex-wrap items-center gap-2">
        <ClaimBadge claim="interpreted" />
        <span className="text-xs text-ink-secondary">
          {group.region.display_name} · {group.participant_count} participants · {Math.round(group.share * 100)}% allocation
          share (a configuration choice, not market share)
        </span>
      </div>
      <p className="text-sm">{group.description}</p>
      {result && <ReactionBar d={result.distribution} compact />}
      {group.interests.length > 0 && (
        <div className="grid gap-1">
          <p className="text-xs font-medium text-ink-secondary">Interests (weight = relative emphasis from evidence rank, not prevalence)</p>
          <ul className="flex flex-wrap gap-1.5">
            {group.interests.map((i) => (
              <li key={i.ref_id} className="rounded-sm border px-1.5 py-0.5 text-xs tabular-nums">
                {i.name} <span className="text-ink-secondary">{i.weight.toFixed(2)}</span>
              </li>
            ))}
          </ul>
        </div>
      )}
      <div className="[contain:inline-size]">
        <EvidenceLinks ids={group.evidence_ids} evidence={evidence} title={group.label} />
      </div>
      <div className="flex flex-wrap gap-2">
        <Button variant="outline" size="sm" onClick={() => onOpenInterviews(group.id)}>
          Open interviews
        </Button>
        {showParticipants && (
          <Button variant="ghost" size="sm" aria-expanded={open} onClick={() => setOpen(!open)}>
            {open ? "Hide participants" : "Show participants"}
          </Button>
        )}
      </div>
      {open && <ParticipantList populationId={populationId} groupId={group.id} />}
    </div>
  );
}

/** A group's synthetic participants, paginated. */
export function ParticipantList({ populationId, groupId, studyId }: { populationId: string; groupId: string; studyId?: string }) {
  const [offset, setOffset] = useState(0);
  const [openId, setOpenId] = useState<string | null>(null);
  const participants = useParticipants(populationId, groupId, offset);
  return participants.isError ? (
          <ErrorState error={participants.error} onRetry={() => participants.refetch()} />
        ) : participants.isPending ? (
          <LoadingState label="Loading participants…" />
        ) : (
          <div className="grid gap-2">
            <p className="text-xs text-ink-secondary">
              Synthetic participants, expanded deterministically from this group with the run seed. Traits are seeded
              variation knobs, not demographics.
            </p>
            <ul className="grid gap-1.5">
              {participants.data.items.map((p) => (
                <li key={p.id} className="grid gap-0.5 rounded-md border px-2.5 py-1.5 text-xs">
                  <span className="font-medium tabular-nums">
                    Participant {p.ordinal} <span className="font-mono font-normal text-ink-secondary">{shortId(p.id)}</span> ·{" "}
                    {p.region.display_name}
                  </span>
                  <span className="text-ink-secondary">
                    {Object.entries(p.traits)
                      .map(([k, v]) => `${humanize(k)}: ${v}`)
                      .join(" · ")}
                  </span>
                  {p.interests.length > 0 && <span>Interests: {p.interests.map((i) => i.name).join(", ")}</span>}
                  {studyId && (
                    <Button variant="ghost" size="xs" className="w-fit" aria-expanded={openId === p.id} onClick={() => setOpenId(openId === p.id ? null : p.id)}>
                      {openId === p.id ? "Hide details" : "Details and follow-up"}
                    </Button>
                  )}
                  {studyId && openId === p.id && <ParticipantDetailPanel studyId={studyId} participantId={p.id} />}
                </li>
              ))}
            </ul>
            {participants.data.total > PAGE && (
              <div className="flex items-center gap-2 text-xs tabular-nums">
                <Button variant="outline" size="xs" disabled={offset === 0} onClick={() => setOffset(Math.max(0, offset - PAGE))}>
                  Previous
                </Button>
                <Button variant="outline" size="xs" disabled={offset + PAGE >= participants.data.total} onClick={() => setOffset(offset + PAGE)}>
                  Next
                </Button>
                {offset + 1}–{Math.min(offset + PAGE, participants.data.total)} of {participants.data.total}
              </div>
            )}
          </div>
  );
}

/** Selected group(s): one profile, or two side by side for comparison. */
export function GroupPanel({
  groups,
  results,
  evidence,
  populationId,
  onClose,
  onOpenInterviews,
}: {
  groups: PopulationGroup[];
  results: GroupResult[];
  evidence: EvidenceRecord[];
  populationId: string;
  onClose: () => void;
  onOpenInterviews: (groupId: string) => void;
}) {
  if (groups.length === 0) return null;
  return (
    <section aria-label={groups.length > 1 ? "Group comparison" : "Group profile"} className="grid min-w-0 grid-cols-[minmax(0,1fr)] gap-3 rounded-lg border bg-card p-4">
      <div className="flex items-start justify-between gap-2">
        <h3 className="text-[15px] font-semibold">
          {groups.length > 1 ? `Comparing ${groups[0].label} and ${groups[1].label}` : groups[0].label}
        </h3>
        <Button variant="ghost" size="icon-sm" aria-label="Close group panel" onClick={onClose}>
          <XIcon aria-hidden />
        </Button>
      </div>
      <div className={groups.length > 1 ? "grid min-w-0 grid-cols-[minmax(0,1fr)] gap-6 md:grid-cols-[minmax(0,1fr)_minmax(0,1fr)]" : "grid gap-6"}>
        {groups.map((g) => (
          <div key={g.id} className="grid min-w-0 grid-cols-[minmax(0,1fr)] content-start gap-2">
            {groups.length > 1 && <h4 className="text-sm font-semibold">{g.label}</h4>}
            <GroupProfile
              group={g}
              result={results.find((r) => r.group_id === g.id)}
              evidence={evidence}
              populationId={populationId}
              onOpenInterviews={onOpenInterviews}
              showParticipants={groups.length === 1}
            />
          </div>
        ))}
      </div>
    </section>
  );
}
