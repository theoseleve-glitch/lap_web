/**
 * In-memory token store.
 *
 * Access tokens are held in a JS variable — NOT localStorage — so they
 * cannot be exfiltrated by XSS.  On page refresh the token is lost, but
 * a silent refresh call (using the httpOnly cookie) recovers it.
 */

let _accessToken: string | null = null;

export function getAccessToken(): string | null {
  return _accessToken;
}

export function setAccessToken(token: string | null): void {
  _accessToken = token;
}
