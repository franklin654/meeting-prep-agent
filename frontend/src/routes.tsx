import type { RouteObject } from 'react-router-dom'
import { Layout } from '@/components/Layout'
import { Brief } from '@/pages/Brief'
import { ContactTimeline } from '@/pages/ContactTimeline'
import { Dashboard } from '@/pages/Dashboard'

/**
 * The three routes from docs/technical-design.md's Frontend table:
 * Dashboard ("/"), Brief ("/meetings/:id"), Contact timeline ("/contacts/:id").
 * Kept separate from the router instance so tests can mount them with a
 * memory router instead of a browser router.
 */
export const routes: RouteObject[] = [
  {
    path: '/',
    element: <Layout />,
    children: [
      { index: true, element: <Dashboard /> },
      { path: 'meetings/:id', element: <Brief /> },
      { path: 'contacts/:id', element: <ContactTimeline /> },
    ],
  },
]
