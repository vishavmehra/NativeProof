import { expect, test } from "@playwright/test";

import {
  AUTH_FILE,
  SYNTHETIC_LABEL,
  backendIsUp,
  expectBackendCurrent,
  expectDemoLabels,
  runTimeout,
  savedDemoProject,
  startAction,
} from "./helpers";

test.use({ storageState: AUTH_FILE }); // fresh context seeded with the run's anonymous session

test.beforeEach(async ({ request }) => {
  test.skip(!(await backendIsUp(request)), "backend is not reachable (set E2E_API_URL)");
});

/** MVP journey (docs/01 §15): Discover → Simulate → Adapt → Compare → Prove, on the seeded demo scenario. */
test("demo journey through the UI", async ({ page, request }) => {
  test.setTimeout(600_000); // five demo runs against remote Supabase Postgres take minutes, not seconds
  const id = savedDemoProject();
  await page.goto(`/projects/${id}`);
  await expectDemoLabels(page);
  await expectBackendCurrent(page, request, id);

  await page.goto(`/projects/${id}/atlas`);
  await startAction(page, "Discover cultural signals");
  await expect(page.getByRole("heading", { name: "Discovery results" })).toBeVisible(runTimeout);
  await expect(page.getByText("Missing record"), "every referenced evidence id resolves").toHaveCount(0);
  await page.getByRole("list", { name: /^Evidence for / }).getByRole("button").first().click();
  await expect(page.getByText("Fixture", { exact: true }).first(), "the inspector shows the Fixture retrieval badge").toBeVisible();
  await page.keyboard.press("Escape");
  await expectDemoLabels(page);

  await page.goto(`/projects/${id}/audience`);
  await startAction(page, "Run campaign rehearsal");
  await expect(page.getByText(SYNTHETIC_LABEL).first(), "every reaction is labeled synthetic").toBeVisible(runTimeout);
  await expectDemoLabels(page);

  await page.goto(`/projects/${id}/voice`);
  await startAction(page, "Generate adaptations", "New adaptations");
  await expect(page.getByRole("heading", { name: /Candidate variants \(3\)/ }), "demo honors variant_count up to 3").toBeVisible(runTimeout);
  const selectors = page.getByRole("checkbox", { name: "Select for evaluation" });
  for (let i = 0; i < (await selectors.count()); i += 1) await selectors.nth(i).check();
  const evaluate = page.getByRole("button", { name: "Evaluate selected versions" });
  await expect(evaluate, "selection enables evaluation; selection is not approval").toBeEnabled();
  await evaluate.click();
  await page.waitForURL(/\/loop/, { timeout: 30_000 });
  await startAction(page, "Run evaluation", "New evaluation");
  await expect(
    page.getByText(/Accept for next review|Validate with real users|Revise|Inconclusive/).first(),
    "a recommendation with its documented label",
  ).toBeVisible(runTimeout);
  await expectDemoLabels(page);

  await page.goto(`/projects/${id}/proof`);
  await startAction(page, "Create report");
  await expect(page.getByText("Fixture", { exact: true }).first(), "the evidence register labels fixture evidence").toBeVisible(runTimeout);
  for (const format of ["Export Markdown", "Export JSON"]) {
    const button = page.getByRole("button", { name: format });
    await expect(button).toBeVisible(runTimeout);
    const [download] = await Promise.all([page.waitForEvent("download"), button.click()]);
    expect(download.suggestedFilename(), `${format} downloads a file`).toMatch(format.endsWith("Markdown") ? /\.md$/ : /\.json$/);
    if (format === "Export Markdown") {
      const text = await (await download.createReadStream()).toArray().then((chunks) => Buffer.concat(chunks).toString("utf8"));
      expect(text.trimStart().split("\n").slice(0, 3).join("\n"), "demo exports start with the banner (C4)").toContain(
        "DEMO DATA: fixture results, not live research",
      );
    }
  }
  await expectDemoLabels(page);

  // Reload persistence: the report and earlier results come back from the server, in the same session.
  await page.reload();
  await expect(page.getByRole("button", { name: "Export Markdown" }), "the report survives a reload").toBeVisible(runTimeout);
  await expectDemoLabels(page);
  await page.goto(`/projects/${id}/atlas`);
  await expect(page.getByRole("heading", { name: "Discovery results" }), "the discovery survives a reload").toBeVisible(runTimeout);
  await page.goto(`/projects/${id}/audience`);
  await expect(page.getByText(SYNTHETIC_LABEL).first(), "the rehearsal survives a reload").toBeVisible(runTimeout);
});
