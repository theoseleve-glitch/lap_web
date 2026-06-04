'use client';

import Link from 'next/link';
import { PageIntro } from '@/components/ui/PageIntro';
import { useEntitlements } from '@/hooks/useEntitlements';
import { b2cPlans } from '@/data/pricing';

/* ── Page ─────────────────────────────────────────────────── */
// One membership, monthly only. Nothing to "upgrade/downgrade" between — this
// page now shows membership status and routes to the billing hub.

export default function MembershipPage() {
  const { entitlements } = useEntitlements();
  const status = entitlements?.subscriptionStatus ?? 'free';
  const hasMembership = status === 'active' || status === 'trialing' || status === 'past_due';
  const plan = b2cPlans[0];

  if (!plan) return null;

  const statusLabel =
    status === 'trialing'
      ? 'Trial'
      : status === 'active'
        ? 'Active'
        : status === 'past_due'
          ? 'Payment due'
          : null;

  return (
    <div>
      <PageIntro title="Your membership" subtitle="One membership unlocks the entire product." />

      <div className="max-w-xl mx-auto bg-concrete rounded-lg border border-acid-green/40 ring-1 ring-acid-green/10 p-6">
        {/* Header */}
        <div className="mb-4">
          <div className="flex items-center gap-2">
            <h2 className="font-monument text-lg text-chalk">{plan.name} Membership</h2>
            {hasMembership && statusLabel && (
              <span className="bg-acid-green/20 text-acid-green text-[10px] font-telemetry px-2 py-0.5 rounded-full">
                {statusLabel}
              </span>
            )}
          </div>
          <div className="mt-2">
            <span className="font-telemetry text-2xl text-chalk">{plan.priceMonthly}</span>
            <span className="text-steel text-xs font-body ml-2">
              · {plan.foundingPriceMonthly} for the first {plan.foundingLimit} members · {plan.trialDays}-day free trial
            </span>
          </div>
        </div>

        {/* Features */}
        <ul className="space-y-1.5 mb-6">
          {Object.entries(plan.features).map(([feature, value]) => (
            <li key={feature} className="flex items-start gap-2 text-xs">
              <span className="mt-0.5 text-acid-green">✓</span>
              <span className="text-steel font-body">
                <span className="text-chalk">{feature}:</span> {value}
              </span>
            </li>
          ))}
        </ul>

        {/* CTA */}
        {hasMembership ? (
          <Link
            href="/app/account/billing"
            className="block w-full text-center bg-concrete border border-steel/30 text-chalk font-telemetry text-sm py-2.5 rounded-md hover:border-acid-green/40 transition"
          >
            Manage billing
          </Link>
        ) : (
          <Link
            href="/app/account/billing"
            className="block w-full text-center bg-gold text-white font-telemetry text-sm py-2.5 rounded-md hover:brightness-110 transition"
          >
            {plan.cta}
          </Link>
        )}
      </div>

      <div className="mt-8 text-center">
        <Link href="/app/account/billing" className="text-steel hover:text-chalk text-sm font-body transition">
          ← Back to Billing
        </Link>
      </div>
    </div>
  );
}
