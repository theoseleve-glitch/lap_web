import {
  setAccessToken,
  getAccessToken,
  setWorkspaceId,
  getWorkspaceId,
  setUserProfile,
  broadcastTokenRefresh,
  broadcastLogout,
} from './auth-store';
import { parseEnvelopeOrThrow } from './http-envelope';

const BACKEND_URL = process.env.NEXT_PUBLIC_API_URL || 'http://localhost:5000';
const AUTH_BASE = `${BACKEND_URL}/auth`;
const API_BASE = `${BACKEND_URL}/api/v1`;

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
  return parseEnvelopeOrThrow<T>(res);
}

/**
 * Fetch the user's current (default) workspace from the backend and store
 * the ID so it is sent as X-Workspace-Id on every subsequent API call.
 *
 * Uses a direct fetch (not apiFetch) to avoid circular dependency with the
 * 401-retry logic in api-client.ts.  Failures are silently ignored — the
 * backend tenant middleware will fall back to the user's default workspace.
 */
async function resolveWorkspace(): Promise<void> {
  try {
    const token = getAccessToken();
    if (!token) return;
    const res = await fetch(`${API_BASE}/workspaces/current`, {
      headers: {
        'Content-Type': 'application/json',
        Authorization: `Bearer ${token}`,
      },
      credentials: 'include',
    });
    if (!res.ok) return;
    const envelope = await res.json();
    const wsId = envelope?.data?.workspace_id;
    if (typeof wsId === 'number') {
      setWorkspaceId(wsId);
    }
  } catch {
    // Non-fatal — tenant middleware falls back to default workspace
  }
}

export interface TwoFaRequired {
  requires_2fa: true;
  temp_token: string;
}

/** Login can return either normal tokens or a 2FA challenge. */
export type LoginResult = LoginResponse | TwoFaRequired;

export async function login(email: string, password: string): Promise<LoginResult> {
  const result = await authFetch<LoginResult>('/login', { email, password });
  if ('access_token' in result) {
    setAccessToken(result.access_token);
    setUserProfile(result.user);
    await resolveWorkspace();
    broadcastTokenRefresh(result.access_token, getWorkspaceId());
  }
  return result;
}

/** Complete 2FA login by verifying a TOTP code or backup code. */
export async function verify2fa(
  tempToken: string,
  code: string,
  isBackup?: boolean,
): Promise<LoginResponse> {
  const body = isBackup
    ? { temp_token: tempToken, backup_code: code }
    : { temp_token: tempToken, totp_code: code };
  const result = await authFetch<LoginResponse>('/2fa/verify', body);
  setAccessToken(result.access_token);
  setUserProfile(result.user);
  await resolveWorkspace();
  broadcastTokenRefresh(result.access_token, getWorkspaceId());
  return result;
}

/** Request a password reset email. Always succeeds (prevents enumeration). */
export async function forgotPassword(email: string): Promise<{ message: string }> {
  return authFetch<{ message: string }>('/forgot-password', { email });
}

/** Reset password using a token from the reset email. */
export async function resetPassword(
  token: string,
  newPassword: string,
): Promise<{ message: string }> {
  return authFetch<{ message: string }>('/reset-password', {
    token,
    new_password: newPassword,
  });
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
  setUserProfile(result.user);
  await resolveWorkspace();
  broadcastTokenRefresh(result.access_token, getWorkspaceId());
  return result;
}

export async function verifyEmail(token: string): Promise<{ verified: boolean }> {
  return authFetch<{ verified: boolean }>('/verify-email', { token });
}

export async function logout(): Promise<void> {
  await authFetch('/logout');
  setAccessToken(null);
  setUserProfile(null);
  setWorkspaceId(null);
  broadcastLogout();
}

/**
 * Silent refresh — uses the httpOnly cookie to get a new access token.
 * Called on page load to restore the session without localStorage.
 */
export async function silentRefresh(): Promise<AuthUser | null> {
  try {
    const result = await authFetch<LoginResponse>('/refresh');
    setAccessToken(result.access_token);
    setUserProfile(result.user);
    await resolveWorkspace();
    broadcastTokenRefresh(result.access_token, getWorkspaceId());
    return result.user;
  } catch {
    setAccessToken(null);
    setUserProfile(null);
    setWorkspaceId(null);
    return null;
  }
}

export async function refreshToken(): Promise<{ access_token: string }> {
  const result = await authFetch<{ access_token: string; user?: AuthUser }>('/refresh');
  setAccessToken(result.access_token);
  broadcastTokenRefresh(result.access_token, getWorkspaceId());
  return result;
}

