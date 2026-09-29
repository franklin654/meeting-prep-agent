import createClient from 'openapi-fetch'
import { ApiError, apiErrorFromResponse } from './errors'
import type { paths } from './schema'

/**
 * Typed client over the generated `paths`. The generated paths already begin
 * with `/api`, so baseUrl is empty and Vite proxies `/api` to the backend.
 *
 * The fetch wrapper:
 * - looks up `globalThis.fetch` per call (so tests can stub it),
 * - applies no client-side timeout (brief generation takes 36-54 s; any
 *   timeout must stay at or above 150 s),
 * - throws ApiError for non-2xx responses (parsing the error envelope) and for
 *   network failures (code `network_error`, status 0), so callers only ever see
 *   `data` on success.
 */
async function apiFetch(request: Request): Promise<Response> {
  let response: Response
  try {
    response = await globalThis.fetch(request)
  } catch (err) {
    throw new ApiError({
      code: 'network_error',
      status: 0,
      message: err instanceof Error ? err.message : 'Network request failed',
    })
  }
  if (!response.ok) {
    throw apiErrorFromResponse(response.status, await response.text())
  }
  return response
}

// openapi-fetch builds `new Request(url)`, which needs an absolute URL outside a
// browser page (Node/jsdom), so anchor to the page origin. Same origin in the
// browser, so the Vite proxy still handles `/api`.
const baseUrl = typeof window === 'undefined' ? '' : window.location.origin

export const api = createClient<paths>({ baseUrl, fetch: apiFetch })
