// Typed API client, generated from the backend's OpenAPI document.
//
// `npm run gen:api` regenerates ./schema.d.ts from /openapi.json (see
// scripts/gen-api.mjs). Nothing in this file should hand-declare request or
// response shapes — import them from `./schema` instead, once the backend
// (T13/T15) exists and real endpoints land here.
//
// This file is intentionally a thin placeholder until then: later FE
// tickets (T16-T18) wire real calls through TanStack Query using the types
// generated into ./schema.d.ts.
export type { paths, components } from './schema'

export const API_BASE_URL = '/api'
