'use client';

import { useState, useCallback } from 'react';
import { MonumentText } from '@/components/ui/MonumentText';
import { ScrutineeringStamp } from '@/components/ui/ScrutineeringStamp';
import { PricingTable } from '@/components/ui/PricingTable';
import { FaqAccordion } from '@/components/ui/FaqAccordion';
import { PitButton } from '@/components/ui/PitButton';
import { StampButton } from '@/components/ui/StampButton';
import { b2cPlans, b2bCard } from '@/data/pricing';
import { faqItems } from '@/data/faq';
import { pitStop } from '@/data/copy';
import {
  trackPricingToggle,
  trackFaqExpand,
  trackCtaClick,
} from '@/lib/analytics';
import { PitWheel } from '@/components/chrome/PitWheel';

export function PitStop() {
  const [billingPeriod, setBillingPeriod] = useState<'monthly' | 'annual'>('annual');

  const toggleBilling = useCallback(() => {
    const next = billingPeriod === 'monthly' ? 'annual' : 'monthly';
    setBillingPeriod(next);
    trackPricingToggle(next);
  }, [billingPeriod]);

  return (
    <section
      id="pit-stop"
      data-accent="orange"
      className="relative py-16 md:py-24"
      style={{ minHeight: '100vh' }}
      aria-label="Pit Stop — Pricing and demo"
    >
      {/* Decorative wheel behind pricing content */}
      <div className="absolute right-8 top-1/3 -translate-y-1/2 hidden lg:block z-0">
        <PitWheel />
      </div>

      <div className="grid-lap relative" style={{ zIndex: 1 }}>
        {/* Header */}
        <div className="col-span-full text-center mb-4">
          <MonumentText size="h1" as="h2">
            {pitStop.monument}
          </MonumentText>
        </div>
        <div className="col-span-full text-center mb-12">
          <p className="font-monument text-steel">CHOOSE YOUR DEPTH</p>
        </div>

        {/* Billing toggle */}
        <div className="col-span-full flex items-center justify-center gap-3 mb-8">
          <span className={`font-telemetry text-[11px] ${billingPeriod === 'monthly' ? 'text-chalk' : 'text-steel'}`}>
            MONTHLY
          </span>
          <button
            role="switch"
            aria-checked={billingPeriod === 'annual'}
            className="relative w-12 h-6 bg-concrete border border-steel/30"
            onClick={toggleBilling}
            aria-label="Annual billing"
          >
            <span
              aria-hidden="true"
              className="absolute top-1 w-4 h-4 bg-pit-orange transition-all duration-300"
              style={{ left: billingPeriod === 'annual' ? 'calc(100% - 20px)' : '4px' }}
            />
          </button>
          <span className={`font-telemetry text-[11px] ${billingPeriod === 'annual' ? 'text-chalk' : 'text-steel'}`}>
            ANNUAL
          </span>
        </div>

        {/* Pricing Table + B2B card */}
        <div className="col-span-full grid grid-cols-1 lg:grid-cols-[3fr_1fr] gap-0 mb-8">
          <PricingTable
            plans={b2cPlans}
            billingPeriod={billingPeriod}
            onCtaClick={(plan) => trackCtaClick(plan, 'pit-stop', 'b2c')}
          />

          {/* B2B card */}
          <div className="p-6 bg-concrete border border-steel/20 lg:border-l-0">
            <h3 className="font-monument text-[var(--text-h3)] mb-4">{b2bCard.name}</h3>
            <ul className="space-y-2 mb-6">
              {b2bCard.features.map((feature) => (
                <li key={feature} className="flex items-start gap-2 font-body text-sm text-steel">
                  <span className="text-pit-orange mt-0.5 shrink-0">&bull;</span>
                  {feature}
                </li>
              ))}
            </ul>
            <StampButton
              href={b2bCard.ctaHref}
              onClick={() => trackCtaClick('contact_sales', 'pit-stop', 'b2b')}
              className="w-full"
            >
              {b2bCard.cta}
            </StampButton>
          </div>
        </div>

        {/* CTAs */}
        <div className="col-span-full flex flex-col md:flex-row items-center justify-center gap-4 mb-12">
          <PitButton
            href="/register?source=free-report&redirect=/free-report/analyze"
            onClick={() => trackCtaClick('try_demo', 'pit-stop', 'b2c')}
          >
            START FREE REPORT
          </PitButton>
          <StampButton
            href="/contact"
            onClick={() => trackCtaClick('talk_sales', 'pit-stop', 'b2c')}
          >
            TALK TO SALES
          </StampButton>
        </div>

        {/* Risk reversal */}
        <div className="col-span-full flex flex-wrap justify-center gap-4 mb-12">
          {pitStop.riskReversal.map((item) => (
            <ScrutineeringStamp key={item} label={item} />
          ))}
        </div>

        {/* FAQ */}
        <div className="col-span-full max-w-2xl mx-auto mb-12">
          <h3 className="font-monument text-[var(--text-h3)] mb-4">FAQ</h3>
          <FaqAccordion items={faqItems} onExpand={trackFaqExpand} />
        </div>

        {/* Trust strip */}
        <div className="col-span-full flex flex-wrap justify-center gap-4 border-t border-steel/20 pt-8">
          {pitStop.trustStrip.map((item) => (
            <ScrutineeringStamp key={item} label={item} />
          ))}
        </div>
      </div>
    </section>
  );
}
