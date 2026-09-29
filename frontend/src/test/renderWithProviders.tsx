import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { render, type RenderOptions } from '@testing-library/react'
import type { ReactElement, ReactNode } from 'react'
import { createMemoryRouter, MemoryRouter, RouterProvider } from 'react-router-dom'
import type { RouteObject } from 'react-router-dom'
import { Toaster } from '@/components/ui/sonner'

export function createTestQueryClient() {
  return new QueryClient({
    defaultOptions: {
      queries: { retry: false, gcTime: Infinity },
      mutations: { retry: false },
    },
  })
}

export function TestProviders({
  children,
  client,
  route = '/',
}: {
  children: ReactNode
  client: QueryClient
  route?: string
}) {
  return (
    <QueryClientProvider client={client}>
      <MemoryRouter initialEntries={[route]}>{children}</MemoryRouter>
      <Toaster />
    </QueryClientProvider>
  )
}

interface Options extends Omit<RenderOptions, 'wrapper'> {
  route?: string
  client?: QueryClient
}

/** Render a component inside QueryClientProvider (retries off), a memory router and the Toaster. */
export function renderWithProviders(
  ui: ReactElement,
  { route = '/', client = createTestQueryClient(), ...options }: Options = {},
) {
  const result = render(ui, {
    wrapper: ({ children }) => (
      <TestProviders client={client} route={route}>
        {children}
      </TestProviders>
    ),
    ...options,
  })
  return { ...result, client }
}

/** Render a full route table (e.g. the app's `routes`) at `route`. */
export function renderRoutes(
  routes: RouteObject[],
  { route = '/', client = createTestQueryClient() }: { route?: string; client?: QueryClient } = {},
) {
  const router = createMemoryRouter(routes, { initialEntries: [route] })
  const result = render(
    <QueryClientProvider client={client}>
      <RouterProvider router={router} />
      <Toaster />
    </QueryClientProvider>,
  )
  return { ...result, client, router }
}
