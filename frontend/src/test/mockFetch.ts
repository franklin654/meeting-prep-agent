import { vi } from 'vitest'

export interface MockResponse {
  status?: number
  body?: unknown
  /** Resolve after this many ms (uses real/fake timers as configured). */
  delayMs?: number
}

export interface RecordedCall {
  method: string
  path: string
  search: string
  body: unknown
}

type Handler = MockResponse | ((call: RecordedCall) => MockResponse)
/** An array is consumed one entry per call; the last entry repeats. */
type Route = Handler | Handler[]

export interface MockFetch {
  calls: RecordedCall[]
  /** Calls whose "METHOD /path" key matches. */
  callsTo: (key: string) => RecordedCall[]
  /** Replace the routes (e.g. to flip a job from pending to done). */
  setRoutes: (routes: Record<string, Route>) => void
}

/**
 * Route-based fetch stub. Keys are "METHOD /path" (query string ignored) or
 * "METHOD /path?query" for an exact match, tried first. Records every call.
 * Unmatched requests reject, so a test never talks to a real server.
 */
export function mockFetch(initial: Record<string, Route>): MockFetch {
  let routes = initial
  const counters = new Map<string, number>()
  const calls: RecordedCall[] = []

  const fn = async (input: RequestInfo | URL, init?: RequestInit) => {
    const req = input instanceof Request ? input : new Request(input, init)
    const url = new URL(req.url, 'http://localhost')
    const method = req.method.toUpperCase()
    const text = method === 'GET' || method === 'HEAD' ? '' : await req.clone().text()
    const call: RecordedCall = {
      method,
      path: url.pathname,
      search: url.search,
      body: text ? JSON.parse(text) : undefined,
    }
    calls.push(call)

    const key = [`${method} ${url.pathname}${url.search}`, `${method} ${url.pathname}`].find(
      (k) => k in routes,
    )
    if (!key) throw new Error(`mockFetch: no route for ${method} ${url.pathname}${url.search}`)

    const route = routes[key]
    let handler: Handler
    if (Array.isArray(route)) {
      const n = counters.get(key) ?? 0
      counters.set(key, n + 1)
      handler = route[Math.min(n, route.length - 1)]
    } else {
      handler = route
    }
    const res = typeof handler === 'function' ? handler(call) : handler
    if (res.delayMs) await new Promise((r) => setTimeout(r, res.delayMs))
    return new Response(res.body === undefined ? null : JSON.stringify(res.body), {
      status: res.status ?? 200,
      headers: { 'Content-Type': 'application/json' },
    })
  }

  vi.stubGlobal('fetch', vi.fn(fn))

  return {
    calls,
    callsTo: (key) => calls.filter((c) => `${c.method} ${c.path}` === key),
    setRoutes: (next) => {
      routes = next
      counters.clear()
    },
  }
}
