import { NextResponse } from 'next/server';
import { verifyBillingAuth } from '@/lib/stripe-billing';

const BACKEND_URL = process.env.NEXT_PUBLIC_API_URL || 'http://localhost:5000';

interface PortalBody {
  return_url?: string;
}

export async function POST(request: Request) {
  const auth = await verifyBillingAuth(request);
  if (!auth) {
    return NextResponse.json({ ok: false, message: 'Authentication required' }, { status: 401 });
  }

  const body = (await request.json().catch(() => ({}))) as PortalBody;
  const cookie = request.headers.get('cookie') ?? '';

  // Proxy to the already-correct, authenticated backend endpoint, which looks
  // up stripe_customer_id from the DB using the JWT-verified user -- never from
  // client input. No customerId/customerEmail is forwarded. The backend lives
  // under /api/v1/ and requires a Bearer access token (not the refresh cookie),
  // so exchange the refresh cookie for an access token first.
  let backendRes: Response;
  try {
    const refreshRes = await fetch(`${BACKEND_URL}/auth/refresh`, {
      method: 'POST',
      headers: { cookie },
    });
    if (!refreshRes.ok) {
      return NextResponse.json({ ok: false, message: 'Authentication required' }, { status: 401 });
    }
    const refreshPayload = (await refreshRes.json()) as { data?: { access_token?: string } };
    const accessToken = refreshPayload.data?.access_token;
    if (!accessToken) {
      return NextResponse.json({ ok: false, message: 'Authentication required' }, { status: 401 });
    }

    backendRes = await fetch(`${BACKEND_URL}/api/v1/billing/portal`, {
      method: 'POST',
      headers: {
        'content-type': 'application/json',
        authorization: `Bearer ${accessToken}`,
      },
      body: JSON.stringify(body.return_url ? { return_url: body.return_url } : {}),
    });
  } catch {
    return NextResponse.json({ ok: false, message: 'Billing service unavailable' }, { status: 502 });
  }

  if (!backendRes.ok) {
    return NextResponse.json({ ok: false, message: 'Could not create portal session' }, { status: 502 });
  }

  const payload = (await backendRes.json().catch(() => null)) as {
    data?: { portal_url?: string };
  } | null;
  const portalUrl = payload?.data?.portal_url;
  if (!portalUrl) {
    return NextResponse.json({ ok: false, message: 'Could not create portal session' }, { status: 502 });
  }

  return NextResponse.json({ ok: true, portalUrl, mode: 'stripe' });
}
