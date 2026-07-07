/**
 * Tests for BroadcastChannel-based multi-tab auth coordination.
 *
 * When one tab refreshes its access token (single-use rotation), it
 * broadcasts the new token to all other tabs so they don't make
 * redundant /auth/refresh calls that would fail (token already revoked).
 *
 * jsdom does not ship BroadcastChannel, so we provide a minimal mock.
 *
 * NOTE: the app is single-user / server-resolved workspace (see
 * src/lib/auth-store.ts) — AuthBroadcastMessage carries no workspaceId.
 */
import { describe, it, expect, vi, beforeEach, afterEach } from 'vitest';
import {
  getAccessToken,
  setAccessToken,
  getAuthChannel,
  broadcastTokenRefresh,
  broadcastLogout,
  closeAuthChannel,
  AUTH_CHANNEL_NAME,
  type AuthBroadcastMessage,
} from '@/lib/auth-store';

// ── BroadcastChannel mock ────────────────────────────────────────────
// Simulates the real BroadcastChannel API: messages sent via postMessage
// are delivered to all OTHER channels with the same name (not the sender).

type BCListener = (event: MessageEvent) => void;

const channelRegistry = new Map<string, Set<MockBroadcastChannel>>();

class MockBroadcastChannel {
  readonly name: string;
  onmessage: BCListener | null = null;
  private _closed = false;

  constructor(name: string) {
    this.name = name;
    if (!channelRegistry.has(name)) {
      channelRegistry.set(name, new Set());
    }
    channelRegistry.get(name)!.add(this);
  }

  postMessage(data: unknown): void {
    if (this._closed) throw new DOMException('Channel is closed');
    const peers = channelRegistry.get(this.name);
    if (!peers) return;
    for (const peer of peers) {
      // BroadcastChannel delivers to OTHER channels, not the sender
      if (peer !== this && !peer._closed && peer.onmessage) {
        peer.onmessage(new MessageEvent('message', { data }));
      }
    }
  }

  close(): void {
    this._closed = true;
    channelRegistry.get(this.name)?.delete(this);
  }
}

// ── Setup / teardown ─────────────────────────────────────────────────

let fetchSpy: ReturnType<typeof vi.fn>;

beforeEach(() => {
  // Install BroadcastChannel mock
  vi.stubGlobal('BroadcastChannel', MockBroadcastChannel);

  // Reset in-memory store
  setAccessToken(null);
  closeAuthChannel();

  // Clear channel registry
  channelRegistry.clear();

  // Mock fetch
  fetchSpy = vi.fn();
  vi.stubGlobal('fetch', fetchSpy);
});

afterEach(() => {
  closeAuthChannel();
  channelRegistry.clear();
  vi.restoreAllMocks();
  vi.unstubAllGlobals();
});

// ── Tests ────────────────────────────────────────────────────────────

describe('BroadcastChannel auth coordination', () => {
  describe('getAuthChannel', () => {
    it('returns a BroadcastChannel with the correct name', () => {
      const channel = getAuthChannel();
      expect(channel).not.toBeNull();
      expect(channel!.name).toBe(AUTH_CHANNEL_NAME);
    });

    it('returns the same instance on subsequent calls', () => {
      const a = getAuthChannel();
      const b = getAuthChannel();
      expect(a).toBe(b);
    });

    it('returns null when BroadcastChannel is undefined (SSR)', () => {
      closeAuthChannel();
      vi.stubGlobal('BroadcastChannel', undefined);
      expect(getAuthChannel()).toBeNull();
    });
  });

  describe('broadcastTokenRefresh', () => {
    it('sends token-refresh message to other tabs', () => {
      // Tab A: initialize its channel (the module's channel)
      getAuthChannel();

      // Tab B: simulate another tab listening
      const tabB = new MockBroadcastChannel(AUTH_CHANNEL_NAME);
      const received: AuthBroadcastMessage[] = [];
      tabB.onmessage = (e) => received.push(e.data);

      broadcastTokenRefresh('new-access-token');

      expect(received).toHaveLength(1);
      expect(received[0]).toEqual({
        type: 'token-refresh',
        accessToken: 'new-access-token',
      });

      tabB.close();
    });
  });

  describe('broadcastLogout', () => {
    it('sends logout message to other tabs', () => {
      getAuthChannel();

      const tabB = new MockBroadcastChannel(AUTH_CHANNEL_NAME);
      const received: AuthBroadcastMessage[] = [];
      tabB.onmessage = (e) => received.push(e.data);

      broadcastLogout();

      expect(received).toHaveLength(1);
      expect(received[0]).toEqual({ type: 'logout' });

      tabB.close();
    });
  });

  describe('receiving token-refresh from another tab', () => {
    it('updates in-memory access token', () => {
      // This tab has an old token
      setAccessToken('old-token');

      // Initialize our channel listener
      getAuthChannel();

      // Another tab broadcasts a refreshed token
      const otherTab = new MockBroadcastChannel(AUTH_CHANNEL_NAME);
      otherTab.postMessage({
        type: 'token-refresh',
        accessToken: 'refreshed-token',
      } satisfies AuthBroadcastMessage);

      expect(getAccessToken()).toBe('refreshed-token');

      otherTab.close();
    });

    it('does not trigger a new refresh request (no fetch call)', () => {
      getAuthChannel();

      const otherTab = new MockBroadcastChannel(AUTH_CHANNEL_NAME);
      otherTab.postMessage({
        type: 'token-refresh',
        accessToken: 'broadcast-token',
      } satisfies AuthBroadcastMessage);

      // No fetch should have been called — token was received via broadcast
      expect(fetchSpy).not.toHaveBeenCalled();
      expect(getAccessToken()).toBe('broadcast-token');

      otherTab.close();
    });
  });

  describe('receiving logout from another tab', () => {
    it('clears access token', () => {
      setAccessToken('active-token');
      getAuthChannel();

      const otherTab = new MockBroadcastChannel(AUTH_CHANNEL_NAME);
      otherTab.postMessage({ type: 'logout' } satisfies AuthBroadcastMessage);

      expect(getAccessToken()).toBeNull();

      otherTab.close();
    });
  });

  describe('closeAuthChannel', () => {
    it('allows re-creation of channel after close', () => {
      const first = getAuthChannel();
      closeAuthChannel();
      const second = getAuthChannel();
      expect(second).not.toBe(first);
      expect(second).not.toBeNull();
    });
  });
});

// ── Integration: auth.ts broadcasts on refresh/logout ────────────────

describe('auth.ts broadcasts via BroadcastChannel', () => {
  function mockAuthResponse(data: unknown) {
    return new Response(
      JSON.stringify({ ok: true, data, meta: {} }),
      { status: 200, headers: { 'Content-Type': 'application/json' } },
    );
  }

  it('silentRefresh broadcasts the new token to other tabs', async () => {
    // Simulate a peer tab listening
    const peerTab = new MockBroadcastChannel(AUTH_CHANNEL_NAME);
    const received: AuthBroadcastMessage[] = [];
    peerTab.onmessage = (e) => received.push(e.data);

    // Mock /auth/refresh
    fetchSpy.mockResolvedValueOnce(
      mockAuthResponse({
        access_token: 'refreshed-jwt',
        refresh_token: 'new-rt',
        user: { id: 1, email: 'a@b.com', display_name: 'A' },
      }),
    );

    const { silentRefresh } = await import('@/lib/auth');
    await silentRefresh();

    expect(received).toHaveLength(1);
    expect(received[0]).toEqual({
      type: 'token-refresh',
      accessToken: 'refreshed-jwt',
    });

    peerTab.close();
  });

  it('logout broadcasts logout event to other tabs', async () => {
    setAccessToken('current-jwt');

    const peerTab = new MockBroadcastChannel(AUTH_CHANNEL_NAME);
    const received: AuthBroadcastMessage[] = [];
    peerTab.onmessage = (e) => received.push(e.data);

    // Mock /auth/logout
    fetchSpy.mockResolvedValueOnce(
      mockAuthResponse({ message: 'Logged out' }),
    );

    const { logout } = await import('@/lib/auth');
    await logout();

    expect(received).toHaveLength(1);
    expect(received[0]).toEqual({ type: 'logout' });

    peerTab.close();
  });

  it('login broadcasts token to other tabs', async () => {
    const peerTab = new MockBroadcastChannel(AUTH_CHANNEL_NAME);
    const received: AuthBroadcastMessage[] = [];
    peerTab.onmessage = (e) => received.push(e.data);

    // Mock /auth/login
    fetchSpy.mockResolvedValueOnce(
      mockAuthResponse({
        access_token: 'login-jwt',
        refresh_token: 'rt',
        user: { id: 1, email: 'a@b.com', display_name: 'A' },
      }),
    );

    const { login } = await import('@/lib/auth');
    await login('a@b.com', 'pass');

    expect(received).toHaveLength(1);
    expect(received[0]).toEqual({
      type: 'token-refresh',
      accessToken: 'login-jwt',
    });

    peerTab.close();
  });

  it('register broadcasts token to other tabs', async () => {
    const peerTab = new MockBroadcastChannel(AUTH_CHANNEL_NAME);
    const received: AuthBroadcastMessage[] = [];
    peerTab.onmessage = (e) => received.push(e.data);

    // Mock /auth/register
    fetchSpy.mockResolvedValueOnce(
      mockAuthResponse({
        access_token: 'reg-jwt',
        refresh_token: 'rt',
        user: { id: 2, email: 'b@c.com', display_name: 'B' },
      }),
    );

    const { register } = await import('@/lib/auth');
    await register('b@c.com', 'pass', 'B');

    expect(received).toHaveLength(1);
    expect(received[0]).toEqual({
      type: 'token-refresh',
      accessToken: 'reg-jwt',
    });

    peerTab.close();
  });
});

// ── Multi-tab race scenario ──────────────────────────────────────────

describe('multi-tab race condition prevention', () => {
  it('tab B receives broadcast before it needs to refresh, avoiding revoked token', () => {
    // Scenario: Tab A and Tab B both have an expired access token.
    // Tab A calls /auth/refresh first and gets a new token.
    // Tab A broadcasts the new token.
    // Tab B receives the broadcast and updates its token WITHOUT calling /auth/refresh.
    // This prevents Tab B from using the now-revoked refresh token.

    setAccessToken('expired-token');

    // Tab B listener (our module acts as Tab B)
    getAuthChannel();

    // Tab A refreshes and broadcasts
    const tabA = new MockBroadcastChannel(AUTH_CHANNEL_NAME);
    tabA.postMessage({
      type: 'token-refresh',
      accessToken: 'tab-a-refreshed-token',
    } satisfies AuthBroadcastMessage);

    // Tab B (our module) should now have the refreshed token
    expect(getAccessToken()).toBe('tab-a-refreshed-token');

    // Tab B should NOT need to call /auth/refresh
    expect(fetchSpy).not.toHaveBeenCalled();

    tabA.close();
  });

  it('multiple rapid broadcasts settle on the last token', () => {
    getAuthChannel();

    const tabA = new MockBroadcastChannel(AUTH_CHANNEL_NAME);

    // Rapid sequence of token refreshes from Tab A
    tabA.postMessage({
      type: 'token-refresh',
      accessToken: 'token-1',
    } satisfies AuthBroadcastMessage);

    tabA.postMessage({
      type: 'token-refresh',
      accessToken: 'token-2',
    } satisfies AuthBroadcastMessage);

    tabA.postMessage({
      type: 'token-refresh',
      accessToken: 'token-3',
    } satisfies AuthBroadcastMessage);

    // Should have the last token
    expect(getAccessToken()).toBe('token-3');

    tabA.close();
  });

  it('logout from any tab clears tokens in all tabs', () => {
    setAccessToken('active');
    getAuthChannel();

    // Another tab logs out
    const tabC = new MockBroadcastChannel(AUTH_CHANNEL_NAME);
    tabC.postMessage({ type: 'logout' } satisfies AuthBroadcastMessage);

    expect(getAccessToken()).toBeNull();

    tabC.close();
  });
});
