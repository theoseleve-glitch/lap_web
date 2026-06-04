import { NextResponse } from 'next/server';

/**
 * Start a subscription checkout for the single membership plan.
 *
 * The Founding-50 logic (race-safe ≤50 cap, €14.90 vs €19.90 price selection,
 * 30-day trial) lives in the backend at POST /api/v1/billing/checkout — the
 * Worker has no DB, so the cap MUST be enforced there. This route just forwards
 * and surfaces the result.
 *
 * FAILS LOUD: unlike the previous version (which returned `{ok:true}` + HTTP 200
 * pointing at `?checkout=error` even when nothing was charged), a missing config
 * or a backend error now returns a real non-2xx with `ok:false`.
 */
interface CheckoutBody {
  email?: string;
}

export async function POST(request: Request) {
  const apiUrl = process.env.NEXT_PUBLIC_API_URL;
  if (!apiUrl) {
    return NextResponse.json(
      { ok: false, error: 'billing_not_configured', message: 'Checkout is temporarily unavailable.' },
      { status: 503 },
    );
  }

  const body = (await request.json().catch(() => ({}))) as CheckoutBody;

  let backend: Response;
  try {
    backend = await fetch(`${apiUrl}/api/v1/billing/checkout`, {
      method: 'POST',
      headers: { 'content-type': 'application/json' },
      body: JSON.stringify({ email: body?.email ?? null }),
    });
  } catch {
    return NextResponse.json(
      { ok: false, error: 'checkout_unreachable', message: 'Could not reach the billing service.' },
      { status: 502 },
    );
  }

  const payload = (await backend.json().catch(() => null)) as
    | { ok?: boolean; data?: { checkout_url?: string; offer?: string } }
    | null;
  const checkoutUrl = payload?.data?.checkout_url;

  if (!backend.ok || !checkoutUrl) {
    // Surface the failure — do NOT pretend success (no HTTP 200 on a broken checkout).
    return NextResponse.json(
      { ok: false, error: 'checkout_failed', message: 'Could not start checkout. Please try again.' },
      { status: backend.ok ? 502 : backend.status },
    );
  }

  return NextResponse.json({ ok: true, checkoutUrl, offer: payload?.data?.offer ?? 'standard' });
}
