import type { User } from '@/types'

// Auth endpoints are always at root — never prefixed by BASE_PATH
const AUTH_BASE = ''

interface AuthResponse {
  user: User
}

interface RawUser {
  id: string
  email: string
  display_name: string
  avatar_url: string | null
  role: string
  status: string
  created_at: string
}

function mapUser(raw: RawUser): User {
  return {
    id: raw.id,
    email: raw.email,
    name: raw.display_name || raw.email,
    avatar_url: raw.avatar_url,
    role: raw.role,
    status: raw.status,
    created_at: raw.created_at,
  }
}

async function request<T>(path: string, options?: RequestInit): Promise<T> {
  const res = await fetch(`${AUTH_BASE}${path}`, {
    credentials: 'include',
    headers: {
      'Content-Type': 'application/json',
    },
    ...options,
  })

  if (!res.ok) {
    const body = await res.json().catch(() => ({}))
    throw new Error(
      (body as Record<string, string>).detail ||
        (body as Record<string, string>).message ||
        `Request failed: ${res.status}`,
    )
  }

  return res.json()
}

export async function register(
  email: string,
  password: string,
  name: string,
): Promise<AuthResponse> {
  const r = await request<{ user: RawUser }>('/auth/register', {
    method: 'POST',
    body: JSON.stringify({ email, password, name }),
  })
  return { user: mapUser(r.user) }
}

export async function login(email: string, password: string): Promise<AuthResponse> {
  const r = await request<{ user: RawUser }>('/auth/login', {
    method: 'POST',
    body: JSON.stringify({ email, password }),
  })
  return { user: mapUser(r.user) }
}

export async function logout(): Promise<void> {
  const res = await fetch(`${AUTH_BASE}/auth/logout`, {
    method: 'POST',
    credentials: 'include',
    headers: {
      'Content-Type': 'application/json',
    },
  })
  if (!res.ok) {
    throw new Error(`Logout failed: ${res.status}`)
  }
}

export async function getSession(): Promise<AuthResponse> {
  const r = await request<{ user: RawUser }>('/auth/session', {
    method: 'GET',
  })
  return { user: mapUser(r.user) }
}
