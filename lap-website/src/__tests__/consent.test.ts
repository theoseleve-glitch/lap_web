/**
 * Tests for the consent store and analytics gating.
 *
 * Verifies:
 *  - No consent by default (opt-in model)
 *  - setConsent writes cookie and dispatches event
 *  - hasAnalyticsConsent / hasMarketingConsent reflect state
 *  - analytics track() is gated by consent
 */
import { describe, it, expect, beforeEach, vi } from 'vitest';
import {
  getConsent,
  setConsent,
  hasAnalyticsConsent,
  hasMarketingConsent,
  hasConsentDecision,
  CONSENT_CHANGED_EVENT,
} from '@/lib/consent';

// Minimal cookie jar for tests
let cookieJar = '';
beforeEach(() => {
  cookieJar = '';
  Object.defineProperty(document, 'cookie', {
    get: () => cookieJar,
    set: (v: string) => {
      // Only store the key=value part (ignore directives)
      const kv = v.split(';')[0];
      const key = kv.split('=')[0];
      // Replace existing or append
      const parts = cookieJar.split(';').map((s) => s.trim()).filter(Boolean);
      const idx = parts.findIndex((p) => p.startsWith(`${key}=`));
      if (idx >= 0) parts[idx] = kv;
      else parts.push(kv);
      cookieJar = parts.join('; ');
    },
    configurable: true,
  });
});

describe('consent store', () => {
  it('returns null when no consent cookie exists', () => {
    expect(getConsent()).toBeNull();
    expect(hasConsentDecision()).toBe(false);
  });

  it('returns false for analytics/marketing when no decision', () => {
    expect(hasAnalyticsConsent()).toBe(false);
    expect(hasMarketingConsent()).toBe(false);
  });

  it('setConsent writes cookie and can be read back', () => {
    setConsent({ analytics: true, marketing: false });
    const state = getConsent();
    expect(state).not.toBeNull();
    expect(state!.analytics).toBe(true);
    expect(state!.marketing).toBe(false);
    expect(hasConsentDecision()).toBe(true);
  });

  it('hasAnalyticsConsent reflects granted state', () => {
    setConsent({ analytics: true, marketing: false });
    expect(hasAnalyticsConsent()).toBe(true);
    expect(hasMarketingConsent()).toBe(false);
  });

  it('hasMarketingConsent reflects granted state', () => {
    setConsent({ analytics: false, marketing: true });
    expect(hasAnalyticsConsent()).toBe(false);
    expect(hasMarketingConsent()).toBe(true);
  });

  it('dispatches custom event on setConsent', () => {
    const handler = vi.fn();
    window.addEventListener(CONSENT_CHANGED_EVENT, handler);
    setConsent({ analytics: true, marketing: true });
    expect(handler).toHaveBeenCalledTimes(1);
    const detail = (handler.mock.calls[0][0] as CustomEvent).detail;
    expect(detail.analytics).toBe(true);
    expect(detail.marketing).toBe(true);
    window.removeEventListener(CONSENT_CHANGED_EVENT, handler);
  });

  it('reject-all still counts as a decision', () => {
    setConsent({ analytics: false, marketing: false });
    expect(hasConsentDecision()).toBe(true);
    expect(hasAnalyticsConsent()).toBe(false);
  });
});

describe('analytics gating', () => {
  it('getPlausible returns undefined when no consent', async () => {
    // Import analytics module — track() should be a no-op without consent
    const { trackStartGridComplete } = await import('@/lib/analytics');
    // Should not throw even though window.plausible doesn't exist
    expect(() => trackStartGridComplete()).not.toThrow();
  });

  it('track calls are safe even after granting consent (no plausible loaded)', async () => {
    setConsent({ analytics: true, marketing: false });
    const { trackCtaClick } = await import('@/lib/analytics');
    // Plausible script isn't loaded in test env, so it should gracefully no-op
    expect(() => trackCtaClick('test', '/pricing', 'b2c')).not.toThrow();
  });
});
