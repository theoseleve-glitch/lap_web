/**
 * Tests that setConsent() mirrors consent to the backend POST /api/v1/consent
 * when (and only when) the user is authenticated.
 */
import { describe, it, expect, beforeEach, vi } from 'vitest';

const postMock = vi.fn();
const getAccessTokenMock = vi.fn();

vi.mock('@/lib/api-client', () => ({
  api: { post: (...args: unknown[]) => postMock(...args) },
}));
vi.mock('@/lib/auth-store', () => ({
  getAccessToken: () => getAccessTokenMock(),
}));

// Minimal cookie jar (cookie write must still succeed independent of the POST)
let cookieJar = '';
beforeEach(() => {
  cookieJar = '';
  Object.defineProperty(document, 'cookie', {
    get: () => cookieJar,
    set: (v: string) => { cookieJar = v.split(';')[0]; },
    configurable: true,
  });
  postMock.mockReset();
  postMock.mockResolvedValue({});
  getAccessTokenMock.mockReset();
  vi.resetModules();
});

describe('consent server sync', () => {
  it('POSTs {analytics,marketing,version} to /consent when authenticated', async () => {
    getAccessTokenMock.mockReturnValue('jwt-token');
    const { setConsent } = await import('@/lib/consent');
    setConsent({ analytics: true, marketing: false });
    await vi.waitFor(() => expect(postMock).toHaveBeenCalledTimes(1));
    expect(postMock).toHaveBeenCalledWith('/consent', {
      analytics: true,
      marketing: false,
      version: 1,
    });
  });

  it('does NOT POST when unauthenticated (no token)', async () => {
    getAccessTokenMock.mockReturnValue(null);
    const { setConsent } = await import('@/lib/consent');
    setConsent({ analytics: true, marketing: true });
    // Give the fire-and-forget microtask a chance to run; it must not POST.
    await Promise.resolve();
    await Promise.resolve();
    expect(postMock).not.toHaveBeenCalled();
  });

  it('swallows a failing POST without throwing (cookie still written)', async () => {
    getAccessTokenMock.mockReturnValue('jwt-token');
    postMock.mockRejectedValue(new Error('network'));
    const { setConsent, getConsent } = await import('@/lib/consent');
    expect(() => setConsent({ analytics: true, marketing: true })).not.toThrow();
    expect(getConsent()?.analytics).toBe(true);
  });
});
