import type { RouteObject } from 'react-router-dom'
import { Layout } from '@/components/Layout'
import { Brief } from '@/pages/Brief'
import { Dashboard } from '@/pages/Dashboard'
import { Capture } from '@/pages/Capture'
import { Ask } from '@/pages/Ask'
import { Memory } from '@/pages/Memory'
import { Contacts } from '@/pages/Contacts'

/**
 * Shared shell route table. Existing meeting and contact-detail paths remain
 * available while the new section pages land in their later tickets.
 */
export const routes: RouteObject[] = [
  {
    path: '/',
    element: <Layout />,
    children: [
      { index: true, element: <Dashboard /> },
      { path: 'meetings/:id', element: <Brief /> },
      { path: 'contacts', element: <Contacts /> },
      { path: 'contacts/:id', element: <Contacts /> },
      { path: 'ask', element: <Ask /> },
      { path: 'capture', element: <Capture /> },
      { path: 'memory', element: <Memory /> },
    ],
  },
]
