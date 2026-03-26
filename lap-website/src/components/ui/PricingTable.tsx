'use client';

import { useState, useRef } from 'react';
import type { Plan } from '@/data/pricing';
import { useCurrency } from '@/hooks/useCurrency';
import { useFocusTrap } from '@/hooks/useFocusTrap';
import { PitButton } from './PitButton';
import { StampButton } from './StampButton';

/** 3 key differentiating features shown by default per plan slug */
const KEY_FEATURES: Record<string, string[]> = {
  demo: ['Session Upload', 'Race Strategy', 'Visualization'],
  racer: ['Analysis Reports', 'Race Strategy', 'Visualization'],
  'world-class': ['Analysis Reports', 'Race Strategy', 'Visualization'],
};

/** A/B CTA text overrides per plan slug, keyed by experiment variant */
const CTA_VARIANTS: Record<string, Record<string, string>> = {
  book_first: {
    demo: 'Try It Free',
    racer: 'Start Racing',
    'world-class': 'Unlock Full Access',
  },
  demo_first: {
    demo: 'Analyze a Session',
    racer: 'Upgrade Now',
    'world-class': 'Go World-Class',
  },
};

interface PricingTableProps {
  plans: Plan[];
  billingPeriod: 'monthly' | 'annual';
  onCtaClick?: (planName: string) => void;
  /** A/B experiment variant for CTA text (from lap_exp_cta cookie) */
  ctaVariant?: string;
  /** Slug of the plan to highlight as "Recommended for you" (from use-case selector) */
  recommendedSlug?: string | null;
  className?: string;
}

export function PricingTable({
  plans,
  billingPeriod,
  onCtaClick,
  ctaVariant,
  recommendedSlug,
  className = '',
}: PricingTableProps) {
  const [loadingPlan, setLoadingPlan] = useState<string | null>(null);
  const [expanded, setExpanded] = useState(false);
  const [confirmPlan, setConfirmPlan] = useState<Plan | null>(null);
  const { currency } = useCurrency();
  const confirmRef = useRef<HTMLDivElement>(null);
  useFocusTrap(confirmRef, !!confirmPlan, () => setConfirmPlan(null));

  async function proceedToCheckout(plan: Plan) {
    setConfirmPlan(null);
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
      window.location.href = plan.ctaHref;
    } finally {
      setLoadingPlan(null);
    }
  }

  function handleCheckout(plan: Plan) {
    onCtaClick?.(plan.name);

    // Free plan — go straight to register
    if (plan.priceAnnualPerMonth === 'Free') {
      window.location.href = '/register?source=demo';
      return;
    }

    // Show confirmation before creating Stripe session
    setConfirmPlan(plan);
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
          const ctaText = (ctaVariant && CTA_VARIANTS[ctaVariant]?.[plan.slug]) || plan.cta;
          const isRecommended = recommendedSlug === plan.slug;

          return (
            <div
              key={plan.name}
              className={`
                p-6 bg-concrete transition-all duration-300 hover:scale-[1.02] hover:shadow-xl hover:z-10
                ${plan.highlighted ? 'beam-card border-2 border-pit-orange' : 'border border-chalk/15 hover:border-chalk/30'}
                ${isRecommended ? 'ring-2 ring-acid-green/60' : ''}
                ${i > 0 ? 'md:border-l-0' : ''}
              `}
            >
              {isRecommended && (
                <p className="inline-flex mb-3 mr-2 border border-acid-green bg-acid-green/10 px-2 py-1 font-telemetry text-[10px] tracking-[0.12em] uppercase text-acid-green">
                  Recommended for you
                </p>
              )}
              {plan.highlighted && (
                <p className="inline-flex mb-3 border border-pit-orange bg-pit-orange/18 px-2 py-1 font-telemetry text-[10px] tracking-[0.12em] uppercase text-pit-orange">
                  Most Popular
                </p>
              )}

              <h3 className="font-monument text-[var(--text-h3)] mb-2">
                {plan.name}
              </h3>

              <p className="font-monument text-[clamp(34px,4vw,52px)] text-chalk leading-[0.95] transition-opacity duration-300">
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
                    <span className={val === '\u2014' ? 'text-steel/60' : 'text-chalk'}>
                      {val}
                    </span>
                  </div>
                ))}
              </div>

              {plan.highlighted ? (
                <PitButton
                  onClick={() => handleCheckout(plan)}
                  className="w-full"
                  loading={isLoading}
                  disabled={loadingPlan !== null && !isLoading}
                >
                  {isLoading ? 'Redirecting...' : ctaText}
                </PitButton>
              ) : (
                <StampButton
                  onClick={() => handleCheckout(plan)}
                  className="w-full"
                  loading={isLoading}
                  disabled={loadingPlan !== null && !isLoading}
                >
                  {isLoading ? 'Redirecting...' : ctaText}
                </StampButton>
              )}
            </div>
          );
        })}
      </div>

      {/* Expand/collapse toggle */}
      <div className="flex justify-center mt-4">
        <button
          type="button"
          className="font-telemetry text-[11px] tracking-[0.12em] uppercase text-steel hover:text-chalk transition-colors duration-300 border border-chalk/15 px-4 py-2"
          onClick={() => setExpanded(!expanded)}
        >
          {expanded ? 'Show key features' : 'See all features'}
        </button>
      </div>

      {/* Checkout confirmation dialog */}
      {confirmPlan && (
        <div
          ref={confirmRef}
          className="fixed inset-0 z-50 flex items-center justify-center bg-carbon/80 backdrop-blur-sm"
          onClick={() => setConfirmPlan(null)}
          role="dialog"
          aria-modal="true"
          aria-labelledby="confirm-checkout-title"
        >
          <div
            className="bg-concrete border border-chalk/15 p-8 max-w-md w-full mx-4"
            onClick={(e) => e.stopPropagation()}
          >
            <h3
              id="confirm-checkout-title"
              className="font-monument text-xl text-chalk mb-4"
            >
              Confirm subscription
            </h3>
            <div className="space-y-3 mb-6">
              <div className="flex justify-between py-2 px-2 bg-asphalt/40">
                <span className="text-steel font-telemetry text-sm">Plan</span>
                <span className="text-chalk font-telemetry text-sm">{confirmPlan.name}</span>
              </div>
              <div className="flex justify-between py-2 px-2">
                <span className="text-steel font-telemetry text-sm">Billing</span>
                <span className="text-chalk font-telemetry text-sm capitalize">{billingPeriod}</span>
              </div>
              <div className="flex justify-between py-2 px-2 bg-asphalt/40">
                <span className="text-steel font-telemetry text-sm">Price</span>
                <span className="text-chalk font-telemetry text-sm">
                  {billingPeriod === 'annual' ? confirmPlan.priceAnnualPerMonth : confirmPlan.priceMonthly}/mo
                </span>
              </div>
              {billingPeriod === 'annual' && confirmPlan.annualTotal && (
                <div className="flex justify-between py-2 px-2">
                  <span className="text-steel font-telemetry text-sm">Annual total</span>
                  <span className="text-chalk font-telemetry text-sm">{confirmPlan.annualTotal}</span>
                </div>
              )}
            </div>
            <p className="text-steel text-xs mb-6">
              You&apos;ll be redirected to Stripe to complete payment securely. You can cancel anytime.
            </p>
            <div className="flex gap-3">
              <button
                type="button"
                onClick={() => setConfirmPlan(null)}
                className="flex-1 py-2.5 border border-chalk/15 text-steel font-telemetry text-xs tracking-[0.08em] uppercase hover:text-chalk transition-colors"
              >
                Cancel
              </button>
              <PitButton
                onClick={() => proceedToCheckout(confirmPlan)}
                className="flex-1"
                loading={loadingPlan !== null}
              >
                {loadingPlan ? 'Redirecting...' : 'Continue to payment'}
              </PitButton>
            </div>
          </div>
        </div>
      )}
    </div>
  );
}
