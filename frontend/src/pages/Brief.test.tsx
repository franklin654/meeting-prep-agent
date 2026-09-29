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
      'GET /api/style': { body: { section_order: [], hidden_sections: [], length: 'standard', notes: ['Prefers shorter briefs.'] } },
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

  it('shows the empty-brief state when a cached brief has no sections', async () => {
    mockFetch({ 'GET /api/meetings/mtg_1/brief': { body: {
      id: 'brf_empty', meeting_id: 'mtg_1', mode: 'memory', generated_at: '2026-09-29T10:00:00Z',
      sections: [], facts_used: 0, preferences_applied: [],
    } } })
    renderRoutes(routes, { route: '/meetings/mtg_1' })
    expect(await screen.findByText(/this brief has no items yet/i)).toBeInTheDocument()
  })

  it('shows skeletons and disables generation while the cached brief is loading', async () => {
    const f = mockFetch({ 'GET /api/meetings/mtg_1/brief': { delayMs: 500, status: 404, body: { error: { code: 'not_found', message: 'No brief' } } } })
    renderRoutes(routes, { route: '/meetings/mtg_1' })
    expect(screen.getByLabelText('Loading memory brief')).toBeInTheDocument()
    expect(screen.getByRole('button', { name: /loading brief/i })).toBeDisabled()
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

  it('restores a hidden section on the cached brief and keeps collapsed critical items visible', async () => {
    const hiddenBrief = {
      id: 'brf_1', meeting_id: 'mtg_1', mode: 'memory', generated_at: '2026-09-29T10:00:00Z',
      sections: [{ key: 'open_commitments', title: 'Open commitments', collapsed: true, items: [{
        id: 'i_1', text: 'Pricing deck is overdue', severity: 'critical', contact_ids: [], citations: [],
      }] }], facts_used: 5, preferences_applied: ['Collapsed Open commitments (it has a critical item)', 'Hid Personal touchpoints (repeated negative feedback)'],
    }
    const restoredBrief = { ...hiddenBrief, sections: [...hiddenBrief.sections, {
      key: 'personal_touchpoints', title: 'Personal touchpoints', collapsed: false, items: [{
        id: 'i_2', text: 'Ask Anita about her half marathon.', severity: 'info', contact_ids: [], citations: [],
      }],
    }], preferences_applied: ['Collapsed Open commitments (it has a critical item)'] }
    const f = mockFetch({
      'GET /api/meetings/mtg_1/brief': [{ body: hiddenBrief }, { body: restoredBrief }],
      'GET /api/style': { body: { section_order: [], hidden_sections: ['personal_touchpoints'], length: 'standard', notes: ['Hides Personal touchpoints.'] } },
      'POST /api/briefs/brf_1/feedback': { body: { section_order: [], hidden_sections: [], length: 'standard', notes: [] } },
    })
    renderRoutes(routes, { route: '/meetings/mtg_1' })
    expect(await screen.findByText('Critical items remain visible.')).toBeInTheDocument()
    expect(screen.getByText('Pricing deck is overdue')).toBeInTheDocument()
    const restore = await screen.findByRole('button', { name: 'Restore section' })
    expect(screen.getByText(/Personal touchpoints is hidden by your learned preferences/i)).toBeInTheDocument()
    restore.click()
    expect(await screen.findByText('Ask Anita about her half marathon.')).toBeInTheDocument()
    expect(f.calls.find((call) => call.method === 'POST')?.body).toEqual({ section: 'personal_touchpoints', action: 'up' })
  })
})
