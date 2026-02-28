/**
 * In-memory token store.
 *
 * Access tokens are held in a JS variable — NOT localStorage — so they
 * cannot be exfiltrated by XSS.  On page refresh the token is lost, but
 * a silent refresh call (using the httpOnly cookie) recovers it.
 *
 * The active workspace ID follows the same in-memory pattern.  It is
 * sent as the `X-Workspace-Id` header on every API call so the backend
 * tenant middleware can set the correct RLS context.
 *
 * BroadcastChannel coordination: when one tab refreshes its access token,
 * it broadcasts the new token to all other tabs so they don't make
 * redundant refresh requests (which would fail due to single-use refresh
 * token rotation).
 */

let _accessToken: string | null = null;
let _workspaceId: number | null = null;

export function getAccessToken(): string | null {
  return _accessToken;
}

export function setAccessToken(token: string | null): void {
  _accessToken = token;
}

export function getWorkspaceId(): number | null {
  return _workspaceId;
}

export function setWorkspaceId(id: number | null): void {
  _workspaceId = id;
}

// ── BroadcastChannel for cross-tab token coordination ─────────────

export const AUTH_CHANNEL_NAME = 'lap-auth';

export type AuthBroadcastMessage =
  | { type: 'token-refresh'; accessToken: string; workspaceId: number | null }
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
        if (msg.workspaceId !== undefined) {
          _workspaceId = msg.workspaceId;
        }
      } else if (msg.type === 'logout') {
        _accessToken = null;
        _workspaceId = null;
      }
    };
  }
  return _channel;
}

/**
 * Broadcast a token-refresh event to other tabs.
 * Called after a successful silent refresh or login.
 */
export function broadcastTokenRefresh(accessToken: string, workspaceId: number | null): void {
  const channel = getAuthChannel();
  channel?.postMessage({ type: 'token-refresh', accessToken, workspaceId });
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
