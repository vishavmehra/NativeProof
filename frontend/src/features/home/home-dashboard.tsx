"use client";

import { useQuery } from "@tanstack/react-query";
import { ArrowRight, FlaskConical, Plus } from "lucide-react";
import Link from "next/link";
import { useRouter } from "next/navigation";
import { useEffect, useState, useSyncExternalStore } from "react";

import { AppShell } from "@/components/app-shell/app-shell";
import { useProjectList } from "@/components/app-shell/project-switcher";
import { WorldMap } from "@/components/data/world-map";
import { ModeBadge } from "@/components/evidence/badges";
import { Card } from "@/components/layout/page-parts";
import { EmptyState, ErrorState, LoadingState } from "@/components/states";
import { Button } from "@/components/ui/button";
import { evidenceByMarket, useResearchOverview } from "@/features/home/use-research-overview";
import { FEATURES, type FeatureKey } from "@/features/project/features";
import { ProjectForm } from "@/features/project/project-form";
import { useCreateDemoProject } from "@/features/project/projects-dashboard";
import { sectionHref } from "@/features/project/workflow";
import { api } from "@/lib/api/client";
import { unwrap } from "@/lib/api/errors";
import { getSupabase } from "@/lib/auth/supabase";
import { env } from "@/lib/env";
import { formatRelative } from "@/lib/format";
import { pickImagery } from "@/lib/imagery";
import { cn } from "@/lib/utils";

const noop = () => () => {};
function useGreeting() {
  const hour = useSyncExternalStore(noop, () => new Date().getHours(), () => null);
  if (hour === null) return "Welcome";
  return hour < 12 ? "Good morning" : hour < 18 ? "Good afternoon" : "Good evening";
}

/** Account label for the greeting (email name), when one exists. Anonymous and dev sessions get none (docs/16 §3). */
function useAccountName() {
  const [name, setName] = useState<string | null>(null);
  useEffect(() => {
    if (env.authMode !== "supabase") return;
    void getSupabase()
      .auth.getSession()
      .then(({ data }) => {
        const email = data.session?.user?.email;
        if (email) setName(email.split("@")[0]);
      });
  }, []);
  return name;
}

const CARDS: { key: FeatureKey; title: string; text: string; cta: string }[] = [
  { key: "audience", title: "Audience Intelligence", text: "Synthetic audience groups grounded in Qloo signals.", cta: "Explore audiences" },
  { key: "arena", title: "Campaign Arena", text: "Compare campaign concepts with one audience and criteria.", cta: "Test campaigns" },
  { key: "risk", title: "Risk Radar", text: "Identify cultural risks early.", cta: "View risk analysis" },
  { key: "voice", title: "Voice", text: "Adapt content for any market.", cta: "Generate variations" },
];

export function HomeDashboard() {
  const router = useRouter();
  const greeting = useGreeting();
  const name = useAccountName();
  const projects = useProjectList();
  const demo = useCreateDemoProject();
  const [creating, setCreating] = useState(false);
  const recent = [...(projects.data?.items ?? [])].sort(
    (a, b) => Date.parse(b.last_activity_at ?? b.updated_at) - Date.parse(a.last_activity_at ?? a.updated_at),
  );
  const current = recent[0] ?? null;
  const research = useResearchOverview(recent.slice(0, 6));
  const studies = useQuery({
    queryKey: ["studies-total", current?.id],
    enabled: Boolean(current),
    queryFn: async () => (await unwrap(api.GET("/api/v1/projects/{project_id}/studies", { params: { path: { project_id: current!.id }, query: { limit: 1 } } }))).total,
  });

  const discoveries = research.data?.discoveries ?? [];
  const live = evidenceByMarket(discoveries, "live");
  const mapMode: "live" | "demo" = live.length > 0 ? "live" : "demo";
  const mapData = mapMode === "live" ? live : evidenceByMarket(discoveries, "demo");
  const evidenceTotal = mapData.reduce((sum, d) => sum + d.value, 0);
  const completedRuns = research.data?.activity.filter((a) => a.run.status === "completed" || a.run.status === "partial").length;

  return (
    <AppShell current={current} homeActive crumbs={[{ label: "Home" }]}>
      <div className="space-y-8">
        {/* Greeting */}
        <header className="flex flex-wrap items-end justify-between gap-4">
          <div className="space-y-2">
            <h1 className="font-serif text-[40px] leading-[1.02] font-semibold tracking-tight text-ink sm:text-[56px]">
              {greeting}
              {name ? `, ${name}.` : "."}
            </h1>
            <p className="text-lg text-ink-body">Turn cultural intelligence into campaigns that truly resonate.</p>
          </div>
          <div className="flex flex-wrap gap-3">
            <Button size="lg" variant="outline" onClick={() => demo.mutate()} disabled={demo.isPending}>
              <FlaskConical aria-hidden />
              {demo.isPending ? "Creating demo…" : "Try the demo"}
            </Button>
            <Button size="lg" onClick={() => setCreating(true)} disabled={creating}>
              <Plus aria-hidden />
              New project
            </Button>
          </div>
        </header>
        {demo.error && <ErrorState error={demo.error} onRetry={() => demo.mutate()} />}
        {projects.error && <ErrorState error={projects.error} onRetry={() => void projects.refetch()} />}
        {creating && (
          <Card title="New project" subtitle="Creates a live project. Its runs call Qloo and the model provider.">
            <ProjectForm onCancel={() => setCreating(false)} onCreated={(p) => router.push(`/projects/${p.id}`)} />
          </Card>
        )}

        {/* Feature cards */}
        <ul className="grid grid-cols-[minmax(0,1fr)] gap-4 sm:grid-cols-2 xl:grid-cols-4">
          {CARDS.map((c) => {
            const f = FEATURES[c.key];
            const meta = c.key === "audience" && studies.data !== undefined ? `${studies.data} ${studies.data === 1 ? "study" : "studies"} in ${current?.name}` : c.text;
            return (
              <li key={c.key} className="flex flex-col gap-3 rounded-card border border-border bg-surface p-5 shadow-card">
                <span className={cn("flex size-11 items-center justify-center rounded-xl", f.tone.soft)}>
                  <f.Icon aria-hidden className={cn("size-5", f.tone.text)} />
                </span>
                <div className="space-y-1">
                  <p className="font-serif text-[20px] leading-tight font-semibold text-ink">{c.title}</p>
                  <p className="text-[14px] text-ink-secondary">{meta}</p>
                </div>
                {current ? (
                  <Link href={sectionHref(current.id, f.segment)} className="mt-auto inline-flex h-9 w-fit items-center gap-2 rounded-lg bg-primary px-3.5 text-[13.5px] font-medium text-primary-foreground hover:bg-accent-hover">
                    {c.cta}
                    <ArrowRight aria-hidden className="size-4" />
                  </Link>
                ) : (
                  <p className="mt-auto text-[13px] text-ink-secondary">Create or open a project first.</p>
                )}
              </li>
            );
          })}
        </ul>

        {/* Recent projects · map · quick stats */}
        {projects.isPending ? (
          <LoadingState label="Loading your projects…" />
        ) : projects.data && (
          <div className="grid grid-cols-[minmax(0,1fr)] gap-4 lg:grid-cols-[minmax(0,1fr)_minmax(0,1.35fr)_minmax(0,0.75fr)]">
            <Card title="Recent projects">
              {recent.length === 0 ? (
                <EmptyState title="No projects yet" description="Create a project for your brand, or try the demo on labeled fixture data." />
              ) : (
                <ul className="space-y-3">
                  {recent.slice(0, 4).map((p) => {
                    const img = pickImagery([p.brand_name, p.description, ...p.target_markets.map((m) => m.display_name)], p.id);
                    return (
                      <li key={p.id}>
                        <Link href={`/projects/${p.id}`} className="flex items-center gap-3 rounded-xl p-1.5 hover:bg-surface-muted">
                          {/* eslint-disable-next-line @next/next/no-img-element -- decorative library image */}
                          <img src={img.src} alt="" className="size-14 shrink-0 rounded-lg object-cover" />
                          <span className="min-w-0 flex-1">
                            <span className="flex items-center gap-2">
                              <span className="truncate text-[14.5px] font-semibold text-ink">{p.name}</span>
                              {p.mode === "demo" && <ModeBadge mode="demo" />}
                            </span>
                            <span className="block truncate text-[13px] text-ink-secondary">{p.description ?? p.brand_name}</span>
                            <span className="block text-xs text-ink-secondary">{formatRelative(p.last_activity_at ?? p.updated_at)}</span>
                          </span>
                        </Link>
                      </li>
                    );
                  })}
                </ul>
              )}
            </Card>

            <Card
              title="Global audience insights"
              subtitle="Evidence records from your completed discoveries, by market. Research coverage, not market potential."
              action={mapMode === "demo" && mapData.length > 0 ? <ModeBadge mode="demo" /> : undefined}
            >
              {research.isPending && recent.length > 0 ? (
                <LoadingState label="Loading research…" />
              ) : (
                <WorldMap data={mapData.map(({ country_code, value }) => ({ country_code, value }))} valueLabel="evidence records" tone="text-primary" />
              )}
            </Card>

            <Card title="Quick stats" subtitle={recent.length > 6 ? "Across your 6 most recent projects." : "Across your projects."}>
              <dl className="space-y-4">
                {[
                  ["Projects", projects.data.total],
                  ["Markets researched", research.data ? mapData.length : null],
                  ["Evidence records", research.data ? evidenceTotal : null],
                  ["Completed runs (recent)", completedRuns ?? null],
                ].map(([label, value]) => (
                  <div key={label as string} className="flex items-baseline justify-between gap-3 border-b border-border pb-3 last:border-0 last:pb-0">
                    <dt className="text-[14px] text-ink-secondary">{label}</dt>
                    <dd className="font-serif text-[26px] leading-none font-semibold text-ink tabular-nums">{value ?? "—"}</dd>
                  </div>
                ))}
              </dl>
            </Card>
          </div>
        )}
      </div>
    </AppShell>
  );
}
