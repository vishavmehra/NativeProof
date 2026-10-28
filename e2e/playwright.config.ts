import { defineConfig, devices } from "@playwright/test";

/** Frontend under test (the dev server). The backend URL is only used for a preflight health check. */
const baseURL = process.env.E2E_BASE_URL ?? "http://localhost:3001";

export default defineConfig({
  testDir: "./tests",
  timeout: 180_000,
  expect: { timeout: 45_000 },
  fullyParallel: false,
  workers: 1, // the journey is stateful; one browser at a time keeps runs within MAX_ACTIVE_RUNS_PER_USER
  retries: 0,
  reporter: [["list"], ["html", { open: "never", outputFolder: "playwright-report" }]],
  use: { baseURL, trace: "retain-on-failure", screenshot: "only-on-failure", video: "off" },
  projects: [
    { name: "setup", testMatch: /auth\.setup\.ts/ },
    { name: "chromium", use: { ...devices["Desktop Chrome"] }, dependencies: ["setup"], testIgnore: /auth\.setup\.ts/ },
  ],
});
