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

export function hasBillingAuth(request: Request): boolean {
  if (process.env.BILLING_ALLOW_GUEST === 'true') return true;

  const cookieHeader = request.headers.get('cookie') ?? '';
  const authCookiePatterns = [
    'session=',
    'access_token_cookie=',
    'refresh_token_cookie=',
    '__session=',
  ];

  return authCookiePatterns.some((pattern) => cookieHeader.includes(pattern));
}
