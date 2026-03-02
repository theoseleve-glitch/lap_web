'use client';

import { useState, useCallback } from 'react';
import { MonumentText } from '@/components/ui/MonumentText';
import { PricingTable } from '@/components/ui/PricingTable';
import { FaqAccordion } from '@/components/ui/FaqAccordion';
import { PitButton } from '@/components/ui/PitButton';
import { StampButton } from '@/components/ui/StampButton';
import {
  trackPricingToggle,
  trackFaqExpand,
  trackCtaClick,
} from '@/lib/analytics';
import { PitWheel } from '@/components/chrome/PitWheel';
import { useTranslation } from '@/i18n';
import { useCurrency } from '@/hooks/useCurrency';


export function PitStop() {
  const [billingPeriod, setBillingPeriod] = useState<'monthly' | 'annual'>('annual');
  const { t } = useTranslation();
  const { localizedPlans } = useCurrency();

  const toggleBilling = useCallback(() => {
    const next = billingPeriod === 'monthly' ? 'annual' : 'monthly';
    setBillingPeriod(next);
    trackPricingToggle(next);
  }, [billingPeriod]);

  const riskReversalKeys = [
    'home.pitStop.risk1',
    'home.pitStop.risk2',
    'home.pitStop.risk3',
    'home.pitStop.risk4',
    'home.pitStop.risk5',
    'home.pitStop.risk6',
  ];

  const trustStripKeys = [
    'home.pitStop.trust1',
    'home.pitStop.trust2',
    'home.pitStop.trust3',
    'home.pitStop.trust4',
  ];

  const faqItems = [
    { question: t('faq.q1'), answer: t('faq.a1') },
    { question: t('faq.q2'), answer: t('faq.a2') },
    { question: t('faq.q3'), answer: t('faq.a3') },
    { question: t('faq.q4'), answer: t('faq.a4') },
    { question: t('faq.q5'), answer: t('faq.a5') },
    { question: t('faq.q6'), answer: t('faq.a6') },
  ];

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
            {t('home.pitStop.monument')}
          </MonumentText>
        </div>
        <div className="col-span-full text-center mb-12">
          <p className="font-monument text-steel">{t('home.pitStop.chooseDepth')}</p>
        </div>

        {/* Billing toggle */}
        <div className="col-span-full flex items-center justify-center gap-3 mb-8">
          <span className={`font-telemetry text-[11px] ${billingPeriod === 'monthly' ? 'text-chalk' : 'text-steel'}`}>
            {t('home.pitStop.monthly')}
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
            {t('home.pitStop.annual')}
          </span>
        </div>

        {/* Pricing Table */}
        <div className="col-span-full mb-8">
          <PricingTable
            plans={localizedPlans}
            billingPeriod={billingPeriod}
            onCtaClick={(plan) => trackCtaClick(plan, 'pit-stop', 'b2c')}
          />
        </div>

        {/* CTAs */}
        <div className="col-span-full flex flex-col md:flex-row items-center justify-center gap-4 mb-12">
          <PitButton
            href="/register?source=free-report&redirect=/free-report/analyze"
            onClick={() => trackCtaClick('try_demo', 'pit-stop', 'b2c')}
          >
            {t('cta.startFreeReport')}
          </PitButton>
          <StampButton
            href="/contact"
            onClick={() => trackCtaClick('talk_sales', 'pit-stop', 'b2c')}
          >
            {t('cta.talkToSales')}
          </StampButton>
        </div>

        {/* Risk reversal */}
        <div className="col-span-full flex flex-wrap justify-center gap-3 mb-12">
          {riskReversalKeys.map((key) => (
            <span key={key} className="inline-block border border-chalk/20 px-3 py-1 font-telemetry text-[11px] tracking-[0.12em] uppercase text-chalk">
              {t(key)}
            </span>
          ))}
        </div>

        {/* FAQ */}
        <div className="col-span-full max-w-2xl mx-auto mb-12">
          <h3 className="font-monument text-[var(--text-h3)] mb-4">{t('home.pitStop.faq')}</h3>
          <FaqAccordion items={faqItems} onExpand={trackFaqExpand} />
        </div>

        {/* Trust strip */}
        <div className="col-span-full flex flex-wrap justify-center gap-3 border-t border-chalk/15 pt-8">
          {trustStripKeys.map((key) => (
            <span key={key} className="inline-block border border-chalk/20 px-3 py-1 font-telemetry text-[11px] tracking-[0.12em] uppercase text-steel">
              {t(key)}
            </span>
          ))}
        </div>
      </div>
    </section>
  );
}
