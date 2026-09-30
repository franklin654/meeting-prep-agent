import { fireEvent, screen, waitFor } from '@testing-library/react'
import { describe, expect, it } from 'vitest'
import { Capture } from './Capture'
import { mockFetch } from '@/test/mockFetch'
import { renderWithProviders } from '@/test/renderWithProviders'
import { renderRoutes } from '@/test/renderWithProviders'
import { routes } from '@/routes'

const MEETINGS = [
  {
    id: 'm_up', account_id: 'acc_1', account_name: 'FinEdge', title: 'Pilot decision',
    scheduled_at: '2026-10-01T10:00:00Z', status: 'upcoming',
    attendees: [{ id: 'c_anita', name: 'Anita Desai', role: 'CFO' }], brief_ready: false,
    prepared: false, open_followups: 0, overdue_followups: 0, past_meetings: 1, has_history: true, has_notes: false,
  },
  {
    id: 'm_recent', account_id: 'acc_1', account_name: 'FinEdge', title: 'Budget review',
    scheduled_at: '2026-09-29T10:00:00Z', status: 'done', attendees: [], brief_ready: true,
    prepared: false, open_followups: 0, overdue_followups: 0, past_meetings: 0, has_history: true, has_notes: true,
  },
  {
    id: 'm_old', account_id: 'acc_1', account_name: 'FinEdge', title: 'Discovery',
    scheduled_at: '2026-09-15T10:00:00Z', status: 'done', attendees: [], brief_ready: true,
    prepared: false, open_followups: 0, overdue_followups: 0, past_meetings: 0, has_history: true, has_notes: false,
  },
]

const DRAFT = {
  draft_id: 'draft_1', meeting_id: 'm_up',
  counts: { commitments: 1, closes: 0, facts: 2 },
  items: [
    { id: 'commitment_0', kind: 'commitment', text: 'Send the revised proposal', owner: 'them', contact: 'Anita', due_date: null, quote: 'I will send the revised proposal.', badge: 'new', target_commitment_id: null, checked: true },
    { id: 'fact_0', kind: 'fact', fact_kind: 'deal_fact', text: 'Needs EU hosting', contact: null, quote: 'The pilot needs EU hosting.', badge: 'new', target_commitment_id: null, checked: true },
    { id: 'fact_1', kind: 'fact', fact_kind: 'personal', text: 'Enjoys trail running', contact: 'Anita', quote: 'I enjoy trail running.', badge: 'duplicate', target_commitment_id: null, checked: false },
  ],
}

describe('Capture page', () => {
  it('defaults to the latest meeting without notes and shows sizing and disabled guidance', async () => {
    mockFetch({ 'GET /api/meetings': { body: MEETINGS } })
    renderWithProviders(<Capture />)
    const meetingSelect = await screen.findByRole('combobox', { name: 'Choose meeting' })
    await waitFor(() => expect(meetingSelect).toHaveValue('m_up'))
    expect(screen.getByLabelText('Upload transcript file')).toHaveClass('h-11')
    expect(meetingSelect).toHaveClass('h-11')
    expect(screen.getByText('Choose a meeting and paste at least 50 characters')).toBeInTheDocument()
    expect(screen.getByRole('button', { name: 'Extract memories' })).toBeDisabled()
    expect(screen.queryByRole('heading', { name: 'Capture notes' })).not.toBeInTheDocument()
  })

  it('preselects the meeting from the query string', async () => {
    mockFetch({ 'GET /api/meetings': { body: MEETINGS } })
    renderRoutes(routes, { route: '/capture?meeting=m_recent' })
    const meetingSelect = await screen.findByRole('combobox', { name: 'Choose meeting' })
    await waitFor(() => expect(meetingSelect).toHaveValue('m_recent'))
  })

  it('sorts meetings newest-first, reviews a draft, allows duplicate re-check, and saves', async () => {
    const fetchMock = mockFetch({
      'GET /api/meetings': { body: MEETINGS },
      'POST /api/meetings/m_up/capture/preview': { status: 202, body: { job_id: 'job_preview' } },
      'GET /api/jobs/job_preview': { body: { id: 'job_preview', kind: 'capture_preview', status: 'done', draft: DRAFT } },
      'POST /api/capture/draft_1/save': { status: 202, body: { job_id: 'job_save' } },
      'GET /api/jobs/job_save': { body: { id: 'job_save', kind: 'capture_save', status: 'done', learned: { facts: ['Needs EU hosting'], new_commitments: 1, closed_commitments: 0, alerts: [] } } },
    })
    renderWithProviders(<Capture />)
    const meetingSelect = await screen.findByRole('combobox', { name: 'Choose meeting' })
    await screen.findByRole('option', { name: /Pilot decision/ })
    const options = Array.from(meetingSelect.querySelectorAll('option')).map((option) => option.textContent)
    expect(options[1]).toContain('Pilot decision')
    expect(options[2]).toContain('Budget review')
    expect(options[3]).toContain('Discovery')
    fireEvent.change(meetingSelect, { target: { value: 'm_up' } })
    fireEvent.change(screen.getByRole('textbox', { name: 'Meeting transcript or notes' }), { target: { value: 'A sufficiently long test transcript with an exact quote from Anita about a revised proposal and EU hosting.' } })
    fireEvent.click(screen.getByRole('button', { name: 'Extract memories' }))

    expect(await screen.findByRole('heading', { name: 'Review what the agent found' })).toBeInTheDocument()
    expect(screen.getByText('Merged into existing')).toBeInTheDocument()
    expect(screen.getByText('Unchecking removes an item from the ledger and fact list only. The transcript is still remembered; edit the notes to leave something out.')).toBeInTheDocument()
    const duplicate = screen.getByRole('checkbox', { name: 'Include Enjoys trail running' })
    expect(duplicate).not.toBeChecked()
    fireEvent.click(duplicate)
    expect(duplicate).toBeChecked()
    fireEvent.click(screen.getByRole('button', { name: 'Save to memory' }))

    expect(await screen.findByRole('heading', { name: 'Memory updated' })).toBeInTheDocument()
    expect(screen.getByRole('link', { name: 'Open the brief' })).toHaveAttribute('href', '/meetings/m_up')
    expect(screen.getByRole('link', { name: 'Open contact' })).toHaveAttribute('href', '/contacts/c_anita')
    const saveCall = fetchMock.calls.find((call) => call.method === 'POST' && call.path === '/api/capture/draft_1/save')
    expect(saveCall?.body).toEqual({ unchecked_item_ids: [] })
  })

  it('retries a memory-unavailable save with the same draft and no new preview', async () => {
    const fetchMock = mockFetch({
      'GET /api/meetings': { body: MEETINGS },
      'POST /api/meetings/m_up/capture/preview': { status: 202, body: { job_id: 'job_preview' } },
      'GET /api/jobs/job_preview': { body: { id: 'job_preview', kind: 'capture_preview', status: 'done', draft: DRAFT } },
      'POST /api/capture/draft_1/save': [
        { status: 202, body: { job_id: 'job_save_failed' } },
        { status: 202, body: { job_id: 'job_save_retry' } },
      ],
      'GET /api/jobs/job_save_failed': { body: { id: 'job_save_failed', kind: 'capture_save', status: 'failed', error: 'memory_unavailable' } },
      'GET /api/jobs/job_save_retry': { body: { id: 'job_save_retry', kind: 'capture_save', status: 'done', learned: { facts: ['Needs EU hosting'], new_commitments: 1, closed_commitments: 0, alerts: [] } } },
    })
    renderWithProviders(<Capture />)
    const meetingSelect = await screen.findByRole('combobox', { name: 'Choose meeting' })
    await screen.findByRole('option', { name: /Pilot decision/ })
    fireEvent.change(meetingSelect, { target: { value: 'm_up' } })
    fireEvent.change(screen.getByRole('textbox', { name: 'Meeting transcript or notes' }), { target: { value: 'A sufficiently long test transcript with an exact quote from Anita about a revised proposal and EU hosting.' } })
    fireEvent.click(screen.getByRole('button', { name: 'Extract memories' }))
    await screen.findByRole('heading', { name: 'Review what the agent found' })
    fireEvent.click(screen.getByRole('button', { name: 'Save to memory' }))

    expect(await screen.findByText('Memory temporarily unavailable. Your review is safe; retrying will not re-extract it.')).toBeInTheDocument()
    fireEvent.click(screen.getByRole('button', { name: 'Retry' }))
    expect(await screen.findByRole('heading', { name: 'Memory updated' })).toBeInTheDocument()
    expect(fetchMock.callsTo('POST /api/meetings/m_up/capture/preview')).toHaveLength(1)
    const saves = fetchMock.callsTo('POST /api/capture/draft_1/save')
    expect(saves).toHaveLength(2)
    expect(saves[0].body).toEqual(saves[1].body)
  })

  it('rejects non-text uploads and oversized files', async () => {
    mockFetch({ 'GET /api/meetings': { body: MEETINGS } })
    renderWithProviders(<Capture />)
    const upload = await screen.findByLabelText('Upload transcript file')
    fireEvent.change(upload, { target: { files: [new File(['audio'], 'voice.wav', { type: 'audio/wav' })] } })
    expect(await screen.findByText('Choose a .txt or .md file. Voice notes are not supported.')).toBeInTheDocument()
    fireEvent.change(upload, { target: { files: [new File(['x'.repeat(200_001)], 'oversized.txt', { type: 'text/plain' })] } })
    expect(await screen.findByText('Files must be 200 KB or smaller.')).toBeInTheDocument()
  })

  it('discards an open preview without attempting save', async () => {
    const fetchMock = mockFetch({
      'GET /api/meetings': { body: MEETINGS },
      'POST /api/meetings/m_up/capture/preview': { status: 202, body: { job_id: 'job_preview' } },
      'GET /api/jobs/job_preview': { body: { id: 'job_preview', kind: 'capture_preview', status: 'done', draft: DRAFT } },
      'DELETE /api/capture/draft_1': { status: 204 },
    })
    renderWithProviders(<Capture />)
    const meetingSelect = await screen.findByRole('combobox', { name: 'Choose meeting' })
    await screen.findByRole('option', { name: /Pilot decision/ })
    fireEvent.change(meetingSelect, { target: { value: 'm_up' } })
    expect(meetingSelect).toHaveValue('m_up')
    fireEvent.change(screen.getByRole('textbox', { name: 'Meeting transcript or notes' }), { target: { value: 'A sufficiently long test transcript with more than fifty characters to be accepted.' } })
    fireEvent.click(screen.getByRole('button', { name: 'Extract memories' }))
    await screen.findByRole('heading', { name: 'Review what the agent found' })
    fireEvent.click(screen.getByRole('button', { name: 'Discard' }))
    await waitFor(() => expect(fetchMock.calls.some((call) => call.method === 'DELETE')).toBe(true))
    expect(screen.getByRole('button', { name: 'Extract memories' })).toBeInTheDocument()
    expect(fetchMock.calls.some((call) => call.method === 'POST' && call.path.endsWith('/save'))).toBe(false)
  })
})
