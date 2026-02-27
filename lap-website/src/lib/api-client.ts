/**
 * Typed API client for the Flask telemetry backend.
 * Calls the backend API directly via CORS (no Next.js rewrite proxy).
 */

import { getAccessToken } from './auth-store';

const BACKEND_URL = process.env.NEXT_PUBLIC_API_URL || 'http://localhost:5000';
const API_BASE = `${BACKEND_URL}/api/v1`;

export class ApiError extends Error {
  constructor(
    public code: string,
    message: string,
    public status: number,
    public details?: Array<{ field?: string; message: string }>,
  ) {
    super(message);
    this.name = 'ApiError';
  }
}

interface ApiEnvelope<T> {
  ok: boolean;
  data: T;
  error?: { code: string; message: string; details?: Array<{ field?: string; message: string }> };
  meta: { request_id: string };
}

/**
 * Fetch from the API, unwrapping the standard envelope.
 * Throws ApiError on non-ok responses.
 */
export async function apiFetch<T>(path: string, init?: RequestInit): Promise<T> {
  const headers: Record<string, string> = {
    'Content-Type': 'application/json',
  };

  // Attach JWT token from in-memory store (never localStorage)
  if (typeof window !== 'undefined') {
    const token = getAccessToken();
    if (token) {
      headers['Authorization'] = `Bearer ${token}`;
    }
  }

  const res = await fetch(`${API_BASE}${path}`, {
    ...init,
    headers: {
      ...headers,
      ...init?.headers,
    },
    credentials: 'include',
  });

  const body: ApiEnvelope<T> = await res.json();

  if (!body.ok) {
    throw new ApiError(
      body.error?.code ?? 'UNKNOWN',
      body.error?.message ?? 'Request failed',
      res.status,
      body.error?.details,
    );
  }

  return body.data;
}

/** Convenience wrappers */
export const api = {
  get: <T>(path: string) => apiFetch<T>(path),
  post: <T>(path: string, data?: unknown) =>
    apiFetch<T>(path, { method: 'POST', body: data ? JSON.stringify(data) : undefined }),
  put: <T>(path: string, data?: unknown) =>
    apiFetch<T>(path, { method: 'PUT', body: data ? JSON.stringify(data) : undefined }),
  delete: <T>(path: string) => apiFetch<T>(path, { method: 'DELETE' }),
};
