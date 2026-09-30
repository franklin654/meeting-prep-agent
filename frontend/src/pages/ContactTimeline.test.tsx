import { screen } from '@testing-library/react'
import { describe, expect, it } from 'vitest'
import { routes } from '@/routes'
import { mockFetch } from '@/test/mockFetch'
import { renderRoutes } from '@/test/renderWithProviders'

const profile = (name: string) => ({
  contact: { id: 'c_anita', name, role: 'CFO' },
  account: { id: 'acc', name: 'FinEdge', industry: 'Finance', stage: 'evaluation' },
  stats: { meetings: 1, facts: 1, open_follow_ups: 0 },
  timeline: [{ meeting_id: 'mtg_m6', title: 'Pricing review', meeting_date: '2026-09-29', items: [{ kind: 'deal_fact', text: 'Anita approved a $75K budget.', learned_on: '2026-09-29', citation: { source_type: 'meeting', meeting_id: 'mtg_m6', meeting_date: '2026-09-29', label: 'Pricing review · Sep 29', quote: 'We can go up to $75K.', memory_id: null } }] }],
  facts: [{ id: 'fact_1', kind: 'deal_fact', text: 'Anita approved a $75K budget.', learned_on: '2026-09-29', citation: { source_type: 'meeting', meeting_id: 'mtg_m6', meeting_date: '2026-09-29', label: 'Pricing review · Sep 29', quote: 'We can go up to $75K.', memory_id: null } }],
  follow_ups: [], preferences: [], patterns: [], hidden_count: 0,
})

describe('Contact profile page', () => {
  it('shows contact context and meeting source links', async () => {
    const fetchMock = mockFetch({ 'GET /api/contacts/c_anita/profile': { body: profile('Anita Rao') } })
    renderRoutes(routes, { route: '/contacts/c_anita' })
    expect(await screen.findByRole('heading', { name: 'Anita Rao' })).toBeInTheDocument()
    expect(screen.getByText(/FinEdge/)).toBeInTheDocument()
    expect(screen.getByText('Anita approved a $75K budget.')).toBeInTheDocument()
    expect(screen.getByRole('link', { name: /Pricing review/ })).toHaveAttribute('href', '/meetings/mtg_m6')
    expect(fetchMock.calls.some((call) => call.path === '/api/contacts/c_anita/profile')).toBe(true)
  })

  it('shows an empty state for a contact with no history', async () => {
    mockFetch({ 'GET /api/contacts/c_empty/profile': { body: { ...profile('Vikram'), timeline: [], facts: [], stats: { meetings: 0, facts: 0, open_follow_ups: 0 } } } })
    renderRoutes(routes, { route: '/contacts/c_empty' })
    expect(await screen.findByText('No timeline items yet.')).toBeInTheDocument()
  })

  it('disables pattern refresh until facts span two meetings', async () => {
    mockFetch({ 'GET /api/contacts/c_anita/profile': { body: profile('Anita Rao') } })
    renderRoutes(routes, { route: '/contacts/c_anita' })
    const refresh = await screen.findByRole('button', { name: 'Refresh' })
    expect(refresh).toBeDisabled()
    expect(refresh).toHaveAttribute('title', 'Needs facts from at least 2 meetings')
  })
})
