import { ApiError } from './api-client';
import { setAccessToken } from './auth-store';

const AUTH_BASE = `${process.env.NEXT_PUBLIC_API_URL || 'http://localhost:5000'}/auth`;

export interface AuthUser {
  id: number;
  email: string;
  display_name: string;
}

export interface LoginResponse {
  access_token: string;
  refresh_token: string;
  user: AuthUser;
}

/** Helper: call an auth endpoint directly (Flask serves auth at /auth/*). */
async function authFetch<T>(path: string, body?: unknown): Promise<T> {
  const headers: Record<string, string> = { 'Content-Type': 'application/json' };
  if (typeof window !== 'undefined') {
    const { getAccessToken } = await import('./auth-store');
    const token = getAccessToken();
    if (token) headers['Authorization'] = `Bearer ${token}`;
  }
  const res = await fetch(`${AUTH_BASE}${path}`, {
    method: 'POST',
    headers,
    credentials: 'include',
    body: body ? JSON.stringify(body) : undefined,
  });
  const envelope = await res.json();
  if (!envelope.ok) {
    throw new ApiError(
      envelope.error?.code ?? 'UNKNOWN',
      envelope.error?.message ?? 'Request failed',
      res.status,
      envelope.error?.details,
    );
  }
  return envelope.data;
}

export async function login(email: string, password: string): Promise<LoginResponse> {
  const result = await authFetch<LoginResponse>('/login', { email, password });
  setAccessToken(result.access_token);
  return result;
}

export async function register(
  email: string,
  password: string,
  displayName: string,
): Promise<LoginResponse> {
  const result = await authFetch<LoginResponse>('/register', {
    email,
    password,
    display_name: displayName,
  });
  setAccessToken(result.access_token);
  return result;
}

export async function verifyEmail(token: string): Promise<{ verified: boolean }> {
  return authFetch<{ verified: boolean }>('/verify-email', { token });
}

export async function logout(): Promise<void> {
  await authFetch('/logout');
  setAccessToken(null);
}

/**
 * Silent refresh — uses the httpOnly cookie to get a new access token.
 * Called on page load to restore the session without localStorage.
 */
export async function silentRefresh(): Promise<AuthUser | null> {
  try {
    const result = await authFetch<LoginResponse>('/refresh');
    setAccessToken(result.access_token);
    return result.user;
  } catch {
    setAccessToken(null);
    return null;
  }
}

export async function refreshToken(): Promise<{ access_token: string }> {
  const result = await authFetch<{ access_token: string; user?: AuthUser }>('/refresh');
  setAccessToken(result.access_token);
  return result;
}

/**
 * @deprecated Use silentRefresh() instead. Kept for migration period only.
 */
// eslint-disable-next-line @typescript-eslint/no-unused-vars
export function storeTokens(accessToken: string, refreshToken: string) {
  setAccessToken(accessToken);
}

/**
 * @deprecated Use logout() instead. Kept for migration period only.
 */
export function clearTokens() {
  setAccessToken(null);
}
