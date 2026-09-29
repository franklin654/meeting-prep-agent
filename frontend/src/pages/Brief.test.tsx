import { screen } from '@testing-library/react'
import { describe, expect, it } from 'vitest'
import { mockFetch } from '@/test/mockFetch'
import { renderRoutes } from '@/test/renderWithProviders'
import { routes } from '@/routes'

describe('Brief page', () => {
  it('loads the cached brief with GET only and shows citations and the learning meter', async () => {
    const f = mockFetch({
      'GET /api/meetings/mtg_1/brief': { body: {
        id: 'brf_1', meeting_id: 'mtg_1', mode: 'memory', generated_at: '2026-09-29T10:00:00Z',
        sections: [{ key: 'open_commitments', title: 'Open commitments', collapsed: false, items: [{
          id: 'i_1', text: 'Pricing deck is overdue', severity: 'critical', contact_ids: [],
          citations: [{ source_type: 'meeting', meeting_id: 'mtg_old', meeting_date: '2026-09-20', label: 'M4 · Sep 20', quote: 'I will send the pricing deck.', memory_id: 'mem_1' }],
        }] }], facts_used: 4, preferences_applied: ['shorter_sections'],
      } },
      'GET /api/style': { body: { section_order: [], hidden_sections: [], preferences_applied: ['shorter_sections'] } },
    })
    renderRoutes(routes, { route: '/meetings/mtg_1' })
    expect(await screen.findAllByText('Pricing deck is overdue')).toHaveLength(1)
    expect(screen.getByText(/4 facts · 1 prefs/i)).toBeInTheDocument()
    expect(screen.getAllByRole('button', { name: /M4 · Sep 20/i })).toHaveLength(1)
    expect(f.calls.every((call) => call.method === 'GET')).toBe(true)
    expect(f.calls.some((call) => call.method === 'POST')).toBe(false)
  })

  it('shows the empty state and keeps generation behind an explicit confirmation', async () => {
    const f = mockFetch({ 'GET /api/meetings/mtg_1/brief': { status: 404, body: { error: { code: 'not_found', message: 'No brief' } } } })
    renderRoutes(routes, { route: '/meetings/mtg_1' })
    expect(await screen.findAllByText(/no brief yet/i)).toHaveLength(1)
    expect(f.calls.every((call) => call.method === 'GET')).toBe(true)
  })

  it('sends section feedback and refreshes the read-time brief', async () => {
    const f = mockFetch({
      'GET /api/meetings/mtg_1/brief': { body: {
        id: 'brf_1', meeting_id: 'mtg_1', mode: 'memory', generated_at: '2026-09-29T10:00:00Z',
        sections: [{ key: 'open_commitments', title: 'Open commitments', collapsed: false, items: [{
          id: 'i_1', text: 'Pricing deck is overdue', severity: 'critical', contact_ids: [], citations: [],
        }] }], facts_used: 2, preferences_applied: [],
      } },
      'POST /api/briefs/brf_1/feedback': { body: {
        section_order: ['open_commitments'], hidden_sections: [], length: 'standard', notes: ['Puts Open commitments first.'],
      } },
    })
    renderRoutes(routes, { route: '/meetings/mtg_1' })
    const useful = await screen.findByRole('button', { name: 'Useful' })
    useful.click()
    await screen.findByText('Preference learned')
    expect(f.calls.find((call) => call.method === 'POST')?.body).toEqual({ section: 'open_commitments', action: 'up' })
  })
})
