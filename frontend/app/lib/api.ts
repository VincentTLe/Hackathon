export const API_URL = process.env.NEXT_PUBLIC_API_URL ?? 'http://localhost:8000'

export function founderToken(): string | null {
  if (typeof window === 'undefined') return null
  return window.localStorage.getItem('bridge_founder_token')
}
export function setFounderToken(t: string) {
  window.localStorage.setItem('bridge_founder_token', t)
}

export function receiverToken(): string | null {
  if (typeof window === 'undefined') return null
  return window.localStorage.getItem('bridge_receiver_token')
}
export function setReceiverToken(t: string) {
  window.localStorage.setItem('bridge_receiver_token', t)
}

export function tokenForConnection(connId: string): string | null {
  return founderToken() ?? receiverToken()
}

async function req<T>(path: string, init: RequestInit = {}, token?: string | null): Promise<T> {
  const headers: Record<string, string> = { 'Content-Type': 'application/json', ...(init.headers as any) }
  if (token) headers.Authorization = `Bearer ${token}`
  const r = await fetch(`${API_URL}${path}`, { ...init, headers })
  if (!r.ok) {
    const body = await r.text()
    throw new Error(`${r.status}: ${body}`)
  }
  return r.json()
}

export const api = {
  onboardFounder: (name: string, answers: string[]) =>
    req<any>('/onboarding/founder', { method: 'POST', body: JSON.stringify({ name, answers }) }),
  createConnection: (receiver_display_name: string, relationship: string, invite_note: string) =>
    req<any>('/connections', { method: 'POST', body: JSON.stringify({ receiver_display_name, relationship, invite_note }) }, founderToken()),
  listConnections: () => req<any>('/connections', {}, founderToken()),
  invitePreview: (token: string) => req<any>(`/connections/invite/${token}`),
  accept: (magic_link_token: string, receiver_name: string) =>
    req<any>('/session/b-accept', { method: 'POST', body: JSON.stringify({ magic_link_token, receiver_name }) }),
  translate: (connection_id: string, raw_message: string, token: string) =>
    req<any>('/messages/translate', { method: 'POST', body: JSON.stringify({ connection_id, raw_message }) }, token),
  approve: (preview_id: string, token: string) =>
    req<any>('/messages/approve', { method: 'POST', body: JSON.stringify({ preview_id }) }, token),
  list: (connection_id: string, since: string | null, token: string) =>
    req<any>(`/messages/${connection_id}${since ? `?since=${encodeURIComponent(since)}` : ''}`, {}, token),
}
