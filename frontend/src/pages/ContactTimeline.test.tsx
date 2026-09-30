import { fireEvent, screen } from '@testing-library/react'
import { describe, expect, it, vi } from 'vitest'
import { routes } from '@/routes'
import { mockFetch } from '@/test/mockFetch'
import { renderRoutes } from '@/test/renderWithProviders'

const profile = (name: string, needs_review = false) => ({
  contact: { id: 'c_anita', name, role: 'CFO', needs_review },
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
    expect(screen.getAllByRole('link', { name: /Pricing review/ }).every((link) => link.getAttribute('href') === '/meetings/mtg_m6')).toBe(true)
    expect(screen.getByRole('heading', { name: 'Pricing review · Sep 29, 2026' })).toBeInTheDocument()
    expect(screen.getByText('Deal fact')).toBeInTheDocument()
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

  it('confirms an unconfirmed contact with the edited name and role', async () => {
    const prompt = vi.fn().mockReturnValueOnce('Anita Shah').mockReturnValueOnce('CEO')
    vi.stubGlobal('prompt', prompt)
    const fetchMock = mockFetch({
      'GET /api/contacts/c_anita/profile': [{ body: profile('Ananya', true) }, { body: profile('Anita Shah', false) }],
      'PATCH /api/contacts/c_anita': { body: { id: 'c_anita', name: 'Anita Shah', role: 'CEO', account_id: 'acc', account_name: 'FinEdge', needs_review: false } },
    })
    renderRoutes(routes, { route: '/contacts/c_anita' })
    expect(await screen.findByText('Unconfirmed')).toBeInTheDocument()
    fireEvent.click(screen.getByRole('button', { name: 'Confirm contact' }))
    expect(await screen.findByRole('heading', { name: /Anita Shah/ })).toBeInTheDocument()
    expect(screen.queryByText('Unconfirmed')).not.toBeInTheDocument()
    expect(fetchMock.calls.find((call) => call.method === 'PATCH')?.body).toEqual({ name: 'Anita Shah', role: 'CEO' })
    vi.unstubAllGlobals()
  })

  it('puts fact and follow-up controls in keyboard-reachable per-item menus', async () => {
    const followUp = { id: 'cm_1', owner: 'ae', text: 'Send the pricing deck', due_date: '2026-09-20', status: 'open', citation: { source_type: 'ledger', meeting_id: 'mtg_m6', meeting_date: '2026-09-29', label: 'Pricing review · Sep 29', quote: null, memory_id: null } }
    mockFetch({
      'GET /api/contacts/c_anita/profile': { body: { ...profile('Anita Rao'), follow_ups: [followUp] } },
      'POST /api/memories/fact_1/hide': { body: {} },
      'PATCH /api/commitments/cm_1': { body: followUp },
      'DELETE /api/commitments/cm_1': { status: 204 },
    })
    vi.stubGlobal('confirm', vi.fn().mockReturnValue(true))
    renderRoutes(routes, { route: '/contacts/c_anita' })
    fireEvent.click(await screen.findByRole('button', { name: 'Facts' }))
    fireEvent.click(screen.getByLabelText('Actions for Anita approved a $75K budget.'))
    expect(screen.getByRole('button', { name: 'Correct' })).toBeInTheDocument()
    expect(screen.getByRole('button', { name: 'Hide' })).toBeInTheDocument()
    fireEvent.click(screen.getByRole('button', { name: 'Follow-ups' }))
    fireEvent.click(screen.getByLabelText('Actions for Send the pricing deck'))
    expect(screen.getByRole('button', { name: 'Mark done' })).toBeInTheDocument()
    expect(screen.getByRole('button', { name: 'Edit due date' })).toBeInTheDocument()
    expect(screen.getByRole('button', { name: 'Delete' })).toBeInTheDocument()
    vi.unstubAllGlobals()
  })
})
