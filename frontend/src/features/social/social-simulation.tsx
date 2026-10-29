"use client";

import { Megaphone } from "lucide-react";
import { useState, type FormEvent } from "react";

import { ClaimBadge } from "@/components/evidence/badges";
import { LimitationList } from "@/components/evidence/limitation-list";
import { Field } from "@/components/forms/fields";
import { ErrorState, LoadingState } from "@/components/states";
import { RunStatusPanel } from "@/components/workflow/run-status";
import { Button } from "@/components/ui/button";
import { hasResult } from "@/features/proof/api";
import { Panel, SELECT_CLASS } from "@/features/voice/field";
import { isTerminal, useRun } from "@/lib/api/runs";
import type { PopulationStudyResult, SocialSimulationResult } from "@/lib/api/types";
import { shortId } from "@/lib/format";

import { useDiffusion, useRunControl, useSocialSimulation, useSocialSimulations, useStartSocialSimulation } from "./api";
import { DistributionBar } from "./distribution";
import { FeedBrowser } from "./feed-browser";
import { GraphCanvas, fromGraphView } from "@/components/graph/graph-canvas";

export const SOCIAL_DISCLOSURE = "Simulated social dynamics: illustrative, not a forecast";
const UUID = /[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}/gi;

function Disclosure({ sim }: { sim?: SocialSimulationResult }) {
  return (
    <div role="note" className="flex gap-3 rounded-xl border border-ink-secondary/30 bg-surface-muted px-4 py-3">
      <Megaphone aria-hidden className="mt-0.5 size-5 shrink-0 text-ink" />
      <div className="grid gap-0.5 text-sm text-ink">
        <p className="font-semibold">{SOCIAL_DISCLOSURE}</p>
        <p className="text-[13px] text-ink-secondary">
          {sim?.disclosure.description ?? "Synthetic participants react to each other's synthetic posts over a few bounded rounds."}{" "}
          {sim?.disclosure.shared_model_note ?? "All agents share one model, so agreement is not confirmation."} It does not
          measure real virality, reach, or market behavior.
        </p>
      </div>
    </div>
  );
}

function StartForm({ result, projectId, busy, onStarted }: { result: PopulationStudyResult; projectId: string; busy: boolean; onStarted(id: string): void }) {
  const start = useStartSocialSimulation(projectId);
  const [rounds, setRounds] = useState(3);
  const [activePct, setActivePct] = useState(20);
  const [feedSize, setFeedSize] = useState(5);
  const ready = result.status === "completed" || result.status === "partial";

  function submit(event: FormEvent) {
    event.preventDefault();
    start.mutate(
      { population_study_id: result.id, rounds, active_share: activePct / 100, feed_size: feedSize, seed: 42 },
      { onSuccess: (accepted) => onStarted(accepted.run_id) },
    );
  }

  return (
    <form onSubmit={submit} className="grid gap-4" noValidate>
      <div className="grid grid-cols-[minmax(0,1fr)] gap-x-6 gap-y-4 sm:grid-cols-3">
        <Field label="Rounds" htmlFor="sim-rounds" required hint="1 to 5.">
          <select id="sim-rounds" aria-describedby="sim-rounds-hint" className={SELECT_CLASS} value={rounds} onChange={(e) => setRounds(Number(e.target.value))}>
            {[1, 2, 3, 4, 5].map((n) => (
              <option key={n} value={n}>
                {n}
              </option>
            ))}
          </select>
        </Field>
        <Field label="Active share per round" htmlFor="sim-active" required hint="5% to 50% of participants act each round.">
          <select id="sim-active" aria-describedby="sim-active-hint" className={SELECT_CLASS} value={activePct} onChange={(e) => setActivePct(Number(e.target.value))}>
            {[5, 10, 15, 20, 25, 30, 40, 50].map((n) => (
              <option key={n} value={n}>
                {n}%
              </option>
            ))}
          </select>
        </Field>
        <Field label="Feed size" htmlFor="sim-feed" required hint="Peer posts each active participant sees (2 to 10).">
          <select id="sim-feed" aria-describedby="sim-feed-hint" className={SELECT_CLASS} value={feedSize} onChange={(e) => setFeedSize(Number(e.target.value))}>
            {[2, 3, 4, 5, 6, 8, 10].map((n) => (
              <option key={n} value={n}>
                {n}
              </option>
            ))}
          </select>
        </Field>
      </div>
      {start.error ? <ErrorState error={start.error} /> : null}
      <div className="flex flex-wrap items-center gap-3">
        <Button type="submit" disabled={!ready || busy || start.isPending}>
          {start.isPending ? "Starting…" : "Run social simulation"}
        </Button>
        <p className="text-xs text-ink-secondary">
          {!ready ? "Needs a completed population study." : busy ? "A simulation is running." : "Seeded and bounded; every influence claim cites the posts it rests on."}
        </p>
      </div>
    </form>
  );
}

function Results({ sim, result }: { sim: SocialSimulationResult; result: PopulationStudyResult }) {
  const [round, setRound] = useState<number>();
  const diffusion = useDiffusion(sim.id, round);

  return (
    <div className="grid gap-6">
      <p className="text-xs text-ink-secondary tabular-nums">
        {sim.rounds_completed} of {sim.rounds_requested} rounds completed · network: {sim.network.method} (degree {sim.network.degree};{" "}
        {sim.network.similarity_definition})
      </p>

      <section aria-labelledby="sim-timeline" className="grid gap-2">
        <h4 id="sim-timeline" className="text-sm font-semibold text-ink">
          Stance by round
        </h4>
        <ol className="grid gap-3">
          {sim.rounds.map((r) => (
            <li key={r.round_index} className="grid gap-1">
              <p className="text-xs text-ink tabular-nums">
                <span className="font-semibold">Round {r.round_index}</span> · {r.active_participants} active · {r.shifts} stance{" "}
                {r.shifts === 1 ? "change" : "changes"} ·{" "}
                {Object.entries(r.actions)
                  .map(([a, n]) => `${a} ${n}`)
                  .join(", ")}
              </p>
              <DistributionBar distribution={r.stance} compact />
            </li>
          ))}
        </ol>
      </section>

      <section aria-labelledby="sim-shifts" className="grid gap-2">
        <h4 id="sim-shifts" className="text-sm font-semibold text-ink">
          Group shifts (before → after)
        </h4>
        <ul className="grid grid-cols-[minmax(0,1fr)] gap-3 md:grid-cols-2">
          {sim.group_shifts.map((g) => (
            <li key={g.group_id} className="grid gap-1 rounded-lg border border-border bg-surface p-3">
              <p className="text-[13px] font-medium text-ink">{g.label}</p>
              <p className="text-[11px] text-ink-secondary">Before</p>
              <DistributionBar distribution={g.before} compact />
              <p className="text-[11px] text-ink-secondary">After</p>
              <DistributionBar distribution={g.after} compact />
            </li>
          ))}
        </ul>
      </section>

      <div className="grid grid-cols-[minmax(0,1fr)] gap-6 lg:grid-cols-2">
        <section aria-labelledby="sim-themes" className="grid content-start gap-2">
          <h4 id="sim-themes" className="text-sm font-semibold text-ink">
            Emergent themes
          </h4>
          {sim.emergent_themes.length === 0 ? (
            <p className="text-xs text-ink-secondary">No new themes emerged.</p>
          ) : (
            <ul className="grid gap-1 text-[13px] text-ink">
              {sim.emergent_themes.map((t) => (
                <li key={t.label}>
                  {t.label} <span className="text-xs text-ink-secondary tabular-nums">· {t.count} ({Math.round(t.share * 100)}%)</span>
                </li>
              ))}
            </ul>
          )}
        </section>
        <section aria-labelledby="sim-paths" className="grid content-start gap-2">
          <h4 id="sim-paths" className="flex items-center gap-1.5 text-sm font-semibold text-ink">
            Influence paths <ClaimBadge claim="interpreted" />
          </h4>
          {sim.influence_paths.length === 0 ? (
            <p className="text-xs text-ink-secondary">No influence path was identified.</p>
          ) : (
            <ul className="grid gap-2 text-[13px] text-ink">
              {sim.influence_paths.map((p, i) => {
                const cited = p.match(UUID) ?? [];
                return (
                  <li key={i} className="grid gap-0.5">
                    <span>{p.replace(UUID, (id) => shortId(id))}</span>
                    <span className="text-[11px] text-ink-secondary">
                      {cited.length ? `Cites ${cited.length} ${cited.length === 1 ? "post" : "posts"}; find them in the feed below.` : "Cites no post ids."}
                    </span>
                  </li>
                );
              })}
            </ul>
          )}
        </section>
      </div>

      <section aria-labelledby="sim-diffusion" className="grid gap-2">
        <h4 id="sim-diffusion" className="text-sm font-semibold text-ink">
          Diffusion
        </h4>
        <GraphCanvas
          label="Social diffusion between groups and participants"
          height={480}
          isLoading={diffusion.isPending}
          error={diffusion.error}
          onRetry={() => diffusion.refetch()}
          {...(diffusion.data ? fromGraphView(diffusion.data) : { nodes: [], edges: [], legend: [] })}
          filters={
            <select aria-label="Diffusion round" className={`${SELECT_CLASS} w-auto`} value={round ?? ""} onChange={(e) => setRound(e.target.value ? Number(e.target.value) : undefined)}>
              <option value="">All rounds (group flows)</option>
              {sim.rounds.map((r) => (
                <option key={r.round_index} value={r.round_index}>
                  Round {r.round_index}
                </option>
              ))}
            </select>
          }
        />
      </section>

      <section aria-labelledby="sim-feed" className="grid gap-2">
        <h4 id="sim-feed" className="text-sm font-semibold text-ink">
          Feed browser
        </h4>
        <FeedBrowser simulationId={sim.id} rounds={sim.rounds_completed} groups={result.by_group} />
      </section>

      <LimitationList items={sim.limitations} />
    </div>
  );
}

/** Social simulation on a finished population study. Mounted by B on the population study result. */
export function SocialSimulationPanel({ projectId, result }: { projectId: string; result: PopulationStudyResult }) {
  const sims = useSocialSimulations(result.id);
  const [startedId, setStartedId] = useState<string | null>(null);
  const simId = startedId ?? sims.data?.items[0]?.id ?? null;
  const runQuery = useRun(simId);
  const run = runQuery.data;
  const done = Boolean(run && hasResult(run));
  const sim = useSocialSimulation(done || run?.status === "cancelled" ? simId : null);
  const { cancel, resume } = useRunControl(projectId, simId);
  const busy = Boolean(run && !isTerminal(run.status));

  return (
    <Panel id="social-sim-heading" title="Social dynamics">
      <div className="grid gap-5">
        <Disclosure sim={sim.data} />
        {sims.isPending ? <LoadingState label="Loading simulations…" /> : null}
        {(!simId || isTerminal(run?.status ?? "completed")) && (
          <StartForm result={result} projectId={projectId} busy={busy} onStarted={setStartedId} />
        )}
        {run && (!done || run.status === "partial") && (
          <div className="grid gap-2">
            <RunStatusPanel run={run} operation="Social simulation" />
            <div className="flex flex-wrap gap-2">
              {busy && (
                <Button variant="outline" size="sm" disabled={cancel.isPending} onClick={() => cancel.mutate()}>
                  {cancel.isPending ? "Cancelling…" : "Cancel (keeps finished rounds)"}
                </Button>
              )}
              {run.status === "failed" && (
                <Button variant="outline" size="sm" disabled={resume.isPending} onClick={() => resume.mutate()}>
                  {resume.isPending ? "Resuming…" : "Resume from last round"}
                </Button>
              )}
            </div>
            {cancel.error ? <ErrorState error={cancel.error} /> : null}
            {resume.error ? <ErrorState error={resume.error} /> : null}
          </div>
        )}
        {sim.isError && <ErrorState error={sim.error} onRetry={() => sim.refetch()} />}
        {sim.data && sim.data.rounds.length > 0 && <Results sim={sim.data} result={result} />}
        {simId && sim.data && sim.data.rounds.length === 0 && (
          <p className="text-sm text-ink-secondary">No round finished, so there are no dynamics to show.</p>
        )}
      </div>
    </Panel>
  );
}
