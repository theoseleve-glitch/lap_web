/**
 * Tests for the prefetch guardrail system.
 *
 * Verifies:
 *  - Save-Data blocks prefetch
 *  - Slow connection (2g) blocks prefetch
 *  - TTL dedup prevents re-prefetch within window
 *  - Concurrency cap respected
 *  - Route allowlist filtering
 */
import { describe, it, expect, beforeEach, vi } from 'vitest';
import {
  shouldPrefetch,
  canPrefetch,
  markPrefetched,
  incrementInFlight,
  decrementInFlight,
  isAllowedRoute,
  PREFETCH_ALLOWLIST,
  _resetPrefetchState,
} from '@/lib/prefetch';

describe('prefetch guardrails', () => {
  beforeEach(() => {
    _resetPrefetchState();
    // Reset navigator.connection
    vi.stubGlobal('navigator', { ...navigator, connection: undefined });
  });

  describe('shouldPrefetch', () => {
    it('returns true when Network API is not available', () => {
      expect(shouldPrefetch()).toBe(true);
    });

    it('returns false when Save-Data is enabled', () => {
      vi.stubGlobal('navigator', {
        connection: { saveData: true, effectiveType: '4g' },
      });
      expect(shouldPrefetch()).toBe(false);
    });

    it('returns false on 2g connections', () => {
      vi.stubGlobal('navigator', {
        connection: { saveData: false, effectiveType: '2g' },
      });
      expect(shouldPrefetch()).toBe(false);
    });

    it('returns false on slow-2g connections', () => {
      vi.stubGlobal('navigator', {
        connection: { saveData: false, effectiveType: 'slow-2g' },
      });
      expect(shouldPrefetch()).toBe(false);
    });

    it('returns true on 4g connections', () => {
      vi.stubGlobal('navigator', {
        connection: { saveData: false, effectiveType: '4g' },
      });
      expect(shouldPrefetch()).toBe(true);
    });

    it('returns true on 3g connections', () => {
      vi.stubGlobal('navigator', {
        connection: { saveData: false, effectiveType: '3g' },
      });
      expect(shouldPrefetch()).toBe(true);
    });
  });

  describe('canPrefetch', () => {
    it('blocks when already prefetched (TTL dedup)', () => {
      expect(canPrefetch('route:/app/sessions')).toBe(true);
      markPrefetched('route:/app/sessions');
      expect(canPrefetch('route:/app/sessions')).toBe(false);
    });

    it('blocks when max concurrent reached', () => {
      incrementInFlight();
      incrementInFlight();
      expect(canPrefetch('route:/app/dashboard')).toBe(false);
      decrementInFlight();
      expect(canPrefetch('route:/app/dashboard')).toBe(true);
    });

    it('allows different keys', () => {
      markPrefetched('route:/app/sessions');
      expect(canPrefetch('route:/app/dashboard')).toBe(true);
    });
  });

  describe('isAllowedRoute', () => {
    it('allows exact matches from allowlist', () => {
      for (const route of PREFETCH_ALLOWLIST) {
        expect(isAllowedRoute(route)).toBe(true);
      }
    });

    it('allows dynamic child routes', () => {
      expect(isAllowedRoute('/app/sessions/abc-123')).toBe(true);
      expect(isAllowedRoute('/app/compare/sessions')).toBe(true);
    });

    it('rejects routes not in allowlist', () => {
      expect(isAllowedRoute('/login')).toBe(false);
      expect(isAllowedRoute('/pricing')).toBe(false);
      expect(isAllowedRoute('/app/unknown-page')).toBe(false);
    });
  });
});
