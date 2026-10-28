"use client";

import { Download } from "lucide-react";
import Link from "next/link";
import { useState } from "react";

import { ClaimBadge, SyntheticBadge } from "@/components/evidence/badges";
import { EvidenceLinks } from "@/components/evidence/evidence-links";
import { GraphCanvas, fromGraphView } from "@/components/graph/graph-canvas";
import { FilterCard, FilterField, filterSelectClass } from "@/components/layout/page-parts";
import { ErrorState, LoadingState } from "@/components/states";
import { Button, buttonVariants } from "@/components/ui/button";
import type { GraphView, PopulationStudyResult, ViewNode } from "@/lib/api/types";
import { humanize } from "@/lib/format";

import { useInterviews, useReactionMap } from "./api";
import { DistributionBar } from "./distribution";

const ELEMENTS = [
  ["", "All elements"],
  ["headline", "Headline"],
  ["body", "Body"],
  ["call_to_action", "Call to action"],
  ["creative", "Creative"],
] as const;

/** Nodes connected to `id`, with the relation and provenance of each edge. */
function neighbors(graph: GraphView, id: string) {
  const byId = new Map(graph.nodes.map((n) => [n.id, n]));
  return graph.edges.flatMap((e) => {
    const other = e.source === id ? e.target : e.target === id ? e.source : null;
    const node = other ? byId.get(other) : undefined;
    return node ? [{ node, edge: e }] : [];
  });
}

/** The stored GraphView as JSON (it already carries provenance and limitations). */
function download(graph: GraphView, studyId: string) {
  const url = URL.createObjectURL(new Blob([JSON.stringify(graph, null, 2)], { type: "application/json" }));
  const link = Object.assign(document.createElement("a"), { href: url, download: `reaction-network-${studyId.slice(0, 8)}.json` });
  document.body.append(link);
  link.click();
  link.remove();
  setTimeout(() => URL.revokeObjectURL(url), 1000);
}

/** What the selected groups said: a few synthetic interviews, labeled as such. */
function InterviewSnippets({ studyId, groupId }: { studyId: string; groupId: string }) {
  const interviews = useInterviews(studyId, { groupId });
  if (interviews.isPending) return <LoadingState label="Loading interviews…" />;
  if (interviews.isError) return <ErrorState error={interviews.error} onRetry={() => interviews.refetch()} />;
  const items = interviews.data.items.filter((i) => i.status === "completed").slice(0, 3);
  if (items.length === 0) return <p className="text-xs text-ink-secondary">No completed interviews for this group.</p>;
  return (
    <ul className="grid gap-2">
      {items.map((i) => {
        const first = i.answers.find((a) => a.question_id === "first_impression") ?? i.answers[0];
        return (
          <li key={i.id} className="grid gap-0.5 border-l-2 border-dashed border-ink-secondary/40 pl-2 text-[13px]">
            <span className="text-xs text-ink-secondary">{i.reaction ? humanize(i.reaction) : "No reaction recorded"}</span>
            {first && <span className="text-ink">“{first.answer}”</span>}
            {i.misunderstanding && <span className="text-xs text-ink-secondary">Misread: {i.misunderstanding}</span>}
          </li>
        );
      })}
    </ul>
  );
}

function SelectionDetail({
  node,
  graph,
  result,
  projectId,
}: {
  node: ViewNode;
  graph: GraphView;
  result: PopulationStudyResult;
  projectId: string;
}) {
  const linked = neighbors(graph, node.id);
  const ofKind = (kind: ViewNode["kind"]) => linked.filter((l) => l.node.kind === kind);
  const groups = ofKind("audience_group").map((l) => result.by_group.find((g) => g.group_id === (l.node.group_id ?? l.node.resource_id)) ?? null);
  const knownGroups = groups.filter((g) => g !== null);
  const evidenceIds = ofKind("evidence").flatMap((l) => (l.node.resource_id ? [l.node.resource_id] : []));
  const misunderstandings = knownGroups.flatMap((g) => g.misunderstandings.map((m) => ({ ...m, group: g.label })));
  const campaignQuery = `campaign=${result.campaign_id}`;

  // The canvas detail panel already shows the node's label, kind, facts, and relations.
  return (
    <div className="grid gap-4">
      <section className="grid gap-2" aria-label="Groups that reacted">
        <h5 className="text-xs font-semibold text-ink">Groups that reacted ({knownGroups.length})</h5>
        {knownGroups.length === 0 ? (
          <p className="text-xs text-ink-secondary">No group is linked to this item.</p>
        ) : (
          knownGroups.map((g) => (
            <div key={g.group_id} className="grid gap-1">
              <span className="text-[13px] text-ink">
                {g.label} <span className="text-xs text-ink-secondary">{g.region.display_name}</span>
              </span>
              <DistributionBar distribution={g.distribution} compact />
            </div>
          ))
        )}
      </section>

      {knownGroups[0] && (
        <section className="grid gap-2" aria-label="What they said">
          <h5 className="flex items-center gap-1.5 text-xs font-semibold text-ink">
            What {knownGroups[0].label} said <ClaimBadge claim="synthetic" />
          </h5>
          <InterviewSnippets studyId={result.id} groupId={knownGroups[0].group_id} />
        </section>
      )}

      <section className="grid gap-1.5" aria-label="Misunderstandings">
        <h5 className="text-xs font-semibold text-ink">Misunderstandings</h5>
        {misunderstandings.length === 0 ? (
          <p className="text-xs text-ink-secondary">None recorded for these groups.</p>
        ) : (
          <ul className="grid gap-1 text-[13px] text-ink">
            {misunderstandings.slice(0, 6).map((m, i) => (
              <li key={i}>
                {m.label}{" "}
                <span className="text-xs text-ink-secondary tabular-nums">
                  {m.group} · {m.count} ({Math.round(m.share * 100)}%)
                </span>
              </li>
            ))}
          </ul>
        )}
      </section>

      <section className="grid gap-1.5" aria-label="Cultural evidence">
        <h5 className="text-xs font-semibold text-ink">Cultural evidence behind it</h5>
        <EvidenceLinks ids={evidenceIds} evidence={result.evidence} title={node.label} />
      </section>

      <section className="grid gap-1.5" aria-label="Alternative to test">
        <h5 className="flex items-center gap-1.5 text-xs font-semibold text-ink">
          Alternative to test <ClaimBadge claim="interpreted" />
        </h5>
        {ofKind("recommendation").length === 0 ? (
          <p className="text-xs text-ink-secondary">No recommendation is linked to this item.</p>
        ) : (
          <ul className="grid gap-1 text-[13px] text-ink">
            {ofKind("recommendation").map((l) => (
              <li key={l.node.id}>{l.node.label}</li>
            ))}
          </ul>
        )}
        <div className="flex flex-wrap gap-2">
          <Link className={buttonVariants({ variant: "outline", size: "sm" })} href={`/projects/${projectId}/voice?${campaignQuery}`}>
            Draft it in Voice
          </Link>
          <Link className={buttonVariants({ variant: "outline", size: "sm" })} href={`/projects/${projectId}/arena?${campaignQuery}`}>
            Test it in Arena
          </Link>
        </div>
      </section>
    </div>
  );
}

/** Graph C: which campaign elements drew which reactions from which groups, and why. Mounted by B on the study result. */
export function ReactionMap({ projectId, result }: { projectId: string; result: PopulationStudyResult }) {
  const [element, setElement] = useState("");
  const [groupId, setGroupId] = useState("");
  const map = useReactionMap(result.id, { element, groupId });
  const graph = map.data;
  const canvas = graph && fromGraphView(graph);

  return (
    <section aria-labelledby="reaction-map-heading" className="grid gap-4">
      <div className="grid gap-1">
        <h3 id="reaction-map-heading" className="font-serif text-xl text-ink">
          Audience reaction network
        </h3>
        <p className="flex flex-wrap items-center gap-2 text-xs text-ink-secondary tabular-nums">
          <SyntheticBadge />
          {result.completed_interviews} completed synthetic interviews
          {result.failed_interviews > 0 && `, ${result.failed_interviews} failed`}. {result.disclosure.shared_model_note}
        </p>
      </div>

      <GraphCanvas
        label="Audience reaction network: campaign elements, audience groups, and reaction themes"
        isLoading={map.isPending}
        error={map.error}
        onRetry={() => map.refetch()}
        nodes={canvas?.nodes ?? []}
        edges={canvas?.edges ?? []}
        legend={canvas?.legend ?? []}
        truncated={canvas?.truncated}
        limitations={canvas?.limitations}
        emptyTitle="No reactions match these filters"
        emptyDescription="Choose another campaign element or group."
        filters={
          <FilterCard>
            <FilterField label="Campaign element" htmlFor="reaction-element">
              <select id="reaction-element" className={filterSelectClass} value={element} onChange={(e) => setElement(e.target.value)}>
                {ELEMENTS.map(([value, label]) => (
                  <option key={value} value={value}>
                    {label}
                  </option>
                ))}
              </select>
            </FilterField>
            <FilterField label="Group" htmlFor="reaction-group">
              <select id="reaction-group" className={filterSelectClass} value={groupId} onChange={(e) => setGroupId(e.target.value)}>
                <option value="">All groups</option>
                {result.by_group.map((g) => (
                  <option key={g.group_id} value={g.group_id}>
                    {g.label}
                  </option>
                ))}
              </select>
            </FilterField>
          </FilterCard>
        }
        renderDetails={(node) => {
          const vn = graph?.nodes.find((n) => n.id === node.id);
          return graph && vn ? <SelectionDetail node={vn} graph={graph} result={result} projectId={projectId} /> : null;
        }}
      />

      {graph && graph.nodes.length > 0 && (
        <div className="flex flex-wrap items-center justify-between gap-3 rounded-card border border-border bg-surface px-5 py-3 shadow-card">
          <dl className="flex flex-wrap gap-x-5 gap-y-1 text-sm">
            {(
              [
                ["campaign_element", "campaign elements"],
                ["audience_group", "audience groups"],
                ["theme", "reaction themes"],
                ["reaction", "reaction categories"],
              ] as const
            ).map(([kind, label]) => (
              <div key={kind} className="flex gap-1.5">
                <dt className="font-semibold text-ink tabular-nums">{graph.nodes.filter((n) => n.kind === kind).length}</dt>
                <dd className="text-ink-secondary">{label}</dd>
              </div>
            ))}
            <div className="flex gap-1.5">
              <dt className="font-semibold text-ink tabular-nums">{graph.edges.length}</dt>
              <dd className="text-ink-secondary">connections, each from stored records</dd>
            </div>
          </dl>
          <Button variant="outline" onClick={() => download(graph, result.id)}>
            <Download aria-hidden />
            Download graph
          </Button>
        </div>
      )}
    </section>
  );
}
