import { fireEvent, screen } from '@testing-library/react'
import { describe, expect, it } from 'vitest'
import { Ask } from './Ask'
import { mockFetch } from '@/test/mockFetch'
import { renderWithProviders } from '@/test/renderWithProviders'

describe('Ask page', () => {
  it('changes scope from list endpoints and shows the selected answer citations', async () => {
    const calls = mockFetch({
      'GET /api/accounts': { body: [{ id: 'acc_1', name: 'FinEdge', industry: 'Fintech', stage: 'evaluation' }] },
      'GET /api/contacts': { body: [{ id: 'c_anita', name: 'Anita Rao', role: 'CFO', account_id: 'acc_1', account_name: 'FinEdge', meetings_count: 2, open_followups: 1, last_meeting_date: '2026-09-20', needs_review: false }] },
      'GET /api/meetings': { body: [{ id: 'm1', account_id: 'acc_1', account_name: 'FinEdge', title: 'Budget review', scheduled_at: '2026-09-20T10:00:00Z', status: 'done', attendees: [], brief_ready: true, prepared: false, open_followups: 0, past_meetings: 1, has_history: true, overdue_followups: 0, has_notes: true }] },
      'POST /api/ask': { body: { ask_answer_id: 'ans_1', answer: 'Anita said the budget is $75K.', grounded: true, citations: [{ source_type: 'meeting', meeting_id: 'm1', meeting_date: '2026-09-20', label: 'm1 on Sep 20, 2026', quote: 'Our budget is $75K.', memory_id: 'mem_1' }] } },
    })
    renderWithProviders(<Ask />)
    fireEvent.click(await screen.findByRole('button', { name: /change scope/i }))
    fireEvent.click(await screen.findByRole('button', { name: 'contact' }))
    fireEvent.click(await screen.findByRole('option', { name: /Anita Rao/i }))
    expect(screen.getByRole('button', { name: /Anita Rao/i })).toHaveTextContent('contact')
    expect(screen.getByRole('button', { name: /What have they said about priorities/i })).toBeInTheDocument()
    fireEvent.change(screen.getByRole('textbox', { name: 'Question' }), { target: { value: 'What did Anita say about the budget?' } })
    fireEvent.click(screen.getByRole('button', { name: 'Ask' }))
    expect(await screen.findByText('Anita said the budget is $75K.')).toBeInTheDocument()
    const sources = screen.getByRole('complementary', { name: 'Sources for this answer' })
    expect(sources).toHaveTextContent('Budget review · Sep 20, 2026')
    expect(sources).toHaveTextContent('Our budget is $75K.')
    expect(sources).not.toHaveTextContent('m1 on Sep 20, 2026')
    expect(calls.calls.some((call) => call.path.includes('suggested-questions'))).toBe(false)
  })

  it('shows the fixed not-found callout for an ungrounded answer', async () => {
    mockFetch({
      'GET /api/accounts': { body: [{ id: 'acc_1', name: 'FinEdge', industry: 'Fintech', stage: 'evaluation' }] },
      'GET /api/contacts': { body: [] }, 'GET /api/meetings': { body: [] },
      'POST /api/ask': { body: { ask_answer_id: 'ans_2', answer: 'Nothing in memory covers that yet.', grounded: false, citations: [] } },
    })
    renderWithProviders(<Ask />)
    fireEvent.change(await screen.findByRole('textbox', { name: 'Question' }), { target: { value: 'What is Rahul favourite food?' } })
    fireEvent.click(screen.getByRole('button', { name: 'Ask' }))
    expect(await screen.findByRole('note')).toHaveTextContent('Not found in memory')
  })

  it('shows explicit loading and keeps sources attached to the selected answer', async () => {
    let answerCount = 0
    mockFetch({
      'GET /api/accounts': { body: [{ id: 'acc_1', name: 'FinEdge', industry: 'Fintech', stage: 'evaluation' }] },
      'GET /api/contacts': { body: [] },
      'GET /api/meetings': { body: [{ id: 'm1', account_id: 'acc_1', account_name: 'FinEdge', title: 'Budget review', scheduled_at: '2026-09-20T10:00:00Z', status: 'done', attendees: [], brief_ready: true, prepared: false, open_followups: 0, past_meetings: 1, has_history: true, has_notes: true }] },
      'POST /api/ask': () => {
        answerCount += 1
        return { body: { ask_answer_id: `ans_${answerCount}`, answer: `Answer ${answerCount}`, grounded: true, citations: [{ source_type: 'meeting', meeting_id: 'm1', meeting_date: '2026-09-20', label: 'Budget review · Sep 20, 2026', quote: `Quote ${answerCount}`, memory_id: `mem_${answerCount}` }] } }
      },
    })
    renderWithProviders(<Ask />)
    await screen.findByRole('button', { name: /change scope/i })
    fireEvent.change(screen.getByRole('textbox', { name: 'Question' }), { target: { value: 'First question?' } })
    fireEvent.click(screen.getByRole('button', { name: 'Ask' }))
    await screen.findByText('Answer 1')
    fireEvent.change(screen.getByRole('textbox', { name: 'Question' }), { target: { value: 'Second question?' } })
    fireEvent.click(screen.getByRole('button', { name: 'Ask' }))
    await screen.findByText('Answer 2')
    fireEvent.click(screen.getByRole('button', { name: 'View sources for answer: First question?' }))
    expect(screen.getByRole('complementary', { name: 'Sources for this answer' })).toHaveTextContent('Quote 1')
    expect(screen.getByRole('button', { name: 'View sources for answer: First question?' })).toHaveAttribute('aria-pressed', 'true')
  })
})
