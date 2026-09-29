import { screen, within } from '@testing-library/react'
import { describe, expect, it } from 'vitest'
import { routes } from '@/routes'
import { mockFetch } from '@/test/mockFetch'
import { renderRoutes } from '@/test/renderWithProviders'

describe('ContactTimeline page', () => {
  it('shows newest memories first with meeting links and source quotes', async () => {
    const fetchMock = mockFetch({ 'GET /api/contacts/c_anita/timeline': { body: {
      contact: { id: 'c_anita', name: 'Anita Rao', role: 'CFO' },
      entries: [
        { text: 'Anita approved a $75K budget.', fact_kind: 'deal_fact', learned_on: '2026-09-29', citation: { source_type: 'meeting', meeting_id: 'mtg_m6', meeting_date: '2026-09-29', label: 'M6 · Sep 29', quote: 'We can go up to $75K.', memory_id: 'mem_new' } },
        { text: 'Anita planned a half marathon.', fact_kind: 'personal', learned_on: '2026-07-28', citation: { source_type: 'meeting', meeting_id: 'mtg_m2', meeting_date: '2026-07-28', label: 'M2 · Jul 28', quote: 'I am training for a half marathon.', memory_id: 'mem_old' } },
      ],
    } } })
    renderRoutes(routes, { route: '/contacts/c_anita' })
    expect(await screen.findByRole('heading', { name: 'Anita Rao' })).toBeInTheDocument()
    const cards = screen.getAllByRole('listitem')
    expect(within(cards[0]).getByText('Anita approved a $75K budget.')).toBeInTheDocument()
    expect(within(cards[1]).getByText('Anita planned a half marathon.')).toBeInTheDocument()
    expect(screen.getByRole('link', { name: 'M2 · Jul 28' })).toHaveAttribute('href', '/meetings/mtg_m2')
    expect(fetchMock.calls.map((call) => call.method)).toEqual(['GET'])
  })

  it('shows a clear empty state', async () => {
    mockFetch({ 'GET /api/contacts/c_empty/timeline': { body: { contact: { id: 'c_empty', name: 'Vikram', role: null }, entries: [] } } })
    renderRoutes(routes, { route: '/contacts/c_empty' })
    expect(await screen.findByText(/no memories for this contact yet/i)).toBeInTheDocument()
  })
})
