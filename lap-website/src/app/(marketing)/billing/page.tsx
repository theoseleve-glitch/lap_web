import { redirect } from 'next/navigation';

/**
 * This marketing-side /billing page used to render its own (broken) billing
 * panel: its client-side AuthGate checked `document.cookie` for
 * `lap_refresh` -- but the real session cookie, `lap_refresh_token`, is
 * httpOnly and invisible to JS, so the gate was false for every visitor and
 * the panel never appeared. The real, working, authenticated billing UI
 * lives at /app/account/billing -- send everyone there instead.
 */
export default function BillingPage() {
  redirect('/app/account/billing');
}
