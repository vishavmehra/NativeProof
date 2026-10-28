"use client";

import { useState, type FormEvent } from "react";

import { ClaimBadge, SyntheticBadge } from "@/components/evidence/badges";
import { ErrorState, LoadingState } from "@/components/states";
import { Button } from "@/components/ui/button";
import { Label } from "@/components/ui/label";
import { Textarea } from "@/components/ui/textarea";
import { humanize } from "@/lib/format";

import { useAskGroup, useAskParticipant, useFollowUps, useGroupQuestions, useParticipantDetail, type FollowUpAnswer } from "./api";
import { REACTION_LABEL, ReactionBar } from "./reaction-bars";

const SOURCE = { interview: "from the interview", social_round: "from a social simulation round", none: "no stance recorded yet" } as const;

function Answer({ a }: { a: FollowUpAnswer }) {
  return (
    <li className="grid min-w-0 grid-cols-[minmax(0,1fr)] gap-1 rounded-lg border bg-surface p-2.5 text-sm">
      <p className="text-xs text-ink-secondary">Q: {a.question}</p>
      <p>{a.answer}</p>
      <p className="text-[11px] text-ink-secondary">
        {a.stance ? `Stance: ${REACTION_LABEL[a.stance]}` : "No stance"} · drew on {a.memory_refs.length} stored{" "}
        {a.memory_refs.length === 1 ? "memory" : "memories"}
      </p>
      <SyntheticBadge />
    </li>
  );
}

function QuestionForm({ id, pending, error, onAsk, extra }: { id: string; pending: boolean; error: unknown; onAsk: (q: string) => void; extra?: React.ReactNode }) {
  const [q, setQ] = useState("");
  function submit(e: FormEvent) {
    e.preventDefault();
    if (q.trim()) onAsk(q.trim());
  }
  return (
    <form onSubmit={submit} className="grid gap-2">
      <Label htmlFor={id} className="text-xs">
        Question
      </Label>
      <Textarea id={id} value={q} maxLength={1000} rows={2} onChange={(e) => setQ(e.target.value)} className="bg-surface" />
      {extra}
      {Boolean(error) && <ErrorState error={error} />}
      <Button type="submit" size="sm" className="w-fit" disabled={pending || !q.trim()} aria-busy={pending || undefined}>
        Ask
      </Button>
    </form>
  );
}

/** One participant: latest stance, stored memories, and follow-up questions answered from those memories. */
export function ParticipantDetailPanel({ studyId, participantId }: { studyId: string; participantId: string }) {
  const detail = useParticipantDetail(studyId, participantId);
  const followUps = useFollowUps(studyId, participantId);
  const ask = useAskParticipant(studyId, participantId);
  if (detail.isError) return <ErrorState error={detail.error} onRetry={() => detail.refetch()} />;
  if (detail.isPending) return <LoadingState label="Loading participant…" />;
  const d = detail.data;
  return (
    <div className="grid min-w-0 grid-cols-[minmax(0,1fr)] gap-3 rounded-lg bg-surface-muted p-3">
      <p className="text-sm">
        <span className="font-medium">Stance: {d.state.stance ? REACTION_LABEL[d.state.stance] : "none"}</span>{" "}
        <span className="text-ink-secondary">({SOURCE[d.state.stance_source]}{d.state.last_round_index !== null ? `, round ${d.state.last_round_index}` : ""})</span>
      </p>
      <div className="grid gap-1">
        <h5 className="text-xs font-semibold">Memories ({d.memories.length})</h5>
        {d.memories.length === 0 ? (
          <p className="text-xs text-ink-secondary">No stored memories yet.</p>
        ) : (
          <ul className="grid max-h-48 gap-1 overflow-y-auto text-xs">
            {d.memories.map((m) => (
              <li key={`${m.kind}-${m.ref_id}`}>
                <span className="font-medium">{humanize(m.kind)}</span>
                {m.round_index !== null && ` · round ${m.round_index}`}: {m.summary}
              </li>
            ))}
          </ul>
        )}
        <p className="text-[11px] text-ink-secondary">Quoted or shortened from stored records, most recent first (at most 50).</p>
      </div>
      <div className="grid gap-2">
        <h5 className="text-xs font-semibold">Ask a follow-up</h5>
        <QuestionForm id={`fu-${participantId}`} pending={ask.isPending} error={ask.error} onAsk={(q) => ask.mutate(q)} />
        {followUps.data && followUps.data.items.length > 0 && (
          <ul className="grid gap-2">
            {followUps.data.items.map((a) => (
              <Answer key={a.id} a={a} />
            ))}
          </ul>
        )}
      </div>
    </div>
  );
}

/** Ask a seeded sample (3–10) of one group; the tally covers the sampled answers only. */
export function AskGroup({ studyId, groupId }: { studyId: string; groupId: string }) {
  const [size, setSize] = useState(5);
  const history = useGroupQuestions(studyId, groupId);
  const ask = useAskGroup(studyId, groupId);
  return (
    <div className="grid gap-3">
      <QuestionForm
        id={`gq-${groupId}`}
        pending={ask.isPending}
        error={ask.error}
        onAsk={(question) => ask.mutate({ question, sample_size: size })}
        extra={
          <Label className="text-xs font-normal">
            Sample
            <select value={size} onChange={(e) => setSize(Number(e.target.value))} className="h-7 rounded-md border bg-surface px-1.5 tabular-nums">
              {[3, 4, 5, 6, 7, 8, 9, 10].map((n) => (
                <option key={n} value={n}>
                  {n}
                </option>
              ))}
            </select>
            participants
          </Label>
        }
      />
      {history.isError && <ErrorState error={history.error} onRetry={() => history.refetch()} />}
      {history.data?.items.map((r) => (
        <article key={r.id} className="grid min-w-0 grid-cols-[minmax(0,1fr)] gap-2 border-t pt-3">
          <h5 className="text-sm font-semibold">{r.question}</h5>
          <p className="text-xs text-ink-secondary">{r.sample_note}</p>
          <ReactionBar d={r.stance} compact />
          <div className="flex flex-wrap items-center gap-2">
            <ClaimBadge claim="interpreted" />
            <p className="text-sm">{r.summary}</p>
          </div>
          <ul className="grid gap-2">
            {r.answers.map((a) => (
              <Answer key={a.id} a={a} />
            ))}
          </ul>
        </article>
      ))}
    </div>
  );
}
