# Nativeproof end-to-end tests (Playwright)

These tests drive the real frontend against the real backend. They do not start servers.

## Prerequisites

1. Backend on `E2E_API_URL` (default `http://localhost:8010`):
   `cd backend && uv run alembic upgrade head && uv run uvicorn app.main:app --port 8010`
2. Frontend on `E2E_BASE_URL` (default `http://localhost:3001`), pointed at that backend with the mock transport
   off: `NEXT_PUBLIC_API_BASE_URL=http://localhost:8010`, `NEXT_PUBLIC_API_MOCK=0`, then `npm run dev -- --port 3001`.
3. Backend `FRONTEND_ORIGINS` must include the frontend origin (CORS).
4. For the anonymous-isolation test, both sides run with Supabase auth (`AUTH_MODE=supabase` and
   `NEXT_PUBLIC_AUTH_MODE=supabase`). In dev mode every browser shares one token, so that test skips itself.

## Run

```bash
cd e2e
npm install
npx playwright install chromium
npx playwright test                      # all specs
npx playwright test tests/try-demo.spec.ts
E2E_BASE_URL=http://localhost:3001 E2E_API_URL=http://localhost:8010 npx playwright test
npx playwright show-report               # HTML report (playwright-report/); traces for failures in test-results/
```

## Specs

| Spec | Checks |
|---|---|
| `try-demo.spec.ts` | "Try the demo" creates a demo project; it survives a reload and stays listed; a second anonymous visitor cannot list or open it (Supabase mode only). |
| `demo-journey.spec.ts` | Discover → Simulate → Adapt → Compare → Prove on the seeded scenario: "Discover cultural signals", "Run campaign rehearsal" (every reaction labeled "AI-generated reaction — not a real participant response"), "Generate adaptations", "Evaluate selected versions" → "Run evaluation", "Create report", Markdown and JSON exports (the Markdown starts with the DEMO DATA banner). |
| `v2-pages.spec.ts` | Each v2 page (brand, cultural-dna, market-expansion, trend-watch, arena, risk-radar, graph) renders without page errors, keeps the DEMO DATA indicator, shows no Live label, and search reports "unavailable" when embeddings are not configured. |

Every spec fails if the "MOCK API" banner is visible: these tests are only meaningful against the real API.
A spec skips itself when the backend health check fails, so a down server is reported as skipped, not as a UI bug.
