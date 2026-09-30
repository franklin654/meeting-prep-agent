import { fireEvent, screen } from '@testing-library/react'
import { describe, expect, it } from 'vitest'
import { routes } from '@/routes'
import { mockFetch } from '@/test/mockFetch'
import { renderRoutes } from '@/test/renderWithProviders'

describe('Contacts list', () => {
  it('searches contacts by name and shows account filters', async () => {
    mockFetch({
      'GET /api/contacts': { body: [
        { id: 'c_anita', name: 'Anita Rao', role: 'CFO', account_id: 'acc_finedge', account_name: 'FinEdge Payments', meetings_count: 4, open_followups: 2, last_meeting_date: '2026-09-29' },
        { id: 'c_rahul', name: 'Rahul Mehta', role: 'CTO', account_id: 'acc_finedge', account_name: 'FinEdge Payments', meetings_count: 2, open_followups: 0, last_meeting_date: null },
      ] },
      'GET /api/accounts': { body: [{ id: 'acc_finedge', name: 'FinEdge Payments', industry: 'Finance', stage: 'evaluation' }] },
    })
    renderRoutes(routes, { route: '/contacts' })
    expect(await screen.findByText('Anita Rao')).toBeInTheDocument()
    expect(screen.getByText('Rahul Mehta')).toBeInTheDocument()
    fireEvent.change(screen.getByRole('textbox', { name: 'Search contacts' }), { target: { value: 'Rahul' } })
    expect(screen.getByText('Rahul Mehta')).toBeInTheDocument()
    expect(screen.queryByText('Anita Rao')).not.toBeInTheDocument()
    expect(screen.getByRole('option', { name: 'FinEdge Payments' })).toBeInTheDocument()
  })

  it('shows confirmed contacts by default and lets the user reveal unconfirmed contacts', async () => {
    const fetchMock = mockFetch({
      'GET /api/contacts': { body: [
        { id: 'c_rahul', name: 'Rahul Mehta', role: 'CTO', account_id: 'acc_finedge', account_name: 'FinEdge Payments', needs_review: false, meetings_count: 2, open_followups: 0, last_meeting_date: null },
      ] },
      'GET /api/contacts?include_unconfirmed=true': { body: [
        { id: 'c_rahul', name: 'Rahul Mehta', role: 'CTO', account_id: 'acc_finedge', account_name: 'FinEdge Payments', needs_review: false, meetings_count: 2, open_followups: 0, last_meeting_date: null },
        { id: 'c_ananya', name: 'Ananya', role: null, account_id: 'acc_finedge', account_name: 'FinEdge Payments', needs_review: true, meetings_count: 1, open_followups: 0, last_meeting_date: null },
      ] },
      'GET /api/accounts': { body: [] },
    })
    renderRoutes(routes, { route: '/contacts' })
    expect(await screen.findByText('Rahul Mehta')).toBeInTheDocument()
    expect(screen.queryByText('Ananya')).not.toBeInTheDocument()
    fireEvent.click(screen.getByRole('button', { name: /Show unconfirmed/ }))
    expect(await screen.findByText('Ananya')).toBeInTheDocument()
    expect(screen.getByText('Unconfirmed')).toBeInTheDocument()
    expect(fetchMock.calls.some((call) => call.search.includes('include_unconfirmed=true'))).toBe(true)
  })
})
