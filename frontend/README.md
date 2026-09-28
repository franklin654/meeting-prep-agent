# frontend

React + Vite + TypeScript, Tailwind CSS, shadcn/ui, React Router and
TanStack Query. See `docs/technical-design.md` (Frontend section) for the
page/route map and styling rules.

## Commands

```bash
npm install
npm run dev          # http://localhost:5173, proxies /api to http://localhost:8000
npm run build         # tsc -b && vite build
npm run lint          # eslint .
npx tsc --noEmit
npm test              # vitest run
npm run gen:api       # regenerate src/api/schema.d.ts from /openapi.json
```

`gen:api` requires the backend to be running (`OPENAPI_URL`, default
`http://localhost:8000/openapi.json`); if it isn't reachable, it writes a
stub `src/api/schema.d.ts` and exits 0 instead of failing.

## Structure

```text
src/
├─ pages/        # Dashboard (/), Brief (/meetings/:id), ContactTimeline (/contacts/:id)
├─ components/   # shared layout + shadcn/ui primitives (components/ui)
├─ api/          # typed client generated from OpenAPI (schema.d.ts is generated, do not hand-edit)
└─ lib/          # cross-cutting helpers (query client, etc.)
```
