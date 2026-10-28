import { expect, test } from "@playwright/test";

import {
  API_URL,
  AUTH_FILE,
  backendIsUp,
  bearerToken,
  createDemo,
  expectDemoLabels,
  savedDemoProject,
  sessionUserId,
  usesSupabaseSession,
} from "./helpers";

const PNG = Buffer.from("iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAYAAAAfFcSJAAAADUlEQVR42mNkYPhfDwAChwGA60e6kgAAAABJRU5ErkJggg==", "base64");

test.use({ storageState: AUTH_FILE }); // the run's one anonymous session (auth.setup.ts), in a fresh context

test.beforeEach(async ({ request }) => {
  test.skip(!(await backendIsUp(request)), "backend is not reachable (set E2E_API_URL)");
});

test("the demo session and project persist in a new context and across reloads", async ({ page }) => {
  const projectId = savedDemoProject();
  await page.goto("/projects");
  await expect(page.locator(`a[href*="${projectId}"]`).first(), "the demo project is listed").toBeVisible();
  const user = await sessionUserId(page);
  await page.goto(`/projects/${projectId}`);
  await expectDemoLabels(page);
  await page.reload();
  await expectDemoLabels(page);
  expect(await sessionUserId(page), "same anonymous user after reload").toBe(user);
});

/** Anonymous sign-in #2 of 2 per run: a second visitor in an isolated context. */
test("a second anonymous user can neither list nor open the first user's project or assets", async ({ page, browser, request }) => {
  const projectId = savedDemoProject();
  await page.goto(`/projects/${projectId}`);
  await expectDemoLabels(page);
  test.skip(!(await usesSupabaseSession(page)), "needs AUTH_MODE=supabase (dev mode shares one token for every browser)");
  const owner = { Authorization: `Bearer ${await bearerToken(page)}` };
  const uploaded = await request.post(`${API_URL}/api/v1/projects/${projectId}/assets`, {
    headers: owner,
    multipart: { kind: "image", file: { name: "creative.png", mimeType: "image/png", buffer: PNG } },
  });
  expect(uploaded.status(), "owner uploads an asset").toBe(201);
  const assetId = (await uploaded.json()).id as string;

  // Explicitly empty: Playwright applies `use` options (including storageState) to browser.newContext() too.
  const other = await browser.newContext({ storageState: { cookies: [], origins: [] } });
  try {
    const stranger = await other.newPage();
    const strangerProject = await createDemo(stranger);
    expect(strangerProject).not.toBe(projectId);
    expect(await sessionUserId(stranger), "a different anonymous user").not.toBe(await sessionUserId(page));
    await stranger.goto("/projects");
    await expect(stranger.locator(`a[href*="${strangerProject}"]`).first()).toBeVisible();
    await expect(stranger.locator(`a[href*="${projectId}"]`), "the other user's project is not listed").toHaveCount(0);
    await stranger.goto(`/projects/${projectId}`);
    await expect(stranger.getByText("Not found", { exact: true }), "the other user's project does not open").toBeVisible();
    const intruder = { Authorization: `Bearer ${await bearerToken(stranger)}` };
    for (const path of [
      `/api/v1/projects/${projectId}`,
      `/api/v1/projects/${projectId}/assets`,
      `/api/v1/assets/${assetId}`,
      `/api/v1/assets/${assetId}/content`,
    ]) {
      const response = await request.get(`${API_URL}${path}`, { headers: intruder });
      expect(response.status(), `stranger GET ${path}`).toBe(404);
    }
    const listed = await (await request.get(`${API_URL}/api/v1/projects`, { headers: intruder })).json();
    expect(listed.items.map((p: { id: string }) => p.id)).not.toContain(projectId);
  } finally {
    await other.close();
  }
});
