import fs from "node:fs";
import path from "node:path";

import { expect, type APIRequestContext, type Page } from "@playwright/test";

/** One anonymous demo session per run (auth.setup.ts), reused by fresh per-test contexts: keeps Supabase
 *  anonymous sign-ups under the project's rate limit. Holds session cookies: gitignored, never commit. */
export const AUTH_FILE = path.join(__dirname, "..", ".auth", "demo-session.json");
const DEMO_FILE = path.join(__dirname, "..", ".auth", "demo-project.json");

export function saveDemoProject(projectId: string): void {
  fs.mkdirSync(path.dirname(DEMO_FILE), { recursive: true });
  fs.writeFileSync(DEMO_FILE, JSON.stringify({ projectId }));
}

export function savedDemoProject(): string {
  return (JSON.parse(fs.readFileSync(DEMO_FILE, "utf8")) as { projectId: string }).projectId;
}

/** Backend used by the frontend under test; only probed so a down server is reported, not mistaken for a UI bug. */
export const API_URL = process.env.E2E_API_URL ?? "http://localhost:8010";
export const UUID = "[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}";
export const SYNTHETIC_LABEL = "AI-generated reaction, not a real participant";
const RUN_TIMEOUT = 120_000;

export async function backendIsUp(request: APIRequestContext): Promise<boolean> {
  try {
    const response = await request.get(`${API_URL}/health`, { timeout: 5_000 });
    return response.ok() && (await response.json()).status === "ok";
  } catch {
    return false;
  }
}

/** The run must hit the real API: the mock transport is for UI development only (README §5). */
export async function expectRealApi(page: Page): Promise<void> {
  await expect(page.getByText("MOCK API", { exact: true }), "frontend is on the mock transport (NEXT_PUBLIC_API_MOCK=1)").toHaveCount(0);
}

/** DEMO DATA is persistent in demo projects and no Live label appears (docs/08 §12.4). */
export async function expectDemoLabels(page: Page): Promise<void> {
  await expect(page.getByText("DEMO DATA", { exact: true }).first()).toBeVisible();
  await expect(page.getByText("Live", { exact: true }), "a Live label in a demo project").toHaveCount(0);
  await expectRealApi(page);
}

export async function createDemo(page: Page): Promise<string> {
  await page.goto("/projects");
  await expectRealApi(page);
  await page.getByRole("button", { name: "Try the demo" }).click();
  await page.waitForURL(new RegExp(`/projects/${UUID}`), { timeout: 60_000 });
  const id = new RegExp(`/projects/(${UUID})`).exec(page.url())?.[1];
  expect(id, "project id in URL").toBeTruthy();
  await expectDemoLabels(page);
  return id as string;
}

/** The Supabase session the frontend stored: @supabase/ssr keeps it in (possibly chunked, base64-) cookies. */
export async function supabaseAccessToken(page: Page): Promise<string | null> {
  const cookies = (await page.context().cookies())
    .filter((c) => c.name.startsWith("sb-") && /-auth-token(\.\d+)?$/.test(c.name))
    .sort((a, b) => a.name.localeCompare(b.name, undefined, { numeric: true }));
  let raw = cookies.map((c) => c.value).join("");
  if (!raw) {
    raw = await page.evaluate(() => {
      const key = Object.keys(localStorage).find((k) => k.startsWith("sb-") && k.endsWith("-auth-token"));
      return key ? (localStorage.getItem(key) ?? "") : "";
    });
  }
  if (!raw) return null;
  const json = raw.startsWith("base64-") ? Buffer.from(raw.slice(7), "base64").toString("utf8") : decodeURIComponent(raw);
  const session = JSON.parse(json) as { access_token?: string; currentSession?: { access_token?: string } };
  return session.access_token ?? session.currentSession?.access_token ?? null;
}

/** True when the browser holds a Supabase session (AUTH_MODE=supabase); dev mode shares one token for everyone. */
export async function usesSupabaseSession(page: Page): Promise<boolean> {
  return (await supabaseAccessToken(page)) !== null;
}

export async function clickWhenVisible(page: Page, name: string | RegExp): Promise<boolean> {
  const button = page.getByRole("button", { name }).first();
  if (await button.isVisible().catch(() => false)) {
    await button.click();
    return true;
  }
  return false;
}

/** Click a primary action, opening its form first when the page shows an opener button instead. */
export async function startAction(page: Page, action: string, opener?: string): Promise<void> {
  const button = page.getByRole("button", { name: action }).first();
  const either = opener ? button.or(page.getByRole("button", { name: opener }).first()) : button;
  await expect(either.first(), `"${action}" or its opener`).toBeVisible({ timeout: 30_000 });
  if (!(await button.isVisible()) && opener) {
    await page.getByRole("button", { name: opener }).first().click();
  }
  await expect(button).toBeEnabled({ timeout: 30_000 });
  await button.click();
}

export const runTimeout = { timeout: RUN_TIMEOUT };

/** The browser's Supabase access token (AUTH_MODE=supabase), or the dev token in dev mode. */
export async function bearerToken(page: Page): Promise<string> {
  return (await supabaseAccessToken(page)) ?? "dev-local";
}

/** The signed-in user id (JWT `sub`), or null in dev mode where there is no Supabase session. */
export async function sessionUserId(page: Page): Promise<string | null> {
  const token = await bearerToken(page);
  if (!token.includes(".")) return null;
  const payload = token.split(".")[1].replace(/-/g, "+").replace(/_/g, "/");
  return (JSON.parse(Buffer.from(payload, "base64").toString("utf8")) as { sub?: string }).sub ?? null;
}

/** Catch a backend serving stale code (the 2026-10-26 reload hang): /ready and a v2 list route answer 200, not 500. */
export async function expectBackendCurrent(page: Page, request: APIRequestContext, projectId: string): Promise<void> {
  const ready = await request.get(`${API_URL}/ready`);
  expect(ready.status(), "/ready").toBe(200);
  const headers = { Authorization: `Bearer ${await bearerToken(page)}` };
  for (const path of [`/api/v1/projects/${projectId}/snapshots`, `/api/v1/projects/${projectId}/evidence-graph`]) {
    const response = await request.get(`${API_URL}${path}`, { headers });
    expect(response.status(), `GET ${path}`).toBe(200);
  }
}
