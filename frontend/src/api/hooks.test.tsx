import { QueryClientProvider } from '@tanstack/react-query'
import { act, renderHook, waitFor } from '@testing-library/react'
import type { ReactNode } from 'react'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import { createTestQueryClient } from '@/test/renderWithProviders'
import { mockFetch } from '@/test/mockFetch'
import { ApiError } from './errors'
import {
  JOB_POLL_MS,
  useBrief,
  useGenerateBrief,
  useJob,
  useMeetings,
  useSubmitNotes,
} from './hooks'
import { queryKeys } from './keys'

const BRIEF = {
  id: 'brf_1',
  meeting_id: 'mtg_1',
  mode: 'memory',
  generated_at: '2026-09-29T10:00:00Z',
  sections: [],
  facts_used: 3,
  preferences_applied: [],
}

function wrapperFor(client = createTestQueryClient()) {
  const wrapper = ({ children }: { children: ReactNode }) => (
    <QueryClientProvider client={client}>{children}</QueryClientProvider>
  )
  return { client, wrapper }
}

afterEach(() => {
  vi.unstubAllGlobals()
  vi.useRealTimers()
})

describe('useMeetings', () => {
  it('passes the status filter as a query param', async () => {
    const f = mockFetch({ 'GET /api/meetings': { body: [] } })
    const { wrapper } = wrapperFor()
    const { result } = renderHook(() => useMeetings('upcoming'), { wrapper })
    await waitFor(() => expect(result.current.isSuccess).toBe(true))
    expect(f.calls[0].search).toBe('?status=upcoming')
  })
})

describe('useBrief', () => {
  it('turns a 404 into null and never POSTs', async () => {
    const f = mockFetch({
      'GET /api/meetings/mtg_1/brief': {
        status: 404,
        body: { error: { code: 'not_found', message: 'No brief' } },
      },
      'POST /api/meetings/mtg_1/brief': { body: BRIEF },
    })
    const { wrapper } = wrapperFor()
    const { result } = renderHook(() => useBrief('mtg_1', 'memory'), { wrapper })
    await waitFor(() => expect(result.current.isSuccess).toBe(true))
    expect(result.current.data).toBeNull()
    expect(f.calls.map((c) => c.method)).toEqual(['GET'])
    expect(f.calls[0].search).toBe('?mode=memory')
  })

  it('returns the stored brief on 200', async () => {
    mockFetch({ 'GET /api/meetings/mtg_1/brief': { body: BRIEF } })
    const { wrapper } = wrapperFor()
    const { result } = renderHook(() => useBrief('mtg_1', 'memory'), { wrapper })
    await waitFor(() => expect(result.current.data?.id).toBe('brf_1'))
  })

  it('surfaces other errors as ApiError', async () => {
    mockFetch({
      'GET /api/meetings/mtg_1/brief': {
        status: 503,
        body: { error: { code: 'memory_unavailable', message: 'down' } },
      },
    })
    const { wrapper } = wrapperFor()
    const { result } = renderHook(() => useBrief('mtg_1', 'memory'), { wrapper })
    await waitFor(() => expect(result.current.isError).toBe(true))
    expect(result.current.error).toBeInstanceOf(ApiError)
    expect((result.current.error as ApiError).code).toBe('memory_unavailable')
  })
})

describe('useGenerateBrief', () => {
  it('is pending while in flight and writes the result into the useBrief cache', async () => {
    const f = mockFetch({
      'POST /api/meetings/mtg_1/brief': { body: BRIEF, delayMs: 300 },
    })
    const { client, wrapper } = wrapperFor()
    const { result } = renderHook(() => useGenerateBrief('mtg_1', 'memory'), { wrapper })

    act(() => {
      result.current.mutate()
    })
    await waitFor(() => expect(result.current.isPending).toBe(true))
    await waitFor(() => expect(result.current.isSuccess).toBe(true))

    expect(result.current.isPending).toBe(false)
    expect(client.getQueryData(queryKeys.brief('mtg_1', 'memory'))).toEqual(BRIEF)
    expect(f.calls[0]).toMatchObject({ method: 'POST', search: '?mode=memory' })
  })
})

describe('useJob', () => {
  beforeEach(() => {
    vi.useFakeTimers({ shouldAdvanceTime: true })
  })

  it('polls every 2.5 s and stops once done', async () => {
    const f = mockFetch({
      'GET /api/jobs/job_1': [
        { body: { id: 'job_1', kind: 'ingest', status: 'pending' } },
        { body: { id: 'job_1', kind: 'ingest', status: 'pending' } },
        {
          body: {
            id: 'job_1',
            kind: 'ingest',
            status: 'done',
            learned: { facts: [], new_commitments: 1, closed_commitments: 0, alerts: [] },
          },
        },
      ],
    })
    const { wrapper } = wrapperFor()
    const { result } = renderHook(() => useJob('job_1'), { wrapper })
    await waitFor(() => expect(f.calls).toHaveLength(1))
    await act(() => vi.advanceTimersByTimeAsync(JOB_POLL_MS))
    await waitFor(() => expect(f.calls).toHaveLength(2))
    await act(() => vi.advanceTimersByTimeAsync(JOB_POLL_MS))
    await waitFor(() => expect(result.current.data?.status).toBe('done'))
    const n = f.calls.length
    await act(() => vi.advanceTimersByTimeAsync(JOB_POLL_MS * 4))
    expect(f.calls).toHaveLength(n)
  })

  it('stops polling on failed', async () => {
    const f = mockFetch({
      'GET /api/jobs/job_2': { body: { id: 'job_2', kind: 'ingest', status: 'failed', error: 'llm_timeout' } },
    })
    const { wrapper } = wrapperFor()
    const { result } = renderHook(() => useJob('job_2'), { wrapper })
    await waitFor(() => expect(result.current.data?.status).toBe('failed'))
    await act(() => vi.advanceTimersByTimeAsync(JOB_POLL_MS * 4))
    expect(f.calls).toHaveLength(1)
  })

  it('does not fetch without a job id', async () => {
    const f = mockFetch({})
    const { wrapper } = wrapperFor()
    renderHook(() => useJob(undefined), { wrapper })
    await act(() => vi.advanceTimersByTimeAsync(JOB_POLL_MS * 2))
    expect(f.calls).toHaveLength(0)
  })

  it('gives up after about 150 s of pending', async () => {
    const f = mockFetch({
      'GET /api/jobs/job_3': { body: { id: 'job_3', kind: 'ingest', status: 'pending' } },
    })
    const { wrapper } = wrapperFor()
    renderHook(() => useJob('job_3'), { wrapper })
    await act(() => vi.advanceTimersByTimeAsync(170_000))
    const n = f.calls.length
    expect(n).toBeGreaterThan(50)
    expect(n).toBeLessThanOrEqual(62)
    await act(() => vi.advanceTimersByTimeAsync(20_000))
    expect(f.calls).toHaveLength(n)
  })
})

describe('useSubmitNotes', () => {
  it('POSTs the transcript to the (mocked) notes endpoint and returns the job id', async () => {
    const f = mockFetch({
      'POST /api/meetings/mtg_1/notes': { status: 202, body: { job_id: 'job_9' } },
    })
    const { wrapper } = wrapperFor()
    const { result } = renderHook(() => useSubmitNotes('mtg_1'), { wrapper })
    let out: { job_id: string } | undefined
    await act(async () => {
      out = await result.current.mutateAsync('Met with Dana about pricing.')
    })
    expect(out?.job_id).toBe('job_9')
    expect(f.calls[0].body).toEqual({ transcript: 'Met with Dana about pricing.' })
  })
})
