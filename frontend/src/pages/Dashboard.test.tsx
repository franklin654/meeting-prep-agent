import { fireEvent, screen, waitFor } from '@testing-library/react'
import { describe, expect, it } from 'vitest'
import { Dashboard } from './Dashboard'
import { mockFetch } from '@/test/mockFetch'
import { routes } from '@/routes'
import { renderRoutes, renderWithProviders } from '@/test/renderWithProviders'

const EMPTY_STYLE = { section_order: [], hidden_sections: [], length: 'standard', notes: [] }

describe('Dashboard', () => {
  it('lists upcoming meetings and enforces the notes minimum before submitting', async () => {
    const fetchMock = mockFetch({
      'GET /api/nudges': { body: [] },
      'GET /api/contacts': { body: [] },
      'GET /api/style': { body: EMPTY_STYLE },
      'GET /api/meetings': {
        body: [{
          id: 'mtg_1', account_id: 'acct_1', account_name: 'FinEdge', title: 'Pilot decision',
          scheduled_at: '2026-09-29T13:00:00Z', status: 'upcoming',
          attendees: [{ id: 'c_1', name: 'Anita Rao', role: 'CFO' }], brief_ready: true,
        }],
      },
    })
    renderWithProviders(<Dashboard />)
    expect(await screen.findByText('Pilot decision')).toBeInTheDocument()
    expect(screen.getByText(/Anita Rao · CFO/)).toBeInTheDocument()
    expect(screen.getByText('Brief ready')).toBeInTheDocument()
    fireEvent.click(screen.getAllByRole('button', { name: /log notes/i })[0])
    expect(await screen.findByRole('dialog')).toBeInTheDocument()
    const submit = screen.getByRole('button', { name: /start learning/i })
    expect(submit).toBeDisabled()
    fireEvent.change(screen.getByLabelText(/meeting transcript/i), { target: { value: 'short' } })
    expect(submit).toBeDisabled()
    expect(fetchMock.calls.filter((call) => call.path === '/api/nudges')).toHaveLength(1)
    expect(fetchMock.calls.every((call) => call.method === 'GET')).toBe(true)
  })

  it('submits only valid notes and shows the learned summary when the job finishes', async () => {
    const transcript = 'A'.repeat(50)
    const fetchMock = mockFetch({
      'GET /api/nudges': { body: [] },
      'GET /api/contacts': { body: [] },
      'GET /api/style': { body: EMPTY_STYLE },
      'GET /api/meetings': { body: [{
        id: 'mtg_1', account_id: 'acct_1', account_name: 'FinEdge', title: 'Pilot decision',
        scheduled_at: '2026-09-29T13:00:00Z', status: 'upcoming', attendees: [], brief_ready: false,
      }] },
      'POST /api/meetings/mtg_1/notes': { status: 202, body: { job_id: 'job_1' } },
      'GET /api/jobs/job_1': {
        body: { id: 'job_1', kind: 'ingest', status: 'done', learned: { facts: ['Budget is $75K'], new_commitments: 1, closed_commitments: 0, alerts: ['Contradiction: budget changed.'] } },
      },
    })
    renderWithProviders(<Dashboard />)
    await screen.findByText('Pilot decision')
    fireEvent.click(screen.getAllByRole('button', { name: /log notes/i })[0])
    fireEvent.change(screen.getByLabelText(/meeting transcript/i), { target: { value: transcript } })
    fireEvent.change(screen.getByLabelText(/choose meeting/i), { target: { value: 'mtg_1' } })
    fireEvent.click(screen.getByRole('button', { name: /start learning/i }))
    expect(await screen.findByText(/Budget is \$75K.*Alerts: Contradiction/)).toBeInTheDocument()
    expect(await screen.findByText(/Alerts: Contradiction: budget changed\./)).toBeInTheDocument()
    expect(fetchMock.calls.filter((call) => call.path === '/api/nudges')).toHaveLength(1)
    expect(fetchMock.calls.map((call) => call.method)).toContain('POST')
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
