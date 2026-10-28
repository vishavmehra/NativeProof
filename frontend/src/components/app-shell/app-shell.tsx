"use client";

import { useQuery, useQueryClient } from "@tanstack/react-query";
import { ArrowLeft, Bell, ChevronsUpDown, House, LoaderCircle, LogOut, Menu, Settings } from "lucide-react";
import Link from "next/link";
import { useRouter, useSearchParams, useSelectedLayoutSegment } from "next/navigation";
import { useEffect, useState, type ReactNode } from "react";

import { useProjectList } from "@/components/app-shell/project-switcher";
import { ModeBadge } from "@/components/evidence/badges";
import { EvidenceInspectorProvider } from "@/components/evidence/evidence-inspector";
import { Button } from "@/components/ui/button";
import {
  DropdownMenu,
  DropdownMenuContent,
  DropdownMenuGroup,
  DropdownMenuItem,
  DropdownMenuLabel,
  DropdownMenuSeparator,
  DropdownMenuTrigger,
} from "@/components/ui/dropdown-menu";
import { Popover, PopoverContent, PopoverTrigger } from "@/components/ui/popover";
import { Sheet, SheetContent, SheetTitle } from "@/components/ui/sheet";
import { FEATURES, FEATURE_GROUPS } from "@/features/project/features";
import { projectKeys } from "@/features/project/project-context";
import { RUN_TYPE_META, sectionHref } from "@/features/project/workflow";
import { ProjectSearch } from "@/features/search/project-search";
import { api } from "@/lib/api/client";
import { unwrap } from "@/lib/api/errors";
import { isTerminal } from "@/lib/api/runs";
import type { ProjectSummary } from "@/lib/api/types";
import { getSupabase } from "@/lib/auth/supabase";
import { env } from "@/lib/env";
import { formatRelative } from "@/lib/format";
import { pickImagery } from "@/lib/imagery";
import { cn } from "@/lib/utils";

export type Crumb = { label: string; href?: string };

/** Indigo four-petal mark + wordmark (reference logo). */
export function Logo() {
  return (
    <Link href="/projects" className="flex items-center gap-2.5 rounded-md text-ink">
      <svg aria-hidden viewBox="0 0 32 32" className="size-8 text-primary" fill="currentColor">
        <path d="M16 3c3.6 0 6 2.7 6 6.2 0 2.4-1.3 4.6-3.3 5.8 2-1.2 4.2-2.5 6.6-2.5C28.8 12.5 31 15 31 16s-2.2 3.5-5.7 3.5c-2.4 0-4.6-1.3-6.6-2.5 2 1.2 3.3 3.4 3.3 5.8C22 26.3 19.6 29 16 29s-6-2.7-6-6.2c0-2.4 1.3-4.6 3.3-5.8-2 1.2-4.2 2.5-6.6 2.5C3.2 19.5 1 17 1 16s2.2-3.5 5.7-3.5c2.4 0 4.6 1.3 6.6 2.5C11.3 13.8 10 11.6 10 9.2 10 5.7 12.4 3 16 3Z" />
      </svg>
      <span className="text-[21px] font-semibold tracking-tight">Nativeproof</span>
    </Link>
  );
}

// ---------- account ----------

function useAccount() {
  const [label, setLabel] = useState<string | null>(env.authMode === "dev" ? "Development mode" : null);
  useEffect(() => {
    if (env.authMode !== "supabase") return;
    void getSupabase()
      .auth.getSession()
      .then(({ data }) => {
        const user = data.session?.user;
        setLabel(user ? (user.is_anonymous ? "Anonymous demo session" : (user.email ?? "Signed in")) : null);
      });
  }, []);
  return label;
}

/** Account menu shared by the avatar and the sidebar Settings entry: who is signed in, and sign out. */
function AccountMenu({ trigger, side = "bottom" }: { trigger: ReactNode; side?: "bottom" | "top" }) {
  const router = useRouter();
  const queryClient = useQueryClient();
  const label = useAccount();
  async function signOut() {
    await getSupabase().auth.signOut();
    queryClient.clear();
    router.replace("/login");
  }
  return (
    <DropdownMenu>
      {trigger}
      <DropdownMenuContent side={side} align="end" className="min-w-56">
        <DropdownMenuGroup>
          <DropdownMenuLabel>{label ?? "Account"}</DropdownMenuLabel>
          {env.authMode === "dev" && <DropdownMenuItem disabled>Local development token · no sign-in</DropdownMenuItem>}
        </DropdownMenuGroup>
        {env.authMode === "supabase" && (
          <>
            <DropdownMenuSeparator />
            <DropdownMenuItem onClick={() => void signOut()}>
              <LogOut aria-hidden />
              Sign out
            </DropdownMenuItem>
          </>
        )}
      </DropdownMenuContent>
    </DropdownMenu>
  );
}

function Avatar() {
  const label = useAccount();
  const initial = label && label.includes("@") ? label[0].toUpperCase() : label?.startsWith("Anonymous") ? "A" : env.authMode === "dev" ? "D" : "·";
  return (
    <AccountMenu
      trigger={
        <DropdownMenuTrigger
          aria-label={`Account: ${label ?? "loading"}`}
          className="flex size-10 items-center justify-center rounded-full border border-border bg-surface text-sm font-semibold text-lavender-ink shadow-card"
        >
          {initial}
        </DropdownMenuTrigger>
      }
    />
  );
}

// ---------- notifications (real runs) ----------

function NotificationsBell({ projectId }: { projectId: string | null }) {
  const runs = useQuery({
    queryKey: [...projectKeys.runs(projectId ?? "none"), "bell"],
    enabled: Boolean(projectId),
    queryFn: async () =>
      (await unwrap(api.GET("/api/v1/projects/{project_id}/runs", { params: { path: { project_id: projectId! }, query: { limit: 8 } } }))).items,
    refetchInterval: (q) => (q.state.data?.some((r) => !isTerminal(r.status)) ? 5000 : false),
  });
  const active = runs.data?.filter((r) => !isTerminal(r.status)).length ?? 0;
  return (
    <Popover>
      <PopoverTrigger
        aria-label={active ? `Activity: ${active} run${active > 1 ? "s" : ""} in progress` : "Recent activity"}
        className="relative flex size-10 items-center justify-center rounded-full text-ink-body hover:bg-surface-muted"
      >
        <Bell aria-hidden className="size-5" />
        {active > 0 && <span aria-hidden className="absolute top-2 right-2.5 size-2 rounded-full bg-primary" />}
      </PopoverTrigger>
      <PopoverContent align="end" className="w-80 p-0">
        <p className="border-b border-border px-3 py-2 text-xs font-semibold text-ink">Recent activity</p>
        {!projectId ? (
          <p className="px-3 py-3 text-[13px] text-ink-secondary">Open a project to see its runs.</p>
        ) : runs.isPending ? (
          <p className="px-3 py-3 text-[13px] text-ink-secondary">Loading…</p>
        ) : !runs.data?.length ? (
          <p className="px-3 py-3 text-[13px] text-ink-secondary">No runs yet in this project.</p>
        ) : (
          <ul className="max-h-80 divide-y divide-border overflow-y-auto">
            {runs.data.map((run) => {
              const meta = RUN_TYPE_META[run.run_type];
              return (
                <li key={run.id}>
                  <Link href={sectionHref(projectId, meta.segment, run.campaign_id)} className="flex items-center gap-2 px-3 py-2 text-[13px] hover:bg-surface-muted">
                    {!isTerminal(run.status) && <LoaderCircle aria-hidden className="size-3.5 animate-spin text-info" />}
                    <span className="min-w-0 flex-1 truncate text-ink">
                      {meta.label} <span className="text-ink-secondary">{run.status}</span>
                    </span>
                    <span className="shrink-0 text-xs text-ink-secondary">{formatRelative(run.completed_at ?? run.created_at)}</span>
                  </Link>
                </li>
              );
            })}
          </ul>
        )}
      </PopoverContent>
    </Popover>
  );
}

// ---------- sidebar ----------

function ProjectCard({ current, campaignSlot }: { current: ProjectSummary | null; campaignSlot?: ReactNode }) {
  const router = useRouter();
  const { data } = useProjectList();
  if (!current) {
    return (
      <Link href="/projects" className="block rounded-card border border-border bg-surface p-3 text-[13px] text-ink-secondary shadow-card">
        No project yet. Create one from Home.
      </Link>
    );
  }
  const image = pickImagery([current.brand_name, current.description, ...current.target_markets.map((m) => m.display_name)], current.id);
  const markets = current.target_markets.length;
  return (
    <div className="space-y-2 rounded-card border border-border bg-surface p-2.5 shadow-card">
      <DropdownMenu>
        <DropdownMenuTrigger className="flex w-full items-center gap-2.5 rounded-lg text-left" aria-label={`Project: ${current.name}. Switch project`}>
          {/* eslint-disable-next-line @next/next/no-img-element -- decorative library image */}
          <img src={image.src} alt="" className="size-10 shrink-0 rounded-lg object-cover" />
          <span className="min-w-0 flex-1">
            <span className="block truncate text-[13px] font-semibold text-ink">{current.name}</span>
            <span className="block truncate text-xs text-ink-secondary">
              {markets ? `${markets} market${markets > 1 ? "s" : ""}` : "No markets set"}
              {current.mode === "demo" && " · Demo"}
            </span>
          </span>
          <ChevronsUpDown aria-hidden className="size-4 shrink-0 text-ink-secondary" />
        </DropdownMenuTrigger>
        <DropdownMenuContent side="top" className="w-64">
          <DropdownMenuGroup>
            <DropdownMenuLabel>Your projects</DropdownMenuLabel>
            {data?.items.map((p) => (
              <DropdownMenuItem key={p.id} onClick={() => router.push(`/projects/${p.id}`)} className="gap-2">
                <span className="min-w-0 flex-1 truncate">{p.name}</span>
                {p.mode === "demo" && <ModeBadge mode="demo" />}
              </DropdownMenuItem>
            ))}
          </DropdownMenuGroup>
          <DropdownMenuSeparator />
          <DropdownMenuItem onClick={() => router.push(`/projects/${current.id}`)}>Open project overview</DropdownMenuItem>
          <DropdownMenuItem onClick={() => router.push("/projects")}>All projects</DropdownMenuItem>
        </DropdownMenuContent>
      </DropdownMenu>
      {campaignSlot}
    </div>
  );
}

function SidebarContent({
  current,
  homeActive,
  onNavigate,
  campaignSlot,
}: {
  current: ProjectSummary | null;
  homeActive?: boolean;
  onNavigate?: () => void;
  campaignSlot?: ReactNode;
}) {
  const segment = useSelectedLayoutSegment();
  const campaignId = useSearchParams().get("campaign");
  const item = "flex items-center gap-3 rounded-xl px-3 py-2 text-[14.5px] text-ink-body transition-colors hover:bg-surface-muted";
  const activeItem = "bg-lavender font-medium text-lavender-ink hover:bg-lavender";
  return (
    <div className="flex h-full flex-col">
      <div className="px-5 pt-6 pb-6">
        <Logo />
      </div>
      <nav aria-label="Main" className="flex-1 space-y-5 overflow-y-auto px-3 pb-4">
        <Link href="/projects" onClick={onNavigate} aria-current={homeActive ? "page" : undefined} className={cn(item, homeActive && activeItem)}>
          <House aria-hidden className={cn("size-[18px]", homeActive ? "text-lavender-ink" : "text-ink-secondary")} />
          Home
        </Link>
        {FEATURE_GROUPS.map((g) => (
          <div key={g.group}>
            <p className="px-3 pb-2 text-[11px] font-semibold tracking-[0.12em] text-ink uppercase">{g.label}</p>
            <ul className="space-y-0.5">
              {g.keys.map((key) => {
                const f = FEATURES[key];
                const active = !homeActive && Boolean(current) && segment === f.segment;
                return (
                  <li key={key}>
                    {current ? (
                      <Link
                        href={sectionHref(current.id, f.segment, campaignId)}
                        onClick={onNavigate}
                        aria-current={active ? "page" : undefined}
                        className={cn(item, active && activeItem)}
                      >
                        <f.Icon aria-hidden className={cn("size-[18px]", f.tone.text)} />
                        {f.label}
                      </Link>
                    ) : (
                      <span aria-disabled className={cn(item, "cursor-not-allowed opacity-60 hover:bg-transparent")} title="Create or open a project first">
                        <f.Icon aria-hidden className={cn("size-[18px]", f.tone.text)} />
                        {f.label}
                      </span>
                    )}
                  </li>
                );
              })}
            </ul>
          </div>
        ))}
      </nav>
      <div className="space-y-2 px-3 pb-4">
        <ProjectCard current={current} campaignSlot={campaignSlot} />
        <AccountMenu
          side="top"
          trigger={
            <DropdownMenuTrigger className={cn(item, "w-full")}>
              <Settings aria-hidden className="size-[18px] text-ink-secondary" />
              Settings
            </DropdownMenuTrigger>
          }
        />
      </div>
    </div>
  );
}

// ---------- top bar ----------

function TopBar({ crumbs, projectId, campaignId, onOpenNav, badge }: { crumbs: Crumb[]; projectId: string | null; campaignId?: string | null; onOpenNav(): void; badge?: ReactNode }) {
  const parent = [...crumbs].reverse().find((c, i) => i > 0 && c.href) ?? crumbs.find((c) => c.href);
  return (
    <header className="sticky top-0 z-20 bg-canvas/95 supports-backdrop-filter:backdrop-blur-sm">
      <div className="mx-auto flex h-16 w-full max-w-[1280px] items-center gap-3 px-4 sm:px-6 lg:h-[72px] lg:px-10">
        <Button variant="ghost" size="icon-sm" className="lg:hidden" onClick={onOpenNav} aria-label="Open navigation">
          <Menu aria-hidden />
        </Button>
        {parent?.href && (
          <Link href={parent.href} aria-label={`Back to ${parent.label}`} className="hidden rounded-md p-1 text-ink-body hover:bg-surface-muted sm:block">
            <ArrowLeft aria-hidden className="size-5" />
          </Link>
        )}
        <nav aria-label="Breadcrumb" className="min-w-0 flex-1">
          <ol className="flex min-w-0 items-center gap-2 text-[14.5px]">
            {crumbs.map((c, i) => {
              const last = i === crumbs.length - 1;
              return (
                <li key={`${c.label}-${i}`} className={cn("flex min-w-0 items-center gap-2", !last && "hidden md:flex")}>
                  {c.href && !last ? (
                    <Link href={c.href} className="truncate text-ink-body hover:text-ink">
                      {c.label}
                    </Link>
                  ) : (
                    <span className={cn("truncate", last ? "font-medium text-ink" : "text-ink-body")} aria-current={last ? "page" : undefined}>
                      {c.label}
                    </span>
                  )}
                  {!last && <span aria-hidden className="text-ink-secondary">/</span>}
                </li>
              );
            })}
          </ol>
        </nav>
        {badge}
        <div className="hidden lg:block">{projectId && <ProjectSearch projectId={projectId} campaignId={campaignId} />}</div>
        <NotificationsBell projectId={projectId} />
        <Avatar />
      </div>
    </header>
  );
}

/**
 * Reference app frame (docs/16 §1): ivory sidebar with grouped, colored feature links, and a top bar with breadcrumb,
 * search (Ctrl K), activity bell, and account avatar. Used by Home (/projects) and the project workspace.
 */
export function AppShell({
  current,
  homeActive,
  crumbs,
  campaignId,
  campaignSlot,
  badge,
  children,
}: {
  /** The project the sidebar links into (the open project, or the most recent one on Home). */
  current: ProjectSummary | null;
  /** True on the Home page (/projects). */
  homeActive?: boolean;
  crumbs: Crumb[];
  campaignId?: string | null;
  /** Campaign switcher shown in the project card. */
  campaignSlot?: ReactNode;
  /** Extra marker in the top bar, e.g. the DEMO DATA badge. */
  badge?: ReactNode;
  children: ReactNode;
}) {
  const [navOpen, setNavOpen] = useState(false);
  return (
    // The inspector lives here (not in a page layout) because the top-bar search opens it on every page, Home included.
    <EvidenceInspectorProvider>
    <div className="min-h-dvh bg-canvas">
      <a href="#main" className="sr-only focus:not-sr-only focus:fixed focus:top-2 focus:left-2 focus:z-50 focus:rounded-md focus:bg-surface focus:px-3 focus:py-2 focus:text-sm focus:shadow">
        Skip to content
      </a>
      <aside className="fixed top-0 bottom-[var(--mock-offset,0px)] left-0 z-30 hidden w-[256px] border-r border-sidebar-border bg-sidebar lg:block">
        <SidebarContent current={current} homeActive={homeActive} campaignSlot={campaignSlot} />
      </aside>
      <Sheet open={navOpen} onOpenChange={setNavOpen}>
        <SheetContent side="left" className="w-[280px] gap-0 bg-sidebar p-0 data-[side=left]:w-[280px]">
          <SheetTitle className="sr-only">Navigation</SheetTitle>
          <SidebarContent current={current} homeActive={homeActive} campaignSlot={campaignSlot} onNavigate={() => setNavOpen(false)} />
        </SheetContent>
      </Sheet>
      <div className="lg:pl-[256px]">
        <TopBar crumbs={crumbs} projectId={current?.id ?? null} campaignId={campaignId} onOpenNav={() => setNavOpen(true)} badge={badge} />
        <main id="main" className="mx-auto w-full max-w-[1280px] px-4 pt-2 pb-12 sm:px-6 lg:px-10">
          {children}
        </main>
      </div>
    </div>
    </EvidenceInspectorProvider>
  );
}
