/**
 * Typed API client for the Flask telemetry backend.
 * Calls the backend API directly via CORS (no Next.js rewrite proxy).
 *
 * Includes a transparent 401 retry: when an API call fails with 401
 * (expired access token), we attempt a single silent refresh via the
 * httpOnly cookie and then replay the original request.
 */

import { getAccessToken, broadcastLogout } from './auth-store';
import { parseEnvelopeOrThrow } from './http-envelope';

/**
 * Custom event emitted when a 401 cannot be recovered by silent refresh.
 * The AuthGuard listens for this to show the SessionExpiredModal.
 */
export const SESSION_EXPIRED_EVENT = 'lap:session-expired';

export const BACKEND_URL = process.env.NEXT_PUBLIC_API_URL || 'http://localhost:5000';
const API_BASE = `${BACKEND_URL}/api/v1`;

export class ApiError extends Error {
  constructor(
    public code: string,
    message: string,
    public status: number,
    public details?: Array<{ field?: string; message: string }>,
    public requestId?: string,
  ) {
    super(message);
    this.name = 'ApiError';
  }
}

// Deduplication: only one silent-refresh in flight at a time.
let _refreshPromise: Promise<boolean> | null = null;

async function tryRefreshOnce(): Promise<boolean> {
  if (_refreshPromise) return _refreshPromise;
  _refreshPromise = (async () => {
    try {
      const { silentRefresh } = await import('./auth');
      const user = await silentRefresh();
      return user !== null;
    } catch {
      return false;
    } finally {
      _refreshPromise = null;
    }
  })();
  return _refreshPromise;
}

function buildHeaders(): Record<string, string> {
  const headers: Record<string, string> = {
    'Content-Type': 'application/json',
  };

  // Generate client-side request ID for distributed tracing
  if (typeof crypto !== 'undefined' && crypto.randomUUID) {
    headers['X-Request-Id'] = crypto.randomUUID();
  }

  if (typeof window !== 'undefined') {
    const token = getAccessToken();
    if (token) {
      headers['Authorization'] = `Bearer ${token}`;
    }

    // Attach CSRF token from cookie (double-submit pattern)
    const csrfMatch = document.cookie.match(/(?:^|;\s*)csrf_token=([^;]+)/);
    if (csrfMatch) {
      headers['X-CSRF-Token'] = csrfMatch[1] ?? '';
    }
  }

  return headers;
}

// In-flight GET request deduplication: identical concurrent GETs share one fetch.
const _inflightGets = new Map<string, Promise<unknown>>();

/**
 * Fetch from the API, unwrapping the standard envelope.
 * On 401, transparently attempts a single silent refresh and retries.
 * Concurrent identical GET requests are deduplicated (coalesced).
 */
export async function apiFetch<T>(path: string, init?: RequestInit): Promise<T> {
  const method = init?.method?.toUpperCase() ?? 'GET';
  if (method === 'GET') {
    const existing = _inflightGets.get(path);
    if (existing) return existing as Promise<T>;
    const promise = _apiFetchInner<T>(path, init).finally(() => _inflightGets.delete(path));
    _inflightGets.set(path, promise);
    return promise;
  }
  return _apiFetchInner<T>(path, init);
}

async function _apiFetchInner<T>(path: string, init?: RequestInit): Promise<T> {
  const headers = buildHeaders();

  // CRITICAL: cache: 'no-store' is required. Without it the browser HTTP
  // cache can serve stale list data after a DELETE, causing deleted items to
  // reappear instantly (the "ghost row" bug). Do NOT remove or weaken this.
  const res = await fetch(`${API_BASE}${path}`, {
    ...init,
    headers: { ...headers, ...init?.headers },
    credentials: 'include',
    cache: 'no-store',
  });

  // On 401 — try one silent refresh, then replay with the new token
  if (res.status === 401 && typeof window !== 'undefined') {
    const refreshed = await tryRefreshOnce();
    if (refreshed) {
      const retryHeaders = buildHeaders();
      // CRITICAL: cache: 'no-store' — see comment above.
      const retryRes = await fetch(`${API_BASE}${path}`, {
        ...init,
        headers: { ...retryHeaders, ...init?.headers },
        credentials: 'include',
        cache: 'no-store',
      });
      return parseEnvelopeOrThrow<T>(retryRes);
    }

    // Refresh failed — session is truly expired.
    // Emit event for UI (SessionExpiredModal) and broadcast logout to other tabs.
    const { clearAuthState } = await import('./auth');
    clearAuthState();
    broadcastLogout();
    window.dispatchEvent(new CustomEvent(SESSION_EXPIRED_EVENT));

    throw new ApiError(
      'SESSION_EXPIRED',
      'Your session has expired. Please log in again.',
      401,
    );
  }

  return parseEnvelopeOrThrow<T>(res);
}

/**
 * Download a file from the API to disk.
 *
 * Auth is a Bearer token in the Authorization header (see buildHeaders),
 * which a plain `<a href>` cannot attach — so an unauthenticated anchor
 * download 403s. This fetches the bytes WITH the header (and the silent-
 * refresh retry), then triggers a browser download from an object URL.
 */
export async function apiDownload(path: string, filename: string): Promise<void> {
  const doFetch = () =>
    fetch(`${API_BASE}${path}`, {
      headers: buildHeaders(),
      credentials: 'include',
      cache: 'no-store',
    });

  let res = await doFetch();
  if (res.status === 401 && typeof window !== 'undefined') {
    const refreshed = await tryRefreshOnce();
    if (refreshed) {
      res = await doFetch();
    } else {
      const { clearAuthState } = await import('./auth');
      clearAuthState();
      broadcastLogout();
      window.dispatchEvent(new CustomEvent(SESSION_EXPIRED_EVENT));
      throw new ApiError('SESSION_EXPIRED', 'Your session has expired. Please log in again.', 401);
    }
  }
  if (!res.ok) {
    throw new ApiError('DOWNLOAD_FAILED', `Download failed (${res.status})`, res.status);
  }

  const blob = await res.blob();
  const url = URL.createObjectURL(blob);
  const a = document.createElement('a');
  a.href = url;
  a.download = filename;
  document.body.appendChild(a);
  a.click();
  a.remove();
  // Revoke after the click has been dispatched.
  setTimeout(() => URL.revokeObjectURL(url), 1000);
}

/** Convenience wrappers */
export const api = {
  get: <T>(path: string) => apiFetch<T>(path),
  post: <T>(path: string, data?: unknown) =>
    apiFetch<T>(path, { method: 'POST', body: data ? JSON.stringify(data) : undefined }),
  put: <T>(path: string, data?: unknown) =>
    apiFetch<T>(path, { method: 'PUT', body: data ? JSON.stringify(data) : undefined }),
  patch: <T>(path: string, data?: unknown) =>
    apiFetch<T>(path, { method: 'PATCH', body: data ? JSON.stringify(data) : undefined }),
  delete: <T>(path: string) => apiFetch<T>(path, { method: 'DELETE' }),
};
