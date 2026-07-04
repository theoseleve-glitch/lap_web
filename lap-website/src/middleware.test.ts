import { describe, it, expect, vi, afterEach } from 'vitest';
import { NextRequest } from 'next/server';
import { middleware } from './middleware';

const ORIGINAL_FETCH = global.fetch;

function makeRequest(path: string, cookie = ''): NextRequest {
  return new NextRequest(`https://www.lap-coach.racing${path}`, {
    headers: cookie ? { cookie, host: 'www.lap-coach.racing' } : { host: 'www.lap-coach.racing' },
  });
}

describe('middleware — admin/race-control server-side gating', () => {
  afterEach(() => {
    global.fetch = ORIGINAL_FETCH;
    vi.restoreAllMocks();
  });

  it('redirects /admin to /app/sessions when refresh fails (no cookie)', async () => {
    global.fetch = vi.fn().mockResolvedValue(new Response(null, { status: 401 }));
    const res = await middleware(makeRequest('/admin'));
    expect(res.status).toBe(307);
    expect(res.headers.get('location')).toContain('/app/sessions');
  });

  it('redirects /app/race-control/users when refresh succeeds but is_superadmin is false', async () => {
    global.fetch = vi.fn().mockResolvedValue(
      new Response(JSON.stringify({ data: { user: { id: 1, is_superadmin: false } } }), { status: 200 }),
    );
    const res = await middleware(makeRequest('/app/race-control/users', 'lap_refresh_token=abc'));
    expect(res.status).toBe(307);
    expect(res.headers.get('location')).toContain('/app/sessions');
  });

  it('allows /admin through when refresh succeeds with is_superadmin true', async () => {
    global.fetch = vi.fn().mockResolvedValue(
      new Response(JSON.stringify({ data: { user: { id: 1, is_superadmin: true } } }), { status: 200 }),
    );
    const res = await middleware(makeRequest('/admin/users', 'lap_refresh_token=abc'));
    expect(res.status).not.toBe(307);
  });

  it('does not call the backend for ordinary /app routes', async () => {
    const fetchSpy = vi.fn().mockResolvedValue(new Response(null, { status: 401 }));
    global.fetch = fetchSpy;
    await middleware(makeRequest('/app/dashboard'));
    expect(fetchSpy).not.toHaveBeenCalled();
  });

  it('fails closed (redirects) when the backend call throws', async () => {
    global.fetch = vi.fn().mockRejectedValue(new Error('network error'));
    const res = await middleware(makeRequest('/admin', 'lap_refresh_token=abc'));
    expect(res.status).toBe(307);
    expect(res.headers.get('location')).toContain('/app/sessions');
  });
});
