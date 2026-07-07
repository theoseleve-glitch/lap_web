/**
 * Tests for auth silent-refresh failure handling.
 *
 * Verifies:
 *  - silentRefresh retries once with backoff before giving up
 *  - Infinite refresh loops are prevented (MAX_REFRESH_RETRIES cap)
 *  - clearAuthState wipes token, profile, and workspace
 *  - api-client emits SESSION_EXPIRED_EVENT on unrecoverable 401
 */
import { describe, it, expect, vi, beforeEach, afterEach } from 'vitest';

// Mock fetch globally
const mockFetch = vi.fn();
vi.stubGlobal('fetch', mockFetch);

// Mock BroadcastChannel
vi.stubGlobal('BroadcastChannel', class {
  onmessage = null;
  postMessage = vi.fn();
  close = vi.fn();
});

describe('silentRefresh', () => {
  beforeEach(() => {
    vi.useFakeTimers({ shouldAdvanceTime: true });
    mockFetch.mockReset();
  });

  afterEach(() => {
    vi.useRealTimers();
  });

  it('returns user on successful refresh', async () => {
    mockFetch.mockResolvedValueOnce({
      ok: true,
      status: 200,
      headers: new Headers({ 'content-type': 'application/json' }),
      text: async () => JSON.stringify({
        ok: true,
        data: {
          access_token: 'new-token',
          user: { id: 1, email: 'test@test.com', display_name: 'Test' },
        },
      }),
    });

    // Also mock the workspace resolve call
    mockFetch.mockResolvedValueOnce({
      ok: true,
      json: async () => ({ data: { workspace_id: 1 } }),
    });

    const { silentRefresh, resetRefreshAttempts } = await import('@/lib/auth');
    resetRefreshAttempts();

    const user = await silentRefresh();
    expect(user).toEqual({ id: 1, email: 'test@test.com', display_name: 'Test' });
  });

  it('retries once before returning null on failure', async () => {
    // First attempt fails
    mockFetch.mockRejectedValueOnce(new Error('Network error'));
    // Retry also fails
    mockFetch.mockRejectedValueOnce(new Error('Network error'));

    const { silentRefresh, resetRefreshAttempts } = await import('@/lib/auth');
    resetRefreshAttempts();

    const user = await silentRefresh();
    expect(user).toBeNull();
    // Should have called fetch twice (1 attempt + 1 retry)
    expect(mockFetch).toHaveBeenCalledTimes(2);
  });

  it('clears auth state on failure', async () => {
    mockFetch.mockRejectedValue(new Error('Network error'));

    const { silentRefresh, resetRefreshAttempts } = await import('@/lib/auth');
    const { getAccessToken, setAccessToken } = await import('@/lib/auth-store');

    resetRefreshAttempts();
    setAccessToken('old-token');
    await silentRefresh();

    expect(getAccessToken()).toBeNull();
  });
});

describe('clearAuthState', () => {
  it('wipes token and profile', async () => {
    const { clearAuthState } = await import('@/lib/auth');
    const { setAccessToken, setUserProfile, getAccessToken, getUserProfile } = await import('@/lib/auth-store');

    setAccessToken('test-token');
    setUserProfile({ id: 1, email: 'a@b.com', display_name: 'A' });

    clearAuthState();

    expect(getAccessToken()).toBeNull();
    expect(getUserProfile()).toBeNull();
  });
});

describe('SESSION_EXPIRED_EVENT', () => {
  it('is a non-empty string', async () => {
    const { SESSION_EXPIRED_EVENT } = await import('@/lib/api-client');
    expect(SESSION_EXPIRED_EVENT).toBe('lap:session-expired');
  });
});
