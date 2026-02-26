import { NextResponse } from 'next/server';

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
