import { fireEvent, screen } from '@testing-library/react'
import { describe, expect, it } from 'vitest'
import { AskPanel } from './AskPanel'
import { mockFetch } from '@/test/mockFetch'
import { renderWithProviders } from '@/test/renderWithProviders'

describe('AskPanel', () => {
  it('shows the ungrounded response without citation chips using mocked Ask data', async () => {
    const f = mockFetch({
      'GET /api/meetings/mtg_1/suggested-questions': { body: { questions: [] } },
      'POST /api/ask': { body: { ask_answer_id: 'ask_empty', answer: 'Nothing in memory covers that yet.', grounded: false, citations: [] } },
    })
    renderWithProviders(<AskPanel scopeType="meeting" scopeId="mtg_1" meetingId="mtg_1" />, { route: '/meetings/mtg_1' })
    fireEvent.click(screen.getByRole('button', { name: 'Open Ask' }))
    fireEvent.change(await screen.findByRole('textbox', { name: 'Question' }), { target: { value: 'Any recent forecast?' } })
    fireEvent.click(screen.getByRole('button', { name: 'Ask' }))
    expect(await screen.findByText('Nothing in memory covers that yet.')).toBeInTheDocument()
    expect(f.calls.every((call) => call.path !== '/api/meetings/mtg_1/notes')).toBe(true)
  })

  it('loads P4 suggestions, asks with citations, and can remember a note using mocked responses', async () => {
    const f = mockFetch({
      'GET /api/meetings/mtg_1/suggested-questions': { body: { questions: ['What changed about budget?'] } },
      'POST /api/ask': { body: { ask_answer_id: 'ask_1', answer: 'Budget is $40K.', grounded: true, citations: [{ source_type: 'meeting', meeting_id: 'mtg_old', meeting_date: '2026-09-20', label: 'M4 · Sep 20', quote: 'Budget is $40K.', memory_id: 'mem_1' }] } },
      'POST /api/ask/ask_1/pin': { body: { ask_answer_id: 'ask_1', answer: 'Budget is $40K.', grounded: true, citations: [{ source_type: 'meeting', meeting_id: 'mtg_old', meeting_date: '2026-09-20', label: 'M4 · Sep 20', quote: 'Budget is $40K.', memory_id: 'mem_1' }] } },
      'POST /api/memories/notes': { status: 202, body: { job_id: 'job_1' } },
    })
    renderWithProviders(<AskPanel scopeType="meeting" scopeId="mtg_1" meetingId="mtg_1" />, { route: '/meetings/mtg_1' })
    fireEvent.click(await screen.findByRole('button', { name: 'Open Ask' }))
    expect(await screen.findByRole('button', { name: 'What changed about budget?' })).toBeInTheDocument()
    fireEvent.change(screen.getByRole('textbox', { name: 'Question' }), { target: { value: 'What is the budget?' } })
    fireEvent.click(screen.getByRole('button', { name: 'Ask' }))
    expect(await screen.findByText('Budget is $40K.')).toBeInTheDocument()
    expect(await screen.findByRole('link', { name: 'M4 · Sep 20' })).toHaveAttribute('href', '/meetings/mtg_old')
    fireEvent.click(screen.getByRole('button', { name: 'Pin to brief' }))
    expect(await screen.findByText('Pinned to brief')).toBeInTheDocument()
    fireEvent.change(screen.getByRole('textbox', { name: 'Remember this note' }), { target: { value: 'Anita prefers short emails.' } })
    fireEvent.click(screen.getByRole('button', { name: 'Remember this' }))
    expect(await screen.findByText('Note remembered')).toBeInTheDocument()
    expect(f.calls.map((call) => call.method)).toEqual(['GET', 'POST', 'POST', 'POST'])
    expect(f.calls.some((call) => call.path.endsWith('/notes') && call.path.includes('/meetings/'))).toBe(false)
  })
})
