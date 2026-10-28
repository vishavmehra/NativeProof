# Nativeproof frontend

Next.js 16 (App Router, Cache Components), React 19, TypeScript, Tailwind v4, shadcn/ui on Base UI, TanStack Query,
and openapi-fetch. API types are generated from `../contracts/openapi.json`.

## Run

```bash
cp .env.example .env.local   # then fill in the values
npm run dev -- -p 3001       # port 3000 is often taken on the shared dev machine
npm run typecheck && npm run lint && npm run build
npm run gen:api              # after the contract changes
```

## Configuration (`.env.local`, browser-safe values only)

| Variable | Meaning |
|---|---|
| `NEXT_PUBLIC_API_BASE_URL` | Backend origin, for example `http://localhost:8010` |
| `NEXT_PUBLIC_AUTH_MODE` | `supabase`: email/password sign-in or anonymous "Try the demo". `dev`: the local development token, with no sign-in. |
| `NEXT_PUBLIC_SUPABASE_URL`, `NEXT_PUBLIC_SUPABASE_PUBLISHABLE_KEY` | Supabase project. The publishable key is browser-safe. |
| `NEXT_PUBLIC_API_MOCK` | `1` serves `contracts/fixtures` through the development mock transport, which shows a MOCK API banner. It is ignored in production builds, and the v1 routes are the only ones served. |

## Structure

- `src/app/`: routes. `/` is the landing page, `/login` the sign-in page, `/projects` the home dashboard, and
  `/projects/[projectId]/*` the workspace.
- `src/components/`: the shell, evidence badges and inspector, states, forms, the world map, and ui primitives.
- `src/features/`: feature modules. The feature registry (labels, routes, accents) is in `features/project/features.tsx`.
- Design system: `src/app/globals.css` holds the tokens; the reference is `docs/08_UI_UX_SPEC.md` §3–4.

## Imagery and sources

The UI currently uses **no photography**, only a typographic treatment. The Artlist account available during the
build was a free trial: two one-time image generations, and no download rights on a no-credit plan. Generated images
could not be properly licensed, so none are used.

To add decorative imagery later:

1. Use it only on the landing hero, the dashboard banner, or feature cards. Never use it in evidence or result views,
   and never pair it with a metric.
2. Avoid stereotyped depictions of people or cultures. Prefer place, landscape, or craft imagery.
3. Save files under `public/images/` and record each one here: file, source or generator, license, and date.

| File | Source | License | Date |
|---|---|---|---|
| _(none)_ | | | |

Map data: `world-atlas` (Natural Earth 1:110m, public domain), rendered with `d3-geo` and `topojson-client`.
