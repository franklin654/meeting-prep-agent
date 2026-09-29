import { fireEvent, screen } from '@testing-library/react'
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
    expect(screen.getByText('4 facts used')).toBeInTheDocument()
    expect(screen.getByText('1 preference applied')).toBeInTheDocument()
    expect(screen.getAllByRole('button', { name: /M4 · Sep 20/i })).toHaveLength(1)
    expect(f.calls.every((call) => call.method === 'GET')).toBe(true)
    expect(f.calls.some((call) => call.method === 'POST')).toBe(false)
  })

  it('shows enriched brief layout, memory rail, and marks a meeting prepared', async () => {
    const f = mockFetch({
      'GET /api/meetings': { body: [{
        id: 'mtg_1', account_id: 'acc_1', account_name: 'FinEdge', title: 'Pilot decision',
        scheduled_at: '2026-09-29T10:00:00Z', status: 'upcoming',
        attendees: [{ id: 'c_anita', name: 'Anita Desai', role: 'CFO' }], brief_ready: true,
        prepared: false, open_followups: 1, past_meetings: 2, has_history: true,
      }] },
      'GET /api/meetings/mtg_1/brief': { body: {
        id: 'br_rich', meeting_id: 'mtg_1', mode: 'memory', generated_at: '2026-09-29T10:00:00Z',
        sections: [{ key: 'agenda', title: 'Suggested agenda', collapsed: false, items: [{
          id: 'agenda_1', text: 'Confirm the pilot timeline', severity: 'info', contact_ids: [], citations: [],
        }] }], facts_used: 2, preferences_applied: [], first_meeting: false,
        you_owe: [{ text: 'Send the pricing deck', due_date: '2026-09-28', status: 'overdue', days_overdue: 1, owner_name: 'Priya', severity: 'critical', citations: [{ source_type: 'ledger', meeting_id: 'mtg_old', meeting_date: '2026-09-20', label: 'Pilot scoping · Sep 20', quote: 'I will send the deck', memory_id: null }] }],
        they_owe: [], objections: [{ topic: 'Data residency', count: 2, dates: ['2026-09-20'], citations: [{ source_type: 'meeting', meeting_id: 'mtg_old', meeting_date: '2026-09-20', label: 'Pilot scoping · Sep 20', quote: 'Data must stay in India', memory_id: null }] }],
        memory_used: { facts: 2, meetings: 1 }, contact_cards: [{ contact_id: 'c_anita', name: 'Anita Desai', role: 'CFO', account: 'FinEdge', style: 'Prefers numbers first', style_citations: [], recent_meetings: [{ source_type: 'meeting', meeting_id: 'mtg_old', meeting_date: '2026-09-20', label: 'Pilot scoping · Sep 20', quote: null, memory_id: null }], open_follow_ups: 1 }],
      } },
      'POST /api/meetings/mtg_1/prepared': { status: 204 },
    })
    renderRoutes(routes, { route: '/meetings/mtg_1' })

    await screen.findByText('Brief for Pilot decision')
    expect(screen.getByRole('navigation', { name: 'Breadcrumb' })).toHaveTextContent('Today / FinEdge')
    expect(screen.getByText('You owe them')).toBeInTheDocument()
    expect(screen.getByText('Objections to expect')).toBeInTheDocument()
    expect(screen.getByText('Suggested plan for the call')).toBeInTheDocument()
    expect(screen.getByText('2 facts from 1 meetings')).toBeInTheDocument()
    expect(screen.getByRole('region', { name: 'Needs attention' })).toHaveTextContent('Send the pricing deck')
    expect(screen.getByRole('link', { name: 'Full history' })).toHaveAttribute('href', '/contacts/c_anita')
    fireEvent.click(screen.getByRole('button', { name: 'Mark as prepared' }))
    expect(await screen.findByRole('button', { name: 'Prepared' })).toBeDisabled()
    expect(f.calls.find((call) => call.path.endsWith('/prepared'))?.method).toBe('POST')
    fireEvent.click(screen.getByRole('button', { name: 'Ask about Anita' }))
    expect(await screen.findByRole('region', { name: 'Ask your memory' })).toBeInTheDocument()
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

  it('does not render feedback controls in the without-memory column', async () => {
    const brief = (mode: 'memory' | 'no_memory') => ({ id: `br_${mode}`, meeting_id: 'mtg_1', mode, generated_at: '2026-09-29T10:00:00Z', sections: [{ key: 'where_left_off', title: 'Where we left off', collapsed: false, items: [{ id: `i_${mode}`, text: 'Context', severity: 'info', contact_ids: [], citations: [] }] }], facts_used: 1, preferences_applied: [] })
    mockFetch({ 'GET /api/meetings/mtg_1/brief': [{ body: brief('memory') }, { body: brief('no_memory') }] })
    renderRoutes(routes, { route: '/meetings/mtg_1' })
    fireEvent.click(await screen.findByRole('button', { name: 'Without' }))
    expect(await screen.findByText('Context')).toBeInTheDocument()
    expect(screen.queryByTestId('feedback-slot-where_left_off')).not.toBeInTheDocument()
  })

  it('hoists contradiction alerts into Needs attention without duplicating them', async () => {
    const f = mockFetch({ 'GET /api/meetings/mtg_1/brief': { body: {
      id: 'br_alert', meeting_id: 'mtg_1', mode: 'memory', generated_at: '2026-09-29T10:00:00Z',
      sections: [{ key: 'alerts', title: 'Alerts', collapsed: false, items: [{ id: 'alert_1', text: 'Budget contradiction: the forecast changed from $40K to $75K.', severity: 'warning', contact_ids: [], citations: [{ source_type: 'meeting', meeting_id: 'mtg_old', meeting_date: '2026-09-20', label: 'M4 · Sep 20', quote: 'The revised forecast is $75K.', memory_id: 'mem_1' }] }] }], facts_used: 1, preferences_applied: [],
    } } })
    renderRoutes(routes, { route: '/meetings/mtg_1' })
    expect(await screen.findByRole('region', { name: 'Needs attention' })).toBeInTheDocument()
    expect(screen.getAllByText(/Budget contradiction/)).toHaveLength(1)
    expect(f.calls.every((call) => call.method === 'GET')).toBe(true)
  })

  it('shows skeletons and disables generation while the cached brief is loading', async () => {
    const f = mockFetch({ 'GET /api/meetings/mtg_1/brief': { delayMs: 500, status: 404, body: { error: { code: 'not_found', message: 'No brief' } } } })
    renderRoutes(routes, { route: '/meetings/mtg_1' })
    expect(screen.getByLabelText('Loading memory brief')).toBeInTheDocument()
    expect(screen.getByRole('button', { name: /loading brief/i })).toBeDisabled()
    expect(f.calls.every((call) => call.method === 'GET')).toBe(true)
  })

  it('shows the generating skeleton and wait message for a slow mocked brief response', async () => {
    const cached = { id: 'brf_1', meeting_id: 'mtg_1', mode: 'memory', generated_at: '2026-09-29T10:00:00Z', sections: [{ key: 'where_left_off', title: 'Where we left off', collapsed: false, items: [{ id: 'i1', text: 'Context', severity: 'info', contact_ids: [], citations: [] }] }], facts_used: 1, preferences_applied: [] }
    const f = mockFetch({
      'GET /api/meetings/mtg_1/brief': { body: cached },
      'POST /api/meetings/mtg_1/brief': { delayMs: 350, body: cached },
    })
    renderRoutes(routes, { route: '/meetings/mtg_1' })
    fireEvent.click(await screen.findByRole('button', { name: 'Regenerate with memory' }))
    fireEvent.click(screen.getByRole('button', { name: 'Confirm regenerate' }))
    expect(await screen.findByText('This can take about a minute.')).toBeInTheDocument()
    expect(screen.getByLabelText('Generating memory brief')).toBeInTheDocument()
    expect(f.calls.every((call) => call.method === 'GET' || call.path.endsWith('/brief'))).toBe(true)
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
    const useful = await screen.findByRole('button', { name: 'Thumbs up: useful' })
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
    expect(await screen.findByText('Collapsed by your preferences')).toBeInTheDocument()
    expect(screen.getByText('Pricing deck is overdue')).toBeInTheDocument()
    const restore = await screen.findByRole('button', { name: 'Restore section' })
    expect(screen.getByText(/Personal touchpoints is hidden by your learned preferences/i)).toBeInTheDocument()
    restore.click()
    expect(await screen.findByText('Ask Anita about her half marathon.')).toBeInTheDocument()
    expect(f.calls.find((call) => call.method === 'POST')?.body).toEqual({ section: 'personal_touchpoints', action: 'up' })
  })
})
