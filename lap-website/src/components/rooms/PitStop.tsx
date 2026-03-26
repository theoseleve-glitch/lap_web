'use client';

import { useState, useCallback, useEffect } from 'react';
import { MonumentText } from '@/components/ui/MonumentText';
import { PricingTable } from '@/components/ui/PricingTable';
import { FaqAccordion } from '@/components/ui/FaqAccordion';
import { PitButton } from '@/components/ui/PitButton';
import {
  trackPricingToggle,
  trackFaqExpand,
  trackCtaClick,
} from '@/lib/analytics';
import { PitWheel } from '@/components/chrome/PitWheel';
import { useTranslation } from '@/i18n';
import { useCurrency } from '@/hooks/useCurrency';

/**
 * Core feature rows — always visible.
 * Cross-checked against PLAN_ENTITLEMENTS in telemetry_tool/auth/entitlements.py
 */
const CORE_FEATURES: { label: string; demo: string; racer: string; worldClass: string }[] = [
  { label: 'Analysis Reports', demo: '1 report', racer: '10/mo', worldClass: 'Unlimited' },
  { label: 'Race Strategy', demo: '4h limit', racer: 'Up to 24h', worldClass: 'Unlimited' },
  { label: 'Visualization', demo: '\u2014', racer: 'Full', worldClass: 'Full' },
  { label: 'Raw Telemetry Retention', demo: '1 month', racer: '3 months', worldClass: '12 months' },
  { label: 'Report Retention', demo: '5 years', racer: '5 years', worldClass: '5 years' },
];

/** Detail rows — revealed on expand. Cross-checked against backend entitlements. */
const DETAIL_FEATURES: { label: string; demo: string; racer: string; worldClass: string }[] = [
  { label: '4-Pillar Scoring', demo: 'Full', racer: 'Full', worldClass: 'Full' },
  { label: 'Corner Coaching', demo: 'Full', racer: 'Full', worldClass: 'Full' },
  { label: 'Session Intelligence', demo: 'Full', racer: 'Full', worldClass: 'Full' },
  { label: 'Comparison & Progress', demo: '\u2014', racer: 'Full', worldClass: 'Full' },
  { label: 'Coaching Plans', demo: '\u2014', racer: 'Full', worldClass: 'Full' },
  { label: 'Optimizer Modes', demo: 'Equal-time', racer: 'Equal-time', worldClass: 'All modes' },
  { label: 'Live Monitoring', demo: '\u2014', racer: 'Full', worldClass: 'Full' },
  { label: 'Pit Stop Planning', demo: '\u2014', racer: 'Full', worldClass: 'Full' },
  { label: 'PDF Reports', demo: '\u2014', racer: 'Full', worldClass: 'Full' },
  { label: 'API Access', demo: '\u2014', racer: '\u2014', worldClass: 'Full' },
];

export function PitStop() {
  const [billingPeriod, setBillingPeriod] = useState<'monthly' | 'annual'>('annual');
  const [matrixExpanded, setMatrixExpanded] = useState(false);
  const { t } = useTranslation();
  const { localizedPlans } = useCurrency();

  const [ctaVariant, setCtaVariant] = useState<string | undefined>();
  useEffect(() => {
    const match = document.cookie.match(/(?:^|;\s*)lap_exp_cta=([^;]+)/);
    if (match) setCtaVariant(match[1]);
  }, []);

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
            type="button"
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
            ctaVariant={ctaVariant}
          />
        </div>

        {/* Feature comparison mini-matrix */}
        <div className="col-span-full mb-8 overflow-x-auto">
          <table className="w-full border-collapse text-sm">
            <thead>
              <tr className="bg-concrete">
                <th className="border border-steel/20 p-2 text-left text-steel">Feature</th>
                <th className="border border-steel/20 p-2 text-center text-steel">Demo</th>
                <th className="border border-steel/20 p-2 text-center text-pit-orange font-monument">Racer</th>
                <th className="border border-steel/20 p-2 text-center text-steel">World-Class</th>
              </tr>
            </thead>
            <tbody>
              {/* Core rows — always visible */}
              {CORE_FEATURES.map((row) => (
                <tr key={row.label} className="hover:bg-concrete/40 transition-colors">
                  <td className="border border-steel/20 p-2 text-chalk">{row.label}</td>
                  {[row.demo, row.racer, row.worldClass].map((val, i) => (
                    <td key={i} className="border border-steel/20 p-2 text-center">
                      {val === '\u2014'
                        ? <span className="text-steel/30">&mdash;</span>
                        : <span className="text-chalk text-xs">{val}</span>}
                    </td>
                  ))}
                </tr>
              ))}

              {/* Detail rows — collapsible */}
              {matrixExpanded && DETAIL_FEATURES.map((row) => (
                <tr key={row.label} className="bg-concrete/20 hover:bg-concrete/40 transition-colors">
                  <td className="border border-steel/20 p-2 text-chalk">{row.label}</td>
                  {[row.demo, row.racer, row.worldClass].map((val, i) => (
                    <td key={i} className="border border-steel/20 p-2 text-center">
                      {val === '\u2014'
                        ? <span className="text-steel/30">&mdash;</span>
                        : <span className="text-chalk text-xs">{val}</span>}
                    </td>
                  ))}
                </tr>
              ))}

              {/* Expand/collapse row inside table */}
              <tr>
                <td colSpan={4} className="border border-steel/20 p-0">
                  <button
                    type="button"
                    className="w-full py-3 font-telemetry text-[11px] tracking-[0.12em] uppercase text-steel hover:text-chalk hover:bg-concrete/40 transition-colors duration-300 flex items-center justify-center gap-2"
                    onClick={() => setMatrixExpanded(!matrixExpanded)}
                  >
                    {matrixExpanded ? 'Show key features' : 'See all features'}
                    <span
                      className="inline-block transition-transform duration-300"
                      style={{ transform: matrixExpanded ? 'rotate(180deg)' : 'rotate(0deg)' }}
                    >
                      &#9662;
                    </span>
                  </button>
                </td>
              </tr>
            </tbody>
          </table>
        </div>

        {/* CTA */}
        <div className="col-span-full flex items-center justify-center mb-12">
          <PitButton
            href="/register?source=pit-stop"
            onClick={() => trackCtaClick('try_demo', 'pit-stop', 'b2c')}
          >
            {t('cta.startFreeReport')}
          </PitButton>
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
