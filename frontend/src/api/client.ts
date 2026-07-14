import { apiBase } from './base'

// Per-launch API token injected into the served document by the backend
// (see _react_index_response in api.py). Sent on every API request so the
// backend can reject cross-origin / unauthenticated state-changing calls.
function readApiToken(): string {
  if (typeof document !== 'undefined') {
    const meta = document.querySelector('meta[name="storyboarder-token"]')
    const content = meta?.getAttribute('content')
    if (content) return content
  }
  const injected = (window as Window & { __STORYBOARDER_TOKEN__?: string }).__STORYBOARDER_TOKEN__
  return typeof injected === 'string' ? injected : ''
}

const API_TOKEN = readApiToken()

export class ApiError extends Error {
  readonly status: number
  readonly code: string | undefined

  constructor(status: number, message: string, code?: string) {
    super(message)
    this.name = 'ApiError'
    this.status = status
    this.code = code
  }
}

export interface RequestOptions extends Omit<RequestInit, 'body'> {
  body?: BodyInit | object | null
}

function buildBody(
  body: RequestOptions['body'],
  headers: Headers,
): BodyInit | undefined {
  if (body == null) return undefined
  if (body instanceof FormData || typeof body === 'string') return body
  if (!headers.has('Content-Type')) {
    headers.set('Content-Type', 'application/json')
  }
  return JSON.stringify(body)
}

async function readErrorMessage(response: Response): Promise<{ message: string; code?: string }> {
  let message = response.statusText
  let code: string | undefined
  try {
    const payload = (await response.json()) as { detail?: string; error?: string; code?: string }
    message = payload.detail || payload.error || message
    code = payload.code
  } catch {
    // Keep HTTP status when body is not JSON.
  }
  return { message, code }
}

export async function requestJson<T>(url: string, options: RequestOptions = {}): Promise<T> {
  const { body, headers: customHeaders, ...fetchOptions } = options
  const headers = new Headers(customHeaders)
  if (API_TOKEN && !headers.has('X-Storyboarder-Token')) {
    headers.set('X-Storyboarder-Token', API_TOKEN)
  }
  const response = await fetch(apiBase() + url, {
    ...fetchOptions,
    headers,
    body: buildBody(body, headers),
  })

  if (!response.ok) {
    const { message, code } = await readErrorMessage(response)
    throw new ApiError(response.status, message, code)
  }

  if (response.status === 204) {
    return {} as T
  }

  return (await response.json()) as T
}

export function isNoProjectOpenError(error: unknown): boolean {
  return (
    error instanceof ApiError &&
    (error.code === 'PROJECT_NOT_OPEN' ||
      (error.status === 400 && /no project opened/i.test(error.message)))
  )
}
