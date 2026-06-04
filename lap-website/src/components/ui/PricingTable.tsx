'use client';

import { useState } from 'react';
import type { Plan } from '@/data/pricing';
import { PitButton } from './PitButton';

interface PricingTableProps {
  /** The membership plan(s); the first is rendered (one-membership model). */
  plans: Plan[];
  onCtaClick?: (planName: string) => void;
  className?: string;
}

export function PricingTable({ plans, onCtaClick, className = '' }: PricingTableProps) {
  const plan = plans[0];
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);

  async function startCheckout() {
    if (!plan) return;
    onCtaClick?.(plan.name);
    setLoading(true);
    setError(null);
    try {
      const res = await fetch('/api/billing/checkout', {
        method: 'POST',
        headers: { 'content-type': 'application/json' },
        body: JSON.stringify({}), // Stripe Checkout collects the email; backend reserves the slot
      });
      const data = (await res.json().catch(() => null)) as
        | { ok?: boolean; checkoutUrl?: string }
        | null;
      if (res.ok && data?.ok && data.checkoutUrl) {
        window.location.href = data.checkoutUrl;
        return;
      }
      // Fail loud — never pretend success or silently bounce.
      setError('We couldn’t start checkout just now. Please try again in a moment.');
    } catch {
      setError('We couldn’t reach checkout. Please check your connection and try again.');
    } finally {
      setLoading(false);
    }
  }

  if (!plan) return null;

  const features = Object.entries(plan.features);

  return (
    <div className={`mx-auto max-w-xl ${className}`}>
      <div className="beam-card border-2 border-pit-orange bg-concrete p-8">
        <p className="inline-flex mb-3 border border-pit-orange bg-pit-orange/18 px-2 py-1 font-telemetry text-[10px] tracking-[0.12em] uppercase text-pit-orange">
          Founding offer · first {plan.foundingLimit} members
        </p>

        <h3 className="font-monument text-[var(--text-h3)] mb-2">{plan.name} Membership</h3>

        <p className="font-monument text-[clamp(34px,4vw,52px)] text-chalk leading-[0.95]">
          {plan.foundingPriceMonthly}
        </p>
        <p className="mt-1 mb-4 font-telemetry text-[12px] tracking-[0.06em] text-steel">
          for the first {plan.foundingLimit} members · then{' '}
          <span className="text-chalk">{plan.priceMonthly}</span>
          <span className="mx-2 text-steel/50">·</span>
          {plan.trialDays}-day free trial
        </p>

        <div className="space-y-2 mb-6">
          {features.map(([key, val], j) => (
            <div
              key={key}
              className={`flex justify-between py-2 px-2 font-body text-base ${j % 2 === 0 ? 'bg-asphalt/40' : ''}`}
            >
              <span className="text-steel">{key}</span>
              <span className="text-chalk">{val}</span>
            </div>
          ))}
        </div>

        <PitButton onClick={startCheckout} className="w-full" loading={loading} disabled={loading}>
          {loading ? 'Redirecting…' : plan.cta}
        </PitButton>

        {error && (
          <p
            role="alert"
            className="mt-3 border border-safety-red/40 bg-safety-red/10 px-3 py-2 font-telemetry text-[12px] text-safety-red"
          >
            {error}
          </p>
        )}

        <p className="mt-3 text-center font-telemetry text-[11px] tracking-[0.06em] text-steel">
          No charge for {plan.trialDays} days · cancel anytime
        </p>
      </div>
    </div>
  );
}
