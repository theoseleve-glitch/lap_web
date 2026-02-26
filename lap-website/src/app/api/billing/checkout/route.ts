import { NextResponse } from 'next/server';
import { getStripePriceId, getStripeSecretKey, isB2BPlan } from '@/lib/stripe-billing';

interface CheckoutBody {
  plan: string;
  billingCycle: 'monthly' | 'annual';
  currency?: string;
  vatId?: string;
  email?: string;
}

export async function POST(request: Request) {
  const body = (await request.json().catch(() => null)) as CheckoutBody | null;

  if (!body?.plan || !body?.billingCycle) {
    return NextResponse.json(
      { ok: false, message: 'plan and billingCycle are required' },
      { status: 400 },
    );
  }

  if (isB2BPlan(body.plan)) {
    return NextResponse.json({
      ok: true,
      checkoutUrl: `/contact?plan=${encodeURIComponent(body.plan)}`,
      mode: 'contact_only',
    });
  }

  if (body.plan.toUpperCase() === 'STARTER') {
    return NextResponse.json({
      ok: true,
      checkoutUrl: '/register?source=starter',
      mode: 'starter_redirect',
    });
  }

  const stripeKey = getStripeSecretKey();
  const stripePriceId = getStripePriceId(body.plan, body.billingCycle);
  const origin = request.headers.get('origin') ?? 'https://lap.racing';
  const successUrl = `${origin}/thank-you/book`;
  const cancelUrl = `${origin}/pricing?checkout=cancelled`;

  if (stripeKey && stripePriceId) {
    const params = new URLSearchParams();
    params.set('mode', 'subscription');
    params.set('success_url', successUrl);
    params.set('cancel_url', cancelUrl);
    params.set('line_items[0][price]', stripePriceId);
    params.set('line_items[0][quantity]', '1');
    params.set('allow_promotion_codes', 'true');
    params.set('tax_id_collection[enabled]', 'true');
    params.set('metadata[plan]', body.plan);
    params.set('metadata[billingCycle]', body.billingCycle);

    if (body.email) {
      params.set('customer_email', body.email);
    }

    if (body.currency) {
      params.set('currency', body.currency.toLowerCase());
    }

    try {
      const stripeResponse = await fetch('https://api.stripe.com/v1/checkout/sessions', {
        method: 'POST',
        headers: {
          Authorization: `Bearer ${stripeKey}`,
          'Content-Type': 'application/x-www-form-urlencoded',
        },
        body: params.toString(),
      });

      if (stripeResponse.ok) {
        const data = (await stripeResponse.json()) as { url?: string };
        if (data.url) {
          return NextResponse.json({ ok: true, checkoutUrl: data.url, mode: 'stripe' });
        }
      }
    } catch {
      // Fallback below.
    }
  }

  const providerEndpoint = process.env.BILLING_CHECKOUT_WEBHOOK_URL;
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
        const data = (await response.json().catch(() => null)) as { checkoutUrl?: string } | null;
        if (data?.checkoutUrl) {
          return NextResponse.json({ ok: true, checkoutUrl: data.checkoutUrl });
        }
      }
    } catch {
      // Fallback below.
    }
  }

  const fallbackUrl = `/book?plan=${encodeURIComponent(body.plan)}&billing=${encodeURIComponent(
    body.billingCycle,
  )}`;
  return NextResponse.json({
    ok: true,
    checkoutUrl: fallbackUrl,
    mode: 'fallback',
  });
}
