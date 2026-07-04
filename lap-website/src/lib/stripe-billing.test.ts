import { describe, it, expect, vi, afterEach } from 'vitest';
import { verifyBillingAuth } from './stripe-billing';

const ORIGINAL_FETCH = global.fetch;
const ORIGINAL_ENV = { ...process.env };

describe('verifyBillingAuth', () => {
  afterEach(() => {
    global.fetch = ORIGINAL_FETCH;
    process.env = { ...ORIGINAL_ENV };
    vi.restoreAllMocks();
  });

  it('returns null when there is no cookie at all', async () => {
    const req = new Request('https://www.lap-coach.racing/api/billing/portal', { method: 'POST' });
    expect(await verifyBillingAuth(req)).toBeNull();
  });

  it('returns null for a visitor with only the anonymous lap_session_id cookie', async () => {
    global.fetch = vi.fn().mockResolvedValue(new Response(null, { status: 401 }));
    const req = new Request('https://www.lap-coach.racing/api/billing/portal', {
      method: 'POST',
      headers: { cookie: 'lap_session_id=11111111-1111-1111-1111-111111111111' },
    });
    expect(await verifyBillingAuth(req)).toBeNull();
  });

  it('returns the verified user id when the backend confirms the refresh cookie', async () => {
    global.fetch = vi.fn().mockResolvedValue(
      new Response(JSON.stringify({ data: { user: { id: 42, is_superadmin: false } } }), { status: 200 }),
    );
    const req = new Request('https://www.lap-coach.racing/api/billing/portal', {
      method: 'POST',
      headers: { cookie: 'lap_refresh_token=validtoken' },
    });
    expect(await verifyBillingAuth(req)).toEqual({ userId: 42 });
  });

  it('returns null when the backend rejects the refresh cookie', async () => {
    global.fetch = vi.fn().mockResolvedValue(new Response(null, { status: 401 }));
    const req = new Request('https://www.lap-coach.racing/api/billing/portal', {
      method: 'POST',
      headers: { cookie: 'lap_refresh_token=expiredtoken' },
    });
    expect(await verifyBillingAuth(req)).toBeNull();
  });

  it('returns null when the backend call throws', async () => {
    global.fetch = vi.fn().mockRejectedValue(new Error('network error'));
    const req = new Request('https://www.lap-coach.racing/api/billing/portal', {
      method: 'POST',
      headers: { cookie: 'lap_refresh_token=validtoken' },
    });
    expect(await verifyBillingAuth(req)).toBeNull();
  });

  it('ignores BILLING_ALLOW_GUEST — the switch is removed entirely', async () => {
    process.env.BILLING_ALLOW_GUEST = 'true';
    const req = new Request('https://www.lap-coach.racing/api/billing/portal', { method: 'POST' });
    expect(await verifyBillingAuth(req)).toBeNull();
  });
});
