import { fireEvent, screen, waitFor } from '@testing-library/react'
import { describe, expect, it } from 'vitest'
import { Dashboard } from './Dashboard'
import { mockFetch } from '@/test/mockFetch'
import { routes } from '@/routes'
import { renderRoutes, renderWithProviders } from '@/test/renderWithProviders'

const EMPTY_STYLE = { section_order: [], hidden_sections: [], length: 'standard', notes: [] }

describe('Dashboard', () => {
  it('shows customer attendees and follow-up chips, and links notes to the meeting capture form', async () => {
    mockFetch({
      'GET /api/nudges': { body: [] },
      'GET /api/contacts': { body: [] },
      'GET /api/style': { body: EMPTY_STYLE },
      'GET /api/meetings': {
        body: [{
          id: 'mtg_1', account_id: 'acct_1', account_name: 'FinEdge', title: 'Pilot decision',
          scheduled_at: '2026-09-29T13:00:00Z', status: 'upcoming',
          attendees: [
            { id: 'c_priya', name: 'Priya Nair', role: 'Account Executive' },
            { id: 'c_arjun', name: 'Arjun Menon', role: 'Sales Engineer' },
            { id: 'c_1', name: 'Anita Rao', role: 'CFO' },
          ], brief_ready: true, prepared: false, open_followups: 3, overdue_followups: 1,
          past_meetings: 2, has_history: true, has_notes: false,
        }],
      },
    })
    renderWithProviders(<Dashboard />)
    expect(await screen.findByText('Pilot decision')).toBeInTheDocument()
    expect(screen.getByText(/Anita Rao \(CFO\)/)).toBeInTheDocument()
    expect(screen.queryByText(/Priya Nair/)).not.toBeInTheDocument()
    expect(screen.queryByText(/Arjun Menon/)).not.toBeInTheDocument()
    expect(screen.getByText('Brief ready')).toBeInTheDocument()
    expect(screen.getByText('1 overdue')).toHaveClass('border-alert-warning/40')
    expect(screen.getByText('2 other open')).toBeInTheDocument()
    expect(screen.getByRole('link', { name: 'Log notes' })).toHaveAttribute('href', '/capture?meeting=mtg_1')
  })

  it('searches meetings and contacts client-side', async () => {
    mockFetch({
      'GET /api/health': { body: { status: 'ok', demo_today: '2026-09-30', ae_name: 'Priya Nair', company_name: 'Tracewise' } },
      'GET /api/meetings': { body: [{
        id: 'm_1', account_id: 'acc_1', account_name: 'FinEdge', title: 'Pilot decision',
        scheduled_at: '2026-10-01T10:00:00Z', status: 'upcoming', attendees: [], brief_ready: false,
        prepared: false, open_followups: 0, past_meetings: 1, has_history: true,
      }] },
      'GET /api/contacts': { body: [{
        id: 'c_anita', name: 'Anita Desai', role: 'CFO', account_id: 'acc_1', account_name: 'FinEdge',
        meetings_count: 2, open_followups: 0, last_meeting_date: '2026-09-29',
      }] },
      'GET /api/nudges': { body: [] },
      'GET /api/style': { body: EMPTY_STYLE },
    })
    renderRoutes(routes)
    const search = await screen.findByRole('searchbox', { name: 'Search contacts or meetings' })
    fireEvent.change(search, { target: { value: 'Anita' } })
    expect(await screen.findByRole('link', { name: /Anita Desai/ })).toHaveAttribute('href', '/contacts/c_anita')
    fireEvent.change(search, { target: { value: 'Pilot' } })
    expect(await screen.findByRole('link', { name: /Pilot decision/ })).toHaveAttribute('href', '/meetings/m_1')
  })

  it('creates an account and inline contact before scheduling its first meeting', async () => {
    const fetchMock = mockFetch({
      'GET /api/health': { body: { status: 'ok', demo_today: '2026-09-30', ae_name: 'Priya Nair', company_name: 'Tracewise' } },
      'GET /api/meetings': { body: [] },
      'GET /api/nudges': { body: [] },
      'GET /api/style': { body: EMPTY_STYLE },
      'GET /api/accounts': { body: [] },
      'POST /api/accounts': { body: { id: 'acc_new', name: 'Northstar', industry: 'SaaS', stage: 'discovery' } },
      'POST /api/contacts': { body: { id: 'c_new', name: 'Jordan Lee', role: 'VP Sales', account_id: 'acc_new', account_name: 'Northstar', meetings_count: 0, open_followups: 0, last_meeting_date: null } },
      'POST /api/meetings': { status: 201, body: { id: 'm_new', account_id: 'acc_new', account_name: 'Northstar', title: 'Introduction', scheduled_at: '2026-10-01T10:00:00Z', status: 'upcoming', attendees: [], brief_ready: false, prepared: false, open_followups: 0, past_meetings: 0, has_history: false } },
    })
    renderRoutes(routes)
    await screen.findByRole('button', { name: 'Schedule meeting' })
    fireEvent.click(screen.getAllByRole('button', { name: 'Schedule meeting' })[0])
    const accountPicker = await screen.findByRole('combobox', { name: 'Account' })
    fireEvent.change(accountPicker, { target: { value: '__new_account__' } })
    fireEvent.change(screen.getByRole('textbox', { name: 'New account name' }), { target: { value: 'Northstar' } })
    fireEvent.change(screen.getByRole('textbox', { name: 'Industry (optional)' }), { target: { value: 'SaaS' } })
    fireEvent.change(screen.getByRole('textbox', { name: 'Meeting title' }), { target: { value: 'Introduction' } })
    fireEvent.click(screen.getByRole('checkbox', { name: 'Add a contact to this account' }))
    fireEvent.change(screen.getByRole('textbox', { name: 'Contact name' }), { target: { value: 'Jordan Lee' } })
    fireEvent.change(screen.getByRole('textbox', { name: 'Contact role (optional)' }), { target: { value: 'VP Sales' } })
    fireEvent.click(screen.getByRole('button', { name: 'Schedule meeting' }))
    await waitFor(() => expect(fetchMock.calls.filter((call) => call.method === 'POST')).toHaveLength(3))
    expect(fetchMock.calls.find((call) => call.path === '/api/meetings' && call.method === 'POST')?.body).toMatchObject({
      account_id: 'acc_new', title: 'Introduction', attendee_ids: ['c_new'],
    })
  })
})
