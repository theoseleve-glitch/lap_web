/**
 * Tests for Web Vitals collection.
 *
 * Verifies:
 *  - initWebVitals does not throw
 *  - Module exports expected functions
 */
import { describe, it, expect } from 'vitest';

describe('web-vitals', () => {
  it('exports initWebVitals function', async () => {
    const mod = await import('@/lib/web-vitals');
    expect(typeof mod.initWebVitals).toBe('function');
  });

  it('initWebVitals does not throw', async () => {
    const { initWebVitals } = await import('@/lib/web-vitals');
    expect(() => initWebVitals()).not.toThrow();
  });
});
