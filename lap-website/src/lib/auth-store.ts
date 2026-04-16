/**
 * In-memory token store.
 *
 * Access tokens are held in a JS variable — NOT localStorage — so they
 * cannot be exfiltrated by XSS.  On page refresh the token is lost, but
 * a silent refresh call (using the httpOnly cookie) recovers it.
 *
 * Single-user model: workspace is auto-resolved server-side from the
 * authenticated user.  No X-Workspace-Id header or client-side workspace
 * state is needed.
 *
 * BroadcastChannel coordination: when one tab refreshes its access token,
 * it broadcasts the new token to all other tabs so they don't make
 * redundant refresh requests (which would fail due to single-use refresh
 * token rotation).
 */

let _accessToken: string | null = null;

export function getAccessToken(): string | null {
  return _accessToken;
}

export function setAccessToken(token: string | null): void {
  _accessToken = token;
}

// ── User profile (cached from last auth action) ───────────────────

interface StoredUserProfile {
  id: number;
  email: string;
  display_name: string;
  is_superadmin?: boolean;
}

let _userProfile: StoredUserProfile | null = null;

export function getUserProfile(): StoredUserProfile | null {
  return _userProfile;
}

export function setUserProfile(user: StoredUserProfile | null): void {
  _userProfile = user;
}

// ── BroadcastChannel for cross-tab token coordination ─────────────

export const AUTH_CHANNEL_NAME = 'lap-auth';

export type AuthBroadcastMessage =
  | { type: 'token-refresh'; accessToken: string }
  | { type: 'logout' };

let _channel: BroadcastChannel | null = null;

/**
 * Returns the shared BroadcastChannel for auth events.
 * Lazily created on first call.  Returns null during SSR or in
 * environments that don't support BroadcastChannel (e.g. Node/jsdom).
 */
export function getAuthChannel(): BroadcastChannel | null {
  if (typeof BroadcastChannel === 'undefined') return null;
  if (!_channel) {
    _channel = new BroadcastChannel(AUTH_CHANNEL_NAME);
    _channel.onmessage = (event: MessageEvent<AuthBroadcastMessage>) => {
      const msg = event.data;
      if (msg.type === 'token-refresh') {
        _accessToken = msg.accessToken;
      } else if (msg.type === 'logout') {
        _accessToken = null;
        _userProfile = null;
      }
    };
  }
  return _channel;
}

/**
 * Broadcast a token-refresh event to other tabs.
 * Called after a successful silent refresh or login.
 */
export function broadcastTokenRefresh(accessToken: string): void {
  const channel = getAuthChannel();
  channel?.postMessage({ type: 'token-refresh', accessToken });
}

/**
 * Broadcast a logout event to other tabs.
 */
export function broadcastLogout(): void {
  const channel = getAuthChannel();
  channel?.postMessage({ type: 'logout' });
}

/**
 * Close the BroadcastChannel (for cleanup in tests).
 */
export function closeAuthChannel(): void {
  if (_channel) {
    _channel.close();
    _channel = null;
  }
}
