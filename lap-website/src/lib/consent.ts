/**
 * Cookie-based consent store for ePrivacy/GDPR compliance.
 *
 * Cookie format: JSON { a: 0|1, m: 0|1, v: number, t: number }
 *   a = analytics, m = marketing, v = schema version, t = unix timestamp
 *
 * Default is opt-in: no analytics or marketing until explicit consent.
 */

const COOKIE_NAME = 'lap_consent';
const COOKIE_MAX_AGE = 365 * 24 * 60 * 60; // 1 year
const SCHEMA_VERSION = 1;

export const CONSENT_CHANGED_EVENT = 'lap:consent-changed';

export interface ConsentState {
  analytics: boolean;
  marketing: boolean;
}

interface CookiePayload {
  a: 0 | 1;
  m: 0 | 1;
  v: number;
  t: number;
}

/** Read consent from cookie. Returns null if no decision yet. */
export function getConsent(): ConsentState | null {
  if (typeof document === 'undefined') return null;
  const raw = document.cookie
    .split(';')
    .map((s) => s.trim())
    .find((s) => s.startsWith(`${COOKIE_NAME}=`));
  if (!raw) return null;
  try {
    const payload: CookiePayload = JSON.parse(decodeURIComponent(raw.split('=').slice(1).join('=')));
    if (payload.v !== SCHEMA_VERSION) return null;
    return { analytics: payload.a === 1, marketing: payload.m === 1 };
  } catch {
    return null;
  }
}

/** Write consent decision to cookie and dispatch event. */
export function setConsent(state: ConsentState): void {
  const payload: CookiePayload = {
    a: state.analytics ? 1 : 0,
    m: state.marketing ? 1 : 0,
    v: SCHEMA_VERSION,
    t: Math.floor(Date.now() / 1000),
  };
  document.cookie = `${COOKIE_NAME}=${encodeURIComponent(JSON.stringify(payload))}; path=/; max-age=${COOKIE_MAX_AGE}; samesite=lax`;
  window.dispatchEvent(new CustomEvent(CONSENT_CHANGED_EVENT, { detail: state }));
}

/** Check if analytics consent has been granted. */
export function hasAnalyticsConsent(): boolean {
  return getConsent()?.analytics === true;
}

/** Check if marketing consent has been granted. */
export function hasMarketingConsent(): boolean {
  return getConsent()?.marketing === true;
}

/** True if user has made any consent decision (accept or reject). */
export function hasConsentDecision(): boolean {
  return getConsent() !== null;
}
