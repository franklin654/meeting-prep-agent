import { fireEvent, screen } from '@testing-library/react'
import { describe, expect, it } from 'vitest'
import { Dashboard } from './Dashboard'
import { mockFetch } from '@/test/mockFetch'
import { renderWithProviders } from '@/test/renderWithProviders'

describe('Dashboard', () => {
  it('lists upcoming meetings and enforces the notes minimum before submitting', async () => {
    const fetchMock = mockFetch({
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
    expect(screen.getByText('Anita Rao')).toBeInTheDocument()
    expect(screen.getByText('Brief ready')).toBeInTheDocument()
    fireEvent.click(screen.getAllByRole('button', { name: /log notes/i })[0])
    expect(await screen.findByRole('dialog')).toBeInTheDocument()
    const submit = screen.getByRole('button', { name: /start learning/i })
    expect(submit).toBeDisabled()
    fireEvent.change(screen.getByLabelText(/meeting transcript/i), { target: { value: 'short' } })
    expect(submit).toBeDisabled()
    expect(fetchMock.calls.map((call) => call.method)).toEqual(['GET'])
  })

  it('submits only valid notes and shows the learned summary when the job finishes', async () => {
    const transcript = 'A'.repeat(50)
    const fetchMock = mockFetch({
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
    expect(fetchMock.calls.map((call) => call.method)).toEqual(['GET', 'POST', 'GET', 'GET'])
  })
})
