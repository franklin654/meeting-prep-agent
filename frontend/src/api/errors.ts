/**
 * Backend error envelope: {"error": {"code", "message"}} (docs/data-model-and-schemas.md).
 * `code` values used by the UI: not_found, validation_error, memory_unavailable,
 * llm_timeout, llm_invalid_output, rate_limited, internal_error; plus
 * `network_error` (status 0) raised client-side when fetch itself fails.
 */
export class ApiError extends Error {
  readonly code: string
  readonly status: number

  constructor({ code, status, message }: { code: string; status: number; message: string }) {
    super(message)
    this.name = 'ApiError'
    this.code = code
    this.status = status
  }
}

const STATUS_CODES: Record<number, string> = {
  404: 'not_found',
  422: 'validation_error',
  429: 'rate_limited',
  502: 'llm_invalid_output',
  503: 'memory_unavailable',
  504: 'llm_timeout',
  500: 'internal_error',
}

const MESSAGES: Record<string, string> = {
  not_found: 'We could not find that. It may have been removed or not created yet.',
  validation_error: 'Something in the request is invalid. Check the details and try again.',
  memory_unavailable: 'Memory is unavailable right now. Try again in a moment.',
  llm_timeout: 'The model took too long to respond. Try again.',
  llm_invalid_output: 'The model returned an unusable answer. Try again.',
  rate_limited: 'Too many requests. Wait a few seconds and try again.',
  internal_error: 'Something went wrong on our side. Try again.',
  network_error: 'Could not reach the server. Check your connection and try again.',
}

const FALLBACK = 'Something went wrong. Try again.'

/** Build an ApiError from a failed Response and its (already read) body text. */
export function apiErrorFromResponse(status: number, bodyText: string): ApiError {
  let code = STATUS_CODES[status] ?? (status >= 500 ? 'internal_error' : 'unknown_error')
  let message = `Request failed with status ${status}`
  try {
    const body: unknown = JSON.parse(bodyText)
    if (body && typeof body === 'object') {
      const env = (body as { error?: { code?: unknown; message?: unknown } }).error
      if (env && typeof env.code === 'string') code = env.code
      if (env && typeof env.message === 'string') message = env.message
    }
  } catch {
    // Non-JSON body: keep the status-derived code.
  }
  return new ApiError({ code, status, message })
}

/** A readable, user-facing message for any thrown value. */
export function describeError(err: unknown): string {
  if (err instanceof ApiError) {
    return MESSAGES[err.code] ?? MESSAGES[STATUS_CODES[err.status] ?? ''] ?? FALLBACK
  }
  if (err instanceof TypeError) return MESSAGES.network_error
  return FALLBACK
}
