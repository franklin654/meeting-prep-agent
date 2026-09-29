import { screen, waitFor } from '@testing-library/react'
import { describe, expect, it } from 'vitest'
import { NudgeDigest } from './NudgeDigest'
import { mockFetch } from '@/test/mockFetch'
import { renderWithProviders } from '@/test/renderWithProviders'

const NUDGES = [
  { kind: 'overdue_commitment', text: 'Pricing deck is 25 days overdue (FinEdge)', link: '/meetings/m6_finedge' },
  { kind: 'they_owe_overdue', text: 'Waiting on the vendor shortlist (FinEdge)', link: '/meetings/m6_finedge' },
  { kind: 'no_history', text: 'No history yet: Northstar\'s first meeting is coming up', link: '/meetings/m_first' },
  { kind: 'brief_ready', text: 'Brief ready: Pilot decision - FinEdge, Sep 29', link: '/meetings/m6_finedge' },
  { kind: 'silent_contact', text: "Sneha Iyer hasn't been on a call for 47 days", link: '/meetings/m6_finedge' },
]

describe('NudgeDigest', () => {
  it('shows a skeleton while loading', () => {
    mockFetch({ 'GET /api/nudges': { body: NUDGES, delayMs: 100 } })
    const { container } = renderWithProviders(<NudgeDigest />)
    expect(screen.getByLabelText('Loading nudges')).toBeInTheDocument()
    expect(container.querySelectorAll('[data-slot="skeleton"]').length).toBeGreaterThan(0)
  })

  it('renders every nudge kind as a route link', async () => {
    const fetchMock = mockFetch({ 'GET /api/nudges': { body: NUDGES } })
    renderWithProviders(<NudgeDigest />)
    expect(await screen.findByRole('heading', { name: 'Needs your attention' })).toBeInTheDocument()
    for (const nudge of NUDGES) {
      expect(screen.getByRole('link', { name: nudge.text })).toHaveAttribute('href', nudge.link)
    }
    expect(fetchMock.calls.map((call) => call.method)).toEqual(['GET'])
  })

  it('renders an explicit empty state for an empty response', async () => {
    const fetchMock = mockFetch({ 'GET /api/nudges': { body: [] } })
    renderWithProviders(<NudgeDigest />)
    await waitFor(() => expect(fetchMock.calls).toHaveLength(1))
    expect(await screen.findByText('You’re all caught up.')).toBeInTheDocument()
  })

  it('renders an error state on request failure', async () => {
    const fetchMock = mockFetch({ 'GET /api/nudges': { status: 503, body: { error: { code: 'server_error', message: 'unavailable' } } } })
    renderWithProviders(<NudgeDigest />)
    await waitFor(() => expect(fetchMock.calls).toHaveLength(1))
    expect(await screen.findByText('Needs your attention could not be loaded.')).toBeInTheDocument()
  })
})
