import { QueryClient } from '@tanstack/react-query'
import { ApiError } from '@/api/errors'

/**
 * Single TanStack Query client for the app. All server state is fetched and
 * cached here; per AGENTS.md, nothing is persisted to browser storage.
 * Client errors (4xx) are not retried; server/network errors retry once.
 */
export const queryClient = new QueryClient({
  defaultOptions: {
    queries: {
      retry: (failureCount, error) =>
        failureCount < 1 && !(error instanceof ApiError && error.status >= 400 && error.status < 500),
      refetchOnWindowFocus: false,
    },
  },
})
