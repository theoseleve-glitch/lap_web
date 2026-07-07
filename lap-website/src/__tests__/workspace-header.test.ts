/**
 * Smoke test for the single-user, server-resolved workspace model.
 *
 * setWorkspaceId/getWorkspaceId/X-Workspace-Id were removed from
 * src/lib/auth-store (see its header comment) — the backend now resolves
 * the workspace server-side from the authenticated user, so the client
 * must never attach an X-Workspace-Id header.
 */
import { describe, it, expect, vi, beforeEach, afterEach } from 'vitest';
import { setAccessToken } from '@/lib/auth-store';

let fetchSpy: ReturnType<typeof vi.fn>;

beforeEach(() => {
  setAccessToken(null);
  fetchSpy = vi.fn();
  vi.stubGlobal('fetch', fetchSpy);
});

afterEach(() => {
  vi.restoreAllMocks();
  vi.unstubAllGlobals();
});

describe('apiFetch headers (single-user workspace model)', () => {
  it('never sends an X-Workspace-Id header', async () => {
    setAccessToken('test-jwt');
    fetchSpy.mockResolvedValueOnce(
      new Response(
        JSON.stringify({ ok: true, data: { items: [] }, meta: {} }),
        { status: 200, headers: { 'Content-Type': 'application/json' } },
      ),
    );

    const { apiFetch } = await import('@/lib/api-client');
    await apiFetch('/sessions');

    expect(fetchSpy).toHaveBeenCalledTimes(1);
    const [, init] = fetchSpy.mock.calls[0];
    expect(init.headers['X-Workspace-Id']).toBeUndefined();
  });
});
