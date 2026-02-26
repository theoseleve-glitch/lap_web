/**
 * Typed API client for the Flask telemetry backend.
 * All requests go through /api/v1/ which Next.js rewrites to the Flask server.
 */

const API_BASE = '/api/v1';

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
  const res = await fetch(`${API_BASE}${path}`, {
    ...init,
    headers: {
      'Content-Type': 'application/json',
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
