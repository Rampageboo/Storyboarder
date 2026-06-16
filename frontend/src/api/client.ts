export class ApiError extends Error {
  readonly status: number

  constructor(status: number, message: string) {
    super(message)
    this.name = 'ApiError'
    this.status = status
  }
}

export interface RequestOptions extends Omit<RequestInit, 'body'> {
  body?: BodyInit | object | null
  silent?: boolean
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

async function readErrorMessage(response: Response): Promise<string> {
  let message = response.statusText
  try {
    const payload = (await response.json()) as { detail?: string; error?: string }
    message = payload.detail || payload.error || message
  } catch {
    // Keep HTTP status when body is not JSON.
  }
  return message
}

export async function requestJson<T>(url: string, options: RequestOptions = {}): Promise<T> {
  const { silent: _silent, body, headers: customHeaders, ...fetchOptions } = options
  const headers = new Headers(customHeaders)
  const response = await fetch(url, {
    ...fetchOptions,
    headers,
    body: buildBody(body, headers),
  })

  if (!response.ok) {
    throw new ApiError(response.status, await readErrorMessage(response))
  }

  if (response.status === 204) {
    return {} as T
  }

  return (await response.json()) as T
}

export function isNoProjectOpenError(error: unknown): boolean {
  return error instanceof ApiError && error.status === 400 && /no project opened/i.test(error.message)
}
