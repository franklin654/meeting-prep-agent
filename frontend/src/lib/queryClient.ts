import { QueryClient } from '@tanstack/react-query'

/**
 * Single TanStack Query client for the app. All server state (meetings,
 * briefs, contact timelines, etc.) is fetched and cached here; per
 * AGENTS.md, nothing is persisted to browser storage.
 */
export const queryClient = new QueryClient({
  defaultOptions: {
    queries: {
      retry: 1,
      refetchOnWindowFocus: false,
    },
  },
})
