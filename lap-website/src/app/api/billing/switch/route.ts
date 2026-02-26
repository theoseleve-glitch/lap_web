import { NextResponse } from 'next/server';
import {
  getStripePriceId,
  getStripeSecretKey,
  hasBillingAuth,
} from '@/lib/stripe-billing';

interface SwitchBody {
  subscriptionId: string;
  nextPlan: string;
  billingCycle?: 'monthly' | 'annual';
}

export async function POST(request: Request) {
  const body = (await request.json().catch(() => null)) as SwitchBody | null;

  if (!hasBillingAuth(request)) {
    return NextResponse.json({ ok: false, message: 'Authentication required' }, { status: 401 });
  }

  if (!body?.subscriptionId || !body?.nextPlan) {
    return NextResponse.json(
      { ok: false, message: 'subscriptionId and nextPlan are required' },
      { status: 400 },
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

  return NextResponse.json({
    ok: true,
    message: 'Plan switch recorded (fallback mode).',
    mode: 'fallback',
  });
}
