import { beforeEach, afterEach, describe, expect, it, vi } from 'vitest';
import { POST } from '@/app/api/billing/checkout/route';

/**
 * The checkout route forwards {email} to the backend's /api/v1/billing/checkout
 * (which owns the Founding-50 cap + price selection) and fails loud. It no
 * longer calls Stripe directly or reflects the request Origin, so the previous
 * origin-hardening assertions moved to the backend; these cover the new contract.
 */

function makeRequest(body: unknown = {}) {
  return new Request('http://localhost/api/billing/checkout', {
    method: 'POST',
    headers: { 'content-type': 'application/json' },
    body: JSON.stringify(body),
  });
}

describe('billing checkout route (fail-loud, forwards to backend)', () => {
  const originalEnv = { ...process.env };

  beforeEach(() => {
    vi.restoreAllMocks();
    process.env = { ...originalEnv };
  });

  afterEach(() => {
    process.env = { ...originalEnv };
  });

  it('returns 503 (ok:false) when the API URL is not configured', async () => {
    delete process.env.NEXT_PUBLIC_API_URL;
    const res = await POST(makeRequest({}));
    expect(res.status).toBe(503);
    expect((await res.json()).ok).toBe(false);
  });

  it('forwards {email} to the backend and returns the checkout URL on success', async () => {
    process.env.NEXT_PUBLIC_API_URL = 'https://api.lap-coach.racing';
    const fetchMock = vi.spyOn(global, 'fetch').mockResolvedValue(
      new Response(
        JSON.stringify({ ok: true, data: { checkout_url: 'https://checkout.stripe.test/session', offer: 'founding' } }),
        { status: 200, headers: { 'content-type': 'application/json' } },
      ),
    );

    const res = await POST(makeRequest({ email: 'driver@example.com' }));

    const call = fetchMock.mock.calls[0];
    expect(call?.[0]).toBe('https://api.lap-coach.racing/api/v1/billing/checkout');
    const sentBody = JSON.parse(String((call?.[1] as RequestInit)?.body ?? '{}'));
    expect(sentBody.email).toBe('driver@example.com');

    const json = await res.json();
    expect(json.ok).toBe(true);
    expect(json.checkoutUrl).toBe('https://checkout.stripe.test/session');
    expect(json.offer).toBe('founding');
  });

  it('fails loud (ok:false, propagates backend status) when there is no checkout URL', async () => {
    process.env.NEXT_PUBLIC_API_URL = 'https://api.lap-coach.racing';
    vi.spyOn(global, 'fetch').mockResolvedValue(
      new Response(JSON.stringify({ ok: false }), { status: 409, headers: { 'content-type': 'application/json' } }),
    );

    const res = await POST(makeRequest({ email: 'driver@example.com' }));
    expect(res.ok).toBe(false);
    expect(res.status).toBe(409);
    expect((await res.json()).ok).toBe(false);
  });

  it('returns 502 when the backend is unreachable', async () => {
    process.env.NEXT_PUBLIC_API_URL = 'https://api.lap-coach.racing';
    vi.spyOn(global, 'fetch').mockRejectedValue(new Error('network down'));
    const res = await POST(makeRequest({ email: 'x@y.z' }));
    expect(res.status).toBe(502);
    expect((await res.json()).ok).toBe(false);
  });
});
