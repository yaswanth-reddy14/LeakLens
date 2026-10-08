export const isHosted = import.meta.env.VITE_HOSTED_DEMO === 'true'
const base = (import.meta.env.VITE_API_BASE_URL || '').replace(/\/$/, '')
if (
  base &&
  (!/^https:\/\/[^/?#]+$/.test(base) || new URL(base).username || new URL(base).password)
) {
  throw new Error(
    'VITE_API_BASE_URL must be an HTTPS origin without a path, credentials, or trailing query.',
  )
}
if (isHosted && !base) throw new Error('Set VITE_API_BASE_URL for a hosted build.')
export const apiUrl = (path: string) => `${base}${path}`
export const viewStorage = () => (isHosted ? sessionStorage : localStorage)
const key = 'leaklens-session-v1'
let creating: Promise<string> | null = null

async function sessionToken(): Promise<string> {
  const saved = sessionStorage.getItem(key)
  if (saved) return saved
  if (!creating) {
    creating = (async () => {
      const response = await fetch(apiUrl('/api/sessions'), {
        method: 'POST',
        signal: AbortSignal.timeout(15000),
      })
      if (!response.ok)
        throw new Error('Could not start a private demo session. Please try again shortly.')
      const result = await response.json()
      if (typeof result.token !== 'string') throw new Error('Invalid session response.')
      // Bearer credential: keep out of URLs, logs and shared localStorage.
      sessionStorage.setItem(key, result.token)
      return result.token as string
    })().finally(() => {
      creating = null
    })
  }
  return creating
}

export async function apiFetch(path: string, init: RequestInit = {}): Promise<Response> {
  const headers = new Headers(init.headers)
  if (isHosted) headers.set('Authorization', `Bearer ${await sessionToken()}`)
  // Do not automatically retry a mutation or silently replace an expired session.
  const response = await fetch(apiUrl(path), { ...init, headers })
  if (response.status === 401 && isHosted)
    throw new Error(
      'Your demo session has expired or is unavailable. Use Start new hosted session; the previous session will not be restored.',
    )
  return response
}

export function restartHostedSession() {
  sessionStorage.removeItem(key)
  sessionStorage.removeItem('leaklens-view')
  window.location.reload()
}
