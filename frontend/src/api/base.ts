let _apiBase = ''

function isTauri(): boolean {
  return typeof (window as Window & { __TAURI_INTERNALS__?: unknown }).__TAURI_INTERNALS__ !== 'undefined'
}

/**
 * Call once at app startup before any API requests.
 * In Tauri mode: resolves the port from the Rust side and sets the absolute base URL.
 * In pywebview mode: no-op; relative URLs work as-is.
 */
export async function initApiBase(): Promise<void> {
  if (!isTauri()) return

  const { invoke } = await import('@tauri-apps/api/core')

  // Setup blocks until the sidecar reports its port, so this should be non-zero
  // immediately. Retry briefly as a safety net for slow machines.
  let port = 0
  for (let i = 0; i < 100; i++) {
    port = await invoke<number>('api_port')
    if (port > 0) break
    await new Promise<void>(r => setTimeout(r, 100))
  }

  if (port === 0) {
    throw new Error('Storyboard backend did not start in time')
  }

  _apiBase = `http://127.0.0.1:${port}`
}

export function apiBase(): string {
  return _apiBase
}
