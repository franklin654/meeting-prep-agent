// Regenerates src/api/schema.d.ts from the backend's OpenAPI document.
//
// Per docs/technical-design.md ("API client: Generated from /openapi.json")
// and AGENTS.md ("Use the generated API client; never hand-write API types"),
// this is the only script that may write src/api/schema.d.ts.
//
// Fails (exit 1) and leaves the existing schema.d.ts untouched when the
// backend is unreachable or the document has no paths. Never writes a stub.
import { mkdir, writeFile } from 'node:fs/promises'
import path from 'node:path'
import { fileURLToPath } from 'node:url'
import openapiTS, { astToString } from 'openapi-typescript'

const __dirname = path.dirname(fileURLToPath(import.meta.url))
const OUT_FILE = path.resolve(__dirname, '../src/api/schema.d.ts')
const OPENAPI_URL = process.env.OPENAPI_URL ?? 'http://localhost:8000/openapi.json'

function fail(message) {
  console.error(`[gen:api] ${message}`)
  process.exit(1)
}

async function main() {
  let doc
  try {
    const res = await fetch(OPENAPI_URL)
    if (!res.ok) fail(`GET ${OPENAPI_URL} returned ${res.status} ${res.statusText}`)
    doc = await res.json()
  } catch (err) {
    fail(`Could not fetch ${OPENAPI_URL} (${err.message}). schema.d.ts was not modified.`)
  }

  const pathCount = Object.keys(doc?.paths ?? {}).length
  if (pathCount === 0) {
    fail(`${OPENAPI_URL} has zero paths. schema.d.ts was not modified.`)
  }

  const contents = astToString(await openapiTS(doc))
  await mkdir(path.dirname(OUT_FILE), { recursive: true })
  await writeFile(OUT_FILE, contents)
  console.log(
    `[gen:api] Wrote ${path.relative(process.cwd(), OUT_FILE)} (${pathCount} paths) from ${OPENAPI_URL}`,
  )
}

main().catch((err) => fail(`Unexpected failure: ${err.stack ?? err}`))
