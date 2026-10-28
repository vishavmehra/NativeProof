import { expect, test, type Page } from "@playwright/test";

import { AUTH_FILE, backendIsUp, expectBackendCurrent, expectDemoLabels, savedDemoProject } from "./helpers";

test.use({ storageState: AUTH_FILE }); // a fresh context per test, seeded with the run's one anonymous session

/** Contract v2 feature pages (README §13) in a demo project: each renders, stays labeled, and is honest about gaps. */
const PAGES: { segment: string; expectVisible: RegExp }[] = [
  { segment: "brand", expectVisible: /read-only|demo/i },
  { segment: "cultural-dna", expectVisible: /No profile selected|Cultural DNA|profile/i },
  { segment: "market-expansion", expectVisible: /market/i },
  { segment: "trend-watch", expectVisible: /Two snapshots are needed to compare|snapshot/i },
  { segment: "arena", expectVisible: /No arena yet|Arena/i },
  { segment: "risk-radar", expectVisible: /No scan yet|Risk/i },
  { segment: "graph", expectVisible: /graph|evidence/i },
];

test.beforeEach(async ({ request }) => {
  test.skip(!(await backendIsUp(request)), "backend is not reachable (set E2E_API_URL)");
});

async function open(page: Page, segment: string): Promise<void> {
  const projectId = savedDemoProject();
  const errors: string[] = [];
  page.on("pageerror", (error) => errors.push(error.message));
  const response = await page.goto(`/projects/${projectId}/${segment}`);
  expect(response?.status(), `GET /projects/:id/${segment}`).toBeLessThan(400);
  await expectDemoLabels(page);
  expect(errors, `uncaught page errors on ${segment}`).toEqual([]);
}

test("backend serves current code: /ready and v2 list routes answer 200", async ({ page, request }) => {
  const projectId = savedDemoProject();
  await page.goto(`/projects/${projectId}`);
  await expectBackendCurrent(page, request, projectId);
});

for (const { segment, expectVisible } of PAGES) {
  test(`v2 page renders honestly: ${segment}`, async ({ page }) => {
    await open(page, segment);
    await expect(page.getByText(expectVisible).first()).toBeVisible();
    await expect(page.getByText(/Something went wrong|Unexpected Application Error/i)).toHaveCount(0);
  });
}

test("search reports unavailable instead of guessing (no embeddings configured)", async ({ page }) => {
  await open(page, "");
  const search = page.getByRole("searchbox").or(page.getByPlaceholder(/search/i)).first();
  test.skip(!(await search.isVisible().catch(() => false)), "no search box on the overview");
  await search.fill("hiking");
  await search.press("Enter");
  await expect(page.getByText(/unavailable|not configured/i).first()).toBeVisible();
});
