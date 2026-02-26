import { NextResponse } from 'next/server';

interface PortalBody {
  customerEmail: string;
}

export async function POST(request: Request) {
  const body = (await request.json().catch(() => null)) as PortalBody | null;
  if (!body?.customerEmail) {
    return NextResponse.json(
      { ok: false, message: 'customerEmail is required' },
      { status: 400 },
    );
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
