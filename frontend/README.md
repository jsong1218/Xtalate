# Xtalate Web UI (`frontend/`)

The Next.js (App Router) presentation layer over the `/v1` service — Part 7 of the MASTER_SPEC.
It is a **faithful presentation layer**: no scientific logic ever runs in the client (Part 1 §2).
Every piece of scientific content on screen is a rendering of a `DiscoveryReport`,
`ConversionReport`, `ValidationReport`, or job envelope served by the backend.

## Stack

- **Next.js 15 + React 18 + TypeScript** (App Router — RSC for shared-link first paint, D90)
- **Tailwind CSS 3** — the loss-communication palette (Part 7 §4) as `--cb-*` CSS custom
  properties defined once in `app/globals.css`
- **TanStack Query** over a **typed client generated from `../docs/openapi.json`** (D90) — no
  hand-written endpoint types; server state is the state (no global client store, Part 7 §5.1)
- **Vitest + Testing Library** for component/unit tests (D91); **Playwright** for e2e (D92)

## Prerequisites

Node.js ≥ 20. The typed API client (`lib/api/schema.d.ts`) is **generated, not committed** — it is
a pure function of the committed OpenAPI artifact. `npm install` regenerates it (via `postinstall`);
regenerate manually after the backend contract changes:

```bash
npm run gen:api   # openapi-typescript ../docs/openapi.json -o lib/api/schema.d.ts
```

## Commands

```bash
npm install       # install deps + generate the typed client
npm run dev       # dev server (proxies /v1/* to the backend, see next.config.mjs)
npm run typecheck # tsc --noEmit
npm run lint      # next lint (eslint)
npm run test      # vitest run (component/unit, incl. the mapping-coverage lint)
npm run build     # production build
npm run e2e       # playwright (needs a running stack; see playwright.config.ts)
```

In the compose stack (`compose.yaml`) the `frontend` service runs `npm run dev` with the API proxy
pointed at the `backend` service; open http://localhost:3000.
