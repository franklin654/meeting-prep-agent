import type { RouteObject } from 'react-router-dom'
import { Layout } from '@/components/Layout'
import { Brief } from '@/pages/Brief'
import { ContactTimeline } from '@/pages/ContactTimeline'
import { ComingSoon } from '@/pages/ComingSoon'
import { Dashboard } from '@/pages/Dashboard'
import { Capture } from '@/pages/Capture'

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
      { path: 'contacts', element: <ComingSoon title="Contacts" /> },
      { path: 'contacts/:id', element: <ContactTimeline /> },
      { path: 'ask', element: <ComingSoon title="Ask" /> },
      { path: 'capture', element: <Capture /> },
      { path: 'memory', element: <ComingSoon title="Memory inspector" /> },
    ],
  },
]
