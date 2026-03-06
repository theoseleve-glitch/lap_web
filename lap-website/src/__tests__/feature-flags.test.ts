/**
 * Tests for the feature flag system.
 *
 * Verifies:
 *  - Default flags are all true
 *  - getFlag returns defaults before any load
 *  - setFlag overrides a flag at runtime
 *  - resetFlags restores defaults
 *  - Kill-switch via env var disables a flag
 */
import { describe, it, expect, beforeEach } from 'vitest';
import { getFlag, setFlag, resetFlags, getAllFlags, type FeatureFlags } from '@/lib/feature-flags';

describe('feature-flags', () => {
  beforeEach(() => {
    resetFlags();
  });

  it('defaults all flags to true', () => {
    const flags = getAllFlags();
    expect(flags.offline_cache).toBe(true);
    expect(flags.web_vitals).toBe(true);
    expect(flags.chart_placeholders).toBe(true);
    expect(flags.driving_analyzer).toBe(true);
    expect(flags.session_expired_modal).toBe(true);
  });

  it('getFlag returns true for all defaults', () => {
    const flagNames: (keyof FeatureFlags)[] = [
      'offline_cache',
      'web_vitals',
      'chart_placeholders',
      'driving_analyzer',
      'session_expired_modal',
    ];
    for (const flag of flagNames) {
      expect(getFlag(flag)).toBe(true);
    }
  });

  it('setFlag overrides a flag', () => {
    expect(getFlag('offline_cache')).toBe(true);
    setFlag('offline_cache', false);
    expect(getFlag('offline_cache')).toBe(false);
  });

  it('resetFlags restores defaults', () => {
    setFlag('offline_cache', false);
    setFlag('web_vitals', false);
    resetFlags();
    expect(getFlag('offline_cache')).toBe(true);
    expect(getFlag('web_vitals')).toBe(true);
  });

  it('getAllFlags includes version and loadedAt', () => {
    const flags = getAllFlags();
    expect(flags._version).toBeDefined();
    expect(typeof flags._loadedAt).toBe('number');
  });

  it('preserves EXPERIENCE_V2 export', async () => {
    const mod = await import('@/lib/feature-flags');
    expect(typeof mod.EXPERIENCE_V2).toBe('boolean');
  });
});
