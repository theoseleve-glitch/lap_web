export type BillingCycle = 'monthly' | 'annual';

const B2B_PLANS = new Set(['FOR TEAMS & CIRCUITS']);

const PRICE_ENV_MAP: Record<string, string> = {
  'RACER:monthly': 'STRIPE_PRICE_PERFORMANCE_MONTHLY',
  'RACER:annual': 'STRIPE_PRICE_PERFORMANCE_ANNUAL',
  'WORLD-CLASS:monthly': 'STRIPE_PRICE_PRO_RACER_MONTHLY',
  'WORLD-CLASS:annual': 'STRIPE_PRICE_PRO_RACER_ANNUAL',
};

export function isB2BPlan(plan: string): boolean {
  return B2B_PLANS.has(plan.toUpperCase());
}

export function getStripePriceId(plan: string, billingCycle: BillingCycle): string | undefined {
  const key = PRICE_ENV_MAP[`${plan.toUpperCase()}:${billingCycle}`];
  return key ? process.env[key] : undefined;
}

export function getStripeSecretKey(): string | undefined {
  return process.env.STRIPE_SECRET_KEY;
}

const BACKEND_URL = process.env.NEXT_PUBLIC_API_URL || 'http://localhost:5000';

export interface VerifiedBillingUser {
  userId: number;
}

/**
 * Verify the caller is actually authenticated by asking the backend to
 * refresh using the forwarded httpOnly cookie -- replaces the old
 * hasBillingAuth(), which only checked for cookie NAME presence (including
 * lap_session_id, an anonymous A/B-testing id set for every visitor by
 * middleware.ts, unrelated to auth) and had a BILLING_ALLOW_GUEST bypass.
 *
 * There is no JWT_SECRET in this codebase and the browser's access token
 * lives in-memory, never as a cookie -- so "verify the token" means asking
 * the backend, not decoding it here. Returns null (unauthenticated) on any
 * missing cookie, non-2xx response, or network error -- fails closed.
 */
export async function verifyBillingAuth(request: Request): Promise<VerifiedBillingUser | null> {
  const cookie = request.headers.get('cookie');
  if (!cookie) return null;

  try {
    const res = await fetch(`${BACKEND_URL}/auth/refresh`, {
      method: 'POST',
      headers: { cookie },
    });
    if (!res.ok) return null;
    const payload = (await res.json()) as { data?: { user?: { id?: number } } };
    const userId = payload.data?.user?.id;
    return typeof userId === 'number' ? { userId } : null;
  } catch {
    return null;
  }
}
