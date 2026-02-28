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
