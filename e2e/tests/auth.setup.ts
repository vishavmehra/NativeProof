import { expect, test as setup } from "@playwright/test";

import { AUTH_FILE, backendIsUp, createDemo, expectDemoLabels, saveDemoProject, sessionUserId } from "./helpers";

/**
 * Anonymous sign-in #1 of 2 per run (the isolation spec adds the second). "Try the demo" signs in anonymously and
 * seeds a demo project; the session must survive a reload. Every other spec reuses this stored session in its own
 * fresh browser context, which keeps the run under Supabase's per-IP anonymous sign-in limit.
 */
setup("Try the demo: anonymous session and seeded project", async ({ page, request }) => {
  setup.skip(!(await backendIsUp(request)), "backend is not reachable (set E2E_API_URL)");
  const projectId = await createDemo(page);
  const user = await sessionUserId(page);
  await page.reload();
  expect(await sessionUserId(page), "the anonymous session survives a reload").toBe(user);
  await expectDemoLabels(page);
  saveDemoProject(projectId);
  await page.context().storageState({ path: AUTH_FILE });
});
