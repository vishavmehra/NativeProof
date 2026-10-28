/**
 * Development-only mock transport (NEXT_PUBLIC_API_MOCK=1, never in production builds).
 * Serves contracts/fixtures (copied into ./fixtures by `npm run gen:api`). Every fixture is
 * labeled demo data; the app shell shows a "MOCK API" banner whenever this transport is active.
 * Fixture ids are fixed, so requested ids are ignored except where noted.
 */
import type { Run, RunType } from "./types";

type Handler = (match: RegExpMatchArray, url: URL) => Promise<Response>;

const json = (body: unknown, status = 200) =>
  new Response(JSON.stringify(body), {
    status,
    headers: { "Content-Type": "application/json", "X-Request-ID": "mock" },
  });

async function load<T = unknown>(name: string): Promise<T> {
  return (await import(`./fixtures/${name}.json`)).default as T;
}

const fixture = (name: string, status = 200) => async () => json(await load(name), status);

async function fromPage(page: string, id: string) {
  const { items } = await load<{ items: { id: string }[] }>(page);
  return json(items.find((item) => item.id === id) ?? items[0]);
}

const RUNNING_STAGE: Record<RunType, string> = {
  market_discovery: "retrieving_affinities",
  campaign_rehearsal: "generating_reactions",
  campaign_adaptation: "generating_adaptations",
  campaign_evaluation: "assessing_candidates",
  cultural_profile: "synthesizing_profile",
  campaign_arena: "generating_reactions",
  risk_scan: "assessing_risks",
  market_comparison: "comparing_markets",
  population_study: "running_interviews",
  social_simulation: "simulating_rounds",
};
const firstPolled = new Map<string, number>();

async function accept(runType: RunType) {
  const { items } = await load<{ items: Run[] }>("RunPage");
  const run = items.find((item) => item.run_type === runType)!;
  firstPolled.delete(run.id);
  return json({ run_id: run.id, status: "queued", run_type: runType, status_url: `/api/v1/runs/${run.id}` }, 202);
}

// A run reports "running" for its first ~2.5 s of polling, then its completed fixture.
async function runStatus(id: string) {
  const { items } = await load<{ items: Run[] }>("RunPage");
  const run = items.find((item) => item.id === id) ?? items[0];
  const since = firstPolled.get(id) ?? Date.now();
  firstPolled.set(id, since);
  if (Date.now() - since > 2500) return json(run);
  return json({
    ...run,
    status: "running",
    result: null,
    completed_at: null,
    progress: { stage: RUNNING_STAGE[run.run_type], completed_steps: 2, total_steps: 4, message: "Running (mock fixtures)." },
  });
}

async function exportReport(url: URL) {
  const report = await load<{ title: string }>("Report");
  if (url.searchParams.get("format") === "json") return json(report);
  return new Response(`# ${report.title}\n\n> Mock export of demo fixture data.\n`, {
    headers: { "Content-Type": "text/markdown" },
  });
}

const ID = "[^/]+";
const routes: [string, RegExp, Handler][] = [
  ["GET", /^\/health$/, async () => json({ status: "ok" })],
  ["GET", /^\/ready$/, fixture("Readiness")],
  ["GET", /^\/api\/v1\/projects$/, fixture("ProjectPage")],
  ["POST", /^\/api\/v1\/projects(\/demo)?$/, fixture("Project", 201)],
  ["GET", new RegExp(`^/api/v1/projects/${ID}$`), fixture("Project")],
  ["PATCH", new RegExp(`^/api/v1/projects/${ID}$`), fixture("Project")],
  ["DELETE", new RegExp(`^/api/v1/projects/${ID}$`), async () => new Response(null, { status: 204 })],
  ["GET", new RegExp(`^/api/v1/projects/${ID}/campaigns$`), fixture("CampaignPage")],
  ["POST", new RegExp(`^/api/v1/projects/${ID}/campaigns$`), fixture("Campaign", 201)],
  ["GET", new RegExp(`^/api/v1/campaigns/${ID}$`), fixture("Campaign")],
  ["PATCH", new RegExp(`^/api/v1/campaigns/${ID}$`), fixture("Campaign")],
  ["POST", new RegExp(`^/api/v1/projects/${ID}/discoveries$`), () => accept("market_discovery")],
  ["GET", new RegExp(`^/api/v1/projects/${ID}/discoveries/${ID}$`), fixture("DiscoveryResult")],
  ["GET", new RegExp(`^/api/v1/projects/${ID}/studies$`), fixture("StudyPage")],
  ["POST", new RegExp(`^/api/v1/projects/${ID}/studies$`), fixture("Study", 201)],
  ["GET", new RegExp(`^/api/v1/studies/${ID}$`), fixture("Study")],
  ["POST", new RegExp(`^/api/v1/studies/${ID}/rehearsals$`), () => accept("campaign_rehearsal")],
  ["GET", new RegExp(`^/api/v1/studies/${ID}/rehearsals/${ID}$`), fixture("RehearsalResult")],
  ["POST", new RegExp(`^/api/v1/campaigns/${ID}/adaptations$`), () => accept("campaign_adaptation")],
  ["GET", new RegExp(`^/api/v1/campaigns/${ID}/adaptations$`), fixture("AdaptationPage")],
  ["GET", new RegExp(`^/api/v1/adaptations/(${ID})$`), (m) => fromPage("AdaptationPage", m[1])],
  ["POST", new RegExp(`^/api/v1/adaptations/${ID}/revisions$`), fixture("Adaptation", 201)],
  ["POST", new RegExp(`^/api/v1/campaigns/${ID}/evaluations$`), () => accept("campaign_evaluation")],
  ["GET", new RegExp(`^/api/v1/campaigns/${ID}/evaluations/${ID}$`), fixture("EvaluationResult")],
  ["GET", new RegExp(`^/api/v1/projects/${ID}/evidence$`), fixture("EvidencePage")],
  ["GET", new RegExp(`^/api/v1/evidence/(${ID})$`), (m) => fromPage("EvidencePage", m[1])],
  ["GET", new RegExp(`^/api/v1/projects/${ID}/reports$`), fixture("ReportPage")],
  ["POST", new RegExp(`^/api/v1/projects/${ID}/reports$`), fixture("Report", 201)],
  ["GET", new RegExp(`^/api/v1/reports/${ID}/export$`), (_m, url) => exportReport(url)],
  ["GET", new RegExp(`^/api/v1/reports/${ID}$`), fixture("Report")],
  ["GET", new RegExp(`^/api/v1/runs/(${ID})$`), (m) => runStatus(m[1])],
  ["GET", new RegExp(`^/api/v1/projects/${ID}/runs$`), fixture("RunPage")],
];

export async function mockFetch(request: Request): Promise<Response> {
  await new Promise((resolve) => setTimeout(resolve, 250));
  const url = new URL(request.url);
  for (const [method, pattern, handler] of routes) {
    const match = url.pathname.match(pattern);
    if (match && request.method === method) return handler(match, url);
  }
  return json(
    {
      error: {
        code: "NOT_FOUND",
        message: `No mock fixture for ${request.method} ${url.pathname}.`,
        details: [],
        request_id: "mock",
      },
    },
    404,
  );
}
