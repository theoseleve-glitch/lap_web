import { beforeEach, afterEach, describe, expect, it, vi } from 'vitest';
import { POST } from '@/app/api/billing/checkout/route';

vi.mock('@/lib/stripe-billing', () => ({
  getStripePriceId: vi.fn(() => 'price_test_123'),
  getStripeSecretKey: vi.fn(() => 'sk_test_123'),
  isB2BPlan: vi.fn(() => false),
}));

describe('billing checkout origin hardening', () => {
  const originalEnv = { ...process.env };

  beforeEach(() => {
    vi.restoreAllMocks();
    process.env = { ...originalEnv };
  });

  afterEach(() => {
    process.env = { ...originalEnv };
  });

  it('ignores hostile Origin header and uses validated NEXT_PUBLIC_SITE_URL host', async () => {
    process.env.NEXT_PUBLIC_SITE_URL = 'https://www.lap-coach.racing';

    const fetchMock = vi.spyOn(global, 'fetch').mockResolvedValue(
      new Response(JSON.stringify({ url: 'https://checkout.stripe.test/session' }), {
        status: 200,
        headers: { 'content-type': 'application/json' },
      }),
    );

    const request = new Request('http://localhost/api/billing/checkout', {
      method: 'POST',
      headers: {
        'content-type': 'application/json',
        origin: 'https://evil.attacker.test',
      },
      body: JSON.stringify({ plan: 'RACER', billingCycle: 'monthly' }),
    });

    await POST(request);

    const stripeCall = fetchMock.mock.calls[0];
    expect(stripeCall?.[0]).toBe('https://api.stripe.com/v1/checkout/sessions');

    const body = String((stripeCall?.[1] as RequestInit)?.body ?? '');
    const params = new URLSearchParams(body);

    expect(params.get('success_url')).toBe('https://www.lap-coach.racing/thank-you/book');
    expect(params.get('cancel_url')).toBe('https://www.lap-coach.racing/pricing?checkout=cancelled');
    expect(params.get('success_url')).not.toContain('evil.attacker.test');
    expect(params.get('cancel_url')).not.toContain('evil.attacker.test');
  });

  it('falls back to default origin when configured site URL is not in allowlist', async () => {
    process.env.NEXT_PUBLIC_SITE_URL = 'https://evil.attacker.test';

    const fetchMock = vi.spyOn(global, 'fetch').mockResolvedValue(
      new Response(JSON.stringify({ url: 'https://checkout.stripe.test/session' }), {
        status: 200,
        headers: { 'content-type': 'application/json' },
      }),
    );

    const request = new Request('http://localhost/api/billing/checkout', {
      method: 'POST',
      headers: {
        'content-type': 'application/json',
        origin: 'https://evil.attacker.test',
      },
      body: JSON.stringify({ plan: 'RACER', billingCycle: 'monthly' }),
    });

    await POST(request);

    const stripeCall = fetchMock.mock.calls[0];
    const body = String((stripeCall?.[1] as RequestInit)?.body ?? '');
    const params = new URLSearchParams(body);

    expect(params.get('success_url')).toBe('https://lap.racing/thank-you/book');
    expect(params.get('cancel_url')).toBe('https://lap.racing/pricing?checkout=cancelled');
  });
});
