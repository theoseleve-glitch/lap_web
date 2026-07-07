import { describe, it, expect, vi, afterEach } from 'vitest';
import { POST } from './route';

const ORIGINAL_FETCH = global.fetch;

function switchRequest(body: Record<string, unknown>, cookie = 'lap_refresh_token=valid') {
  return new Request('https://www.lap-coach.racing/api/billing/switch', {
    method: 'POST',
    headers: cookie ? { cookie } : {},
    body: JSON.stringify(body),
  });
}

describe('POST /api/billing/switch', () => {
  afterEach(() => {
    global.fetch = ORIGINAL_FETCH;
    vi.restoreAllMocks();
    vi.unstubAllEnvs();
  });

  it('returns 401 when verifyBillingAuth fails', async () => {
    const res = await POST(switchRequest({ subscriptionId: 'sub_x', nextPlan: 'WORLD-CLASS' }, ''));
    expect(res.status).toBe(401);
  });

  it("returns 403 when the supplied subscriptionId is not the caller's own", async () => {
    global.fetch = vi
      .fn()
      // verifyBillingAuth's /auth/refresh
      .mockResolvedValueOnce(new Response(JSON.stringify({ data: { user: { id: 42 } } }), { status: 200 }))
      // this handler's own /auth/refresh (to attach an access token to the ownership lookup)
      .mockResolvedValueOnce(new Response(JSON.stringify({ data: { access_token: 'tok' } }), { status: 200 }))
      // GET /api/v1/billing/subscription — caller owns sub_mine, NOT sub_someoneElse
      .mockResolvedValueOnce(
        new Response(JSON.stringify({ ok: true, data: { stripe_subscription_id: 'sub_mine' } }), { status: 200 }),
      );

    const res = await POST(switchRequest({ subscriptionId: 'sub_someoneElse', nextPlan: 'WORLD-CLASS' }));
    expect(res.status).toBe(403);
  });

  it("proceeds to Stripe when subscriptionId matches the caller's own", async () => {
    // Force the Stripe path deterministically -- without these, an
    // environment with no STRIPE_SECRET_KEY set would silently fall through
    // to the fallback branch and this test would pass for the wrong reason.
    vi.stubEnv('STRIPE_SECRET_KEY', 'sk_test_x');
    vi.stubEnv('STRIPE_PRICE_PRO_RACER_ANNUAL', 'price_world_class_annual');

    global.fetch = vi
      .fn()
      .mockResolvedValueOnce(new Response(JSON.stringify({ data: { user: { id: 42 } } }), { status: 200 }))
      .mockResolvedValueOnce(new Response(JSON.stringify({ data: { access_token: 'tok' } }), { status: 200 }))
      .mockResolvedValueOnce(
        new Response(JSON.stringify({ ok: true, data: { stripe_subscription_id: 'sub_mine' } }), { status: 200 }),
      )
      // Stripe subscription lookup (existing logic)
      .mockResolvedValueOnce(new Response(JSON.stringify({ items: { data: [{ id: 'si_1' }] } }), { status: 200 }))
      // Stripe subscription update (existing logic)
      .mockResolvedValueOnce(new Response(JSON.stringify({ id: 'sub_mine' }), { status: 200 }));

    const res = await POST(switchRequest({ subscriptionId: 'sub_mine', nextPlan: 'WORLD-CLASS' }));
    const body = (await res.json()) as { ok: boolean; mode?: string };
    expect(res.status).toBe(200);
    expect(body.ok).toBe(true);
    expect(body.mode).toBe('stripe');
  });

  it('returns a non-2xx honest response when neither Stripe nor a switch webhook is configured', async () => {
    // Simulate prod-as-observed: getStripePriceId('LAP COACH', ...) has no
    // PRICE_ENV_MAP entry (undefined), and BILLING_SWITCH_WEBHOOK_URL is
    // unset -- neither path can actually perform a switch.
    vi.stubEnv('STRIPE_SECRET_KEY', '');
    vi.stubEnv('BILLING_SWITCH_WEBHOOK_URL', '');

    global.fetch = vi
      .fn()
      .mockResolvedValueOnce(new Response(JSON.stringify({ data: { user: { id: 42 } } }), { status: 200 }))
      .mockResolvedValueOnce(new Response(JSON.stringify({ data: { access_token: 'tok' } }), { status: 200 }))
      .mockResolvedValueOnce(
        new Response(JSON.stringify({ ok: true, data: { stripe_subscription_id: 'sub_mine' } }), { status: 200 }),
      );

    const res = await POST(switchRequest({ subscriptionId: 'sub_mine', nextPlan: 'LAP COACH' }));
    const body = (await res.json()) as { ok: boolean; message?: string; mode?: string };

    // Non-2xx: the handler must never claim success when nothing switched.
    expect(res.status < 200 || res.status >= 300).toBe(true);
    expect(body.ok).toBe(false);
  });

  it('returns 403 when the caller has no subscription at all', async () => {
    global.fetch = vi
      .fn()
      .mockResolvedValueOnce(new Response(JSON.stringify({ data: { user: { id: 42 } } }), { status: 200 }))
      .mockResolvedValueOnce(new Response(JSON.stringify({ data: { access_token: 'tok' } }), { status: 200 }))
      .mockResolvedValueOnce(
        new Response(JSON.stringify({ ok: true, data: { stripe_subscription_id: null } }), { status: 200 }),
      );

    const res = await POST(switchRequest({ subscriptionId: 'sub_anything', nextPlan: 'WORLD-CLASS' }));
    expect(res.status).toBe(403);
  });
});
