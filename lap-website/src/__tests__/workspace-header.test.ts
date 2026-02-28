/**
 * Tests that the API client sends the X-Workspace-Id header when a
 * workspace is stored, and omits it when no workspace is set.
 *
 * Also verifies that auth flows (login, register, silentRefresh, logout)
 * correctly populate or clear the workspace ID.
 */
import { describe, it, expect, vi, beforeEach, afterEach } from 'vitest';
import {
  getAccessToken,
  setAccessToken,
  getWorkspaceId,
  setWorkspaceId,
} from '@/lib/auth-store';

// ── Mocks ──────────────────────────────────────────────────────────
// We need to intercept global `fetch` to verify headers and mock
// backend responses.

let fetchSpy: ReturnType<typeof vi.fn>;

beforeEach(() => {
  // Reset in-memory store state
  setAccessToken(null);
  setWorkspaceId(null);

  // Mock fetch globally
  fetchSpy = vi.fn();
  vi.stubGlobal('fetch', fetchSpy);
});

afterEach(() => {
  vi.restoreAllMocks();
  vi.unstubAllGlobals();
});

// ── auth-store unit tests ──────────────────────────────────────────

describe('auth-store workspace', () => {
  it('defaults to null', () => {
    expect(getWorkspaceId()).toBeNull();
  });

  it('stores and retrieves a workspace ID', () => {
    setWorkspaceId(42);
    expect(getWorkspaceId()).toBe(42);
  });

  it('clears workspace ID when set to null', () => {
    setWorkspaceId(7);
    setWorkspaceId(null);
    expect(getWorkspaceId()).toBeNull();
  });
});

// ── buildHeaders / apiFetch header injection ────────────────────────

describe('apiFetch X-Workspace-Id header', () => {
  it('sends X-Workspace-Id when workspace is set', async () => {
    setAccessToken('test-jwt');
    setWorkspaceId(99);

    // Mock a successful envelope response
    fetchSpy.mockResolvedValueOnce(
      new Response(
        JSON.stringify({ ok: true, data: { items: [] }, meta: {} }),
        {
          status: 200,
          headers: { 'Content-Type': 'application/json' },
        },
      ),
    );

    const { apiFetch } = await import('@/lib/api-client');
    await apiFetch('/sessions');

    expect(fetchSpy).toHaveBeenCalledTimes(1);
    const [, init] = fetchSpy.mock.calls[0];
    expect(init.headers['X-Workspace-Id']).toBe('99');
  });

  it('does NOT send X-Workspace-Id when workspace is null', async () => {
    setAccessToken('test-jwt');
    // workspace ID is already null from beforeEach

    fetchSpy.mockResolvedValueOnce(
      new Response(
        JSON.stringify({ ok: true, data: { items: [] }, meta: {} }),
        {
          status: 200,
          headers: { 'Content-Type': 'application/json' },
        },
      ),
    );

    const { apiFetch } = await import('@/lib/api-client');
    await apiFetch('/sessions');

    expect(fetchSpy).toHaveBeenCalledTimes(1);
    const [, init] = fetchSpy.mock.calls[0];
    expect(init.headers['X-Workspace-Id']).toBeUndefined();
  });

  it('sends Authorization AND X-Workspace-Id together', async () => {
    setAccessToken('my-token');
    setWorkspaceId(5);

    fetchSpy.mockResolvedValueOnce(
      new Response(
        JSON.stringify({ ok: true, data: null, meta: {} }),
        {
          status: 200,
          headers: { 'Content-Type': 'application/json' },
        },
      ),
    );

    const { apiFetch } = await import('@/lib/api-client');
    await apiFetch('/tracks');

    const [, init] = fetchSpy.mock.calls[0];
    expect(init.headers['Authorization']).toBe('Bearer my-token');
    expect(init.headers['X-Workspace-Id']).toBe('5');
  });

  it('updates the header when workspace changes between calls', async () => {
    setAccessToken('jwt');
    setWorkspaceId(10);

    const envelope = JSON.stringify({ ok: true, data: {}, meta: {} });
    const opts = { status: 200, headers: { 'Content-Type': 'application/json' } };

    fetchSpy
      .mockResolvedValueOnce(new Response(envelope, opts))
      .mockResolvedValueOnce(new Response(envelope, opts));

    const { apiFetch } = await import('@/lib/api-client');

    await apiFetch('/first');
    expect(fetchSpy.mock.calls[0][1].headers['X-Workspace-Id']).toBe('10');

    // Switch workspace
    setWorkspaceId(20);
    await apiFetch('/second');
    expect(fetchSpy.mock.calls[1][1].headers['X-Workspace-Id']).toBe('20');
  });
});

// ── Auth flow workspace resolution ──────────────────────────────────

describe('auth flow workspace resolution', () => {
  it('login resolves workspace after successful auth', async () => {
    // First call: /auth/login returns tokens
    fetchSpy.mockResolvedValueOnce(
      new Response(
        JSON.stringify({
          ok: true,
          data: {
            access_token: 'fresh-jwt',
            refresh_token: 'rt',
            user: { id: 1, email: 'a@b.com', display_name: 'A' },
          },
          meta: {},
        }),
        { status: 200, headers: { 'Content-Type': 'application/json' } },
      ),
    );

    // Second call: /api/v1/workspaces/current returns workspace
    fetchSpy.mockResolvedValueOnce(
      new Response(
        JSON.stringify({
          ok: true,
          data: { workspace_id: 42, role: 'owner' },
          meta: {},
        }),
        { status: 200, headers: { 'Content-Type': 'application/json' } },
      ),
    );

    const { login } = await import('@/lib/auth');
    await login('a@b.com', 'pass');

    expect(getAccessToken()).toBe('fresh-jwt');
    expect(getWorkspaceId()).toBe(42);

    // Verify the workspace fetch was called with correct auth
    expect(fetchSpy).toHaveBeenCalledTimes(2);
    const [wsUrl, wsInit] = fetchSpy.mock.calls[1];
    expect(wsUrl).toContain('/workspaces/current');
    expect(wsInit.headers['Authorization']).toBe('Bearer fresh-jwt');
  });

  it('logout clears workspace ID', async () => {
    setAccessToken('jwt');
    setWorkspaceId(42);

    // Mock /auth/logout
    fetchSpy.mockResolvedValueOnce(
      new Response(
        JSON.stringify({ ok: true, data: { message: 'Logged out' }, meta: {} }),
        { status: 200, headers: { 'Content-Type': 'application/json' } },
      ),
    );

    const { logout } = await import('@/lib/auth');
    await logout();

    expect(getAccessToken()).toBeNull();
    expect(getWorkspaceId()).toBeNull();
  });

  it('workspace resolution failure does not break login', async () => {
    // Login succeeds
    fetchSpy.mockResolvedValueOnce(
      new Response(
        JSON.stringify({
          ok: true,
          data: {
            access_token: 'tok',
            refresh_token: 'rt',
            user: { id: 1, email: 'a@b.com', display_name: 'A' },
          },
          meta: {},
        }),
        { status: 200, headers: { 'Content-Type': 'application/json' } },
      ),
    );

    // Workspace fetch fails (500)
    fetchSpy.mockResolvedValueOnce(
      new Response('Internal Server Error', { status: 500 }),
    );

    const { login } = await import('@/lib/auth');
    const result = await login('a@b.com', 'pass');

    // Login still succeeds, workspace just stays null
    expect(result).toHaveProperty('access_token', 'tok');
    expect(getAccessToken()).toBe('tok');
    expect(getWorkspaceId()).toBeNull();
  });

  it('silentRefresh resolves workspace', async () => {
    // /auth/refresh returns tokens
    fetchSpy.mockResolvedValueOnce(
      new Response(
        JSON.stringify({
          ok: true,
          data: {
            access_token: 'refreshed-jwt',
            refresh_token: 'new-rt',
            user: { id: 1, email: 'a@b.com', display_name: 'A' },
          },
          meta: {},
        }),
        { status: 200, headers: { 'Content-Type': 'application/json' } },
      ),
    );

    // /api/v1/workspaces/current
    fetchSpy.mockResolvedValueOnce(
      new Response(
        JSON.stringify({
          ok: true,
          data: { workspace_id: 7, role: 'member' },
          meta: {},
        }),
        { status: 200, headers: { 'Content-Type': 'application/json' } },
      ),
    );

    const { silentRefresh } = await import('@/lib/auth');
    const user = await silentRefresh();

    expect(user).toEqual({ id: 1, email: 'a@b.com', display_name: 'A' });
    expect(getWorkspaceId()).toBe(7);
  });

  it('silentRefresh clears workspace on failure', async () => {
    setWorkspaceId(99);

    // /auth/refresh fails
    fetchSpy.mockResolvedValueOnce(
      new Response(
        JSON.stringify({
          ok: false,
          error: { code: 'TOKEN_EXPIRED', message: 'expired' },
          meta: {},
        }),
        { status: 401, headers: { 'Content-Type': 'application/json' } },
      ),
    );

    const { silentRefresh } = await import('@/lib/auth');
    const user = await silentRefresh();

    expect(user).toBeNull();
    expect(getWorkspaceId()).toBeNull();
  });
});
