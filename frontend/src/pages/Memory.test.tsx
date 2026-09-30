import { fireEvent, screen, waitFor } from '@testing-library/react'
import { describe, expect, it } from 'vitest'
import { mockFetch } from '@/test/mockFetch'
import { renderRoutes } from '@/test/renderWithProviders'
import { routes } from '@/routes'

const OVERVIEW = {
  facts_by_kind: { deal_fact: 2, objection: 1, personal: 1, competitor: 0, commitment: 1 },
  growth: [{ account_id: 'acc_1', account_name: 'FinEdge', points: [{ meeting_id: 'm1', meeting_title: 'Discovery', meeting_date: '2026-09-15', fact_count: 3 }] }],
  hidden_item_count: 1,
  hidden_items: [{ target_id: 'fact_hidden', target_type: 'fact', text: 'Anita prefers concise summaries.', meeting_id: 'm1', meeting_title: 'Discovery', meeting_date: '2026-09-15' }],
  style_rules: { section_order: [], hidden_sections: [], length: 'standard', notes: ['Lead with numbers.'] },
  hindsight_stats: { total_nodes: 18, total_documents: 4, nodes_by_fact_type: { world: 14, observation: 4 }, total_observations: 4 },
}

describe('Memory inspector', () => {
  it('shows SQLite growth and cached briefs, and un-hides an item', async () => {
    const f = mockFetch({
      'GET /api/memory/overview': { body: OVERVIEW },
      'GET /api/meetings': { body: [{ id: 'm1', account_id: 'acc_1', account_name: 'FinEdge', title: 'Pilot decision', scheduled_at: '2026-09-20T10:00:00Z', status: 'done', attendees: [], brief_ready: true, prepared: false, open_followups: 0, past_meetings: 1, has_history: true, overdue_followups: 0, has_notes: true }] },
      'GET /api/meetings/m1/brief': { body: { id: 'br_m', meeting_id: 'm1', mode: 'memory', generated_at: '2026-09-20T10:00:00Z', sections: [{ key: 'where_left_off', title: 'Where we left off', collapsed: false, items: [{ id: 'i1', text: 'The pilot is six weeks.', severity: 'info', contact_ids: [], citations: [] }] }], facts_used: 3, preferences_applied: [], memory_used: { facts: 3, meetings: 1 } } },
      'GET /api/meetings/m1/brief?mode=no_memory': { body: { id: 'br_nm', meeting_id: 'm1', mode: 'no_memory', generated_at: '2026-09-20T10:00:00Z', sections: [{ key: 'agenda', title: 'Suggested agenda', collapsed: false, items: [{ id: 'nm1', text: 'Meeting-only context', severity: 'info', contact_ids: [], citations: [] }] }], facts_used: 0, preferences_applied: [], memory_used: { facts: 0, meetings: 0 } } },
      'DELETE /api/memories/fact_hidden/hide': { status: 204 },
    })
    renderRoutes(routes, { route: '/memory' })
    expect(await screen.findByText('Lead with numbers.')).toBeInTheDocument()
    expect(screen.getByRole('img', { name: /facts known after each meeting/i })).toBeInTheDocument()
    expect(screen.getByText(/18 nodes · 4 documents/)).toBeInTheDocument()
    expect(await screen.findByText('The pilot is six weeks.')).toBeInTheDocument()
    fireEvent.click(screen.getByRole('button', { name: 'Memory off' }))
    expect(await screen.findByText('Meeting-only context')).toBeInTheDocument()
    fireEvent.click(screen.getByRole('button', { name: 'Unhide Anita prefers concise summaries.' }))
    await waitFor(() => expect(f.calls.some((call) => call.method === 'DELETE' && call.path.endsWith('/fact_hidden/hide'))).toBe(true))
    expect(f.calls.some((call) => call.method === 'POST')).toBe(false)
  })

  it('confirms before resetting style rules', async () => {
    mockFetch({ 'GET /api/memory/overview': { body: OVERVIEW }, 'GET /api/meetings': { body: [] }, 'POST /api/style/reset': { body: { section_order: [], hidden_sections: [], length: 'standard', notes: [] } } })
    renderRoutes(routes, { route: '/memory' })
    fireEvent.click(await screen.findByRole('button', { name: 'Reset style rules' }))
    expect(await screen.findByRole('alertdialog', { name: 'Reset style rules?' })).toBeInTheDocument()
    fireEvent.click(screen.getByRole('button', { name: 'Confirm reset' }))
  })
})
