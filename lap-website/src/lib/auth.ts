import {
  setAccessToken,
  setUserProfile,
  broadcastTokenRefresh,
  broadcastLogout,
} from './auth-store';
import { parseEnvelopeOrThrow } from './http-envelope';

const BACKEND_URL = process.env.NEXT_PUBLIC_API_URL || 'http://localhost:5000';
const AUTH_BASE = `${BACKEND_URL}/auth`;

export interface AuthUser {
  id: number;
  email: string;
  display_name: string;
  is_superadmin?: boolean;
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

export interface TwoFaRequired {
  requires_2fa: true;
  temp_token: string;
}

/**
 * Step-up challenge required (Cloudflare Turnstile) -- returned with HTTP 428
 * when the email has tripped the backend's distributed-attack detection
 * (see telemetry_tool/auth/lockout.py::challenge_required). `sitekey` is a
 * fallback for when NEXT_PUBLIC_TURNSTILE_SITEKEY isn't set at build time.
 */
export interface ChallengeRequired {
  challenge_required: true;
  sitekey: string | null;
}

/** Login can return normal tokens, a 2FA challenge, or a step-up challenge. */
export type LoginResult = LoginResponse | TwoFaRequired | ChallengeRequired;

export async function login(
  email: string,
  password: string,
  turnstileToken?: string,
): Promise<LoginResult> {
  const body: Record<string, unknown> = { email, password };
  if (turnstileToken) {
    body['cf-turnstile-response'] = turnstileToken;
  }
  const result = await authFetch<LoginResult>('/login', body);
  if ('access_token' in result) {
    setAccessToken(result.access_token);
    setUserProfile(result.user);
    broadcastTokenRefresh(result.access_token);
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
  broadcastTokenRefresh(result.access_token);
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
  broadcastTokenRefresh(result.access_token);
  return result;
}

export async function verifyEmail(token: string): Promise<{ verified: boolean }> {
  return authFetch<{ verified: boolean }>('/verify-email', { token });
}

export async function logout(): Promise<void> {
  await authFetch('/logout');
  setAccessToken(null);
  setUserProfile(null);
  broadcastLogout();
}

/**
 * Silent refresh — uses the httpOnly cookie to get a new access token.
 * Called on page load to restore the session without localStorage.
 *
 * Retries once with exponential backoff before giving up.
 * Caps at MAX_REFRESH_RETRIES to prevent infinite loops.
 */
const MAX_REFRESH_RETRIES = 1;
const REFRESH_BACKOFF_MS = 1000;
let _refreshAttempts = 0;

// Dedup: only one silentRefresh can be in-flight at a time. Multiple
// callers (useAuth on mount + api-client on 401) share the same promise.
// Without this, parallel refreshes cause a race: the first rotates the
// token, the second sends the now-invalidated old token → 401 → logout.
let _silentRefreshPromise: Promise<AuthUser | null> | null = null;

export function silentRefresh(): Promise<AuthUser | null> {
  if (_silentRefreshPromise) return _silentRefreshPromise;
  _silentRefreshPromise = _doSilentRefresh().finally(() => {
    _silentRefreshPromise = null;
  });
  return _silentRefreshPromise;
}

async function _doSilentRefresh(): Promise<AuthUser | null> {
  if (_refreshAttempts > MAX_REFRESH_RETRIES) {
    _refreshAttempts = 0;
    clearAuthState();
    return null;
  }

  try {
    _refreshAttempts++;
    const result = await authFetch<LoginResponse>('/refresh');
    _refreshAttempts = 0;
    setAccessToken(result.access_token);
    setUserProfile(result.user);
    broadcastTokenRefresh(result.access_token);
    return result.user;
  } catch {
    if (_refreshAttempts <= MAX_REFRESH_RETRIES) {
      await new Promise((r) => setTimeout(r, REFRESH_BACKOFF_MS * _refreshAttempts));
      return _doSilentRefresh();
    }
    _refreshAttempts = 0;
    clearAuthState();
    return null;
  }
}

/** Clear all auth state. Exported for use by api-client on unrecoverable 401. */
export function clearAuthState(): void {
  setAccessToken(null);
  setUserProfile(null);
}

/** Reset refresh attempt counter (for tests). */
export function resetRefreshAttempts(): void {
  _refreshAttempts = 0;
}

export async function refreshToken(): Promise<{ access_token: string }> {
  const result = await authFetch<{ access_token: string; user?: AuthUser }>('/refresh');
  setAccessToken(result.access_token);
  broadcastTokenRefresh(result.access_token);
  return result;
}

