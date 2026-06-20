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
  const response = await fetch(url, {
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
