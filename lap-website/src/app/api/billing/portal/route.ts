import { NextResponse } from 'next/server';
import { verifyBillingAuth } from '@/lib/stripe-billing';
import { getSiteUrl } from '@/lib/site-url';

const BACKEND_URL = process.env.NEXT_PUBLIC_API_URL || 'http://localhost:5000';

interface PortalBody {
  return_url?: string;
}

/**
 * Stripe's billing portal session requires an absolute return_url. Only
 * accept one that resolves to this app's own origin -- otherwise a client
 * could point the post-portal redirect at an arbitrary external site.
 */
function sanitizeReturnUrl(raw: string | undefined): string | undefined {
  if (!raw) return undefined;

  const siteOrigin = getSiteUrl();
  let resolved: URL;
  try {
    resolved = new URL(raw, siteOrigin);
  } catch {
    return undefined;
  }

  return resolved.origin === siteOrigin ? resolved.toString() : undefined;
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

    const safeReturnUrl = sanitizeReturnUrl(body.return_url);
    backendRes = await fetch(`${BACKEND_URL}/api/v1/billing/portal`, {
      method: 'POST',
      headers: {
        'content-type': 'application/json',
        authorization: `Bearer ${accessToken}`,
      },
      body: JSON.stringify(safeReturnUrl ? { return_url: safeReturnUrl } : {}),
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
