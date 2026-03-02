'use client';

import { useState } from 'react';
import type { Plan } from '@/data/pricing';
import { useCurrency } from '@/hooks/useCurrency';
import { PitButton } from './PitButton';
import { StampButton } from './StampButton';

/** 3 key differentiating features shown by default per plan slug */
const KEY_FEATURES: Record<string, string[]> = {
  demo: ['Analysis Reports', 'Raw Telemetry Retention', '4-Pillar Scoring'],
  racer: ['Analysis Reports', 'Race Strategy Dashboard', 'Exports'],
  'world-class': ['Analysis Reports', 'Exports', 'Raw Telemetry Retention'],
};

interface PricingTableProps {
  plans: Plan[];
  billingPeriod: 'monthly' | 'annual';
  onCtaClick?: (planName: string) => void;
  className?: string;
}

export function PricingTable({
  plans,
  billingPeriod,
  onCtaClick,
  className = '',
}: PricingTableProps) {
  const [loadingPlan, setLoadingPlan] = useState<string | null>(null);
  const [expanded, setExpanded] = useState(false);
  const { currency } = useCurrency();

  async function handleCheckout(plan: Plan) {
    onCtaClick?.(plan.name);

    // Free plan — go straight to register
    if (plan.priceAnnualPerMonth === 'Free') {
      window.location.href = '/register?source=demo';
      return;
    }

    setLoadingPlan(plan.name);
    try {
      const response = await fetch('/api/billing/checkout', {
        method: 'POST',
        headers: { 'content-type': 'application/json' },
        body: JSON.stringify({
          plan: plan.name,
          billingCycle: billingPeriod,
          currency,
        }),
      });

      const data = (await response.json().catch(() => null)) as {
        ok?: boolean;
        checkoutUrl?: string;
      } | null;

      if (data?.checkoutUrl) {
        window.location.href = data.checkoutUrl;
      }
    } catch {
      // On failure, fall back to billing page
      window.location.href = plan.ctaHref;
    } finally {
      setLoadingPlan(null);
    }
  }

  return (
    <div className={className}>
      <div className="grid grid-cols-1 md:grid-cols-3 gap-0">
        {plans.map((plan, i) => {
          const isFree = plan.priceAnnualPerMonth === 'Free';
          const showAnnual = billingPeriod === 'annual' && !isFree;
          const displayPrice = showAnnual
            ? plan.priceAnnualPerMonth
            : plan.priceMonthly;
          const isLoading = loadingPlan === plan.name;

          const allFeatures = Object.entries(plan.features);
          const keyFeatureNames = KEY_FEATURES[plan.slug] ?? [];
          const summaryFeatures = allFeatures.filter(([key]) =>
            keyFeatureNames.includes(key),
          );
          const displayFeatures = expanded ? allFeatures : summaryFeatures;

          return (
            <div
              key={plan.name}
              className={`
                p-6 bg-concrete
                ${plan.highlighted ? 'beam-card border-2 border-pit-orange' : 'border border-chalk/15'}
                ${i > 0 ? 'md:border-l-0' : ''}
              `}
            >
              {plan.highlighted && (
                <p className="inline-flex mb-3 border border-pit-orange bg-pit-orange/18 px-2 py-1 font-telemetry text-[10px] tracking-[0.12em] uppercase text-pit-orange">
                  Most Popular
                </p>
              )}

              <h3 className="font-monument text-[var(--text-h3)] mb-2">
                {plan.name}
              </h3>

              <p className="font-monument text-[clamp(34px,4vw,52px)] text-chalk leading-[0.95]">
                {displayPrice}
              </p>

              {showAnnual && plan.annualTotal ? (
                <p className="mt-1 mb-4 font-telemetry text-[11px] tracking-[0.08em] text-steel">
                  {plan.annualTotal}{' '}
                  <span className="inline-flex ml-1 px-1.5 py-0.5 bg-chalk/12 text-chalk text-[10px] tracking-[0.12em] uppercase">
                    save {plan.savingsPercent}%
                  </span>
                </p>
              ) : (
                <div className="mb-4" />
              )}

              <div className="space-y-2 mb-6">
                {displayFeatures.map(([key, val], j) => (
                  <div
                    key={key}
                    className={`flex justify-between py-2 px-2 font-body text-base ${
                      j % 2 === 0 ? 'bg-asphalt/40' : ''
                    }`}
                  >
                    <span className="text-steel">{key}</span>
                    <span className={val === '\u2014' ? 'text-steel/40' : 'text-chalk'}>
                      {val}
                    </span>
                  </div>
                ))}
              </div>

              {plan.highlighted ? (
                <PitButton
                  onClick={() => handleCheckout(plan)}
                  className="w-full"
                >
                  {isLoading ? 'Redirecting...' : plan.cta}
                </PitButton>
              ) : (
                <StampButton
                  onClick={() => handleCheckout(plan)}
                  className="w-full"
                >
                  {isLoading ? 'Redirecting...' : plan.cta}
                </StampButton>
              )}
            </div>
          );
        })}
      </div>

      {/* Expand/collapse toggle */}
      <div className="flex justify-center mt-4">
        <button
          className="font-telemetry text-[11px] tracking-[0.12em] uppercase text-steel hover:text-chalk transition-colors duration-300 border border-chalk/15 px-4 py-2"
          onClick={() => setExpanded(!expanded)}
        >
          {expanded ? 'Show key features' : 'See all features'}
        </button>
      </div>
    </div>
  );
}
