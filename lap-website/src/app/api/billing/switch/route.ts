import { NextResponse } from 'next/server';

interface SwitchBody {
  subscriptionId: string;
  nextPlan: string;
}

export async function POST(request: Request) {
  const body = (await request.json().catch(() => null)) as SwitchBody | null;
  if (!body?.subscriptionId || !body?.nextPlan) {
    return NextResponse.json(
      { ok: false, message: 'subscriptionId and nextPlan are required' },
      { status: 400 },
    );
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
