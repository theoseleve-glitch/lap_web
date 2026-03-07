import { NextResponse } from 'next/server';
import { getStripeSecretKey, hasBillingAuth } from '@/lib/stripe-billing';
import { getSiteUrl } from '@/lib/site-url';

interface PortalBody {
  customerEmail?: string;
  customerId?: string;
}

export async function POST(request: Request) {
  const body = (await request.json().catch(() => null)) as PortalBody | null;

  if (!hasBillingAuth(request)) {
    return NextResponse.json({ ok: false, message: 'Authentication required' }, { status: 401 });
  }

  if (!body?.customerEmail && !body?.customerId) {
    return NextResponse.json(
      { ok: false, message: 'customerEmail or customerId is required' },
      { status: 400 },
    );
  }

  const stripeKey = getStripeSecretKey();
  const origin = getSiteUrl();
  if (stripeKey) {
    try {
      let customerId = body.customerId;

      if (!customerId && body.customerEmail) {
        const lookup = await fetch(
          `https://api.stripe.com/v1/customers?email=${encodeURIComponent(body.customerEmail)}&limit=1`,
          {
            headers: { Authorization: `Bearer ${stripeKey}` },
          },
        );
        if (lookup.ok) {
          const customerData = (await lookup.json()) as { data?: Array<{ id: string }> };
          customerId = customerData.data?.[0]?.id;
        }
      }

      if (customerId) {
        const params = new URLSearchParams();
        params.set('customer', customerId);
        params.set('return_url', `${origin}/billing`);

        const response = await fetch('https://api.stripe.com/v1/billing_portal/sessions', {
          method: 'POST',
          headers: {
            Authorization: `Bearer ${stripeKey}`,
            'Content-Type': 'application/x-www-form-urlencoded',
          },
          body: params.toString(),
        });

        if (response.ok) {
          const data = (await response.json()) as { url?: string };
          if (data.url) {
            return NextResponse.json({ ok: true, portalUrl: data.url, mode: 'stripe' });
          }
        }
      }
    } catch {
      // Fallback below.
    }
  }

  const providerEndpoint = process.env.BILLING_PORTAL_WEBHOOK_URL;
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
        const data = (await response.json().catch(() => null)) as { portalUrl?: string } | null;
        if (data?.portalUrl) {
          return NextResponse.json({ ok: true, portalUrl: data.portalUrl });
        }
      }
    } catch {
      // Fallback below.
    }
  }

  return NextResponse.json({
    ok: true,
    portalUrl: '/billing?portal=fallback',
    mode: 'fallback',
  });
}
