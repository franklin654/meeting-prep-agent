import { describe, expect, it } from 'vitest'
import { ApiError, describeError } from './errors'

describe('describeError', () => {
  const cases: [string, number, RegExp][] = [
    ['not_found', 404, /could not find/i],
    ['validation_error', 422, /check|invalid/i],
    ['memory_unavailable', 503, /memory/i],
    ['llm_timeout', 504, /too long|timed out/i],
    ['llm_invalid_output', 502, /unusable|invalid|try again/i],
    ['rate_limited', 429, /too many|rate|wait/i],
    ['internal_error', 500, /went wrong|unexpected/i],
    ['network_error', 0, /reach the server|network|connection/i],
  ]

  it.each(cases)('maps %s (%i) to a readable message', (code, status, pattern) => {
    const message = describeError(new ApiError({ code, status, message: 'raw backend text' }))
    expect(message).toMatch(pattern)
    expect(message).not.toContain('raw backend text')
    expect(message).not.toContain(code)
  })

  it('falls back to the status when the code is unknown', () => {
    expect(describeError(new ApiError({ code: 'weird', status: 503, message: 'x' }))).toMatch(/memory/i)
  })

  it('handles unknown errors and plain TypeErrors from fetch', () => {
    expect(describeError(new TypeError('Failed to fetch'))).toMatch(/reach the server/i)
    expect(describeError('boom')).toMatch(/went wrong/i)
  })
})
