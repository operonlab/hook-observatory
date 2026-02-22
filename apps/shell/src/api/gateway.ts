import type { User } from "@/types";

const BASE = "";

interface AuthResponse {
  user: User;
}

async function request<T>(
  path: string,
  options?: RequestInit,
): Promise<T> {
  const res = await fetch(`${BASE}${path}`, {
    credentials: "include",
    headers: {
      "Content-Type": "application/json",
    },
    ...options,
  });

  if (!res.ok) {
    const body = await res.json().catch(() => ({}));
    throw new Error(
      (body as Record<string, string>).detail ||
        (body as Record<string, string>).message ||
        `Request failed: ${res.status}`,
    );
  }

  return res.json();
}

export function register(
  email: string,
  password: string,
  name: string,
): Promise<AuthResponse> {
  return request<AuthResponse>("/auth/register", {
    method: "POST",
    body: JSON.stringify({ email, password, name }),
  });
}

export function login(
  email: string,
  password: string,
): Promise<AuthResponse> {
  return request<AuthResponse>("/auth/login", {
    method: "POST",
    body: JSON.stringify({ email, password }),
  });
}

export async function logout(): Promise<void> {
  const res = await fetch("/auth/logout", {
    method: "POST",
    credentials: "include",
  });
  if (!res.ok) {
    throw new Error(`Logout failed: ${res.status}`);
  }
}

export function getSession(): Promise<AuthResponse> {
  return request<AuthResponse>("/auth/session", {
    method: "GET",
  });
}
