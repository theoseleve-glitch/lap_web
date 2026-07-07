import { NextResponse } from 'next/server';
import {
  getStripePriceId,
  getStripeSecretKey,
  verifyBillingAuth,
} from '@/lib/stripe-billing';

const BACKEND_URL = process.env.NEXT_PUBLIC_API_URL || 'http://localhost:5000';

interface SwitchBody {
  subscriptionId: string;
  nextPlan: string;
  billingCycle?: 'monthly' | 'annual';
}

/**
 * Fetch the authenticated caller's OWN Stripe subscription id from the
 * backend. There is no backend "execute switch" endpoint yet (only
 * /validate-switch, which checks constraints but doesn't touch Stripe), so
 * this proxy still calls Stripe directly below -- but only after confirming
 * the client-supplied subscriptionId actually belongs to the caller,
 * closing the IDOR without requiring new backend surface.
 */
async function fetchOwnSubscriptionId(cookie: string): Promise<string | null> {
  const refreshRes = await fetch(`${BACKEND_URL}/auth/refresh`, { method: 'POST', headers: { cookie } });
  if (!refreshRes.ok) return null;
  const refreshPayload = (await refreshRes.json()) as { data?: { access_token?: string } };
  const accessToken = refreshPayload.data?.access_token;
  if (!accessToken) return null;

  const subRes = await fetch(`${BACKEND_URL}/api/v1/billing/subscription`, {
    headers: { authorization: `Bearer ${accessToken}` },
  });
  if (!subRes.ok) return null;
  const subPayload = (await subRes.json()) as { data?: { stripe_subscription_id?: string | null } };
  return subPayload.data?.stripe_subscription_id ?? null;
}

export async function POST(request: Request) {
  const auth = await verifyBillingAuth(request);
  if (!auth) {
    return NextResponse.json({ ok: false, message: 'Authentication required' }, { status: 401 });
  }

  const body = (await request.json().catch(() => null)) as SwitchBody | null;

  if (!body?.subscriptionId || !body?.nextPlan) {
    return NextResponse.json(
      { ok: false, message: 'subscriptionId and nextPlan are required' },
      { status: 400 },
    );
  }

  const cookie = request.headers.get('cookie') ?? '';
  let ownSubscriptionId: string | null;
  try {
    ownSubscriptionId = await fetchOwnSubscriptionId(cookie);
  } catch {
    return NextResponse.json({ ok: false, message: 'Billing service unavailable' }, { status: 502 });
  }

  if (!ownSubscriptionId || ownSubscriptionId !== body.subscriptionId) {
    return NextResponse.json(
      { ok: false, message: 'You may only manage your own subscription' },
      { status: 403 },
    );
  }

  const stripeKey = getStripeSecretKey();
  if (stripeKey) {
    try {
      const billingCycle = body.billingCycle ?? 'annual';
      const priceId = getStripePriceId(body.nextPlan, billingCycle);

      if (priceId) {
        const subscriptionRes = await fetch(
          `https://api.stripe.com/v1/subscriptions/${encodeURIComponent(body.subscriptionId)}`,
          {
            headers: { Authorization: `Bearer ${stripeKey}` },
          },
        );

        if (subscriptionRes.ok) {
          const subscription = (await subscriptionRes.json()) as {
            items?: { data?: Array<{ id: string }> };
          };
          const itemId = subscription.items?.data?.[0]?.id;

          if (itemId) {
            const params = new URLSearchParams();
            params.set('items[0][id]', itemId);
            params.set('items[0][price]', priceId);
            params.set('proration_behavior', 'create_prorations');

            const updateRes = await fetch(
              `https://api.stripe.com/v1/subscriptions/${encodeURIComponent(body.subscriptionId)}`,
              {
                method: 'POST',
                headers: {
                  Authorization: `Bearer ${stripeKey}`,
                  'Content-Type': 'application/x-www-form-urlencoded',
                },
                body: params.toString(),
              },
            );

            if (updateRes.ok) {
              return NextResponse.json({
                ok: true,
                message: 'Plan switch accepted by Stripe.',
                mode: 'stripe',
              });
            }
          }
        }
      }
    } catch {
      // Fallback below.
    }
  }

  const providerEndpoint = process.env.BILLING_SWITCH_WEBHOOK_URL;
  if (providerEndpoint) {
    try {
      const response = await fetch(providerEndpoint, {
        method: 'POST',
        headers: {
          'content-type': 'application/json',
          ...(process.env.BILLING_WEBHOOK_BEARER
            ? { authorization: `Bearer ${process.env.BILLING_WEBHOOK_BEARER}` }
            : {}),
        },
        body: JSON.stringify(body),
      });

      if (response.ok) {
        return NextResponse.json({
          ok: true,
          message: 'Plan switch accepted by billing provider.',
        });
      }
    } catch {
      // Fallback below.
    }
  }

  // Neither a real Stripe switch nor a configured webhook actually performed
  // the switch -- do NOT report success. Prior behavior returned HTTP 200
  // {ok:true, mode:'fallback'} here even though nothing changed in Stripe,
  // which told the customer a plan switch happened when it hadn't.
  return NextResponse.json(
    {
      ok: false,
      message: "Plan changes aren't available right now. Contact support to change your plan.",
      mode: 'unavailable',
    },
    { status: 501 },
  );
}
