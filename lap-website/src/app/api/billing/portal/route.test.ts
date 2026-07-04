import { describe, it, expect, vi, afterEach } from 'vitest';
import { POST } from './route';

const ORIGINAL_FETCH = global.fetch;

describe('POST /api/billing/portal', () => {
  afterEach(() => {
    global.fetch = ORIGINAL_FETCH;
    vi.restoreAllMocks();
  });

  it('returns 401 when verifyBillingAuth fails (no cookie)', async () => {
    const req = new Request('https://www.lap-coach.racing/api/billing/portal', {
      method: 'POST',
      body: JSON.stringify({ customerId: 'cus_someoneElse' }),
    });
    const res = await POST(req);
    expect(res.status).toBe(401);
  });

  it('ignores a client-supplied customerId and proxies to the backend', async () => {
    global.fetch = vi
      .fn()
      // 1st call: verifyBillingAuth's /auth/refresh
      .mockResolvedValueOnce(new Response(JSON.stringify({ data: { user: { id: 42 } } }), { status: 200 }))
      // 2nd call: this handler's own /auth/refresh (exchange cookie -> access token)
      .mockResolvedValueOnce(new Response(JSON.stringify({ data: { access_token: 'tok' } }), { status: 200 }))
      // 3rd call: proxied POST /api/v1/billing/portal
      .mockResolvedValueOnce(
        new Response(
          JSON.stringify({ ok: true, data: { portal_url: 'https://billing.stripe.com/session/xyz' } }),
          { status: 200 },
        ),
      );

    const req = new Request('https://www.lap-coach.racing/api/billing/portal', {
      method: 'POST',
      headers: { cookie: 'lap_refresh_token=valid' },
      body: JSON.stringify({ customerId: 'cus_attackerSuppliedId' }),
    });
    const res = await POST(req);
    const body = (await res.json()) as { ok: boolean; portalUrl: string };

    expect(res.status).toBe(200);
    expect(body.portalUrl).toBe('https://billing.stripe.com/session/xyz');

    // The 3rd fetch is the backend proxy -- assert it never forwarded the
    // client-supplied customerId/customerEmail anywhere.
    const proxyCallBody = JSON.parse((global.fetch as any).mock.calls[2][1].body as string);
    expect(proxyCallBody).not.toHaveProperty('customerId');
    expect(proxyCallBody).not.toHaveProperty('customerEmail');
  });

  it('returns 502 when the backend proxy call fails', async () => {
    global.fetch = vi
      .fn()
      .mockResolvedValueOnce(new Response(JSON.stringify({ data: { user: { id: 42 } } }), { status: 200 }))
      .mockResolvedValueOnce(new Response(JSON.stringify({ data: { access_token: 'tok' } }), { status: 200 }))
      .mockResolvedValueOnce(new Response(null, { status: 500 }));

    const req = new Request('https://www.lap-coach.racing/api/billing/portal', {
      method: 'POST',
      headers: { cookie: 'lap_refresh_token=valid' },
      body: JSON.stringify({}),
    });
    const res = await POST(req);
    expect(res.status).toBe(502);
  });
});
