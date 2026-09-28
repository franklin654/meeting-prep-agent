// Regenerates src/api/schema.d.ts from the backend's OpenAPI document.
//
// Per docs/technical-design.md ("API client: Generated from /openapi.json")
// and AGENTS.md ("Use the generated API client; never hand-write API types"),
// this is the only script that may write src/api/schema.d.ts.
//
// During early development the backend (T13/T15) may not exist yet or may
// not be running. In that case this script does NOT fail the command; it
// writes a stub schema.d.ts and exits 0, so `npm run gen:api` is always safe
// to wire into scripts before the backend is up.
import { mkdir, writeFile } from 'node:fs/promises'
import path from 'node:path'
import { fileURLToPath } from 'node:url'
import openapiTS, { astToString } from 'openapi-typescript'

const __dirname = path.dirname(fileURLToPath(import.meta.url))
const OUT_FILE = path.resolve(__dirname, '../src/api/schema.d.ts')
const OPENAPI_URL = process.env.OPENAPI_URL ?? 'http://localhost:8000/openapi.json'

const STUB = `/**
 * STUB — no backend was reachable at ${OPENAPI_URL} when \`npm run gen:api\` last ran.
 * This file is placeholder types only; do not hand-edit. Start the backend
 * (\`docker compose up\` or \`uv run uvicorn app.main:app\`) and re-run
 * \`npm run gen:api\` to generate the real client types from /openapi.json.
 */
export interface paths {}
export interface components {
  schemas: Record<string, never>
}
`

async function main() {
  await mkdir(path.dirname(OUT_FILE), { recursive: true })

  let openapiDocument
  try {
    const res = await fetch(OPENAPI_URL)
    if (!res.ok) {
      throw new Error(`${res.status} ${res.statusText}`)
    }
    openapiDocument = await res.json()
  } catch (err) {
    console.warn(
      `[gen:api] Could not fetch ${OPENAPI_URL} (${err.message}). ` +
        'Writing a stub src/api/schema.d.ts instead — this is expected before the backend exists.',
    )
    await writeFile(OUT_FILE, STUB)
    return
  }

  const ast = await openapiTS(openapiDocument)
  const contents = astToString(ast)
  await writeFile(OUT_FILE, contents)
  console.log(`[gen:api] Wrote ${path.relative(process.cwd(), OUT_FILE)} from ${OPENAPI_URL}`)
}

main().catch((err) => {
  console.error('[gen:api] Unexpected failure:', err)
  process.exitCode = 1
})
